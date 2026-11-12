# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""compat.py change "colour-roles-in-slides" (v0.15.14): slides name what a colour is for, not which colour it is.

Two palette names carry a meaning beyond their colour: a dark mode turns ``c_primary_dark`` white today (it is the ink
of text, lines and rules) and ``c_custom_gray`` light grey (links). The framework has had role colours since v0.15.9
(``c_text``, ``c_canvas``, ``c_text_on_accent``, ...; docs/plans/theme-editor.md section 3.8). In the base mode they
resolve to the same colours as the names they replace, so a migrated slide looks the same there; in any other mode it
follows the mode, where the old name keeps one physical colour once the BREAKING cut removes the flip.

How a use of ``c_primary_dark`` is rewritten (only live code; a mix such as ``!85`` is kept):

| Where                                                     | Becomes             |
|-----------------------------------------------------------|---------------------|
| a line, an arrow, a rule, a shape, text on the canvas      | ``c_text``          |
| text on a coloured fill (``fill=c_primary_highlight, text=``) | ``c_text_on_accent`` |
| an ink-filled box (``fill=c_primary_dark!85``)             | ``c_text``, and its ``text=white`` / ``text=c_primary_white`` becomes ``c_canvas`` |
| the fill of a shape drawn in ink (``fill=c_primary_white``) | ``c_canvas``        |
| ``\\color``, ``\\textcolor``, ``\\arrayrulecolor``, ``fg=`` | ``c_text`` (``c_text_on_accent`` inside a node with a coloured fill) |
| a list of colours (``\\foreach \\c in {c_primary_dark, ...}``) | left alone: it shows the palette |

Everything else (``c_custom_gray`` outside a list, a ``\\colorlet`` of a slide's own, an unknown TikZ key, ``bg=``,
``\\colorbox``, a cell colour) is left as it is and reported with file and line, for a person to decide.

Scope: slides (the current file and every frozen version: a frozen slide shown in a dark deck needs the roles as
much as the current one), snippets, decks (decks/ and decks/archive/) and the project macros. Templates are themes:
their palette is physical by design, and their dark blocks are converted by the BREAKING cut, not here.

The migration is idempotent (the role names are not rewritten again) and returns the planned bytes per file
(compat.run_update backs every file up first).
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .compat_types import APPEARANCE, Change, Finding
from .tex_source import is_commented

CHANGE_ID = "colour-roles-in-slides"
TEMP_DECK_PREFIX = "_slidemage"

INK = "c_primary_dark"
LINK = "c_custom_gray"
WHITE = ("c_primary_white", "white")
_NAME = re.compile(r"(?<![A-Za-z0-9_@])(c_primary_dark|c_custom_gray)(?![A-Za-z0-9_@])")
_WORD = re.compile(r"[A-Za-z@]+")
_COLOUR_MACROS = {"color", "textcolor", "arrayrulecolor", "pagecolor"}
_REPORTED_MACROS = {"colorbox", "fcolorbox", "cellcolor", "rowcolor", "columncolor", "colorlet", "definecolor",
                    "rowcolors"}
_TEXT_KEYS = {"text"}
_LINE_KEYS = {"draw", "color", "fg", "line", "arrows", "mark color"}
_NO_FILL = {"", "none"}
_OPENERS = {"[": "]", "{": "}", "(": ")"}
_CLOSERS = {v: k for k, v in _OPENERS.items()}


# -- the structure around a use -----------------------------------------------------------------

@dataclass
class _Group:
    open: int    # index of the opening bracket
    close: int   # index of the closing bracket (len(text) when unclosed)
    char: str


def _groups(text: str) -> list[_Group]:
    """Every bracket group of the live code, outermost first in source order (comments and \\{ do not count)."""
    found: list[_Group] = []
    stack: list[tuple[int, str]] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "%":
            nl = text.find("\n", i)
            i = n if nl < 0 else nl
            continue
        if ch in _OPENERS:
            stack.append((i, ch))
        elif ch in _CLOSERS:
            for depth in range(len(stack) - 1, -1, -1):
                if stack[depth][1] == _CLOSERS[ch]:
                    start, opener = stack[depth]
                    del stack[depth:]
                    found.append(_Group(start, i, opener))
                    break
        i += 1
    found += [_Group(start, n, opener) for start, opener in stack]
    found.sort(key=lambda g: g.open)
    return found


def _enclosing(groups: list[_Group], pos: int) -> list[_Group]:
    """The groups that contain `pos`, innermost first."""
    return sorted((g for g in groups if g.open < pos < g.close), key=lambda g: g.open, reverse=True)


def _split_items(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """The top-level comma-separated items of text[start:end], as (start, end) spans."""
    items, depth, at, i = [], 0, start, start
    while i < end:
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch in _OPENERS:
            depth += 1
        elif ch in _CLOSERS:
            depth -= 1
        elif ch == "," and depth == 0:
            items.append((at, i))
            at = i + 1
        i += 1
    items.append((at, end))
    return items


@dataclass
class _Item:
    start: int
    end: int
    key: str           # "" for a bare item
    value: str         # stripped
    value_start: int   # index of the value's first character in the text


def _parse_list(text: str, group: _Group) -> list[_Item]:
    out = []
    for start, end in _split_items(text, group.open + 1, group.close):
        raw = text[start:end]
        depth, eq = 0, -1
        for j, ch in enumerate(raw):
            if ch in "{[(":
                depth += 1
            elif ch in "}])":
                depth -= 1
            elif ch == "=" and depth == 0:
                eq = j
                break
        if eq < 0:
            key, value, vstart = "", raw.strip(), start + len(raw) - len(raw.lstrip())
        else:
            key = raw[:eq].strip()
            rest = raw[eq + 1:]
            value, vstart = rest.strip(), start + eq + 1 + len(rest) - len(rest.lstrip())
        out.append(_Item(start, end, key, value, vstart))
    return out


def _word_before(text: str, pos: int) -> str:
    """The control word or key right before `pos` (whitespace skipped): '\\foreach' -> 'foreach', 'style=' -> '='."""
    j = pos - 1
    while j >= 0 and text[j] in " \t\r\n":
        j -= 1
    if j < 0:
        return ""
    if text[j] == "=":
        return "="
    end = j + 1
    while j >= 0 and (text[j].isalpha() or text[j] == "@"):
        j -= 1
    word = text[j + 1:end]
    if j >= 0 and text[j] == "\\":
        return "\\" + word
    return word


def _base(value: str) -> str:
    """The colour name of a value, without a mix: 'c_primary_dark!85' -> 'c_primary_dark'."""
    return value.split("!", 1)[0].strip()


def _is_ink(value: str) -> bool:
    return _base(value) in (INK, "c_text")


def _fill_of(items: list[_Item]) -> Optional[str]:
    for it in items:
        if it.key == "fill":
            return it.value
    return None


_BEAMERCOLOR_ARG = re.compile(r"\\setbeamercolor\*?\s*\{[^{}]*\}\s*$")


def _is_option_list(text: str, group: _Group) -> bool:
    if group.char == "[":
        return True
    if group.char != "{":
        return False
    return _word_before(text, group.open) == "=" or bool(_BEAMERCOLOR_ARG.search(text, 0, group.open))


def _command_of(text: str, group: _Group) -> str:
    """For a [ group: the command or keyword it belongs to (\\fill, \\draw, node, ...)."""
    j = group.open - 1
    while j >= 0 and text[j] in " \t\r\n":
        j -= 1
    end = j + 1
    while j >= 0 and (text[j].isalpha() or text[j] == "@"):
        j -= 1
    return text[j:end] if j >= 0 and text[j] == "\\" else text[j + 1:end]


def _macro_of(text: str, groups: list[_Group], group: _Group) -> str:
    """The control word a {argument} belongs to, over the arguments before it: \\colorlet{a}{b} -> 'colorlet'."""
    while True:
        j = group.open - 1
        while j >= 0 and text[j] in " \t\r\n":
            j -= 1
        before = None
        if j >= 0 and text[j] in "}]":
            before = next((h for h in groups if h.close == j and h.char in "{["), None)
        if before is None:
            return _word_before(text, group.open).lstrip("\\")
        group = before


def _node_fill(text: str, groups: list[_Group], pos: int) -> Optional[str]:
    """The fill of the TikZ node whose {content} holds `pos`, or None."""
    for g in _enclosing(groups, pos):
        if g.char != "{":
            continue
        j = g.open - 1
        while j >= 0 and text[j] in " \t\r\n":
            j -= 1
        # skip "at (x,y)" and "(name)" between the options and the content
        while j >= 0 and text[j] == ")":
            opener = next((h for h in groups if h.close == j and h.char == "("), None)
            if opener is None:
                break
            j = opener.open - 1
            while j >= 0 and text[j] in " \t\r\n":
                j -= 1
            if text[max(0, j - 1):j + 1] == "at":
                j -= 2
                while j >= 0 and text[j] in " \t\r\n":
                    j -= 1
        if j >= 0 and text[j] == "]":
            options = next((h for h in groups if h.close == j and h.char == "["), None)
            if options is not None and "node" in _command_of(text, options).lower():
                return _fill_of(_parse_list(text, options))
    return None


# -- one file -------------------------------------------------------------------------------------

@dataclass
class _Edit:
    start: int
    end: int
    new: str


@dataclass
class _FileResult:
    edits: list[_Edit] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    counts: Counter = field(default_factory=Counter)


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _replace_name(text: str, start: int, name: str, role: str) -> _Edit:
    return _Edit(start, start + len(name), role)


def plan_text(text: str, rel: str = "") -> _FileResult:
    """What the migration does to one file's text: the edits and the uses it leaves for a person."""
    result = _FileResult()
    groups = _groups(text)
    done: set[int] = set()   # starts of names already edited (an ink box's text item)

    def report(pos: int, name: str, why: str) -> None:
        result.findings.append(Finding(rel, _line_of(text, pos), f"{name} left as it is: {why}; choose a role by hand"))

    def edit(pos: int, name: str, role: str) -> None:
        if pos in done:
            return
        done.add(pos)
        result.edits.append(_replace_name(text, pos, name, role))
        result.counts[f"{name} -> {role}"] += 1

    for match in _NAME.finditer(text):
        pos, name = match.start(), match.group(1)
        if is_commented(text, pos) or pos in done:
            continue
        around = _enclosing(groups, pos)
        inner = around[0] if around else None
        if inner is not None and inner.char == "{" and _word_before(text, inner.open) in ("in", "\\foreach"):
            continue                                          # a list of colours shows the palette
        if inner is not None and inner.char == "{" and "/" in text[inner.open:inner.close] \
                and _word_before(text, inner.open) == "in":
            continue
        if name == LINK:
            report(pos, name, "links and muted text are c_link and c_text_muted, depending on what it is")
            continue
        if inner is not None and _is_option_list(text, inner):
            _option_use(text, groups, inner, pos, name, edit, report)
            continue
        if inner is not None and inner.char == "{":
            macro = _macro_of(text, groups, inner)
            if macro in _COLOUR_MACROS and text[inner.open + 1:inner.close].strip().startswith(name):
                fill = _node_fill(text, groups, pos)
                edit(pos, name, "c_text_on_accent" if fill and _base(fill) not in _NO_FILL and not _is_ink(fill)
                     else "c_text")
                continue
            if macro in _REPORTED_MACROS:
                report(pos, name, f"\\{macro} is a fill or a color of the slide's own")
                continue
            # \setbeamercolor{x}{fg=..} has the key form and is handled as an option list above
        report(pos, name, "not in a TikZ option list or a color command")
    result.edits.sort(key=lambda e: e.start)
    return result


def _option_use(text, groups, group, pos, name, edit, report) -> None:
    items = _parse_list(text, group)
    item = next((it for it in items if it.start <= pos < it.end), None)
    if item is None or _base(item.value) != name or item.value_start != pos:
        report(pos, name, "inside a value this update does not read")
        return
    key = item.key
    fill = _fill_of(items)
    on_accent = fill is not None and _base(fill) not in _NO_FILL and not _is_ink(fill) and _base(fill) not in WHITE
    command = _command_of(text, group) if group.char == "[" else ""
    if key == "" and command in ("\\draw", "\\path", "\\filldraw", "\\addplot", "\\addplot+"):
        on_accent = False                                     # a bare colour of a path is its line
    if key == "fill" or (key == "" and command in ("\\fill", "\\shade")):
        edit(pos, name, "c_text")                             # an ink-filled box or shape
        for it in items:
            if it.key in ("text", "") and _base(it.value) in WHITE and it.value_start not in (pos,):
                if it.key == "" and command in ("\\fill", "\\shade"):
                    continue
                edit(it.value_start, _base(it.value), "c_canvas")
        return
    if key in _TEXT_KEYS or key == "":
        edit(pos, name, "c_text_on_accent" if on_accent else "c_text")
        if not on_accent:
            _canvas_fill(items, edit)
        return
    if key in _LINE_KEYS:
        edit(pos, name, "c_text")
        if key in ("draw", "color"):
            _canvas_fill(items, edit)
        return
    if key == "bg":
        report(pos, name, "bg= is a fill; ink as a background is c_text, with its text c_canvas")
        return
    report(pos, name, f"the key '{key}' is not one this update knows")


def _canvas_fill(items: list[_Item], edit) -> None:
    """A shape drawn in ink and filled white: the white is the canvas showing through."""
    for it in items:
        if it.key == "fill" and _base(it.value) in WHITE:
            edit(it.value_start, _base(it.value), "c_canvas")


def rewrite(text: str, rel: str = "") -> tuple[str, _FileResult]:
    result = plan_text(text, rel)
    out, at = [], 0
    for e in result.edits:
        out.append(text[at:e.start])
        out.append(e.new)
        at = e.end
    out.append(text[at:])
    return "".join(out), result


# -- the project --------------------------------------------------------------------------------

def _in_scope(parts: tuple[str, ...]) -> bool:
    if not parts or not parts[-1].endswith(".tex") or parts[-1].startswith(TEMP_DECK_PREFIX):
        return False
    if len(parts) == 1:
        return not parts[0].startswith("SlideMage_template_")
    if parts[0] in ("slides", "snippets"):
        return len(parts) == 2
    return parts[0] == "decks" and (len(parts) == 2 or (len(parts) == 3 and parts[1] == "archive"))


def files(root: Path) -> list[Path]:
    found = list(root.glob("*.tex"))
    for folder in ("slides", "snippets", "decks", "decks/archive"):
        found += list((root / folder).glob("*.tex"))
    return [p.relative_to(root) for p in sorted(found) if p.is_file() and _in_scope(p.relative_to(root).parts)]


def _plans(root: Path) -> dict[Path, tuple[Optional[str], _FileResult]]:
    plans = {}
    for rel in files(root):
        try:
            text = (root / rel).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not _NAME.search(text):
            continue
        new, result = rewrite(text, rel.as_posix())
        plans[rel] = (new if new != text else None, result)
    return plans


def detect(root: Path) -> list[Finding]:
    findings = []
    for rel, (new, result) in _plans(root).items():
        if new is not None:
            shown = ", ".join(f"{k} ({v})" for k, v in sorted(result.counts.items()))
            findings.append(Finding(rel.as_posix(), 0, "colors rewritten to roles: " + shown))
        findings += result.findings
    return sorted(findings, key=lambda f: (f.file, f.line, f.message))


def migrate(root: Path) -> dict[Path, Optional[bytes]]:
    return {rel: new.encode("utf-8") for rel, (new, _r) in _plans(root).items() if new is not None}


CHANGE = Change(
    id=CHANGE_ID,
    since="v0.15.14",
    severity=APPEARANCE,
    title="Slides name the color's role (c_text, c_text_on_accent, c_canvas) instead of c_primary_dark",
    description=(
        "A theme's color modes (dark, gray, color-blind) change what a role color is, not the palette. "
        "c_primary_dark is the palette's dark color; used as the ink of text, lines and rules it should be c_text, "
        "used as dark text on a colored fill c_text_on_accent, and the white text of an ink-filled box c_canvas. "
        "In the theme's base mode the roles give exactly the colors of today, so nothing changes there; in a dark "
        "mode a slide that keeps c_primary_dark keeps dark ink on a dark slide once the dark-mode flip of "
        "c_primary_dark is removed."),
    fix=(
        "In slides (also the frozen -vX-Y-Z versions), snippets, decks and the project macros: \\draw[c_primary_dark] "
        "by \\draw[c_text]; text=c_primary_dark next to fill=c_primary_highlight by text=c_text_on_accent; "
        "fill=c_primary_dark!85, text=white by fill=c_text!85, text=c_canvas. Update project does it for you and "
        "lists the uses it could not classify (c_custom_gray outside a list of colors, a \\colorbox, an unknown key)."),
    detect=detect,
    migrate=migrate,
)
