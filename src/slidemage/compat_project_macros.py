# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""compat.py change "project-macros-by-the-framework" (v0.12.0): the framework loads a project's
``SlideMage_project_macros.tex`` itself.

Before, each project template carried the line ``\\input{SlideMage_project_macros}`` after its
``\\input{SlideMage_base}``; a template without it (an institution template from a theme package) did not get
the project's macros. Now latex/SlideMage_base.tex loads the file when the project has one, at the same place.

Not breaking: the framework skips a second load (see the end of SlideMage_base.tex), so a template that still
has the line compiles as before and the macros are read once.

detect(root): one finding per project template (``SlideMage_template_*.tex`` at the project root) that still
has the line. migrate(root): removes the line and, when the single comment line directly above it only
introduces it (it mentions the macros), that comment line too; line endings are kept.
"""
from __future__ import annotations

import re
from pathlib import Path

from .compat_types import APPEARANCE, Change, Finding

BS = chr(92)
CHANGE_ID = "project-macros-by-the-framework"

_LINE = re.compile(r"^" + re.escape(BS + "input{SlideMage_project_macros") + r"(?:\.tex)?\}[ \t]*(?:%.*)?$")


def _read(path: Path) -> tuple[list[str], str]:
    raw = path.read_bytes().decode("utf-8")
    return raw.replace("\r\n", "\n").split("\n"), ("\r\n" if "\r\n" in raw else "\n")


def _templates(root: Path):
    yield from sorted(root.glob("SlideMage_template_*.tex"))


def _hits(lines: list[str]) -> list[int]:
    return [i for i, ln in enumerate(lines) if _LINE.match(ln)]


def _intro(lines: list[str], at: int) -> bool:
    """Whether the line above `at` is a lone comment about the macros (the line above it is not a comment)."""
    if at == 0 or not lines[at - 1].startswith("%") or "macro" not in lines[at - 1].lower():
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
            out.append(Finding(path.name, i + 1, "loads the project macros itself; the framework does that now, "
                               "so the line can go"))
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
    since="v0.12.0",
    severity=APPEARANCE,
    title="The framework loads the project's macros itself",
    description=(
        "SlideMage_base.tex now loads the project's SlideMage_project_macros.tex when there is one, so a "
        "template (an institution template from a theme package included) needs no line for it. A template "
        "that still has " + BS + "input{SlideMage_project_macros} keeps working: the file is read once. "
        "Optional: the line is redundant."),
    fix=(
        "In each template file of the project, delete the line " + BS + "input{SlideMage_project_macros} "
        "(and the comment directly above it, if that only introduces it)."),
    detect=detect,
    migrate=migrate,
)
