# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""compat.py change "dark-switch-removed" (v0.16.0, BREAKING): the dark switch \\SMDarkMode is gone; a deck chooses
its theme's colour mode with \\newcommand{\\SMModeOverride}{<mode>} before the template, dark included.

| Before                                   | After                                   |
|------------------------------------------|-----------------------------------------|
| \\newcommand{\\SMDarkMode}{} in a deck      | \\newcommand{\\SMModeOverride}{dark}       |
| % SlideMage dark mode: true (template)   | % SlideMage modes: light, dark, and \\SMDeclareMode / \\SMSetRole lines |
| \\ifdefined\\SMDarkMode ... \\fi (template) | \\SMSetRole{<role>}{dark}{<colour>} lines  |
| c_primary_dark turned white in dark mode | c_primary_dark is one colour; slides use c_text (colour-roles-in-slides) |

migrate(root): decks (decks/ and decks/archive/; not the regenerated _slidemage* decks) lose their \\SMDarkMode
definition; it becomes \\newcommand{\\SMModeOverride}{dark} in the same place, or simply goes when the deck already
has a mode line (that line always won). Idempotent.

detect(root): those decks, plus every live \\SMDarkMode or `% SlideMage dark mode:` line in a project template, the
project macros, a slide or a snippet: a template's hand-written dark block cannot be converted mechanically (its
colours become \\SMDeclareMode, \\SMSetColor and \\SMSetRole lines), so it is reported with file and line.

Installed themes are not the project's: themes.check_contents refuses one whose template still uses \\SMDarkMode, and
Settings offers its update.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .compat_types import BREAKS, Change, Finding
from .tex_source import is_commented

CHANGE_ID = "dark-switch-removed"
TEMP_DECK_PREFIX = "_slidemage"

DARK_SWITCH_RE = re.compile(
    r"\\(?:(?:(?:re)?newcommand|providecommand)\*?\s*(?:\{\\SMDarkMode\}|\\SMDarkMode(?![A-Za-z@]))"
    r"|def\s*\\SMDarkMode(?![A-Za-z@]))\s*\{[^{}]*\}")
_MODE_LINE_RE = re.compile(
    r"\\(?:(?:(?:re)?newcommand|providecommand)\*?\s*(?:\{\\SMModeOverride\}|\\SMModeOverride(?![A-Za-z@]))"
    r"|def\s*\\SMModeOverride(?![A-Za-z@]))\s*\{")
_ANY_USE_RE = re.compile(r"\\SMDarkMode(?![A-Za-z@])|^%+\s*SlideMage dark mode:", re.MULTILINE | re.IGNORECASE)
NEW_LINE = "\\newcommand{\\SMModeOverride}{dark}"


def _live(regex: re.Pattern, text: str) -> list[re.Match]:
    return [m for m in regex.finditer(text) if not is_commented(text, m.start())]


def _decks(root: Path) -> list[Path]:
    found = []
    for folder in (root / "decks", root / "decks" / "archive"):
        if folder.is_dir():
            found += [p for p in sorted(folder.glob("*.tex")) if not p.name.startswith(TEMP_DECK_PREFIX)]
    return found


def _others(root: Path) -> list[Path]:
    found = sorted(root.glob("*.tex"))
    for folder in ("slides", "snippets"):
        found += sorted((root / folder).glob("*.tex"))
    return [p for p in found if p.is_file()]


def _read(path: Path) -> Optional[str]:
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def rewrite_deck(text: str) -> str:
    """`text` with its dark switch turned into the mode line (or dropped next to an existing one)."""
    switches = _live(DARK_SWITCH_RE, text)
    if not switches:
        return text
    keep_first = not _live(_MODE_LINE_RE, text)
    for i, match in enumerate(reversed(switches)):
        first = i == len(switches) - 1
        if first and keep_first:
            text = text[:match.start()] + NEW_LINE + text[match.end():]
            continue
        start, end = match.start(), match.end()
        line_start = text.rfind("\n", 0, start) + 1
        line_end = text.find("\n", end)
        line_end = len(text) if line_end < 0 else line_end + 1
        if not text[line_start:start].strip() and not text[end:line_end].strip():
            start, end = line_start, line_end                 # the line held only the switch
        text = text[:start] + text[end:]
    return text


def _line(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def detect(root: Path) -> list[Finding]:
    findings = []
    for path in _decks(root):
        text = _read(path)
        if text is None:
            continue
        rel = path.relative_to(root).as_posix()
        for match in _live(DARK_SWITCH_RE, text):
            findings.append(Finding(rel, _line(text, match.start()),
                                    "\\SMDarkMode is gone: Update project writes \\newcommand{\\SMModeOverride}{dark}"))
    for path in _others(root):
        text = _read(path)
        if text is None:
            continue
        rel = path.relative_to(root).as_posix()
        for match in _ANY_USE_RE.finditer(text):
            if match.group(0).startswith("\\") and is_commented(text, match.start()):
                continue
            what = ("the template's dark block or header needs \\SMDeclareMode and \\SMSetRole lines "
                    "(docs/plans/theme-editor.md, section 3.8); change it by hand"
                    if path.name.startswith("SlideMage_template_") else
                    "\\SMDarkMode is gone; test the mode another way or drop it")
            findings.append(Finding(rel, _line(text, match.start()), what))
    return sorted(findings, key=lambda f: (f.file, f.line, f.message))


def migrate(root: Path) -> dict[Path, Optional[bytes]]:
    plan: dict[Path, Optional[bytes]] = {}
    for path in _decks(root):
        text = _read(path)
        if text is None:
            continue
        new = rewrite_deck(text)
        if new != text:
            plan[path.relative_to(root)] = new.encode("utf-8")
    return plan


CHANGE = Change(
    id=CHANGE_ID,
    since="v0.16.0",
    severity=BREAKS,
    title="Dark slides are a colour mode: \\SMDarkMode is gone",
    description=(
        "A theme declares its colour modes (light, dark, grey, ...) and a deck chooses one with "
        "\\newcommand{\\SMModeOverride}{dark} before the template. The old switch \\newcommand{\\SMDarkMode}{} stops the "
        "compile with a message, a template's `% SlideMage dark mode: true` line and \\ifdefined\\SMDarkMode block do "
        "nothing any more, and c_primary_dark stays dark in every mode: slides that use it as ink need the role "
        "colours (the change \"colour-roles-in-slides\", which Update project runs too). Installed themes made for "
        "an older SlideMage are not used until they are updated."),
    fix=(
        "In each deck, replace \\newcommand{\\SMDarkMode}{} by \\newcommand{\\SMModeOverride}{dark} (Update project "
        "does it). In a template of your own, replace the dark block by data lines: \\SMDeclareMode{light}{} and "
        "\\SMDeclareMode{dark}{dark} after \\input{SlideMage_setup}, then \\SMSetRole{text}{dark}{c_true_white} and the "
        "like for what the dark preset does not already give, and the header line `% SlideMage modes: light, dark`. "
        "Update an installed theme in Settings -> Extensions -> Themes."),
    detect=detect,
    migrate=migrate,
)
