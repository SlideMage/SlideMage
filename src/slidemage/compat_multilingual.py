# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""compat.py change "multilingualtext-keyed" (BREAKING, 2026-11-24, direct request: "Remove the special
English/German \\multilingualtext version"): \\multilingualtext takes one argument, the keyed list of texts per
language, without a star.

| Before                                        | After                                        |
|-----------------------------------------------|----------------------------------------------|
| \\multilingualtext{Hello}{Hallo}              | \\multilingualtext{EN={Hello}, DE={Hallo}}   |
| \\multilingualtext*{EN={Hello}, FR={Bonjour}} | \\multilingualtext{EN={Hello}, FR={Bonjour}} |

The two-argument form was English then German and nothing else; the keyed form, which had the star, does any number
of languages. SlideMage_base.tex still reads the star (it changes nothing) but stops with an error on the two-argument
form.

detect(root): every call of the old forms outside a comment, with file and line. migrate(root): rewrites them, the
two texts in braces, so a comma or an equals sign in a text stays inside its value. Scope: the project's own .tex files
at the top, slides (the current files, the frozen -vX-Y-Z versions and slides/archive/, since a pinned or restored
version is compiled too), snippets and decks (decks/ and decks/archive/). Idempotent: a rewritten call is neither
form any more.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .compat_types import BREAKS, Change, Finding
from .tex_source import braced_argument, is_commented

CHANGE_ID = "multilingualtext-keyed"

_CALL = re.compile(r"\\multilingualtext(?![A-Za-z@])(\s*\*)?\s*(?=\{)")
_KEYED = re.compile(r"\s*[A-Za-z]{2,3}\s*=")
_FOLDERS = ("slides", "slides/archive", "snippets", "decks", "decks/archive")
_TEMP_DECK_PREFIX = "_slidemage"


def files(root: Path) -> list[Path]:
    found = sorted(root.glob("*.tex"))
    for folder in _FOLDERS:
        found += sorted((root / folder).glob("*.tex"))
    return [p.relative_to(root) for p in found if p.is_file() and not p.name.startswith(_TEMP_DECK_PREFIX)]


def rewrite(text: str) -> tuple[str, list[int]]:
    """`text` with every old call rewritten, and the 1-based lines of those calls."""
    out: list[str] = []
    lines: list[int] = []
    index = 0
    for match in _CALL.finditer(text):
        if match.start() < index or is_commented(text, match.start()):
            continue
        first_open = match.end()
        first, after_first = braced_argument(text, first_open)
        if after_first == first_open:
            continue
        if match.group(1):                                  # \multilingualtext*{EN={..}, ...}: the star goes
            new, stop = f"\\multilingualtext{{{first}}}", after_first
        else:
            second_open = after_first
            while second_open < len(text) and text[second_open] in " \t\r":
                second_open += 1
            if second_open < len(text) and text[second_open] == "\n":      # one line break, not a blank line
                second_open += 1
                while second_open < len(text) and text[second_open] in " \t\r":
                    second_open += 1
            if _KEYED.match(first) or text[second_open:second_open + 1] != "{":
                continue                                    # already the keyed form
            second, stop = braced_argument(text, second_open)
            if stop == second_open:
                continue
            new = f"\\multilingualtext{{EN={{{first}}}, DE={{{second}}}}}"
        out.append(text[index:match.start()] + new)
        lines.append(text.count("\n", 0, match.start()) + 1)
        index = stop
    out.append(text[index:])
    return "".join(out), lines


def _plans(root: Path) -> dict[Path, tuple[str, list[int]]]:
    plans = {}
    for rel in files(root):
        try:
            text = (root / rel).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "multilingualtext" not in text:
            continue
        new, lines = rewrite(text)
        if lines:
            plans[rel] = (new, lines)
    return plans


def detect(root: Path) -> list[Finding]:
    return [Finding(rel.as_posix(), line, "\\multilingualtext in the old form (two arguments, or with a star)")
            for rel, (_new, lines) in sorted(_plans(root).items()) for line in lines]


def migrate(root: Path) -> dict[Path, Optional[bytes]]:
    return {rel: new.encode("utf-8") for rel, (new, _lines) in _plans(root).items()}


CHANGE = Change(
    id=CHANGE_ID,
    since="v0.18.0",
    severity=BREAKS,
    title="\\multilingualtext takes the texts per language as keys: \\multilingualtext{EN={...}, DE={...}}",
    description=(
        "The two-argument form \\multilingualtext{English}{German} is gone: it knew only these two languages. "
        "\\multilingualtext now takes one list of texts keyed by language code, for any number of languages, "
        "without the star the keyed form had before. A slide with the two-argument form stops with an error."),
    fix=(
        "\\multilingualtext{Hello}{Hallo} becomes \\multilingualtext{EN={Hello}, DE={Hallo}}, and "
        "\\multilingualtext*{EN={Hello}, FR={Bonjour}} becomes \\multilingualtext{EN={Hello}, FR={Bonjour}}. "
        "Update project does it in slides (also their frozen versions and the archive), snippets and decks."),
    detect=detect,
    migrate=migrate,
)
