# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The content-addressed key of a background render, and the test whether a stored render is still current.

docs/plans/idle-background-rendering.md, section 3. A *unit* is what the Preview would render for one slide
call of a deck in one view and language, with every reveal step (an unrestricted render: no `steps`).
Its **fast key** is a hash of everything that is known without running TeX: the slide file's bytes, the
call, view, language, the deck's preamble, the template, the TeX engine and the project's latexmk
settings. The **manifest** of a render lists every project file the run read (taken from the inputs the
render recorded, see preview_build.recorded_inputs) with its SHA-256. A stored render is current iff
the fast key is the same *and* every manifest file still has its hash; TeX's own files (packages,
fonts) are covered by the engine line, and for a render made on this machine by a stamp of their sizes
and modification times as well. The page number in the footer (`frame_number`) and the time of the render
are not part of the key: a render that differs only in the page number is FRESH_NUMBERING_DIFFERS.

Free of Qt; the TeX run itself is in background_renders.py.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import platform
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from . import compile_records, slide_snapshot
from .dep_hash import HashCache, norm
from .preview_target import PreviewTarget
from .project import ProjectContext

# Bump when the wrapper logic (slide_preview) or this key changes what a render looks like. A test
# guards the wrapper helpers' source (tests/test_render_key.py).
RENDER_SCHEMA = 3     # 2: every reveal step (all_steps) whatever the slide restricts; 3: pages 1920 px wide

KIND_PROJECT = "project"        # under the project folder: rel path from the root
KIND_FRAMEWORK = "framework"    # under a LaTeX framework folder (slide_snapshot.framework_dirs): rel path from it
KIND_ALT_TEXT = "alt-text"      # a project alt-text file: the hash of its rows for the render's pictures (v8.69.0)

_SKIPPED_PARTS = ("luatex-cache", ".build", ".previews", "slidemage_preview_", "_slidemage_")
EVERY_RENDER_READS = ("alt-text.csv", "alt-text.json")      # media files every render reads, whatever its slide names


def unit_inputs(ctx: ProjectContext, paths, source_path: Path, text: Optional[str] = None) -> list[Path]:
    """The files among `paths`, what a document of several slides read, that the pages of the slide at `source_path`
    depend on: not the other slides, and of the media and snippets those whose name its text (`text`, else the
    file's) or a snippet it uses mentions (a name without its extension too), and the alt texts every render reads."""
    if text is None:
        try:
            text = source_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
    slides, optional = ctx.slides_dir, (ctx.root / "media", ctx.root / "snippets")
    kept, maybe = [], []
    for path in paths:
        key = norm(path)
        if any(part in key for part in _SKIPPED_PARTS):
            continue
        if compile_records.is_within(path, slides):
            if key == norm(source_path):
                kept.append(path)                       # another slide does not change this one's page
        elif any(compile_records.is_within(path, folder) for folder in optional):
            (kept if path.name in EVERY_RENDER_READS else maybe).append(path)
        else:
            kept.append(path)
    grown = True
    while grown:                                        # a snippet may name the picture
        grown = False
        for path in maybe[:]:
            if path.stem in text:
                maybe.remove(path)
                kept.append(path)
                grown = True
                if path.suffix == ".tex":
                    try:
                        text += path.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        pass
    return kept


class Freshness(Enum):
    FRESH = "fresh"
    FRESH_NUMBERING_DIFFERS = "fresh, numbering differs"
    STALE = "stale"             # a render exists, but something it depends on changed
    MISSING = "missing"
    FAILED = "failed"           # failed with exactly this input state


@dataclass(frozen=True)
class Unit:
    deck: str                   # deck name ("" when rendered alone)
    macro: str
    id_slug: str
    version: Optional[str]
    conditions: tuple
    view: str
    language: str               # "EN" / "DE"
    frame_number: Optional[int]
    preamble_text: Optional[str]
    template: str
    source_path: Path
    context: str = ""           # the deck whose last compile a slide that needs its deck is typeset in ("": it does not)

    @property
    def label(self) -> str:
        return f"{self.deck or '-'}:{self.id_slug}:{self.view}:{self.language}"

    @property
    def render_conditions(self) -> Optional[list]:
        """What the wrapper's call carries: \\slidestep keeps no conditions (it is shown in every view)."""
        return None if self.macro == "slidestep" else (list(self.conditions) or None)


def unit_for(target: PreviewTarget, view: str, language: str, deck: str = "") -> Unit:
    """The unit of a Preview target: its steps are dropped (all steps are rendered)."""
    return Unit(deck, target.macro, target.id_slug, target.version,
                () if target.macro == "slidestep" else tuple(target.conditions or ()), view, language.upper(),
                target.frame_number, target.preamble_text, target.template, target.source_path,
                deck if target.needs_context and deck else "")


def default_engine_fp() -> str:
    """The TeX engine and the operating system, without paths: portable between machines of one project."""
    from . import compile_records
    return f"{compile_records.engine_version()}|{platform.system()}"


def machine_id() -> str:
    return hashlib.sha256(platform.node().encode()).hexdigest()[:12]


def _json_hash(data) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


@dataclass
class Manifest:
    entries: list = field(default_factory=list)     # [kind, rel, sha256]
    tex_digest: str = ""                            # of the TeX files' (path, size, mtime_ns); local only
    tex_files: list = field(default_factory=list)   # [[path, size, mtime_ns]] behind tex_digest
    stable: bool = True                             # False: a file was being written while the render ran


class Resolver:
    """Keys, manifests and freshness for one project, over a HashCache and a store."""

    def __init__(self, ctx: ProjectContext, hashes: HashCache, store,
                 engine_fp: Optional[Callable[[], str]] = None, clock: Callable[[], float] = time.time) -> None:
        self.ctx, self.hashes, self.store = ctx, hashes, store
        self._engine_fp = engine_fp or default_engine_fp
        self._clock = clock
        self._engine_cache: Optional[str] = None
        self._tex_memo: dict[str, tuple[float, bool]] = {}
        self._alt_memo: dict[str, tuple[Optional[str], tuple[dict, dict]]] = {}

    @property
    def engine_fp(self) -> str:
        if self._engine_cache is None:
            self._engine_cache = self._engine_fp()
        return self._engine_cache

    # -- the fast key ------------------------------------------------------------

    def fast_key(self, unit: Unit) -> Optional[str]:
        """The key of `unit`, or None when the slide file cannot be hashed right now (missing, being written)."""
        slide_sha = self.hashes.hash(unit.source_path)
        if slide_sha is None or self.hashes.is_racy(unit.source_path):
            return None
        rc = [self.hashes.hash(self.ctx.root / name) or "" for name in (".latexmkrc", "decks/.latexmkrc")]
        return _json_hash({
            "schema": RENDER_SCHEMA, "slide": slide_sha,
            "call": [unit.macro, unit.id_slug, unit.version, list(unit.conditions)],
            "view": unit.view, "language": unit.language, "template": unit.template,
            "preamble": hashlib.sha256((unit.preamble_text or "").encode()).hexdigest(),
            "engine": self.engine_fp, "rc": rc,
            **({"context": unit.context} if unit.context else {}),
        })

    # -- manifests ---------------------------------------------------------------

    def _relative(self, path: Path) -> Optional[tuple[str, str]]:
        for root, kind in [(self.ctx.root, KIND_PROJECT), *[(d, KIND_FRAMEWORK) for d in slide_snapshot.framework_dirs(self.ctx.root)]]:
            try:
                rel = Path(os.path.normpath(path)).relative_to(os.path.normpath(root))
            except ValueError:
                continue
            return kind, rel.as_posix()
        return None

    def build_manifest(self, inputs: list[str]) -> Manifest:
        """The manifest of a finished render from the inputs it recorded (absolute paths)."""
        manifest = Manifest()
        seen: set[str] = set()
        tex = []
        for name in inputs:
            path = Path(name)
            key = norm(path)
            if key in seen or any(part in key for part in _SKIPPED_PARTS):
                continue
            seen.add(key)
            where = self._relative(path)
            if where is None:
                try:
                    info = os.stat(path)
                except OSError:
                    continue
                tex.append([key, info.st_size, info.st_mtime_ns])
                continue
            digest = self.hashes.hash(path)
            if digest is None or self.hashes.is_racy(path):
                manifest.stable = False
                continue
            manifest.entries.append([where[0], where[1], digest])
        manifest.entries = self.narrow_alt_text(manifest.entries)
        manifest.entries.sort()
        tex.sort()
        manifest.tex_files = tex
        manifest.tex_digest = _json_hash(tex) if tex else ""
        return manifest

    def _resolve(self, kind: str, rel: str) -> Optional[Path]:
        if kind in (KIND_PROJECT, KIND_ALT_TEXT):
            return self.ctx.root / rel
        for folder in slide_snapshot.framework_dirs(self.ctx.root):
            if (folder / rel).is_file():
                return folder / rel
        return None

    def manifest_current(self, entries: list) -> bool:
        for kind, rel, sha in entries:
            path = self._resolve(kind, rel)
            if path is None or self.hashes.is_racy(path):
                return False
            if kind == KIND_ALT_TEXT:
                if self._alt_digest(path, entries) != sha:
                    return False
            elif self.hashes.hash(path) != sha:
                return False
        return True

    # -- the alt-text files ----------------------------------------------------------

    def narrow_alt_text(self, entries: list, recorded: Optional[dict] = None) -> list:
        """`entries` with each project alt-text file (EVERY_RENDER_READS) turned into a KIND_ALT_TEXT entry: the hash
        of its rows for the files the render read, not of the whole file, so a new alt text for another slide's
        picture leaves this render current (every preview went out of date with each new alt text up to v8.68.0, v8.69.0).
        `recorded`, the file hashes of a compile record: an alt-text file changed since then keeps its whole-file
        entry, which the check then finds out of date."""
        out = []
        for entry in entries:
            kind, rel, sha = entry
            if kind == KIND_PROJECT and Path(rel).name in EVERY_RENDER_READS:
                path = self.ctx.root / rel
                if recorded is None or self.hashes.hash(path) == sha:
                    entry = [KIND_ALT_TEXT, rel, self._alt_digest(path, entries)]
            out.append(entry)
        return out

    def _alt_digest(self, path: Path, entries: list) -> str:
        """The hash of the rows of the alt-text file `path` for the files in `entries`, matched as Slidemaster_alt.lua
        matches a picture: by its lower-case file name, or by the name without its extension."""
        names, stems = set(), set()
        for _kind, rel, _sha in entries:
            name = Path(rel).name.lower()
            if name not in EVERY_RENDER_READS:
                names.add(name)
                stems.add(Path(name).stem)
        by_name, by_stem = self._alt_rows(path)
        rows = {row for name in names for row in by_name.get(name, ())}
        rows |= {row for stem in stems for row in by_stem.get(stem, ())}
        return hashlib.sha256("\n".join(sorted(rows)).encode()).hexdigest()

    def _alt_rows(self, path: Path) -> tuple[dict, dict]:
        """The rows of an alt-text file by lower-case file name and by stem, each a JSON string; read once per
        content (the scan asks for every unit of every deck)."""
        sha = self.hashes.hash(path)
        memo = self._alt_memo.get(str(path))
        if memo is not None and memo[0] == sha:
            return memo[1]
        rows: list[tuple[str, str]] = []
        try:
            text = path.read_text(encoding="utf-8-sig")
            if path.suffix.lower() == ".json":
                images = json.loads(text).get("images", {})
                rows = [(image, json.dumps([image, data], sort_keys=True)) for image, data in images.items()]
            else:
                lines = list(csv.reader(io.StringIO(text)))
                rows = [(fields[0], json.dumps(fields)) for fields in lines[1:] if fields and fields[0]]
        except (OSError, ValueError, AttributeError):
            rows = [("", sha or "")]          # unreadable: every render that reads it is out of date when it changes
        by_name: dict[str, list[str]] = {}
        by_stem: dict[str, list[str]] = {}
        for image, row in rows:
            name = image.replace("\\", "/").rsplit("/", 1)[-1].lower()
            by_name.setdefault(name, []).append(row)
            by_stem.setdefault(Path(name).stem, []).append(row)
        self._alt_memo[str(path)] = (sha, (by_name, by_stem))
        return by_name, by_stem

    def tex_current(self, record: dict) -> bool:
        """The TeX files a render made on this machine read are as they were (stat only; remembered 60 s)."""
        digest = record.get("tex_digest")
        if not digest or record.get("machine") != machine_id():
            return True
        memo = self._tex_memo.get(digest)
        if memo and self._clock() - memo[0] < 60:
            return memo[1]
        files = self.store.tex_files(digest)
        ok = True
        if files is not None:
            for path, size, mtime in files:
                try:
                    info = os.stat(path)
                except OSError:
                    ok = False
                    break
                if (info.st_size, info.st_mtime_ns) != (size, mtime):
                    ok = False
                    break
        self._tex_memo[digest] = (self._clock(), ok)
        return ok

    # -- freshness ---------------------------------------------------------------

    def lookup(self, unit: Unit, key: Optional[str] = None) -> "Lookup":
        key = key or self.fast_key(unit)
        if key is None:
            return Lookup(Freshness.MISSING, None, None)
        records = self.store.find(key)        # background version first
        for record in records:
            if record.get("unstable"):
                continue
            if self.manifest_current(record["manifest"]) and self.tex_current(record):
                same = record.get("frame_number") == unit.frame_number
                return Lookup(Freshness.FRESH if same else Freshness.FRESH_NUMBERING_DIFFERS, record, key)
        failure = self.store.failure(key)
        if failure is not None and self.manifest_current(failure["manifest"]):
            return Lookup(Freshness.FAILED, None, key, failure)
        if records:
            return Lookup(Freshness.STALE, records[0], key)
        # An older render of the same unit under another key (the slide changed): shown as outdated.
        previous = self.store.latest_for_unit(unit.label)
        return Lookup(Freshness.STALE if previous else Freshness.MISSING, previous, key)


@dataclass
class Lookup:
    state: Freshness
    record: Optional[dict]
    key: Optional[str]
    failure: Optional[dict] = None

    @property
    def usable(self) -> bool:
        """The record's images are correct to show (apart from a footer page number)."""
        return self.state in (Freshness.FRESH, Freshness.FRESH_NUMBERING_DIFFERS)

    @property
    def final(self) -> bool:
        """Nothing more for the background sweep to do for this unit now (a render by the reveal slider is
        provisional, a render with another page number is refreshed last)."""
        return (self.state is Freshness.FRESH and self.record is not None and self.record.get("origin") == "background") \
            or self.state is Freshness.FAILED
