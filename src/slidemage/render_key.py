# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The content-addressed key of a background render, and the test whether a stored render is still current.

docs/plans/idle-background-rendering.md, section 3. A *unit* is what the Preview would render for one slide
call of a deck in one view and language, with every reveal step (an unrestricted render: no `steps`).
Its **fast key** is a hash of everything that is known without running TeX: the captured slide text, the
call, view, language, the deck's preamble, the template, the TeX engine and the project's latexmk
settings. The **manifest** of a render lists every project file the run read (taken from the inputs the
render recorded, see preview_build.recorded_inputs) with its SHA-256. A stored render is current iff
the fast key is the same *and* every manifest file still has its hash; TeX's own files (packages,
fonts) are covered by the engine line and, for a render made on this machine, their content states. The page number in the footer (`frame_number`) and the time of the render
are not part of the key: a render that differs only in the page number is FRESH_NUMBERING_DIFFERS.

Free of Qt; the TeX run itself is in background_renders.py.
"""
from __future__ import annotations

import csv
import io
import json
import os
import platform
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from . import citations, compiler, compile_records, deck_language, render_evidence, slide_templates
from .dep_hash import HashCache, norm
from .fileio import text_sha256
from .preview_target import PreviewTarget
from .project import ProjectContext

# Bump when the wrapper logic (slide_preview) or this key changes what a render looks like. A test
# guards the wrapper helpers' source (tests/test_render_key.py).
RENDER_SCHEMA = 3     # 2: every reveal step (all_steps) whatever the slide restricts; 3: pages 1920 px wide

KIND_PROJECT = "project"        # under the project folder: rel path from the root
KIND_FRAMEWORK = "framework"    # under a LaTeX framework folder (slide_templates.framework_dirs): rel path from it
KIND_ALT_TEXT = "alt-text"      # a project alt-text file: the hash of its rows for the render's pictures (v8.69.0)
KIND_MISSING_INPUT = "missing-input"   # a failed run's missing file: retry when it appears in a search folder

_SKIPPED_PARTS = ("luatex-cache", ".build", ".previews", "slidemage_preview_", "_slidemage_")
EVERY_RENDER_READS = ("alt-text.csv", "alt-text.json")      # media files every render reads, whatever its slide names


def unit_inputs(ctx: ProjectContext, paths, source_path: Path, texts: Optional[dict] = None) -> list[Path]:
    """The document's shared inputs, this slide's named inputs, and optional inputs no slide names.

    `texts` supplies captured buffers in place of saved sources, including any inlined by the wrapper.
    """
    texts = dict(texts or {})
    for path in {source_path, *[path for path in paths if compile_records.is_within(path, ctx.slides_dir)]}:
        if path not in texts:
            try:
                texts[path] = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                texts[path] = ""
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
    def named(text):
        remaining, found = list(maybe), []
        grown = True
        while grown:                                    # a snippet may name the picture
            grown = False
            for path in remaining[:]:
                if path.stem in text:
                    remaining.remove(path)
                    found.append(path)
                    grown = True
                    if path.suffix == ".tex":
                        try:
                            text += path.read_text(encoding="utf-8", errors="replace")
                        except OSError:
                            pass
        return found

    own = named(texts[source_path])
    claimed = set(named("\n".join(texts.values())))
    return kept + own + [path for path in maybe if path not in claimed]


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
    return f"{compile_records.engine_version()}|{platform.system()}"


def machine_id() -> str:
    return text_sha256(platform.node())[:12]


def _json_hash(data) -> str:
    return text_sha256(json.dumps(data, sort_keys=True))


@dataclass
class Manifest:
    entries: list = field(default_factory=list)     # [kind, rel, sha256]
    tex_digest: str = ""                            # of the TeX files' content states; local only
    tex_files: list = field(default_factory=list)   # [[path, state]] behind tex_digest
    stable: bool = True                             # False: a recorded input could not be hashed


class Resolver:
    """Keys, manifests and freshness for one project, over a HashCache and a store."""

    def __init__(self, ctx: ProjectContext, hashes: HashCache, store,
                 engine_fp: Optional[Callable[[], str]] = None) -> None:
        self.ctx, self.hashes, self.store = ctx, hashes, store
        self._engine_fp = engine_fp or default_engine_fp
        self._engine_cache: Optional[str] = None
        self._alt_memo: dict[str, tuple[Optional[str], tuple[dict, dict]]] = {}

    @property
    def engine_fp(self) -> str:
        if self._engine_cache is None:
            self._engine_cache = self._engine_fp()
        return self._engine_cache

    # -- the fast key ------------------------------------------------------------

    def fast_key(self, unit: Unit, text: Optional[str] = None, *, strict=False, validation=None) -> Optional[str]:
        """The key of captured `text` (else the saved source), or None when the source cannot be read stably."""
        slide_sha = self.hashes.hash(unit.source_path, verify=strict) if text is None else text_sha256(text)
        if slide_sha is None:
            return None
        validation = validation or render_evidence.ValidationPass()
        configuration = validation.configuration(self.ctx.root, validation.build_env(self.ctx))
        return _json_hash({
            "schema": RENDER_SCHEMA, "slide": slide_sha,
            "call": [unit.macro, unit.id_slug, unit.version, list(unit.conditions)],
            "view": unit.view, "language": unit.language, "template": unit.template,
            "preamble": text_sha256(unit.preamble_text or ""),
            "engine": self.engine_fp, "configuration": configuration,
            **({"context": unit.context} if unit.context else {}),
            # What the wrapper tells TeX about the project's languages.
            "languages": deck_language.language_lines(self.ctx, unit.language),
        })

    def capture(self, unit: Unit, text: Optional[str] = None) -> dict:
        """Evidence captured before the render starts, never reconstructed from its finished inputs."""
        started = time.time()
        inventory = render_evidence.search_inventory(self.ctx.root, compiler.build_env(self.ctx))
        return dict(started=started, inventory=inventory, key=self.fast_key(unit, text, strict=True))

    def publishable(self, unit: Unit, evidence: dict, manifest: Manifest) -> bool:
        if not manifest.stable or evidence["key"] is None or self.fast_key(unit, strict=True) != evidence["key"]:
            return False
        paths = [unit.source_path, *[self._resolve(kind, rel) for kind, rel, _sha in manifest.entries]]
        paths += [Path(path) for path, _state in manifest.tex_files]
        paths += [self.ctx.root / name for name in (".latexmkrc", "decks/.latexmkrc")
                  if (self.ctx.root / name).is_file()]
        try:
            for path in paths:
                if path is None:
                    return False
                info = path.stat()
                if max(info.st_mtime, info.st_ctime) >= evidence["started"]:
                    return False
            current = render_evidence.search_inventory(self.ctx.root, compiler.build_env(self.ctx))
            return render_evidence.inventory_state(current, paths) == render_evidence.inventory_state(evidence["inventory"], paths)
        except (OSError, ValueError):
            return False

    # -- manifests ---------------------------------------------------------------

    def build_manifest(self, inputs: list[str]) -> Manifest:
        """The manifest of a finished render from the inputs it recorded (absolute paths)."""
        manifest = Manifest()
        seen: set[str] = set()
        tex = []
        states = render_evidence.FileStates(render_evidence.search_roots(self.ctx.root, compiler.build_env(self.ctx)))
        for name in [*inputs, *[str(self.ctx.media_dir / name) for name in EVERY_RENDER_READS
                                if (self.ctx.media_dir / name).is_file()]]:
            path = Path(name)
            key = norm(path)
            if key in seen or any(part in key for part in _SKIPPED_PARTS):
                continue
            seen.add(key)
            where = None
            for root, kind in [(self.ctx.root, KIND_PROJECT), *[(d, KIND_FRAMEWORK) for d in slide_templates.framework_dirs(self.ctx.root)]]:
                try:
                    rel = Path(os.path.normpath(path)).relative_to(os.path.normpath(root))
                except ValueError:
                    continue
                where = kind, rel.as_posix()
                break
            if where is None:
                state = states(path)
                if state is not None:
                    tex.append([key, state])
                continue
            digest = self.hashes.hash(path, verify=True)
            if digest is None:
                manifest.stable = False
                continue
            manifest.entries.append([where[0], where[1], digest])
        # Another picture's alt text must leave this render current (v8.69.0).
        for entry in manifest.entries:
            kind, rel, _sha = entry
            if kind == KIND_PROJECT and Path(rel).name in EVERY_RENDER_READS:
                entry[:] = [KIND_ALT_TEXT, rel, self._alt_digest(self.ctx.root / rel, manifest.entries)]
        manifest.entries.sort()
        tex.sort()
        manifest.tex_files = tex
        manifest.tex_digest = _json_hash(tex) if tex else ""
        return manifest

    def _resolve(self, kind: str, rel: str) -> Optional[Path]:
        if kind in (KIND_PROJECT, KIND_ALT_TEXT):
            return self.ctx.root / rel
        for folder in slide_templates.framework_dirs(self.ctx.root):
            if (folder / rel).is_file():
                return folder / rel
        return None

    def missing_input_entry(self, name: str) -> list:
        """Remember even a dependency TeX could not read, so restoring it invalidates a stored failure."""
        paths = {folder / name for folder in [self.ctx.decks_dir, *slide_templates.template_dirs(self.ctx.root),
                                            *citations.citation_dirs()]}
        state = [[str(path), self.hashes.hash(path)] for path in sorted(paths)]
        return [KIND_MISSING_INPUT, name, _json_hash(state)]

    def manifest_current(self, entries: list, *, strict=False) -> bool:
        for kind, rel, sha in entries:
            if kind == KIND_MISSING_INPUT:
                if self.missing_input_entry(rel)[2] != sha:
                    return False
                continue
            path = self._resolve(kind, rel)
            if path is None:
                return False
            if kind == KIND_ALT_TEXT:
                if self._alt_digest(path, entries, strict=strict) != sha:
                    return False
            elif self.hashes.hash(path, verify=strict) != sha:
                return False
        return True

    # -- the alt-text files ----------------------------------------------------------

    def _alt_digest(self, path: Path, entries: list, *, strict=False) -> str:
        """The hash of the rows of the alt-text file `path` for the files in `entries`, matched as Slidemaster_alt.lua
        matches a picture: by its lower-case file name, or by the name without its extension."""
        names, stems = set(), set()
        for _kind, rel, _sha in entries:
            name = Path(rel).name.lower()
            if name not in EVERY_RENDER_READS:
                names.add(name)
                stems.add(Path(name).stem)
        by_name, by_stem = self._alt_rows(path, strict=strict)
        rows = {row for name in names for row in by_name.get(name, ())}
        rows |= {row for stem in stems for row in by_stem.get(stem, ())}
        return text_sha256("\n".join(sorted(rows)))

    def _alt_rows(self, path: Path, *, strict=False) -> tuple[dict, dict]:
        """The rows of an alt-text file by lower-case file name and by stem, each a JSON string; read once per
        content (the scan asks for every unit of every deck)."""
        sha = self.hashes.hash(path, verify=strict)
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

    def tex_current(self, record: dict, validation) -> bool:
        """Content checks with FileStates' process memo for unchanged TeX distribution files."""
        digest = record.get("tex_digest")
        if not digest or record.get("machine") != machine_id():
            return True
        if digest not in validation.tex:
            files = self.store.tex_files(digest)
            if files is None:
                validation.tex[digest] = False
            else:
                states = render_evidence.FileStates(render_evidence.search_roots(self.ctx.root, validation.build_env(self.ctx)))
                current = validation.inputs([path for path, _state in files], states)
                validation.tex[digest] = all(current[str(Path(path).absolute())] == state for path, state in files)
        return validation.tex[digest]

    # -- freshness ---------------------------------------------------------------

    def lookup(self, unit: Unit, key: Optional[str] = None, *, strict=False, validation=None) -> "Lookup":
        validation = validation or render_evidence.ValidationPass()
        key = self.fast_key(unit, strict=strict, validation=validation) if key is None else key
        if key is None:
            return Lookup(Freshness.MISSING, None, None)
        record = self.store.find(key)
        if record is not None and record.get("inventory") is not None:
            env = validation.build_env(self.ctx)
            if strict:
                inputs = [unit.source_path, *[self._resolve(kind, rel) for kind, rel, _sha in record["manifest"]],
                          *[Path(path) for path, _state in self.store.tex_files(record.get("tex_digest", "")) or []]]
                current = render_evidence.search_inventory(self.ctx.root, env, inputs=[path for path in inputs if path is not None])
            else:
                current = validation.inventory(self.ctx.root, env)
            paths = [unit.source_path, *[rel for _kind, rel, _sha in record["manifest"]]]
            # The key already covers the requested source text, which can be an unsaved buffer.
            entries = [entry for entry in record["manifest"] if self._resolve(*entry[:2]) != unit.source_path]
            if (render_evidence.inventory_state(current, paths) == record["inventory"]
                    and self.manifest_current(entries, strict=strict) and self.tex_current(record, validation)):
                same = record.get("frame_number") == unit.frame_number
                return Lookup(Freshness.FRESH if same else Freshness.FRESH_NUMBERING_DIFFERS, record, key)
        failure = self.store.failure(key)
        if failure is not None and self.manifest_current(failure["manifest"], strict=strict):
            return Lookup(Freshness.FAILED, None, key, failure)
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
        """Nothing more for the background sweep to do, apart from retrying failures when eligible."""
        return self.state in (Freshness.FRESH, Freshness.FAILED)
