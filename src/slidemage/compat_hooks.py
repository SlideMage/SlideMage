# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""v10.11.0: two hooks of the catalog were renamed for what they do and three that moved nothing were removed.

``\\SMProgressStripHeight`` is ``\\SMProgressStripRoom`` (the room below a progress strip, not its drawn height) and
``\\SMSideFootnoteTopSep`` is ``\\SMSideFootnoteTitleBlockSep`` (the distance the strip hangs below the title block).
``\\SMFootlineHeight``, ``\\SMFootlineDepth`` and ``\\SMRightFooterPadding`` are gone: the derived
``\\SMFootlineVOffset`` and ``\\SMFooterRightShift`` cancelled them, so no position depended on them.

The setup layer stops a template or profile that still uses one of the five with an error that says what to do.
:func:`migrate` renames the two in the project's templates, layout profiles and macros file (idempotent);
:func:`detect` reports the renamed ones that are still there and every use of the removed ones, which only the
user can delete (a line that sets one is the whole line to go).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .compat_types import BREAKS, Change, Finding
from .tex_source import is_commented

CHANGE_ID = "hook-renames-and-removals"
RENAMED = {
    "SMProgressStripHeight": "SMProgressStripRoom",
    "SMSideFootnoteTopSep": "SMSideFootnoteTitleBlockSep",
}
REMOVED = ("SMFootlineHeight", "SMFootlineDepth", "SMRightFooterPadding")
_PATTERNS = ("SlideMage_template_*.tex", "SlideMage_layout_*.tex", "SlideMage_project_macros.tex")
_RENAMED_RE = re.compile(r"\\(" + "|".join(RENAMED) + r")(?![A-Za-z@])")
_REMOVED_RE = re.compile(r"\\(" + "|".join(REMOVED) + r")(?![A-Za-z@])")


def _paths(root: Path) -> list[Path]:
    return [p for pattern in _PATTERNS for p in sorted(root.glob(pattern))]


def detect(root: Path) -> list[Finding]:
    """Uses of the renamed names (migrate renames them) and of the removed ones (to be deleted by hand)."""
    findings = []
    for path in _paths(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _RENAMED_RE.finditer(text):
            if not is_commented(text, match.start()):
                findings.append(Finding(path.name, text.count("\n", 0, match.start()) + 1,
                                        f"\\{match.group(1)} is \\{RENAMED[match.group(1)]} now."))
        for match in _REMOVED_RE.finditer(text):
            if not is_commented(text, match.start()):
                findings.append(Finding(path.name, text.count("\n", 0, match.start()) + 1,
                                        f"\\{match.group(1)} is gone (it moved nothing on the page); "
                                        "remove this line."))
    return findings


def migrate(root: Path) -> dict[Path, Optional[bytes]]:
    """The files that use a renamed name, with the new names. The removed names are only reported."""
    changed: dict[Path, Optional[bytes]] = {}
    for path in _paths(root):
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        new = _RENAMED_RE.sub(lambda m: "\\" + RENAMED[m.group(1)], text)
        if new != text:
            changed[path.relative_to(root)] = new.encode("utf-8")
    return changed


CHANGE = Change(
    id=CHANGE_ID,
    since="v10.11.0",
    severity=BREAKS,
    title="Two hooks were renamed and three that moved nothing were removed",
    description=(
        "\\SMProgressStripHeight is \\SMProgressStripRoom (the room below a progress strip, not its drawn height) "
        "and \\SMSideFootnoteTopSep is \\SMSideFootnoteTitleBlockSep (the distance the strip hangs below the title "
        "block); the values mean what they did. \\SMFootlineHeight, \\SMFootlineDepth and \\SMRightFooterPadding "
        "are gone: the derived \\SMFootlineVOffset and \\SMFooterRightShift cancelled them, so nothing on the page "
        "depended on them. A template or layout profile that still uses one of the five stops the compile with an "
        "error that names it."),
    fix=(
        "Update project renames the two in the project's templates, layout profiles and macros file. Delete the "
        "lines that set the three removed names, e.g. \\setlength{\\SMFootlineHeight}{2ex}; the footer stays "
        "where it is."),
    detect=detect,
    migrate=migrate,
)
