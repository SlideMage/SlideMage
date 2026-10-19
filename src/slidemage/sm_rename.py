# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Rename this project's own \\gotham... names to \\SM... (v5.3.0, 2026-10-01).

Direct instruction: "rename all \\gotham... commands that this project newly
created to \\SM...". The vendored Gotham beamer theme (latex/beamer*gotham.sty,
gotham.dtx) keeps its names -- \\gothamset, \\gothamFrametitleLeftpading, ... --
everything the SlideMaster framework, its institution preambles and its slides
added on top is renamed: \\gothamContentTopAlign -> \\SMContentTopAlign,
\\ifgothamInstructorVersion -> \\ifSMInstructorVersion, \\gotham@cf@x ->
\\SM@cf@x. The rename works on identifiers, not only on backslash tokens,
because some names are built without one (\\csname gotham@topcorr@...,
Lua's token.set_macro("..."), TikZ node and style names such as
gothamImageBorder) and must stay in step with their definitions.

Rule: an identifier "gotham" + an uppercase letter or "@" (optionally after
"if") is renamed unless the Gotham theme itself uses it (THEME_NAMES).
Lowercase continuations are left alone: they are the theme's (\\gothamset)
or this project's environment names (gothamtable, gothamfloatinginfoblock,
gothamnumitemize, ...), which stay as they are.

Command line, for another project's slides/decks/preambles:
    python -m slidemage.sm_rename <project folder> [--dry-run]
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

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

# "if": \newif's \ifgotham...; "the": a counter's \thegotham... (\newcounter)
_NAME_RE = re.compile(r"(?<![A-Za-z])(if|the)?(gotham)(?=[A-Z@])([A-Za-z@]*)")

# Files of a SlideMaster project the rename applies to.
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
