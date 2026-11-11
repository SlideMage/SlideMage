# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The store of background renders (docs/plans/idle-background-rendering.md, section 4).

Everything lives on this computer, in the user's cache folder (`project.cache_dir()/render-store/<project id>/`),
never in the project: projects live in cloud-synced folders and the renders can be gigabytes. The project id is a
hash of the project's folder, so two projects (or two copies of one) never share a store.

**Objects** are folders, `objects/<ab>/<key>/`, holding `slide.pdf`, one 1920 px `pNNN.webp` per
page (every reveal step), `thumb.webp` shrunk from the last page, and `meta.json`, written last with the
sizes of the other files. Older objects keep their PNG files. Publication replaces the previous object of the key
under the store lock. An object without a complete `meta.json` is ignored.

The **index** is a SQLite file beside them: the records of published objects, the file hashes
(dep_hash), the failures the sweep remembers and the decks' usage. `work/` holds what the renders' LaTeX runs
need outside the project: their wrapper files, build caches and precompiled preamble formats.
Free of Qt.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Iterable, Optional

from . import project
from .fileio import write_json
from .render_evidence import THUMBNAIL_MAX, webp

STORE_FORMAT = 2
DEFAULT_LIMIT_BYTES = 2 * 1024 ** 3
LEFTOVERS_CLEARED = "stale renders cleared"     # the one clearing of legacy stale renders ran in this store
FAILURE_INPUTS_TRACKED = "failures track their own inputs"

SCHEMA = """
CREATE TABLE IF NOT EXISTS renders (
    key TEXT PRIMARY KEY, unit TEXT NOT NULL,
    bytes INTEGER NOT NULL, rendered_at REAL NOT NULL, last_used REAL NOT NULL, decks TEXT NOT NULL, meta TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS renders_unit ON renders(unit);
CREATE TABLE IF NOT EXISTS failures (
    fast_key TEXT PRIMARY KEY, kind TEXT NOT NULL, attempts INTEGER NOT NULL, error TEXT NOT NULL,
    first_at REAL NOT NULL, next_try_at REAL NOT NULL, manifest TEXT NOT NULL, last_try REAL);
CREATE TABLE IF NOT EXISTS texsets (digest TEXT PRIMARY KEY, files TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS deck_usage (
    deck TEXT PRIMARY KEY, last_opened REAL NOT NULL, open_count INTEGER NOT NULL,
    last_slide TEXT, last_view TEXT, last_language TEXT);
CREATE TABLE IF NOT EXISTS store_flags (name TEXT PRIMARY KEY, done_at REAL NOT NULL);
"""

DETERMINISTIC = "deterministic"
TRANSIENT = "transient"
BACKOFF_SECONDS = (300, 1800, 3 * 3600)
MAX_TRANSIENT_ATTEMPTS = 3


def project_copy(ctx: project.ProjectContext) -> Path:
    """Where an earlier version kept the renders, inside the project: now never used."""
    return ctx.root / ".previews" / "render-store"


def object_dir(root: Path, key: str) -> Path:
    return root / "objects" / key[:2] / key


class RenderStore:
    def __init__(self, ctx: project.ProjectContext, local_dir: Optional[Path] = None,
                 clock: Callable[[], float] = time.time) -> None:
        self.ctx = ctx
        self.root = Path(local_dir) if local_dir is not None else project.cache_dir() / "render-store" / project_id(ctx.root)
        self.work_dir = self.root / "work"
        self.forget_project_copy(ctx)
        shutil.rmtree(project.preview_cache_dir(ctx.root) / "render-results", ignore_errors=True)
        self._clock = clock
        self._touched: dict[str, float] = {}
        self.lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.root / "index.sqlite"), check_same_thread=False, timeout=30)
        with self.lock:
            self.db.executescript(SCHEMA)
            if "origin" in {row[1] for row in self.db.execute("PRAGMA table_info(renders)")}:
                self.db.execute("DROP INDEX IF EXISTS renders_key")
                self.db.execute("ALTER TABLE renders DROP COLUMN origin")
                self.db.execute("ALTER TABLE renders DROP COLUMN fast_key")
                self.db.execute("ALTER TABLE renders RENAME COLUMN name TO key")
                self.db.execute("ALTER TABLE failures ADD COLUMN last_try REAL")
                self.db.execute("DROP TABLE IF EXISTS last_tries")
            self.db.commit()
        self.current_keys: frozenset[str] = frozenset()
        with self.lock:
            if self.db.execute("PRAGMA user_version").fetchone()[0] != STORE_FORMAT:
                self.db.execute("DELETE FROM renders")
                self.db.execute("DROP TABLE IF EXISTS filehash")
                self.forget_failure()
                self.db.execute(f"PRAGMA user_version={STORE_FORMAT}")
                self.db.commit()
        # Older failures often recorded only the slide, having searched the project's build folder instead of the
        # background workspace. Their dependency state cannot be recovered: retry once with correct tracking.
        if not self.flag(FAILURE_INPUTS_TRACKED):
            self.forget_failure()
            self.set_flag(FAILURE_INPUTS_TRACKED)
        (self.root / "project.txt").write_text(str(ctx.root.resolve()), encoding="utf-8")

    @staticmethod
    def forget_project_copy(ctx: project.ProjectContext) -> None:
        """An earlier version kept the renders in the project, where the sync would carry them to every computer.
        It is only a cache: delete it."""
        shutil.rmtree(project_copy(ctx), ignore_errors=True)

    def close(self) -> None:
        with self.lock:
            self.db.close()

    # -- objects -----------------------------------------------------------------

    def put(self, key: str, pdf: Path, pages: list[bytes], meta: dict, *,
            decks: Iterable[str] = ()) -> str:
        """Publish a complete render, replacing the object of this key and obsolete keys of its unit."""
        if not pages:
            raise ValueError("a render needs page images")
        encoded = [webp(page) for page in pages]        # before the lock: about 0.3 s a page
        small = webp(pages[-1], THUMBNAIL_MAX)
        with self.lock:
            decks = set(decks)
            row = self.db.execute("SELECT decks FROM renders WHERE key=?", (key,)).fetchone()
            if row:
                decks.update(json.loads(row[0]))
            target = object_dir(self.root, key)
            tmp = self.root / "tmp" / uuid.uuid4().hex
            tmp.mkdir(parents=True)
            try:
                shutil.copyfile(pdf, tmp / "slide.pdf")
                sizes = {"slide.pdf": (tmp / "slide.pdf").stat().st_size}
                for number, data in enumerate(encoded, start=1):
                    (tmp / f"p{number:03d}.webp").write_bytes(data)
                    sizes[f"p{number:03d}.webp"] = len(data)
                (tmp / "thumb.webp").write_bytes(small)
                sizes["thumb.webp"] = len(small)
                meta = dict(meta)
                tex_files = meta.pop("tex_files", None)
                meta.update(format=STORE_FORMAT, key=key, pages=len(pages), files=sizes,
                            bytes=sum(sizes.values()), decks=sorted(set(decks)))
                write_json(tmp / "meta.json", meta, indent=0)       # last: the object is complete only now
                target.parent.mkdir(parents=True, exist_ok=True)
                self._remove(key)
                os.replace(tmp, target)
                self._index(key, meta, tex_files)
                for (old_key,) in self.db.execute("SELECT key FROM renders WHERE unit=? AND key!=?", (meta["unit"], key)).fetchall():
                    if old_key not in self.current_keys:
                        self._remove(old_key)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            self.db.commit()
            return key

    def _exists(self, key: str) -> bool:
        return (object_dir(self.root, key) / "meta.json").is_file()

    def _index(self, key: str, meta: dict, tex_files: Optional[list] = None) -> None:
        now = self._clock()
        self.db.execute(
            "INSERT OR REPLACE INTO renders VALUES (?,?,?,?,?,?,?)",
            (key, meta.get("unit", ""), int(meta.get("bytes", 0)),
             float(meta.get("rendered_at", now)), now, json.dumps(meta.get("decks", [])), json.dumps(meta)))
        if meta.get("tex_digest") and tex_files:
            self.db.execute("INSERT OR IGNORE INTO texsets VALUES (?,?)", (meta["tex_digest"], json.dumps(tex_files)))

    def find(self, key: str) -> Optional[dict]:
        """The current-format object of `key`, if present on disk."""
        with self.lock:
            row = self.db.execute("SELECT meta FROM renders WHERE key=?", (key,)).fetchone()
            record = self._checked_meta(str(object_dir(self.root, key)), row[0]) if row else None
            if record is not None:
                record["dir"] = str(object_dir(self.root, key))
            return record

    def latest_for_unit(self, unit: str) -> Optional[dict]:
        with self.lock:
            rows = self.db.execute("SELECT key FROM renders WHERE unit=? ORDER BY rendered_at DESC, key DESC", (unit,)).fetchall()
            for (key,) in rows:
                if found := self.find(key):
                    return found
        return None

    def page(self, record: dict, number: int) -> Optional[bytes]:
        """The image of page `number` (1-based), read under the publication lock."""
        with self.lock:
            if self.find(record["key"]) != record:
                return None
            name = next((name for name in record["files"] if Path(name).stem == f"p{number:03d}"), None)
            if name is None:
                return None
            try:
                data = (Path(record["dir"]) / name).read_bytes()
            except OSError:
                return None
            self.touch(record["key"])
            return data

    def pages(self, record: dict) -> Optional[list[bytes]]:
        """Every page from one publication, or a miss if the object was replaced or evicted."""
        with self.lock:
            if self.find(record["key"]) != record:
                return None
            try:
                pages = [(Path(record["dir"]) / name).read_bytes()
                         for name in sorted((name for name in record["files"] if name.startswith("p")),
                                            key=lambda name: int(Path(name).stem[1:]))]
            except OSError:
                return None
            self.touch(record["key"])
            return pages if pages and all(pages) else None

    @contextmanager
    def pdf_copy(self, record: dict):
        """A temporary PDF, independent of replacement/eviction, for the caller's context lifetime."""
        with tempfile.TemporaryDirectory(prefix="slidemage-render-") as tmp:
            pdf = Path(tmp) / "slide.pdf"
            with self.lock:
                if self.find(record["key"]) != record:
                    pdf = None
                else:
                    try:
                        shutil.copyfile(Path(record["dir"]) / "slide.pdf", pdf)
                    except OSError:
                        pdf = None
                    else:
                        self.touch(record["key"])
            yield pdf

    def thumbnail_path(self, record: dict) -> Optional[Path]:
        """The slide list's small copy of the last page; eviction may remove it after this returns."""
        with self.lock:
            if self.find(record["key"]) != record:
                return None
            name = next((name for name in record["files"] if Path(name).stem == "thumb"), None)
            if name is None:
                return None
            path = Path(record["dir"]) / name
            self.touch(record["key"])
            return path if path.is_file() else None

    def touch(self, key: str) -> None:
        with self.lock:
            now = self._clock()
            if now - self._touched.get(key, float("-inf")) < 3600:
                return
            self.db.execute("UPDATE renders SET last_used=? WHERE key=?", (now, key))
            self.db.commit()
            self._touched[key] = now

    def tex_files(self, digest: str) -> Optional[list]:
        with self.lock:
            row = self.db.execute("SELECT files FROM texsets WHERE digest=?", (digest,)).fetchone()
        return json.loads(row[0]) if row else None

    def link_decks(self, key: str, decks: Iterable[str]) -> None:
        decks = set(decks)
        if not decks:
            return
        with self.lock:
            row = self.db.execute("SELECT decks FROM renders WHERE key=?", (key,)).fetchone()
            if row is None:
                return
            merged = sorted(set(json.loads(row[0])) | decks)
            self.db.execute("UPDATE renders SET decks=? WHERE key=?", (json.dumps(merged), key))
            self.db.commit()

    def _remove(self, key: str) -> None:
        shutil.rmtree(object_dir(self.root, key), ignore_errors=True)
        self.db.execute("DELETE FROM renders WHERE key=?", (key,))

    def delete(self, key: str) -> None:
        with self.lock:
            self._remove(key)
            self.db.commit()

    def drop_deck(self, deck: str) -> int:
        """A deck was archived: forget it in every render, deleting the renders only it used."""
        removed = 0
        with self.lock:
            rows = self.db.execute("SELECT key, decks FROM renders").fetchall()
            for key, decks in rows:
                names = json.loads(decks)
                if deck not in names:
                    continue
                names.remove(deck)
                if names:
                    self.db.execute("UPDATE renders SET decks=? WHERE key=?", (json.dumps(names), key))
                else:
                    self._remove(key)
                    removed += 1
            self.db.execute("DELETE FROM deck_usage WHERE deck=?", (deck,))
            self.db.commit()
        return removed

    def drop_stale(self, in_scope: Callable[[str], bool], keep_keys: set, clean_decks: set, before: float) -> int:
        """Delete the renders whose key no deck uses any more (docs/plans/render-store-cleanup.md, step 2), of the units
        `in_scope(label)` says the caller knows every current key of. `keep_keys` are the keys
        the last scan found for every unit of the decks in `clean_decks`, the decks it read in full. A render is deleted
        only when its key is not in `keep_keys`, it was rendered before `before` (the scan's start: a render stored after
        it may be of a key the scan did not see yet), and every deck it belongs to is in `clean_decks` (a deck that could
        not be read, is switched off or is not swept keeps what it has; a render of no deck is left to the disk limit).

        Never by label alone: a slide called twice in a deck in two ways has one label and two current keys, and both
        are in `keep_keys`. Returns how many were deleted."""
        deleted = 0
        with self.lock:
            rows = self.db.execute("SELECT key, unit, rendered_at, decks FROM renders").fetchall()
            for key, unit, rendered_at, decks in rows:
                if key in keep_keys or rendered_at >= before or not in_scope(unit):
                    continue
                try:
                    deck_list = json.loads(decks)
                except ValueError:
                    continue
                if not deck_list or not set(deck_list) <= clean_decks:
                    continue
                self._remove(key)
                deleted += 1
            self.db.commit()
        return deleted

    def prune_index(self, keep_failures: Iterable[str], before: float) -> None:
        """Forget old failures no current key uses and TeX file sets no render refers to."""
        with self.lock:
            self.db.execute("DELETE FROM failures WHERE first_at < ? "
                            "AND fast_key NOT IN (SELECT value FROM json_each(?))",
                            (before, json.dumps(list(keep_failures))))
            self.db.execute("DELETE FROM texsets WHERE digest NOT IN "
                            "(SELECT json_extract(meta, '$.tex_digest') FROM renders "
                            "WHERE json_extract(meta, '$.tex_digest') IS NOT NULL)")
            self.db.commit()

    def flag(self, name: str) -> bool:
        """Whether the one-off task `name` ran in this store (set_flag)."""
        with self.lock:
            return self.db.execute("SELECT 1 FROM store_flags WHERE name=?", (name,)).fetchone() is not None

    def set_flag(self, name: str) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO store_flags VALUES (?,?)", (name, self._clock()))
            self.db.commit()

    def clear(self) -> None:
        with self.lock:
            shutil.rmtree(self.root / "objects", ignore_errors=True)
            shutil.rmtree(self.root / "tmp", ignore_errors=True)
            self.db.execute("DELETE FROM renders")
            self.db.commit()

    def total_bytes(self) -> int:
        with self.lock:
            return self.db.execute("SELECT COALESCE(SUM(bytes), 0) FROM renders").fetchone()[0]

    def count(self) -> int:
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM renders").fetchone()[0]

    def rescan(self, should_stop: Callable[[], bool] = lambda: False) -> None:
        """Clear unfinished writes, incomplete or missing indexed objects, and folders without an index row.

        Hold the lock per shard so publication can continue between shards. Check the current row under the lock
        before removing an object, so a render stored during the walk is kept. A stopped walk leaves rows of unseen
        objects alone. Indexed meta supplies the expected file sizes without reading meta.json again.
        """
        with self.lock:
            shutil.rmtree(self.root / "tmp", ignore_errors=True)       # under the lock: put() writes there
            indexed = {row[0] for row in self.db.execute("SELECT key FROM renders")}
        known = set()
        objects = self.root / "objects"
        shards = []
        if objects.is_dir():
            with os.scandir(objects) as listing:
                shards = [e.path for e in listing if e.is_dir()]
        for shard in shards:
            if should_stop():
                with self.lock:
                    self.db.commit()
                return
            with self.lock:
                try:
                    with os.scandir(shard) as listing:
                        folders = [e for e in listing if e.is_dir()]
                except OSError:
                    continue
                for folder in folders:
                    row = self.db.execute("SELECT meta FROM renders WHERE key=?", (folder.name,)).fetchone()
                    if row is None or self._checked_meta(folder.path, row[0]) is None:
                        self._remove(folder.name)
                    known.add(folder.name)
        gone = list(indexed - known)
        for start in range(0, len(gone), 500):
            if should_stop():
                with self.lock:
                    self.db.commit()
                return
            with self.lock:
                for key in gone[start:start + 500]:
                    if not self._exists(key):              # not stored again since the walk began
                        self._remove(key)
        with self.lock:
            self.db.commit()

    @staticmethod
    def _checked_meta(folder: str, indexed: Optional[str]) -> Optional[dict]:
        """The meta of the complete object in `folder`, else None. `indexed` is the index's copy of it, if any: then
        meta.json is not opened, only the folder's listing is compared with the sizes in it."""
        try:
            sizes = {}
            with os.scandir(folder) as listing:
                for entry in listing:
                    if entry.is_file():
                        sizes[entry.name] = entry.stat().st_size
            if "meta.json" not in sizes:
                return None
            meta = None
            if indexed is not None:
                try:
                    meta = json.loads(indexed)
                except ValueError:
                    meta = None
            if not isinstance(meta, dict):
                meta = json.loads(Path(folder, "meta.json").read_text(encoding="utf-8"))
            if meta.get("format") != STORE_FORMAT:
                return None
            for filename, size in meta["files"].items():
                if sizes.get(filename) != size:
                    return None
            return meta
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None

    # -- eviction ----------------------------------------------------------------

    def enforce_limit(self, limit_bytes: int, *, protected_decks: Iterable[str] = (),
                      is_orphan: Callable[[list], bool] = lambda decks: False) -> int:
        """Delete orphans (`is_orphan(decks)`), then the least recently used outside `protected_decks` while over
        `limit_bytes`; the protected ones only above twice the limit. Returns how many were deleted."""
        protected = set(protected_decks)
        deleted = 0
        with self.lock:
            rows = self.db.execute("SELECT key, bytes, last_used, decks FROM renders").fetchall()
            total = sum(r[1] for r in rows)
            order: list[tuple] = []
            for name, size, used, decks in rows:
                deck_list = json.loads(decks)
                if is_orphan(deck_list):
                    rank = 2
                elif not set(deck_list) & protected:
                    rank = 3
                else:
                    rank = 4
                order.append((rank, used, name, size))
            for rank, _used, name, size in sorted(order):
                if rank == 2 or total > limit_bytes and (rank == 3 or total > 2 * limit_bytes):
                    self._remove(name)
                    total -= size
                    deleted += 1
            self.db.commit()
        return deleted

    # -- failures ----------------------------------------------------------------

    def record_failure(self, key: str, kind: str, error: str, manifest: list) -> None:
        now = self._clock()
        with self.lock:
            row = self.db.execute("SELECT attempts, first_at, last_try FROM failures WHERE fast_key=?", (key,)).fetchone()
            attempts = (row[0] if row else 0) + 1
            wait = BACKOFF_SECONDS[min(attempts, len(BACKOFF_SECONDS)) - 1]
            self.db.execute("INSERT OR REPLACE INTO failures VALUES (?,?,?,?,?,?,?,?)",
                            (key, kind, attempts, error[-2000:], row[1] if row else now, now + wait, json.dumps(manifest), row[2] if row else None))
            self.db.commit()

    def failure(self, key: str) -> Optional[dict]:
        with self.lock:
            row = self.db.execute("SELECT kind, attempts, error, first_at, next_try_at, manifest FROM failures WHERE fast_key=?",
                                  (key,)).fetchone()
        if row is None:
            return None
        return dict(kind=row[0], attempts=row[1], error=row[2], first_at=row[3], next_try_at=row[4], manifest=json.loads(row[5]))

    def may_retry(self, failure: dict) -> bool:
        """Whether a failed unit whose inputs are unchanged is tried again automatically: never after a
        deterministic failure, after a transient one with backoff, at most MAX_TRANSIENT_ATTEMPTS times."""
        return (failure["kind"] == TRANSIENT and failure["attempts"] < MAX_TRANSIENT_ATTEMPTS
                and self._clock() >= failure["next_try_at"])

    def tried_last(self, key: str) -> bool:
        """Whether the failed unit of `key` had its try after everything else was rendered (note_last_try)."""
        with self.lock:
            return self.db.execute("SELECT 1 FROM failures WHERE fast_key=? AND last_try IS NOT NULL", (key,)).fetchone() is not None

    def note_last_try(self, key: str) -> None:
        with self.lock:
            self.db.execute("UPDATE failures SET last_try=? WHERE fast_key=?", (self._clock(), key))
            self.db.commit()

    def forget_failure(self, key: Optional[str] = None) -> None:
        with self.lock:
            if key is None:
                self.db.execute("DELETE FROM failures")
            else:
                self.db.execute("DELETE FROM failures WHERE fast_key=?", (key,))
            self.db.commit()

    def failures(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT fast_key, kind, attempts, error FROM failures ORDER BY first_at").fetchall()
        return [dict(key=r[0], kind=r[1], attempts=r[2], error=r[3]) for r in rows]

    # -- deck usage ----------------------------------------------------------------

    def touch_deck(self, deck: str, slide: Optional[str] = None, view: Optional[str] = None,
                   language: Optional[str] = None, *, opened: bool = False) -> None:
        now = self._clock()
        with self.lock:
            row = self.db.execute("SELECT open_count, last_opened, last_slide, last_view, last_language FROM deck_usage WHERE deck=?",
                                  (deck,)).fetchone()
            if row is None:
                self.db.execute("INSERT INTO deck_usage VALUES (?,?,?,?,?,?)", (deck, now, 1, slide, view, language))
            else:
                count, last, old_slide, old_view, old_language = row
                self.db.execute("UPDATE deck_usage SET last_opened=?, open_count=?, last_slide=?, last_view=?, last_language=? WHERE deck=?",
                                (now if opened else last, count + (1 if opened else 0), slide or old_slide,
                                 view or old_view, language or old_language, deck))
            self.db.commit()

    def deck_usage(self) -> list[dict]:
        """Decks opened on this machine, most recently opened first."""
        with self.lock:
            rows = self.db.execute("SELECT deck, last_opened, open_count, last_slide, last_view, last_language "
                                   "FROM deck_usage ORDER BY last_opened DESC").fetchall()
        return [dict(deck=r[0], last_opened=r[1], open_count=r[2], last_slide=r[3], last_view=r[4], last_language=r[5]) for r in rows]


def project_id(root: Path) -> str:
    return project.project_id(root)
