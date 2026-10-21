# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Export LaTeX (v8.44.0, docs/MENU_UPDATE_PLAN.md step M4): one deck as a folder that compiles as it is, on a
machine that has only a TeX distribution -- no SlideMage project around it.

``<destination>/<deck name>-latex/`` holds the deck at its root (its ``\\input@path`` and ``\\graphicspath``
lines point at the root instead of the parent of decks/), the slides it calls under ``slides/``, the media
those slides use under ``media/``, and every other file the build reads from the project or the LaTeX
framework: the institution and base preambles, the theme files, logos, schemes, snippets, the .bib and the
alt-text store. A small ``.latexmkrc`` selects lualatex. Build it with ``latexmk <deck name>.tex``.

Unlike a deck snapshot (deck_snapshot.py: the files a real compile read, a frozen copy that renders to the
same PDF) this follows the sources: it walks the deck's text the way the compiler would, with the search path
of the project's .latexmkrc (decks/, the project root, the framework). The slide calls and the media
references are read by the code that archives unused content (unused_content.py), the framework folders are
found as the slide previews find them (slide_snapshot.framework_dirs). Files that belong to the TeX
distribution are not found there and so not copied. A file the sources name but the project does not hold is
reported in ExportResult.missing; the rest is exported.

Free of Qt.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import unused_content
from .deck_scan import Deck
from .project import ProjectContext
from .slide_snapshot import framework_dirs
from .tex_source import COMMENT_RE

FOLDER_SUFFIX = "-latex"
LATEXMKRC = """$pdf_mode = 4;
$lualatex = 'lualatex -synctex=1 -interaction=nonstopmode -file-line-error %O %S';
"""
ALT_TEXT_FILES = ("media/alt-text.json", "media/alt-text.csv")

# Files whose own text names more files; the rest (images, fonts, data) are copied as they are.
TEXT_SUFFIXES = {".tex", ".sty", ".cls", ".lua"}
FILE_SUFFIXES = TEXT_SUFFIXES | {".pdf", ".png", ".jpg", ".jpeg", ".svg", ".eps", ".gif", ".bib", ".csv", ".json",
                                 ".ttf", ".otf"}
# A name with one of those suffixes, anywhere in a text (a logo path in a \newcommand, a Lua file in kpse.find_file).
TOKEN_RE = re.compile(r"(?<![\w/.:@\\-])\w[\w.+-]*(?:/\w[\w.+-]*)*")
# Commands whose argument is a file name, possibly without its suffix; the first group is what a missing file is reported for.
NAMED_FILE_RE = re.compile(
    r"\\(?P<command>input|include|includegraphics|SMCodeFile|lstinputlisting|usepackage|RequirePackage|documentclass)"
    r"\s*(?:\[[^\]]*\])?\s*\{(?P<names>[^{}\\#%]+)\}")
REPORTED_COMMANDS = {"input", "include", "includegraphics", "SMCodeFile", "lstinputlisting"}
# These typeset a file's text as code; what is in it is not part of the build.
LISTING_COMMANDS = {"SMCodeFile", "lstinputlisting"}
IMPLIED_SUFFIXES = ("", ".tex", ".sty", ".cls")
# \usetheme{gotham} loads beamerthemegotham.sty; \usecolortheme{x} beamercolorthemex.sty, and so on.
THEME_RE = re.compile(r"\\use(?P<kind>color|font|inner|outer)?theme\s*(?:\[[^\]]*\])?\s*\{(?P<names>[^{}]+)\}")
# fontspec's Path=fonts/ : a folder of font files, copied whole.
FONT_DIR_RE = re.compile(r"\bPath\s*=\s*(?:\./)?([\w][\w./-]*)")
# The path lines a deck in decks/ starts with: the root is the parent folder there, the folder itself here.
PATH_LINE_RE = re.compile(r"^(\s*(?:\\def\\input@path|\\graphicspath)\s*\{\{)(?:\.\./)+(\}\})", re.MULTILINE)
DEFAULT_BIBLIOGRAPHY_RE = re.compile(r"\\SMUseBibliography(?!\s*\[)")


@dataclass
class ExportResult:
    folder: Path
    files: list[str] = field(default_factory=list)      # relative to the folder, forward slashes
    missing: list[str] = field(default_factory=list)    # named by the sources, not found in the project

    def summary(self) -> str:
        text = f"Exported {len(self.files)} file(s) to {self.folder}"
        return text + (f"; {len(self.missing)} referenced file(s) not found" if self.missing else "")


class _Collector:
    """The files the deck needs: destination path (relative to the exported folder) -> source."""

    def __init__(self, ctx: ProjectContext, deck: Deck) -> None:
        self.ctx = ctx
        self.deck = deck
        self.frameworks = framework_dirs(ctx.root)
        # TeX's search path during a compile: the deck's folder, the project root, then the framework.
        self.search = [ctx.decks_dir, ctx.root, *self.frameworks]
        self.files: dict[str, Path] = {}
        self.missing: set[str] = set()
        self._texts: list[str] = []         # the project's own texts, for the media references
        self._queue: list[Path] = []
        self._listings: set[Path] = set()   # files shown as code, never read for references

    def destination(self, source: Path) -> str:
        """Where a source file goes: decks/ files to the root, project files where they are, framework files to the root."""
        for base in (self.ctx.decks_dir, self.ctx.root, *self.frameworks):
            if source.is_relative_to(base):
                return source.relative_to(base).as_posix()
        raise ValueError(source)

    def add(self, source: Path) -> None:
        dest = self.destination(source)
        if dest not in self.files:                  # the first folder on the search path wins, as in TeX
            self.files[dest] = source
            if source.suffix.lower() in TEXT_SUFFIXES and source not in self._listings:
                self._queue.append(source)

    def add_tree(self, folder: Path) -> None:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                self.add(path)

    def find(self, name: str, suffixes: tuple[str, ...]) -> list[Path]:
        """What `name` is on the search path: the file, else (a graphic named without its suffix) the files sharing its stem."""
        for folder in self.search:
            for suffix in suffixes:
                if (folder / (name + suffix)).is_file():
                    return [folder / (name + suffix)]
        stem = Path(name)
        for folder in self.search:
            if suffixes == ("",) and not stem.suffix and (folder / stem.parent).is_dir():
                siblings = [p for p in (folder / stem.parent).iterdir() if p.is_file() and p.stem == stem.name]
                if siblings:
                    return siblings
        return []

    def reference(self, name: str, suffixes: tuple[str, ...], own: bool, report: bool, listing: bool = False) -> None:
        if name.startswith("media/"):
            return                                  # media_references() decides these
        found = self.find(name, suffixes)
        if listing:
            self._listings.update(found)
        for path in found:
            self.add(path)
        if not found and own and report:
            self.missing.add(name)

    def scan(self, source: Path) -> None:
        """Read one text file for the files it names. `own` texts (not the framework's) also name slides, media and the .bib."""
        own = not any(source.is_relative_to(framework) for framework in self.frameworks)
        text = COMMENT_RE.sub("", source.read_text(encoding="utf-8", errors="replace"))
        if own:
            self._texts.append(text)
            if source.parent == self.ctx.decks_dir or source == self.deck.path:
                self._scan_slides(text)
            if DEFAULT_BIBLIOGRAPHY_RE.search(text):
                self.reference("Slidemaster.bib", ("",), own, True)
        for match in NAMED_FILE_RE.finditer(text):
            command = match.group("command")
            suffixes = IMPLIED_SUFFIXES if command in {"input", "include", "usepackage", "RequirePackage",
                                                       "documentclass"} else ("",)
            for name in (n.strip() for n in match.group("names").split(",")):
                self.reference(name, suffixes, own, command in REPORTED_COMMANDS, command in LISTING_COMMANDS)
        for match in THEME_RE.finditer(text):
            for name in (n.strip() for n in match.group("names").split(",")):
                self.reference(f"beamer{match.group('kind') or ''}theme{name}.sty", ("",), own, False)
        for token in TOKEN_RE.findall(text):
            if Path(token).suffix.lower() in FILE_SUFFIXES:
                self.reference(token, ("",), own, "/" in token)
        for match in FONT_DIR_RE.finditer(text):
            name = match.group(1).rstrip("/")
            for folder in self.search:
                if (folder / name).is_dir():
                    self.add_tree(folder / name)
                    break

    def _scan_slides(self, text: str) -> None:
        for name in sorted(unused_content.slide_filenames_in(self.ctx, text)):
            path = self.ctx.slides_dir / name
            if path.is_file():
                self.add(path)
            else:
                self.missing.add(f"slides/{name}")

    def collect(self) -> None:
        """Walk from the deck through everything it names (slides, preambles, fragments, themes...)."""
        self._queue.append(self.deck.path)
        while self._queue:
            self.scan(self._queue.pop())
        used, missing = unused_content.media_references(self.ctx, self._texts)
        self.missing |= missing
        for name in sorted(used):
            self.files.setdefault(f"media/{name}", self.ctx.media_dir / name)
        for rel in ALT_TEXT_FILES:
            if (self.ctx.root / rel).is_file():
                self.files.setdefault(rel, self.ctx.root / rel)


def _copy(source: Path, dest: Path, root_paths: bool) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if root_paths:
        data = source.read_bytes().decode("utf-8")
        dest.write_bytes(PATH_LINE_RE.sub(r"\1./\2", data).encode("utf-8"))
    else:
        shutil.copy2(source, dest)


def _rename(source: Path, target: Path, tries: int = 50) -> None:
    """os.replace, tried again for a few seconds while Windows denies it: a virus scanner or the search indexer
    briefly holds files that were just written."""
    for attempt in range(tries):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(0.1)


def export_deck(ctx: ProjectContext, deck: Deck, dest_dir: Path,
                log: Optional[Callable[[str], None]] = None) -> ExportResult:
    """Write ``<dest_dir>/<deck.name>-latex/``, replacing a folder of that name. The files are written into a
    scratch folder next to it first and renamed at the end, so a failure leaves the old folder (if any) and no
    half-written one."""
    collector = _Collector(ctx, deck)
    collector.collect()
    # The deck itself (it may be an archived one) is the .tex of its name at the root.
    collector.files[f"{deck.name}.tex"] = deck.path
    files = collector.files
    target = Path(dest_dir) / f"{deck.name}{FOLDER_SUFFIX}"
    scratch = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=dest_dir))
    old = None
    try:
        for dest, source in sorted(files.items()):
            _copy(source, scratch / dest, source.parent == ctx.decks_dir or source == deck.path)
        (scratch / ".latexmkrc").write_text(LATEXMKRC, encoding="utf-8", newline="\n")
        # The old folder goes aside and is deleted only once the new one is in place, so a failure keeps it.
        old = Path(tempfile.mkdtemp(prefix=f".{target.name}-old-", dir=dest_dir)) / "old" if target.exists() else None
        if old is not None:
            _rename(target, old)
        try:
            _rename(scratch, target)
        except BaseException:
            if old is not None:
                _rename(old, target)
            raise
    except BaseException:
        shutil.rmtree(scratch, ignore_errors=True)
        if old is not None and not old.exists():          # put back; one that could not be is left where it is
            shutil.rmtree(old.parent, ignore_errors=True)
        raise
    if old is not None:
        shutil.rmtree(old.parent, ignore_errors=True)
    result = ExportResult(target, sorted([*files, ".latexmkrc"]), sorted(collector.missing))
    if log is not None:
        for name in result.missing:
            log(f"*** Export LaTeX: {name} is referenced but not in the project ***")
        log(f"==== {result.summary()} ====")
    return result
