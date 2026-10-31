# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Rename this project's own \\gotham... names to \\SM... (v5.3.0, 2026-10-01).

Direct instruction: "rename all \\gotham... commands that this project newly
created to \\SM...". The Gotham beamer theme then vendored (latex/beamer*gotham.sty,
gotham.dtx) kept its names -- \\gothamset, \\gothamFrametitleLeftpading, ... --
everything the SlideMage framework, its institution preambles and its slides
added on top was renamed: \\gothamContentTopAlign -> \\SMContentTopAlign,
\\ifgothamInstructorVersion -> \\ifSMInstructorVersion, \\gotham@cf@x ->
\\SM@cf@x. The rename works on identifiers, not only on backslash tokens,
because some names are built without one (\\csname gotham@topcorr@...,
Lua's token.set_macro("..."), TikZ node and style names such as
gothamImageBorder) and must stay in step with their definitions.

Rule: an identifier "gotham" + an uppercase letter or "@" (optionally after
"if") is renamed unless the Gotham theme itself uses it (THEME_NAMES).
Lowercase continuations are left alone by rename_text: they are the theme's
(\\gothamset) or this project's environment names (gothamtable,
gothamfloatinginfoblock, ...), which rename_identifiers renames in a second
pass (v10.1.0, 2026-10-26, THEME_RENAMES).

Command line, for another project's slides/decks/preambles:
    python -m slidemage.sm_rename <project folder> [--dry-run]
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

from .tex_source import is_commented

# Every gotham... identifier the vendored theme files use (checked
# 2026-10-01 against latex/beamer*gotham.sty and gotham.dtx).
THEME_NAMES = frozenset("""
gotham@@tempColor gotham@@tempColorB gotham@block gotham@blockadjust gotham@blocksep
gotham@blockskip gotham@colors@transparent gotham@framesubtitleformat
gotham@frametitleformat gotham@frametitlestrut@end gotham@frametitlestrut@start
gotham@parskip gotham@parttitleformat gotham@plaintitleformat gotham@progressinheadfoot
gotham@progressonsectionpage gotham@sectiontitleformat gotham@strut
gotham@subsectiontitleformat gotham@subsubsectiontitleformat gotham@subtitleformat
gotham@temp@MiniframeSecDim gotham@temp@MiniframeSubsecDim
gotham@temp@PaperheightFrametitle gotham@temp@heightFrametitle gotham@temp@i
gotham@temp@ii gotham@temp@lastSec gotham@titleformat gotham@titleseparator@lineheight
gotham@titleseparator@linewidth gothamCircleNumberingHshift gothamCircleNumberingVshift
gothamCounterCircleRadius gothamCounterRadius gothamDividedPicBottomIncr
gothamDividedPicTextWidth gothamDividedPicTop gothamFooterHOffset gothamFootlineDepth
gothamFootlineHRightOffset gothamFootlineHeight gothamFootlineRuleHeight
gothamFootlineRuleLeftPadding gothamFootlineRuleLength gothamFootlineVOffset
gothamFrameSubtitleSep gothamFramesubtitleStrutend gothamFrametitleBottompading
gothamFrametitleLeftpading gothamFrametitleRightpading gothamFrametitleToppading
gothamHookFooter gothamHookPostColorBGSet gothamHposLeftRotFooter gothamHposRightRotFooter
gothamInsertNavlength gothamInstituteLogoCircle gothamInstituteLogoSquare
gothamLeftFiligrane gothamLeftFooterPadding gothamPatchInsertNav gothamPatchSectionbox
gothamPatchSectionentry gothamProgCircleMoving gothamProgressCircBorderWidth
gothamProgressCircHeight gothamProgressCircLogoInnerRadius
gothamProgressCircLogoOuterRadius gothamProgressCircLogoRadius gothamProgressCircle
gothamProgressHeadFootLineheight gothamProgressSectionHeight gothamReloadColors
gothamRightFiligrane gothamRightFooterPadding gothamVposLeftRotFooter
gothamVposRightRotFooter gothamZerosectionframes
""".split())

# What the v10.1.0 rename (compat change "own-theme-and-content-names") turns into SlideMage names, by the
# rule that every SlideMage TeX name starts with an uppercase SM and continues in CamelCase (Lua keeps its
# lowercase style). Approved by the user on 2026-10-26. Four groups:
# - the theme's four frametitle paddings (a theme name, renamed with the spelling fixed);
# - SlideMage's own content names that carried Gotham's name: environments, counters (with the Counter
#   suffix, since \SMAlphaItem etc. exist as label macros), TikZ styles, beamer templates;
# - internals built from such names (\csname, pgfkeys, TikZ coordinates, expl3, Lua globals and callback);
# - Python's own _GOTHAMTABLE_RE.
# The other names the theme files define (THEME_NAMES minus the paddings) follow with the own theme.
THEME_RENAMES = {
    # theme registers that slides and templates use
    "gothamFrametitleRightpading": "SMFrametitleRightPadding",
    "gothamFrametitleLeftpading": "SMFrametitleLeftPadding",
    "gothamFrametitleToppading": "SMFrametitleTopPadding",
    "gothamFrametitleBottompading": "SMFrametitleBottomPadding",
    # environments
    "gothamtable": "SMTable",
    "gothamfloatingblock": "SMFloatingBlock",
    "gothamfloatinginfoblock": "SMFloatingInfoBlock",
    "gothamfloatingexampleblock": "SMFloatingExampleBlock",
    "gothamalphaitemize": "SMAlphaItemize",
    "gothamnumitemize": "SMNumItemize",
    "gothamalphaperioditemize": "SMAlphaPeriodItemize",
    "gothamnumperioditemize": "SMNumPeriodItemize",
    "gothamtightflalign": "SMTightFlalign",
    # counters (and their \the...)
    "gothamalphaitem": "SMAlphaItemCounter",
    "gothamnumitem": "SMNumItemCounter",
    "gothamalphaperioditem": "SMAlphaPeriodItemCounter",
    "gothamnumperioditem": "SMNumPeriodItemCounter",
    "thegothamalphaitem": "theSMAlphaItemCounter",
    "thegothamnumitem": "theSMNumItemCounter",
    "thegothamalphaperioditem": "theSMAlphaPeriodItemCounter",
    "thegothamnumperioditem": "theSMNumPeriodItemCounter",
    # TikZ styles
    "gotham arrow": "SMArrow",
    "gotham highlight": "SMHighlight",
    "gotham dotted highlight": "SMDottedHighlight",
    # beamer templates
    "gotham plain enumerate": "SMPlainEnumerate",
    "gothampresenter": "SMPresenter",
    "gothamfn": "SMFootnote",
    "gotham_no_inline_logo": "SMNoInlineLogo",
    # internals
    "gothamtable@spec": "SMTable@spec",
    "gothamtable@gap": "SMTable@gap",
    "gothamtable@begin": "SMTable@begin",
    "gothamcorner": "SMCorner",
    "gothamfit": "SMFit",
    "gothamfit@top": "SMFit@top",
    "gothamfit@bl": "SMFit@bl",
    "gothamfit@r": "SMFit@r",
    "g_gotham_footnote_symbols_seq": "g_SM_footnote_symbols_seq",
    # Lua (lowercase) and Python
    "gothamalt": "slidemage_alt",
    "gotham_layout": "slidemage_measure",
    "gotham_list_has_no_visible_box": "slidemage_list_has_no_visible_box",
    "gotham top margin": "slidemage top margin",
    "_GOTHAMTABLE_RE": "_SMTABLE_RE",
}
# The theme names that live on in latex/beamerthemeSlideMage.sty (v10.1.0), renamed there. A project can use
# the first group in a template or a slide; the rest is the theme's own bookkeeping (named for completeness: a
# macro of a project that reaches into it is migrated too).
THEME_RENAMES.update({
    "gothamFootlineVOffset": "SMFootlineVOffset",
    "gothamFootlineHeight": "SMFootlineHeight",
    "gothamFootlineDepth": "SMFootlineDepth",
    "gothamFootlineHRightOffset": "SMFootlineHRightOffset",
    "gothamRightFooterPadding": "SMRightFooterPadding",
    "gothamInstituteLogoSquare": "SMInstituteLogo",
    "gothamFrameSubtitleSep": "SMFrameSubtitleSep",
    "gothamFramesubtitleStrutend": "SMFrameSubtitleStrutEnd",
    "gotham@frametitlestrut@start": "SM@frametitlestrut@start",
    "gotham@frametitlestrut@end": "SM@frametitlestrut@end",
    "gotham@strut": "SM@strut",
    "gothamProgressHeadFootLineheight": "SMProgressHeadFootLineheight",
    "gothamProgressSectionHeight": "SMProgressSectionHeight",
    "gothamZerosectionframes": "SMZerosectionframes",
    "gothamInsertNavlength": "SMInsertNavlength",
    "gothamPatchInsertNav": "SMPatchInsertNav",
    "gothamPatchSectionbox": "SMPatchSectionbox",
    "gothamPatchSectionentry": "SMPatchSectionentry",
    "gotham@@tempColor": "SM@@tempColor",
    "gotham@@tempColorB": "SM@@tempColorB",
    "gotham@progressinheadfoot": "SM@progressinheadfoot",
    "gotham@progressonsectionpage": "SM@progressonsectionpage",
    "gotham@temp@MiniframeSecDim": "SM@temp@MiniframeSecDim",
    "gotham@temp@MiniframeSubsecDim": "SM@temp@MiniframeSubsecDim",
    "gotham@temp@PaperheightFrametitle": "SM@temp@PaperheightFrametitle",
    "gotham@temp@heightFrametitle": "SM@temp@heightFrametitle",
    "gotham@temp@i": "SM@temp@i",
    "gotham@temp@ii": "SM@temp@ii",
    "gotham@temp@lastSec": "SM@temp@lastSec",
})
# What the SlideMage theme left out of Gotham (title page, TOC frames, side strips, rotated footer, round logo,
# the \gothamset key interface, ...): no SlideMage replacement, so a migration reports each use for a hand fix.
THEME_REMOVED = frozenset(
    (THEME_NAMES - set(THEME_RENAMES))
    | {"gothamset", "gothamreset", "gothamtitlepagebg", "gothamtitlepagelogo"})

_IDENT = "A-Za-z0-9_@"
_IDENTIFIER_RE = re.compile(
    r"(?<![" + _IDENT + r"])(?:gothamfit(\d+)|("
    + "|".join(re.escape(k) for k in sorted(THEME_RENAMES, key=len, reverse=True))
    + r"))(?![" + _IDENT + r"])")
# Any lowercase gotham... name: what a migration cannot place unless it is mapped or the theme's.
_UNKNOWN_RE = re.compile(r"(?<![" + _IDENT + r"])gotham[a-z_@][" + _IDENT + r"]*")
_REMOVED_RE = re.compile(
    r"(?<![" + _IDENT + r"])(" + "|".join(re.escape(k) for k in sorted(THEME_REMOVED, key=len, reverse=True))
    + r")(?![" + _IDENT + r"])")

# "if": \newif's \ifgotham...; "the": a counter's \thegotham... (\newcounter)
_NAME_RE = re.compile(r"(?<![A-Za-z])(if|the)?(gotham)(?=[A-Z@])([A-Za-z@]*)")

# Files of a SlideMage project the rename applies to.
PROJECT_GLOBS = ("slides/*.tex", "decks/*.tex", "decks/**/*.tex", "*.tex",
                 ".slidemage/*.json", "*.md", ".scripts/*.py", "decks/render/*.py")
# Session logs keep the names they were written with.
SKIP_NAMES = frozenset({"SESSION_HANDOFF.md"})


def rename_text(text: str, counts: Counter | None = None) -> str:
    """Every project-created gotham... identifier in text, renamed to SM..."""
    def repl(match: re.Match) -> str:
        prefix, _, rest = match.groups()
        if "gotham" + rest in THEME_NAMES and not prefix:
            return match.group(0)
        if counts is not None:
            counts[match.group(0)] += 1
        return (prefix or "") + "SM" + rest
    return _NAME_RE.sub(repl, text)


def rename_identifiers(text: str, counts: Counter | None = None) -> str:
    """Every old content name (THEME_RENAMES) in text, renamed. Whole identifiers only: gothamtable inside
    \\begin{gothamtable}, gothamtable[gap=1pt], \\csname, a TikZ option list or a Lua string, but not
    the middle of another word. Names with a space (gotham arrow) match as written."""
    def repl(match: re.Match) -> str:
        if match.group(1) is not None:
            old, new = "gothamfit" + match.group(1), "SMFit" + match.group(1)
        else:
            old = match.group(2)
            new = THEME_RENAMES[old]
        if counts is not None:
            counts[old] += 1
        return new
    return _IDENTIFIER_RE.sub(repl, text)


def unknown_names(text: str, live_only: bool = False) -> list[tuple[int, str]]:
    """(1-based line, name) of every gotham... name in text that THEME_RENAMES does not map and the theme
    does not own: a project's own name or a wildcard in prose, which a migration reports instead of renaming.
    With live_only, names in TeX comments do not count."""
    found = []
    for match in _UNKNOWN_RE.finditer(text):
        name = match.group(0)
        if name in THEME_NAMES or name in THEME_RENAMES or name in THEME_REMOVED:
            continue
        if live_only and is_commented(text, match.start()):
            continue
        found.append((text.count("\n", 0, match.start()) + 1, name))
    return found


def removed_names(text: str, live_only: bool = False) -> list[tuple[int, str]]:
    """(1-based line, name) of every name the Gotham theme had and the SlideMage theme has not (THEME_REMOVED):
    a migration reports each for a hand fix. With live_only, names in TeX comments do not count."""
    found = []
    for match in _REMOVED_RE.finditer(text):
        if live_only and is_commented(text, match.start()):
            continue
        found.append((text.count("\n", 0, match.start()) + 1, match.group(1)))
    return found


def rename_file(path: Path, counts: Counter | None = None, dry_run: bool = False) -> bool:
    """Rename in one file (bytes in, bytes out: line endings untouched)."""
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return False
    new = rename_text(text, counts)
    if new == text:
        return False
    if not dry_run:
        path.write_bytes(new.encode("utf-8"))
    return True


def rename_project(root: Path, dry_run: bool = False) -> tuple[list[Path], Counter]:
    counts: Counter = Counter()
    changed: list[Path] = []
    seen: set[Path] = set()
    for pattern in PROJECT_GLOBS:
        for path in sorted(root.glob(pattern)):
            if path in seen or not path.is_file() or path.name in SKIP_NAMES:
                continue
            seen.add(path)
            if rename_file(path, counts, dry_run):
                changed.append(path)
    return changed, counts


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    root = Path(argv[0])
    dry = "--dry-run" in argv[1:]
    changed, counts = rename_project(root, dry_run=dry)
    print(f"{'would change' if dry else 'changed'} {len(changed)} files, "
          f"{sum(counts.values())} names ({len(counts)} distinct)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
