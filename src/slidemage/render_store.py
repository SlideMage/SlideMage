"""The store of background renders (docs/plans/idle-background-rendering.md, section 4).

**Objects** live in the project, `.previews/render-store/objects/<ab>/<name>/`, and sync with it: write-once
folders holding `slide.pdf`, one `pNNN.png` per page (every reveal step) and `meta.json`, written last, with
the sizes of the other files. `<name>` is the render's key, or `<key>.bg` for a render made by the
background sweep (the reveal slider's own render of the same key is the provisional `<key>`, which the
`.bg` one replaces). Nothing in an object is ever modified, so a sync client never finds a conflict, and
an object without a complete `meta.json` (still arriving from another machine) is ignored.

The **index** is a SQLite file *outside* the project (`project.cache_dir()`; SQLite and sync clients do not
mix): a cache of the `meta.json` files (rebuilt by rescan()), the file hashes (dep_hash), the failures the
sweep remembers and the decks' usage on this machine. Free of Qt.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Iterable, Optional

from . import project
from .fileio import write_json

STORE_FORMAT = 1
ORIGIN_BACKGROUND = "background"
ORIGIN_REVEAL = "reveal"
BG_SUFFIX = ".bg"
DEFAULT_LIMIT_BYTES = 2 * 1024 ** 3
DEFAULT_KEEP_DAYS = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS renders (
    name TEXT PRIMARY KEY, fast_key TEXT NOT NULL, origin TEXT NOT NULL, unit TEXT NOT NULL,
    bytes INTEGER NOT NULL, rendered_at REAL NOT NULL, last_used REAL NOT NULL, decks TEXT NOT NULL, meta TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS renders_key ON renders(fast_key);
CREATE INDEX IF NOT EXISTS renders_unit ON renders(unit);
CREATE TABLE IF NOT EXISTS failures (
    fast_key TEXT PRIMARY KEY, kind TEXT NOT NULL, attempts INTEGER NOT NULL, error TEXT NOT NULL,
    first_at REAL NOT NULL, next_try_at REAL NOT NULL, manifest TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS texsets (digest TEXT PRIMARY KEY, files TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS deck_usage (
    deck TEXT PRIMARY KEY, last_opened REAL NOT NULL, open_count INTEGER NOT NULL,
    last_slide TEXT, last_view TEXT, last_language TEXT);
"""

DETERMINISTIC = "deterministic"
TRANSIENT = "transient"
BACKOFF_SECONDS = (300, 1800, 3 * 3600)
MAX_TRANSIENT_ATTEMPTS = 3


def store_root(ctx: project.ProjectContext) -> Path:
    return ctx.root / ".previews" / "render-store"


def object_dir(root: Path, name: str) -> Path:
    return root / "objects" / name[:2] / name


class RenderStore:
    def __init__(self, ctx: project.ProjectContext, local_dir: Optional[Path] = None,
                 clock: Callable[[], float] = time.time) -> None:
        self.ctx = ctx
        self.root = store_root(ctx)
        self.local_dir = Path(local_dir) if local_dir is not None else project.cache_dir() / "render-store" / project_id(ctx.root)
        self._clock = clock
        self._lock = threading.RLock()
        self.local_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.local_dir / "index.sqlite"), check_same_thread=False, timeout=30)
        with self._lock:
            self.db.executescript(SCHEMA)
            self.db.commit()
        self.lock = self._lock

    def close(self) -> None:
        with self._lock:
            self.db.close()

    # -- objects -----------------------------------------------------------------

    def put(self, key: str, origin: str, pdf: Path, pages: list[bytes], meta: dict, *, decks: Iterable[str] = ()) -> str:
        """Store a render and return its object name. A background render replaces the provisional render of
        the same key; a reveal render is not stored when the background one is there."""
        name = key + BG_SUFFIX if origin == ORIGIN_BACKGROUND else key
        with self._lock:
            if origin == ORIGIN_REVEAL and self._exists(key + BG_SUFFIX):
                self.link_decks(key + BG_SUFFIX, decks)
                return key + BG_SUFFIX
            if self._exists(name):
                self.link_decks(name, decks)
                return name
            target = object_dir(self.root, name)
            tmp = self.root / "tmp" / uuid.uuid4().hex
            tmp.mkdir(parents=True)
            try:
                shutil.copyfile(pdf, tmp / "slide.pdf")
                sizes = {"slide.pdf": (tmp / "slide.pdf").stat().st_size}
                for number, data in enumerate(pages, start=1):
                    (tmp / f"p{number:03d}.png").write_bytes(data)
                    sizes[f"p{number:03d}.png"] = len(data)
                tex_files = meta.pop("tex_files", None)      # kept in the local index only, not in the shared object
                meta = dict(meta, format=STORE_FORMAT, key=key, origin=origin, pages=len(pages), files=sizes,
                            bytes=sum(sizes.values()), decks=sorted(set(decks)))
                write_json(tmp / "meta.json", meta, indent=0)       # last: the object is complete only now
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.replace(tmp, target)
                except OSError:
                    if not target.exists():
                        raise
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            self._index(name, meta, tex_files)
            if origin == ORIGIN_BACKGROUND:
                self.delete(key)                    # the provisional render
            return name

    def _exists(self, name: str) -> bool:
        return (object_dir(self.root, name) / "meta.json").is_file()

    def _index(self, name: str, meta: dict, tex_files: Optional[list] = None) -> None:
        now = self._clock()
        self.db.execute(
            "INSERT OR REPLACE INTO renders VALUES (?,?,?,?,?,?,?,?,?)",
            (name, meta["key"], meta["origin"], meta.get("unit", ""), int(meta.get("bytes", 0)),
             float(meta.get("rendered_at", now)), now, json.dumps(meta.get("decks", [])), json.dumps(meta)))
        if meta.get("tex_digest") and tex_files:
            self.db.execute("INSERT OR IGNORE INTO texsets VALUES (?,?)", (meta["tex_digest"], json.dumps(tex_files)))
        self.db.commit()

    def find(self, key: str) -> list[dict]:
        """The renders of `key` that are complete on disk, the background one first."""
        with self._lock:
            rows = self.db.execute("SELECT name, meta FROM renders WHERE fast_key=? ORDER BY name DESC", (key,)).fetchall()
        found = []
        for name, meta in rows:
            if not self._exists(name):
                continue
            record = json.loads(meta)
            record["name"] = name
            record["dir"] = str(object_dir(self.root, name))
            found.append(record)
        found.sort(key=lambda r: r["origin"] != ORIGIN_BACKGROUND)
        return found

    def latest_for_unit(self, unit: str) -> Optional[dict]:
        with self._lock:
            row = self.db.execute("SELECT name, meta FROM renders WHERE unit=? ORDER BY rendered_at DESC LIMIT 1", (unit,)).fetchone()
        if row is None or not self._exists(row[0]):
            return None
        record = json.loads(row[1])
        record["name"], record["dir"] = row[0], str(object_dir(self.root, row[0]))
        return record

    def page(self, record: dict, number: int) -> Optional[bytes]:
        """The PNG of page `number` (1-based) of a record, and the use is remembered for the eviction."""
        try:
            data = (Path(record["dir"]) / f"p{number:03d}.png").read_bytes()
        except OSError:
            return None
        self.touch(record["name"])
        return data

    def pdf_path(self, record: dict) -> Path:
        return Path(record["dir"]) / "slide.pdf"

    def touch(self, name: str) -> None:
        with self._lock:
            self.db.execute("UPDATE renders SET last_used=? WHERE name=?", (self._clock(), name))
            self.db.commit()

    def tex_files(self, digest: str) -> Optional[list]:
        with self._lock:
            row = self.db.execute("SELECT files FROM texsets WHERE digest=?", (digest,)).fetchone()
        return json.loads(row[0]) if row else None

    def link_decks(self, name: str, decks: Iterable[str]) -> None:
        decks = set(decks)
        if not decks:
            return
        with self._lock:
            row = self.db.execute("SELECT decks FROM renders WHERE name=?", (name,)).fetchone()
            if row is None:
                return
            merged = sorted(set(json.loads(row[0])) | decks)
            self.db.execute("UPDATE renders SET decks=? WHERE name=?", (json.dumps(merged), name))
            self.db.commit()

    def delete(self, name: str) -> None:
        with self._lock:
            shutil.rmtree(object_dir(self.root, name), ignore_errors=True)
            self.db.execute("DELETE FROM renders WHERE name=?", (name,))
            self.db.commit()

    def drop_deck(self, deck: str) -> int:
        """A deck was archived: forget it in every render, deleting the renders only it used."""
        removed = 0
        with self._lock:
            rows = self.db.execute("SELECT name, decks FROM renders").fetchall()
            for name, decks in rows:
                names = json.loads(decks)
                if deck not in names:
                    continue
                names.remove(deck)
                if names:
                    self.db.execute("UPDATE renders SET decks=? WHERE name=?", (json.dumps(names), name))
                else:
                    shutil.rmtree(object_dir(self.root, name), ignore_errors=True)
                    self.db.execute("DELETE FROM renders WHERE name=?", (name,))
                    removed += 1
            self.db.execute("DELETE FROM deck_usage WHERE deck=?", (deck,))
            self.db.commit()
        return removed

    def clear(self) -> None:
        with self._lock:
            shutil.rmtree(self.root / "objects", ignore_errors=True)
            shutil.rmtree(self.root / "tmp", ignore_errors=True)
            self.db.execute("DELETE FROM renders")
            self.db.commit()

    def total_bytes(self) -> int:
        with self._lock:
            return self.db.execute("SELECT COALESCE(SUM(bytes), 0) FROM renders").fetchone()[0]

    def count(self) -> int:
        with self._lock:
            return self.db.execute("SELECT COUNT(*) FROM renders").fetchone()[0]

    def rescan(self) -> int:
        """Bring the index in line with the objects on disk: adopt complete objects it does not know (arrived
        by sync, or the index was lost), forget those that are gone, clear unfinished writes. Returns how
        many objects were adopted."""
        shutil.rmtree(self.root / "tmp", ignore_errors=True)
        known = set()
        adopted = 0
        objects = self.root / "objects"
        with self._lock:
            indexed = {row[0] for row in self.db.execute("SELECT name FROM renders")}
        if objects.is_dir():
            for shard in objects.iterdir():
                if not shard.is_dir():
                    continue
                for folder in shard.iterdir():
                    meta = self._read_meta(folder)
                    if meta is None:
                        continue
                    known.add(folder.name)
                    if folder.name not in indexed:
                        with self._lock:
                            self._index(folder.name, meta)
                        adopted += 1
        with self._lock:
            for name in indexed - known:
                self.db.execute("DELETE FROM renders WHERE name=?", (name,))
            self.db.commit()
        return adopted

    @staticmethod
    def _read_meta(folder: Path) -> Optional[dict]:
        try:
            meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
            if meta.get("format") != STORE_FORMAT:
                return None
            for filename, size in meta["files"].items():
                if (folder / filename).stat().st_size != size:
                    return None
            return meta
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None

    # -- eviction ----------------------------------------------------------------

    def enforce_limit(self, limit_bytes: int, *, protected_decks: Iterable[str] = (),
                      keep_days: int = DEFAULT_KEEP_DAYS, is_orphan: Callable[[list], bool] = lambda decks: False) -> int:
        """Delete renders until the store fits `limit_bytes`: first provisional renders that have a background
        one, renders older than `keep_days`, renders of nothing that exists any more (`is_orphan(decks)`), then
        the least recently used outside `protected_decks`; the protected ones only when the store is still more
        than twice over. Returns how many were deleted."""
        protected = set(protected_decks)
        deleted = 0
        with self._lock:
            rows = self.db.execute("SELECT name, fast_key, origin, bytes, last_used, decks FROM renders").fetchall()
            names = {r[0] for r in rows}
            total = sum(r[3] for r in rows)
            order: list[tuple] = []
            cutoff = self._clock() - keep_days * 86400
            for name, key, origin, size, used, decks in rows:
                deck_list = json.loads(decks)
                if origin == ORIGIN_REVEAL and key + BG_SUFFIX in names:
                    rank = 0
                elif used < cutoff and not set(deck_list) & protected:
                    rank = 1
                elif is_orphan(deck_list):
                    rank = 2
                elif not set(deck_list) & protected:
                    rank = 3
                else:
                    rank = 4
                order.append((rank, used, name, size))
            for rank, _used, name, size in sorted(order):
                if rank <= 2 or total > limit_bytes and (rank == 3 or total > 2 * limit_bytes):
                    shutil.rmtree(object_dir(self.root, name), ignore_errors=True)
                    self.db.execute("DELETE FROM renders WHERE name=?", (name,))
                    total -= size
                    deleted += 1
            self.db.commit()
        return deleted

    # -- failures ----------------------------------------------------------------

    def record_failure(self, key: str, kind: str, error: str, manifest: list) -> None:
        now = self._clock()
        with self._lock:
            row = self.db.execute("SELECT attempts, first_at FROM failures WHERE fast_key=?", (key,)).fetchone()
            attempts = (row[0] if row else 0) + 1
            wait = BACKOFF_SECONDS[min(attempts, len(BACKOFF_SECONDS)) - 1]
            self.db.execute("INSERT OR REPLACE INTO failures VALUES (?,?,?,?,?,?,?)",
                            (key, kind, attempts, error[-2000:], row[1] if row else now, now + wait, json.dumps(manifest)))
            self.db.commit()

    def failure(self, key: str) -> Optional[dict]:
        with self._lock:
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

    def forget_failure(self, key: Optional[str] = None) -> None:
        with self._lock:
            if key is None:
                self.db.execute("DELETE FROM failures")
            else:
                self.db.execute("DELETE FROM failures WHERE fast_key=?", (key,))
            self.db.commit()

    def failures(self) -> list[dict]:
        with self._lock:
            rows = self.db.execute("SELECT fast_key, kind, attempts, error FROM failures ORDER BY first_at").fetchall()
        return [dict(key=r[0], kind=r[1], attempts=r[2], error=r[3]) for r in rows]

    # -- deck usage ----------------------------------------------------------------

    def touch_deck(self, deck: str, slide: Optional[str] = None, view: Optional[str] = None,
                   language: Optional[str] = None, *, opened: bool = False) -> None:
        now = self._clock()
        with self._lock:
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
        with self._lock:
            rows = self.db.execute("SELECT deck, last_opened, open_count, last_slide, last_view, last_language "
                                   "FROM deck_usage ORDER BY last_opened DESC").fetchall()
        return [dict(deck=r[0], last_opened=r[1], open_count=r[2], last_slide=r[3], last_view=r[4], last_language=r[5]) for r in rows]


def project_id(root: Path) -> str:
    import hashlib
    return hashlib.sha256(os.path.normcase(os.path.normpath(str(root.resolve()))).encode()).hexdigest()[:16]
