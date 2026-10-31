# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""compat.py change "own-theme-and-content-names" (v10.1.0, BREAKING): the names SlideMage's content
carried from the Gotham theme become SlideMage names (sm_rename.THEME_RENAMES, approved 2026-10-26), and the
Gotham theme's own names become the names of the SlideMage theme (beamerthemeSlideMage.sty).

| Before                                              | After                                       |
|-----------------------------------------------------|---------------------------------------------|
| gothamtable, gothamfloating{,info,example}block      | SMTable, SMFloating{,Info,Example}Block     |
| gotham{alpha,num}{,period}itemize                   | SM{Alpha,Num}{,Period}Itemize               |
| counters gotham{alpha,num}{,period}item             | SM{Alpha,Num}{,Period}ItemCounter           |
| TikZ styles gotham arrow / highlight / dotted ...   | SMArrow, SMHighlight, SMDottedHighlight     |
| beamer templates gotham plain enumerate, ...        | SMPlainEnumerate, SMPresenter, SMFootnote   |
| \\gothamFrametitle<Side>pading                       | \\SMFrametitle<Side>Padding                  |
| \\gothamFootlineVOffset, ...Height, ...Depth        | \\SMFootlineVOffset, ...Height, ...Depth     |
| \\gothamInstituteLogoSquare                         | \\SMInstituteLogo                           |
| \\gothamFrameSubtitleSep, \\gothamFramesubtitleStrutend | \\SMFrameSubtitleSep, \\SMFrameSubtitleStrutEnd |
| \\gotham@frametitlestrut@start/@end                 | \\SM@frametitlestrut@start/@end              |
| and the internals named in THEME_RENAMES            |                                             |

The theme names that have no SlideMage counterpart (sm_rename.THEME_REMOVED: \\gothamset and \\gothamreset, the
title page, TOC and rotated footer hooks, the round logo, ...) cannot be renamed; each use outside a comment is
reported, and the file is otherwise migrated.

Scope: slides (the current file and every frozen version, since a frozen version that is not migrated stops
compiling), snippets, decks (decks/ and decks/archive/), and the .tex files in the project root (templates and
project macros). Left alone: slides/.backups/, .slidemage/backups/ and the regenerated _slidemage* decks.

A file is rewritten as a whole or not at all. It is reported and left as it is when it already uses a new name
in live code next to an old one (a hand-made migration, or a name of the project's own that would collide);
names that start with "gotham" but are in no table (a wildcard in prose, a project's own name) are reported
and not touched, while the rest of their file is migrated.

When the earlier change "slidemage-names-and-setup-layer" is still pending in the same update, both plans are
made from the same project, so this one works on the files as that one will leave them (renamed templates
included) and its plan wins where the two meet.

Returns the planned bytes per file (compat.run_update).
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Optional

from . import compat_names, sm_rename
from .compat_types import BREAKS, Change, Finding
from .tex_source import is_commented

CHANGE_ID = "own-theme-and-content-names"

TEMP_DECK_PREFIX = "_slidemage"
# Frametitle paddings were the same register under either name in v10.0.0 (SlideMage_setup aliased them), so a
# file that mixes the two spellings is not ambiguous.
_ALIASED = frozenset(k for k in sm_rename.THEME_RENAMES if k.startswith("gothamFrametitle"))
_NEW_NAMES = sorted({new for old, new in sm_rename.THEME_RENAMES.items() if old not in _ALIASED}, key=len, reverse=True)
_NEW_RE = re.compile(r"(?<![A-Za-z0-9_@])(" + "|".join(re.escape(n) for n in _NEW_NAMES) + r")(?![A-Za-z0-9_@])")
_OLD_FIT = re.compile(r"(?<![A-Za-z0-9_@])gothamfit\d+(?![A-Za-z0-9_@])")


# -- what a project holds ------------------------------------------------------------------

def _in_scope(parts: tuple[str, ...]) -> bool:
    if not parts or not parts[-1].endswith(".tex") or parts[-1].startswith(TEMP_DECK_PREFIX):
        return False
    if len(parts) == 1:
        return True
    if parts[0] in ("slides", "snippets"):
        return len(parts) == 2
    return parts[0] == "decks" and (len(parts) == 2 or (len(parts) == 3 and parts[1] == "archive"))


def _disk_files(root: Path) -> list[Path]:
    found = [p for p in root.glob("*.tex")]
    for folder in ("slides", "snippets", "decks", "decks/archive"):
        found += list((root / folder).glob("*.tex"))
    return [p.relative_to(root) for p in sorted(found) if p.is_file() and _in_scope(p.relative_to(root).parts)]


class _View:
    """The project's in-scope files as they are now, or as "slidemage-names-and-setup-layer" will leave
    them when it is pending too."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.overlay: dict[Path, Optional[bytes]] = {}
        try:
            if compat_names.detect(root):
                self.overlay = compat_names.migrate(root)
        except OSError:
            self.overlay = {}

    def files(self) -> list[Path]:
        removed = {p for p, data in self.overlay.items() if data is None}
        found = {p for p in _disk_files(self.root) if p not in removed}
        found |= {p for p, data in self.overlay.items() if data is not None and _in_scope(p.parts)}
        return sorted(found)

    def read(self, rel: Path) -> Optional[bytes]:
        data = self.overlay.get(rel)
        if data is not None:
            return data
        try:
            return (self.root / rel).read_bytes()
        except OSError:
            return None


# -- one file --------------------------------------------------------------------------------

def _live_collisions(text: str) -> list[str]:
    return sorted({m[1] for m in _NEW_RE.finditer(text) if not is_commented(text, m.start())})


def _live_old_names(text: str) -> bool:
    for match in sm_rename._IDENTIFIER_RE.finditer(text):
        if match.group(2) in _ALIASED:
            continue
        if not is_commented(text, match.start()):
            return True
    return any(not is_commented(text, m.start()) for m in _OLD_FIT.finditer(text))


class _FilePlan:
    """What the change does to one file: the new text (None = not touched) and what it reports."""

    def __init__(self, rel: Path, text: str) -> None:
        self.rel = rel.as_posix()
        self.new: Optional[str] = None
        self.findings: list[Finding] = []
        self.counts: Counter = Counter()
        rewritten = sm_rename.rename_identifiers(text, self.counts)
        for line, name in sm_rename.unknown_names(rewritten, live_only=True):
            self.findings.append(Finding(self.rel, line, f"{name} is in no rename table; change it by hand"))
        for line, name in sm_rename.removed_names(rewritten, live_only=True):
            self.findings.append(Finding(self.rel, line, _REMOVED_MESSAGE.format(name=name)))
        if rewritten == text:
            return
        collisions = _live_collisions(text) if _live_old_names(text) else []
        if collisions:
            self.counts = Counter()
            self.findings.append(Finding(
                self.rel, 0,
                "not rewritten: it uses " + ", ".join(collisions) + " already, next to names this update renames "
                "(a name of your own, or a hand-made migration); change it by hand"))
            return
        self.new = rewritten
        shown = ", ".join(f"{old} -> {sm_rename.THEME_RENAMES.get(old, 'SMFit<n>')}" for old in sorted(self.counts)[:6])
        more = len(self.counts) - 6
        self.findings.insert(0, Finding(self.rel, 0, "names renamed in this update: " + shown
                                        + (f" and {more} more" if more > 0 else "")))


_REMOVED_MESSAGE = (
    "{name} is gone with the Gotham theme and has no SlideMage replacement; change it by hand "
    "(SlideMage_setup.tex lists what can still be switched)")


def _plans(root: Path) -> tuple[_View, dict[Path, _FilePlan]]:
    view = _View(root)
    plans: dict[Path, _FilePlan] = {}
    for rel in view.files():
        data = view.read(rel)
        if data is None:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        plans[rel] = _FilePlan(rel, text)
    return view, plans


# -- the change --------------------------------------------------------------------------------

def detect(root: Path) -> list[Finding]:
    _view, plans = _plans(root)
    return sorted((f for plan in plans.values() for f in plan.findings), key=lambda f: (f.file, f.line, f.message))


def migrate(root: Path) -> dict[Path, Optional[bytes]]:
    _view, plans = _plans(root)
    return {rel: plan.new.encode("utf-8") for rel, plan in plans.items() if plan.new is not None}


CHANGE = Change(
    id=CHANGE_ID,
    since="v10.1.0",
    severity=BREAKS,
    title="SlideMage has its own beamer theme, and its names no longer carry Gotham's",
    description=(
        "gothamtable is now SMTable, gothamfloatingblock / gothamfloatinginfoblock / gothamfloatingexampleblock "
        "are SMFloatingBlock / SMFloatingInfoBlock / SMFloatingExampleBlock, gothamalphaitemize, gothamnumitemize, "
        "gothamalphaperioditemize and gothamnumperioditemize are SMAlphaItemize, SMNumItemize, SMAlphaPeriodItemize "
        "and SMNumPeriodItemize (their counters end in Counter: SMAlphaItemCounter, ...), the TikZ styles "
        "gotham arrow / gotham highlight / gotham dotted highlight are SMArrow / SMHighlight / SMDottedHighlight, "
        "and the beamer templates gotham plain enumerate / gothampresenter / gothamfn / gotham_no_inline_logo are "
        "SMPlainEnumerate / SMPresenter / SMFootnote / SMNoInlineLogo. \\gothamFrametitle{Top,Bottom,Left,Right}pading "
        "are \\SMFrametitle{Top,Bottom,Left,Right}Padding. The theme itself is SlideMage's own now "
        "(beamerthemeSlideMage.sty, loaded by SlideMage_setup.tex; the Gotham files are gone): "
        "\\gothamFootlineVOffset is \\SMFootlineVOffset, \\gothamInstituteLogoSquare is \\SMInstituteLogo, "
        "\\gothamFrameSubtitleSep and \\gothamFramesubtitleStrutend are \\SMFrameSubtitleSep and "
        "\\SMFrameSubtitleStrutEnd, \\gotham@frametitlestrut@start and @end are \\SM@frametitlestrut@start "
        "and @end. What the Gotham theme had beyond that (\\gothamset and its keys, title page, TOC frames, "
        "side strips, rotated footer, round logo) is gone. There are no aliases: a slide, snippet, deck or "
        "template that keeps the old names does not compile against this framework, frozen slide versions "
        "included."),
    fix=(
        "Replace each old name by the new one in slides (also the frozen -vX-Y-Z versions), snippets, decks "
        "(decks/ and decks/archive/), templates and project macros: \\begin{gothamtable} by \\begin{SMTable} "
        "(and \\end), [gotham arrow] by [SMArrow], \\setbeamertemplate{section in toc}[gotham plain enumerate] "
        "by [SMPlainEnumerate], \\gothamFrametitleRightpading by \\SMFrametitleRightPadding, "
        "\\gothamFootlineVOffset by \\SMFootlineVOffset, and so on. Update project does it for you; a "
        "\\gothamset line or another name of the Gotham theme that has no SlideMage counterpart is listed for you "
        "to change by hand."),
    detect=detect,
    migrate=migrate,
)
