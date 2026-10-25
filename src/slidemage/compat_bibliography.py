# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""compat.py change "bibliography-in-template" (v5.32.0): the citation format
moved from the course decks into the institution template.

Before: every deck that used references carried the same ~90 lines (biblatex
with the house options, the .bib lookup, name format, field formats and four
bibliography drivers). Now a deck says SMUseBibliography and its template
(an institution template, the SlideMage template, ...) defines the
format once (bibliography_house.BLOCK).

Not breaking -- a deck with its own copy still compiles -- but it is the
reference case for the compatibility check's migrations, so it asks (severity
LAYOUT: the dialog on start).

detect(root): one finding per deck whose copy is the house format, code line
for line (comments and blank lines ignored). A deck that differs (a variant on
purpose, an older driver) is left alone and not reported.

migrate(root): for each such deck, replaces the copied block (and the comment
directly above it, if that is about the bibliography) by SMUseBibliography,
and makes sure the deck's template defines the house format: a template file
of the project that has no SMBibliographyStyle yet gets BLOCK inserted after
its input of the base preamble; a framework template (the SlideMage one) must
already have it, else the deck is skipped (update the framework first). A
deck whose template defines a different SMBibliographyStyle is skipped too --
moving the deck would change its format.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import bibliography_house, slide_snapshot
from .compat_types import LAYOUT, Change, Finding

BS = chr(92)
CHANGE_ID = "bibliography-in-template"

_PACKAGE = BS + "usepackage[style=authoryear"
_FINENTRY = BS + "finentry}"
_INPUT_TEMPLATE = re.compile(re.escape(BS + "input{SlideMage_template_") + r"([A-Za-z0-9_-]+)\}")
_INPUT_LINE = re.compile(r"^" + re.escape(BS + "input{") + r"SlideMage_(?:base|project_macros)\}")
_STYLE_MACRO = BS + "renewcommand{" + BS + "SMBibliographyStyle}"

DECK_CALL = (
    "% Bibliography (biblatex + biber, opt-in per deck): the .bib lookup and the house\n"
    "% citation format come from the institution template (" + BS + "SMUseBibliography,\n"
    "% defined in SlideMage_base.tex; the format in this deck's template\n"
    "% file). To use another format in this deck, redefine " + BS + "SMBiblatexOptions /\n"
    "% " + BS + "SMBibliographyStyle before the call.\n"
    + BS + "SMUseBibliography")


def _code(lines) -> list[str]:
    return [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("%")]


def _block_lines() -> list[str]:
    return bibliography_house.BLOCK.rstrip("\n").split("\n")


def _style_lines(lines: list[str]) -> list[str]:
    """The lines of a template's SMBibliographyStyle definition (from its
    renewcommand to the end of `lines`' block), # undoubled."""
    start = next((i for i, ln in enumerate(lines) if ln.startswith(_STYLE_MACRO)), None)
    if start is None:
        return []
    out = []
    for ln in lines[start + 1:]:
        if ln == "}":
            break
        out.append(ln.replace("##", "#"))
    return out


def _house_deck_code() -> list[str]:
    """The code lines a deck carries when it has an unmodified copy."""
    block = _block_lines()
    options_line = next(ln for ln in block if ln.startswith(BS + "renewcommand{" + BS + "SMBiblatexOptions}"))
    options = options_line[options_line.index("}{") + 2:-1]
    lookup = [
        BS + "makeatletter",
        BS + "let" + BS + "SMSavedInputPath" + BS + "input@path",
        BS + "def" + BS + "input@path{}%",
        BS + "IfFileExists{SlideMage.bib}{" + BS + "addbibresource{SlideMage.bib}}{"
        + BS + "addbibresource{../SlideMage.bib}}",
        BS + "let" + BS + "input@path" + BS + "SMSavedInputPath",
        BS + "makeatother",
    ]
    return _code([BS + "usepackage[" + options + "]{biblatex}", *lookup, *_style_lines(block)])


def _deck_region(lines: list[str]):
    """(first, use, last): the first line to replace (the usepackage line moved
    up over the contiguous comment lines above it when those are about the
    bibliography), the usepackage line, the end of the last driver."""
    try:
        use = next(i for i, ln in enumerate(lines) if ln.startswith(_PACKAGE))
        last = max(i for i, ln in enumerate(lines) if ln.strip() == _FINENTRY)
    except (StopIteration, ValueError):
        return None
    if last < use:
        return None
    first = use
    while first > 0 and lines[first - 1].startswith("%"):
        first -= 1
    if not any("ibliograph" in ln or "biblatex" in ln for ln in lines[first:use]):
        first = use
    return first, use, last


def _read(path: Path) -> tuple[str, str]:
    raw = path.read_bytes().decode("utf-8")
    return raw.replace("\r\n", "\n"), ("\r\n" if "\r\n" in raw else "\n")


def decks(root: Path):
    for folder in (root / "decks", root / "decks" / "archive"):
        if folder.is_dir():
            yield from sorted(folder.glob("*.tex"))


def _house_copies(root: Path):
    """(deck path, lines, region) of every deck with an unmodified copy."""
    want = _house_deck_code()
    for path in decks(root):
        try:
            text, _eol = _read(path)
        except (OSError, UnicodeDecodeError):
            continue
        lines = text.split("\n")
        region = _deck_region(lines)
        if region and _code(lines[region[1]:region[2] + 1]) == want:
            yield path, lines, region


def _template_state(root: Path, deck_text: str):
    """(template path or None, state): "ready" (the template defines the house
    format), "add" (a project file that can get it), or a sentence saying why
    the deck stays as it is."""
    m = _INPUT_TEMPLATE.search(deck_text)
    if not m:
        return None, "its template is not one of the SlideMage_template_* files"
    path = slide_snapshot.preamble_file(m.group(1), root)
    if not path.is_file():
        return None, f"template SlideMage_template_{m.group(1)}.tex not found"
    text, _ = _read(path)
    inside = root.resolve() in path.resolve().parents
    if _STYLE_MACRO in text:
        same = _code(_style_lines(text.split("\n"))) == _code(_style_lines(_block_lines()))
        return path, "ready" if same else "its template defines another citation format"
    if not inside:
        return path, "the framework's template has no citation format yet -- update the framework first"
    return path, "add"


def _framework_ready(root: Path) -> bool:
    for folder in slide_snapshot.framework_dirs(root):
        base = folder / "SlideMage_base.tex"
        if "SMUseBibliography" in base.read_text(encoding="utf-8", errors="replace"):
            return True
    return False


def detect(root: Path) -> list[Finding]:
    out = []
    ready = _framework_ready(root)
    for path, lines, (_first, use, last) in _house_copies(root):
        _tpl, state = _template_state(root, "\n".join(lines))
        rel = path.relative_to(root).as_posix()
        if state in ("ready", "add"):
            note = "" if ready else " (the framework here has no SMUseBibliography yet -- update it first)"
            msg = f"carries its own copy of the house citation format ({last - use + 1} lines){note}"
        else:
            msg = f"carries a copy of the house citation format, left as it is: {state}"
        out.append(Finding(rel, use + 1, msg))
    return out


def migrate(root: Path) -> dict[Path, bytes]:
    plan: dict[Path, bytes] = {}
    if not _framework_ready(root):
        return plan                                  # the new command is not there to call
    templates: list[Path] = []
    for path, lines, (first, _use, last) in _house_copies(root):
        tpl, state = _template_state(root, "\n".join(lines))
        if state not in ("ready", "add"):
            continue
        if state == "add" and tpl not in templates:
            templates.append(tpl)
        _, eol = _read(path)
        new = lines[:first] + DECK_CALL.split("\n") + lines[last + 1:]
        plan[path.relative_to(root)] = eol.join(new).encode("utf-8")
    for tpl in templates:
        text, eol = _read(tpl)
        lines = text.split("\n")
        at = next((i for i, ln in enumerate(lines) if ln.startswith(BS + "input{SlideMage_base}")), None)
        if at is None:
            continue
        j = at + 1                      # past the inputs that follow, comments between them included
        while j < len(lines) and (_INPUT_LINE.match(lines[j]) or lines[j].startswith("%")):
            if _INPUT_LINE.match(lines[j]):
                at = j
            j += 1
        lines[at + 1:at + 1] = ["", *_block_lines()]
        plan[tpl.relative_to(root)] = eol.join(lines).encode("utf-8")
    return plan


CHANGE = Change(
    id=CHANGE_ID,
    since="v5.32.0",
    severity=LAYOUT,
    title="The citation format moved from the decks into the template",
    description=(
        "Decks no longer need their own copy of the biblatex setup and citation "
        "drivers: the command " + BS + "SMUseBibliography loads biblatex, finds "
        "SlideMage.bib and applies the format defined by the institution "
        "template. Decks that still carry the house format themselves keep "
        "working; updating replaces the copy in each such deck by one line and "
        "puts the format into the deck's template file."),
    fix=(
        "In each deck, replace everything from " + BS + "usepackage[style=authoryear, "
        "...]{biblatex} to the end of the last " + BS + "DeclareBibliographyDriver "
        "by the single line " + BS + "SMUseBibliography, and copy the block that "
        "begins with \"% Bibliography (SlideMage v5.32.0\" from SlideMage's "
        "latex/SlideMage_template_slidemage.tex into your template file, after "
        "its " + BS + "input{SlideMage_base}."),
    detect=detect,
    migrate=migrate,
)
