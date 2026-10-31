# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
r"""compat.py change "citation-format-by-the-framework" (v0.13.0): the framework loads a template's citation format
itself.

Before, each project template carried the line ``\input{SlideMage_bibliography_default}`` after its
``\input{SlideMage_base}``. Now the catalog's ``\SMCitationFormat`` (default ``default``, the house format
latex/SlideMage_citation_default.tex) names the format and latex/SlideMage_base.tex loads it. A template that wants
another format sets ``\SMCitationFormat`` between ``\input{SlideMage_setup}`` and ``\input{SlideMage_base}``.

Not breaking: latex/SlideMage_bibliography_default.tex stays as a one-line loader of the new file, so a template
that still has the line compiles as before and renders the same.

detect(root): one finding per project template (``SlideMage_template_*.tex`` at the project root) that has the line,
only when the format is the default: a template that sets another ``\SMCitationFormat`` or redefines
``\SMBiblatexOptions`` / ``\SMBibliographyStyle`` itself is left alone. migrate(root): removes the line and, when
the single comment line directly above it only introduces it (it mentions the bibliography or the citation
format), that comment line too; line endings are kept.
"""
from __future__ import annotations

import re
from pathlib import Path

from .compat_types import APPEARANCE, Change, Finding

BS = chr(92)
CHANGE_ID = "citation-format-by-the-framework"

_LINE = re.compile(r"^" + re.escape(BS + "input{SlideMage_bibliography_default") + r"(?:\.tex)?\}[ \t]*(?:%.*)?$")
_OTHER_FORMAT = re.compile(r"^[ \t]*" + re.escape(BS) + r"(?:re)?newcommand\*?\s*\{" + re.escape(BS)
                           + r"SMCitationFormat\}\s*\{(?!default\})", re.MULTILINE)
_OWN_FORMAT = re.compile(r"^[ \t]*" + re.escape(BS) + r"(?:re)?newcommand\*?\s*\{" + re.escape(BS)
                         + r"SMBi(?:blatexOptions|bliographyStyle)\}", re.MULTILINE)


def _read(path: Path) -> tuple[list[str], str]:
    raw = path.read_bytes().decode("utf-8")
    return raw.replace("\r\n", "\n").split("\n"), ("\r\n" if "\r\n" in raw else "\n")


def _templates(root: Path):
    yield from sorted(root.glob("SlideMage_template_*.tex"))


def _hits(lines: list[str]) -> list[int]:
    """The lines to remove: none when the template's format is not the default one."""
    text = "\n".join(lines)
    if _OTHER_FORMAT.search(text) or _OWN_FORMAT.search(text):
        return []
    return [i for i, ln in enumerate(lines) if _LINE.match(ln)]


def _intro(lines: list[str], at: int) -> bool:
    """Whether the line above `at` is a lone comment about the bibliography (the line above it is not a comment)."""
    if at == 0 or not lines[at - 1].startswith("%"):
        return False
    above = lines[at - 1].lower()
    if "bibliograph" not in above and "citation" not in above:
        return False
    return at == 1 or not lines[at - 2].startswith("%")


def detect(root: Path) -> list[Finding]:
    out = []
    for path in _templates(root):
        try:
            lines, _eol = _read(path)
        except (OSError, UnicodeDecodeError):
            continue
        for i in _hits(lines):
            out.append(Finding(path.name, i + 1, "loads the house citation format itself; the framework does that "
                               "now, so the line can go"))
    return out


def migrate(root: Path) -> dict[Path, bytes]:
    plan: dict[Path, bytes] = {}
    for path in _templates(root):
        try:
            lines, eol = _read(path)
        except (OSError, UnicodeDecodeError):
            continue
        hits = _hits(lines)
        if not hits:
            continue
        drop: set[int] = set()
        for at in hits:
            drop.add(at)
            if _intro(lines, at):
                drop.add(at - 1)
        kept = [ln for i, ln in enumerate(lines) if i not in drop]
        plan[path.relative_to(root)] = eol.join(kept).encode("utf-8")
    return plan


CHANGE = Change(
    id=CHANGE_ID,
    since="v0.13.0",
    severity=APPEARANCE,
    title="The framework loads the template's citation format itself",
    description=(
        "The citation format is a catalog setting now, " + BS + "SMCitationFormat (default: the house format, "
        "latex/SlideMage_citation_default.tex), and SlideMage_base.tex loads it, so a template needs no line for "
        "the default. A template that still has " + BS + "input{SlideMage_bibliography_default} keeps working "
        "and renders the same. A template that wants another format (an installed citation package) sets "
        + BS + "renewcommand{" + BS + "SMCitationFormat}{key} between " + BS + "input{SlideMage_setup} and " + BS + "input{SlideMage_base}. "
        "Optional: the line is redundant."),
    fix=(
        "In each template file of the project that uses the house format, delete the line "
        + BS + "input{SlideMage_bibliography_default} (and the comment directly above it, if that only introduces "
        "it). To use another format, say " + BS + "renewcommand{" + BS + "SMCitationFormat}{key} before "
        + BS + "input{SlideMage_base}."),
    detect=detect,
    migrate=migrate,
)
