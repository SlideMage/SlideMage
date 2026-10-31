# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The setup-layer half of compat change "slidemage-names-and-setup-layer" (v10.0.0, BREAKING);
compat_names.py holds the renaming half and calls these text rewrites.

From v10.0.0 a template starts with \\input{SlideMage_setup}, which loads the beamer theme and
defines every template setting with its default (the hook catalog). A template then changes a
setting instead of creating it, and a deck no longer loads the theme:

| Before                                         | After                                      |
|------------------------------------------------|--------------------------------------------|
| deck: \\usetheme{gotham}                        | (removed; SlideMage_setup loads the theme) |
| template: (nothing before its colors)          | \\input{SlideMage_setup}                    |
| \\newcommand{\\SMInstituteLogoPath}, \\SMBulletColor, | \\renewcommand{...}                        |
|   \\SMTitleBoxColor, \\SMTitleTextColor,          |                                            |
|   \\SMFooterBoxColorDefault, \\SMFooterTextColor  |                                            |
| \\newlength{\\SMLogoHeight}                       | (removed; \\setlength stays)                |
| \\gothamFrametitle<Side>pading                   | \\SMFrametitle<Side>Padding                 |

A template is only rewritten when it \\input{}s SlideMage_base in live code; otherwise
template() reports it and leaves it alone.
"""
from __future__ import annotations

import re
from typing import Optional

from .tex_source import is_commented

SETUP = "SlideMage_setup"
BASE = "SlideMage_base"
CATALOG_MACROS = ("SMInstituteLogoPath", "SMBulletColor", "SMTitleBoxColor", "SMTitleTextColor",
                  "SMFooterBoxColorDefault", "SMFooterTextColor")
PADDINGS = {f"gothamFrametitle{side}pading": f"SMFrametitle{side}Padding"
            for side in ("Top", "Bottom", "Left", "Right")}

_SETUP_INPUT = re.compile(r"\\input\s*\{\s*" + SETUP + r"(?:\.tex)?\s*\}")
_BASE_INPUT = re.compile(r"\\input\s*\{\s*" + BASE + r"(?:\.tex)?\s*\}")
_THEME = re.compile(r"\\usetheme\s*\{\s*gotham\s*\}")
_NEWCOMMAND = re.compile(r"\\newcommand(\*?)(\s*\{\s*|\s*)\\(" + "|".join(CATALOG_MACROS) + r")(?![A-Za-z@])")
_NEWLENGTH = re.compile(r"\\newlength\s*(?:\{\s*\\SMLogoHeight\s*\}|\\SMLogoHeight(?![A-Za-z@]))")
_PADDING = re.compile(r"\\(" + "|".join(PADDINGS) + r")(?![A-Za-z@])")
# A deck setting SlideMage writes before the template's own code; the setup line goes after it.
_DARK_MODE = re.compile(r"\\(?:(?:re)?newcommand|providecommand)\*?\s*(?:\{\\SMDarkMode\}|\\SMDarkMode\b)\s*\{[^{}]*\}"
                        r"|\\def\s*\\SMDarkMode\b\s*\{[^{}]*\}")


def _live(pattern: re.Pattern, text: str) -> list[re.Match]:
    return [m for m in pattern.finditer(text) if not is_commented(text, m.start())]


def _drop(text: str, match: re.Match) -> str:
    """`text` without `match`; the whole line goes when nothing but blanks or a comment is left on it."""
    line_start = text.rfind("\n", 0, match.start()) + 1
    line_end = text.find("\n", match.end())
    line_end = len(text) if line_end < 0 else line_end + 1
    before, after = text[line_start:match.start()], text[match.end():line_end]
    if not before.strip() and (not after.strip() or after.lstrip().startswith("%")):
        return text[:line_start] + text[line_end:]
    return text[:match.start()] + text[match.end():]


def needs_setup(text: str) -> bool:
    """Whether a template still lacks \\input{SlideMage_setup} in live code."""
    return not _live(_SETUP_INPUT, text)


def template(text: str) -> tuple[str, Optional[str]]:
    """The template rewritten for the setup layer, and why it was left alone (None if it was not)."""
    if not needs_setup(text):
        return text, None
    if not _live(_BASE_INPUT, text):
        return text, f"does not \\input{{{BASE}}}; add \\input{{{SETUP}}} at its top by hand"
    newline = "\r\n" if "\r\n" in text else "\n"
    for match in reversed(_live(_NEWLENGTH, text)):
        text = _drop(text, match)
    for match in reversed(_live(_NEWCOMMAND, text)):
        text = text[:match.start()] + "\\renewcommand" + match[1] + match[2] + "\\" + match[3] + text[match.end():]
    for match in reversed(_live(_PADDING, text)):
        text = text[:match.start()] + "\\" + PADDINGS[match[1]] + text[match.end():]
    # Insert before the first line of live code that is not a \SMDarkMode definition.
    dark_lines = {text.rfind("\n", 0, m.start()) + 1 for m in _live(_DARK_MODE, text)}
    pos = 0
    while pos < len(text):
        line_end = text.find("\n", pos)
        line_end = len(text) if line_end < 0 else line_end + 1
        code = text[pos:line_end].strip()
        if code and not code.startswith("%") and pos not in dark_lines:
            break
        pos = line_end
    # ... and before the comment lines directly above it, which describe it, unless they are the file's header.
    start = pos
    while start > 0:
        prev = text.rfind("\n", 0, start - 1) + 1
        if not text[prev:start].strip().startswith("%"):
            break
        start = prev
    if start > 0 and start < pos:
        return text[:start] + "\\input{" + SETUP + "}" + newline + newline + text[start:], None
    return text[:pos] + "\\input{" + SETUP + "}" + newline + text[pos:], None


def deck(text: str) -> str:
    """The deck without its \\usetheme{gotham} (SlideMage_setup loads the theme now)."""
    for match in reversed(_live(_THEME, text)):
        text = _drop(text, match)
    return text


def deck_has_theme(text: str) -> bool:
    return bool(_live(_THEME, text))
