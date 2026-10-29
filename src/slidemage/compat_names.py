# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""compat.py change "slidemage-names-and-setup-layer" (v10.0.0, BREAKING): the framework's
files carry the SlideMage name instead of "Slidemaster".

This module holds the part of the change that renames and runs the whole change;
compat_setup.py holds the setup-layer rewrites (decks lose their \\usetheme line,
templates load SlideMage_setup and change catalog settings instead of creating them).

| Before                                  | After                              |
|-----------------------------------------|------------------------------------|
| Slidemaster_preamble_<key>.tex          | SlideMage_template_<key>.tex       |
| Slidemaster_preamble_base               | SlideMage_base                     |
| Slidemaster_project_macros.tex          | SlideMage_project_macros.tex       |
| Slidemaster.bib                         | SlideMage.bib                      |
| $SLIDEMASTER_LATEX in .latexmkrc        | $SLIDEMAGE_LATEX                   |

detect(root): the project's files that carry an old name (template, project macros and
bibliography files; decks, templates, .latexmkrc files and .scripts/*.py that mention one; stored file
names in .slidemage/*.json), plus every place the migration could not rewrite.

migrate(root): renames those three kinds of project files (the content of a bibliography
file is kept, byte for byte) and rewrites the names inside decks, templates, the project
macros, .latexmkrc, .scripts/*.py and .slidemage/*.json. A template whose live code (comments do not count)
still mentions Slidemaster after the rewrite is neither renamed nor rewritten, and neither is
a file whose new name is already taken: they stay as they are and detect() keeps reporting
them. Slides, snippets and frozen slide versions are not touched, since they do not name
these files in code; a comment that still says "Slidemaster" there is harmless.

Returns the planned bytes per file; a file to remove maps to None (compat.run_update).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from . import compat_setup
from .compat_types import BREAKS, Change, Finding
from .tex_source import is_commented

CHANGE_ID = "slidemage-names-and-setup-layer"

OLD_TEMPLATE_PREFIX = "Slidemaster_preamble_"
NEW_TEMPLATE_PREFIX = "SlideMage_template_"
OLD_BASE, NEW_BASE = "Slidemaster_preamble_base", "SlideMage_base"
OLD_MACROS, NEW_MACROS = "Slidemaster_project_macros", "SlideMage_project_macros"
OLD_BIB, NEW_BIB = "Slidemaster.bib", "SlideMage.bib"

# What is left of the old names once rewrite() is done: a file name, an environment variable or a Lua/Perl variable.
# The word on its own (a slide id, a title) is not a file reference and is left alone.
_LEFTOVER = re.compile(r"Slidemaster[_.]|SLIDEMASTER_|slidemaster_")
_KEY = r"[A-Za-z0-9_-]+"
_TEMPLATE_NAME = re.compile(r"^" + re.escape(OLD_TEMPLATE_PREFIX) + r"(" + _KEY + r")\.tex$")
_TEMPLATE_USE = re.compile(re.escape(OLD_TEMPLATE_PREFIX) + r"(" + _KEY + r")")
_BIB_USE = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(OLD_BIB))
_MACROS_USE = re.compile(re.escape(OLD_MACROS) + r"(?![A-Za-z0-9_])")
# Names that are not project files: the framework's Lua files and the environment variables of .latexmkrc.
_OTHER_NAMES = [
    (re.compile(r"Slidemaster_alt\.lua"), "SlideMage_alt.lua"),
    (re.compile(r"Slidemaster_layout\.lua"), "SlideMage_measure.lua"),
    (re.compile(r"SLIDEMASTER_(LATEX|PROJECT)"), r"SLIDEMAGE_\1"),
    (re.compile(r"slidemaster_(native_path|sep|windows|latex)"), r"slidemage_\1"),
]


# -- what a project holds ------------------------------------------------------------------

def _template_files(root: Path) -> list[Path]:
    return sorted(root.glob(OLD_TEMPLATE_PREFIX + "*.tex"))


def _new_template_name(old: str) -> str:
    key = _TEMPLATE_NAME.match(old).group(1)
    return NEW_BASE + ".tex" if key == "base" else f"{NEW_TEMPLATE_PREFIX}{key}.tex"


def _new_template_files(root: Path) -> list[Path]:
    """Templates that already carry the new name (a project the renaming half reached before the setup half)."""
    return sorted(root.glob(NEW_TEMPLATE_PREFIX + "*.tex"))


def _decks(root: Path) -> list[Path]:
    found = []
    for folder in (root / "decks", root / "decks" / "archive"):
        if folder.is_dir():
            found += [p for p in sorted(folder.glob("*.tex")) if not p.name.startswith("_slidemage")]
    return found


def _rc_files(root: Path) -> list[Path]:
    return [p for p in (root / ".latexmkrc", root / "decks" / ".latexmkrc") if p.is_file()]


def _script_files(root: Path) -> list[Path]:
    folder = root / ".scripts"
    return sorted(folder.glob("*.py")) if folder.is_dir() else []


def _json_files(root: Path) -> list[Path]:
    folder = root / ".slidemage"
    return sorted(folder.glob("*.json")) if folder.is_dir() else []


def _read(path: Path) -> Optional[str]:
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


# -- rewriting -----------------------------------------------------------------------------

def rewrite(text: str, *, blocked_keys=frozenset(), bib: bool = True, macros: bool = True) -> str:
    """`text` with every old name replaced, except the template keys in `blocked_keys`
    and, when switched off, the bibliography and project-macros names."""
    def template(match: re.Match) -> str:
        key = match.group(1)
        if key in blocked_keys:
            return match.group(0)
        return NEW_BASE if key == "base" else NEW_TEMPLATE_PREFIX + key

    text = _TEMPLATE_USE.sub(template, text)
    if macros:
        text = _MACROS_USE.sub(NEW_MACROS, text)
    if bib:
        text = _BIB_USE.sub(NEW_BIB, text)
    for pattern, new in _OTHER_NAMES:
        text = pattern.sub(new, text)
    return text


def _leftovers(text: str, kind: str) -> list[int]:
    """1-based line numbers of live code that still names an old file or variable."""
    lines = []
    for match in _LEFTOVER.finditer(text):
        if kind == "tex":
            if is_commented(text, match.start()):
                continue
        elif kind == "rc":
            line_start = text.rfind("\n", 0, match.start()) + 1
            if "#" in text[line_start:match.start()]:
                continue
        else:
            continue
        lines.append(text.count("\n", 0, match.start()) + 1)
    return sorted(set(lines))


class _Plan:
    """What migrate() does and what detect() reports, worked out once from the files."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.renames: dict[Path, Path] = {}        # old project file -> new
        self.problems: list[Finding] = []
        self.blocked_keys: set[str] = set()
        self.bib = self.macros = True
        self.files: dict[Path, bytes] = {}         # path -> new bytes, rewritten files only
        self.leftovers: list[Finding] = []

        self._plan_bib_and_macros()
        self._plan_templates()
        self._plan_texts()

    def _rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def _rename(self, old: Path, new_name: str) -> bool:
        new = old.with_name(new_name)
        if new.exists():
            self.problems.append(Finding(self._rel(old), 0, f"not renamed: {new_name} exists already"))
            return False
        self.renames[old] = new
        return True

    def _plan_bib_and_macros(self) -> None:
        bib = self.root / OLD_BIB
        if bib.is_file():
            self.bib = self._rename(bib, NEW_BIB)
        macros = self.root / (OLD_MACROS + ".tex")
        if macros.is_file():
            self.macros = self._rename(macros, NEW_MACROS + ".tex")

    def _plan_templates(self) -> None:
        for path in _template_files(self.root):
            text = _read(path)
            key = _TEMPLATE_NAME.match(path.name).group(1)
            if text is None:
                self.blocked_keys.add(key)
                self.problems.append(Finding(self._rel(path), 0, "not renamed: the file is not UTF-8 text"))
                continue
            rewritten = rewrite(text, bib=self.bib, macros=self.macros)
            left = _leftovers(rewritten, "tex")
            if left:
                self.blocked_keys.add(key)
                self.problems.append(Finding(
                    self._rel(path), left[0],
                    "not renamed or rewritten: it still names an old file or variable in a way this update does not know"))
            elif not self._rename(path, _new_template_name(path.name)):
                self.blocked_keys.add(key)

    def _plan_texts(self) -> None:
        kinds = [(p, "deck") for p in _decks(self.root)]
        kinds += [(p, "template" if _TEMPLATE_NAME.match(p.name).group(1) != "base" else "tex")
                  for p in _template_files(self.root) if _TEMPLATE_NAME.match(p.name).group(1) not in self.blocked_keys]
        kinds += [(p, "template") for p in _new_template_files(self.root)]
        kinds += [(self.root / (OLD_MACROS + ".tex"), "tex")] if self.macros else []
        kinds += [(p, "rc") for p in _rc_files(self.root) + _script_files(self.root)]
        kinds += [(p, "json") for p in _json_files(self.root)]
        for path, kind in kinds:
            text = _read(path) if path.is_file() else None
            if text is None:
                continue
            new = rewrite(text, blocked_keys=self.blocked_keys, bib=self.bib, macros=self.macros)
            if kind == "deck":
                new = compat_setup.deck(new)
            elif kind == "template":
                new, problem = compat_setup.template(new)
                if problem:
                    self.problems.append(Finding(self._rel(path), 0, problem))
            kind = "tex" if kind in ("deck", "template") else kind
            if new != text:
                self.files[path] = new.encode("utf-8")
            for line in _leftovers(new, kind):
                self.leftovers.append(Finding(self._rel(path), line, "still names an old file or variable; change it by hand"))
        # a blocked template keeps its own leftovers too
        for path in _template_files(self.root):
            if _TEMPLATE_NAME.match(path.name).group(1) in self.blocked_keys:
                text = _read(path)
                for line in _leftovers(text or "", "tex"):
                    self.leftovers.append(Finding(self._rel(path), line, "still names an old file or variable; change it by hand"))


def detect(root: Path) -> list[Finding]:
    plan = _Plan(root)
    findings = [Finding(plan._rel(old), 0, f"is named {new.name} from now on") for old, new in plan.renames.items()]
    findings += [Finding(plan._rel(path), 0, "names renamed files or variables, loads the theme itself or lacks the setup layer")
                 for path in plan.files if path not in plan.renames]
    return sorted(findings + plan.problems + plan.leftovers, key=lambda f: (f.file, f.line, f.message))


def migrate(root: Path) -> dict[Path, Optional[bytes]]:
    plan = _Plan(root)
    out: dict[Path, Optional[bytes]] = {}
    for path, data in plan.files.items():
        out[(plan.renames.get(path) or path).relative_to(root)] = data
    for old, new in plan.renames.items():
        out.setdefault(new.relative_to(root), old.read_bytes())    # a file without names in it moves as it is
        out[old.relative_to(root)] = None
    return out


CHANGE = Change(
    id=CHANGE_ID,
    since="v10.0.0",
    severity=BREAKS,
    title="The framework's files are named SlideMage, and templates load SlideMage_setup",
    description=(
        "Slidemaster_preamble_<key>.tex is now SlideMage_template_<key>.tex, "
        "Slidemaster_preamble_base.tex is SlideMage_base.tex, Slidemaster_project_macros.tex is "
        "SlideMage_project_macros.tex and Slidemaster.bib is SlideMage.bib. Decks, templates and "
        ".latexmkrc files name them, and the variable $SLIDEMASTER_LATEX is now $SLIDEMAGE_LATEX "
        "(also $SLIDEMASTER_PROJECT, now $SLIDEMAGE_PROJECT). A project that keeps the old names "
        "does not compile against this framework. Templates now start with \\input{SlideMage_setup}, "
        "which loads the beamer theme and defines every template setting with its default; a template "
        "changes a setting (\\renewcommand, \\setlength) instead of creating it (\\newcommand, "
        "\\newlength), and decks no longer load the theme (\\usetheme{gotham})."),
    fix=(
        "Rename the three kinds of project files, replace the old names inside your decks, "
        "templates and .latexmkrc files (\\input{Slidemaster_preamble_<key>} by "
        "\\input{SlideMage_template_<key>}, \\input{Slidemaster_preamble_base} by "
        "\\input{SlideMage_base}, Slidemaster.bib by SlideMage.bib, $SLIDEMASTER_LATEX by "
        "$SLIDEMAGE_LATEX), and rename the environment variables you set yourself. In each template, "
        "add \\input{SlideMage_setup} before its colors, turn \\newcommand of \\SMInstituteLogoPath, "
        "\\SMBulletColor, \\SMTitleBoxColor, \\SMTitleTextColor, \\SMFooterBoxColorDefault and "
        "\\SMFooterTextColor into \\renewcommand, delete \\newlength{\\SMLogoHeight}, and write "
        "\\SMFrametitleRightPadding for \\gothamFrametitleRightpading; in each deck, delete "
        "\\usetheme{gotham}."),
    detect=detect,
    migrate=migrate,
)
