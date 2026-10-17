"""Compile-time-generated appendix: an agenda slide plus one or more
thumbnail-grid slides per chapter, hyperlinked to and from the main deck.

Text only -- never written to slides/ or decks/. compiler.py's wrapper
calls generate_appendix_tex() and appends the result right before
\\end{document} when a job has appendix_toc=True. Relies on:
- \\hypertarget{\\slideID}{} in \\setSlideID@aux (Slidemaster_preamble_base.tex)
  as the jump target every real slide already carries, any frame type.
- slide_snapshot.THUMB_SIZE-cached previews for the grid thumbnails.
- \\SMInstituteLogoGraphic's own \\hyperlink to "SMAppendixAgenda"
  (Slidemaster_preamble_base.tex), which this module's agenda slide is the
  landing target for.
"""
from __future__ import annotations

from . import deck_editor, project, slide_snapshot
from .deck_editor import SlideCall
from .deck_scan import Deck

GRID_ROWS = 4
GRID_COLS = 5
PER_PAGE = GRID_ROWS * GRID_COLS
FRONT_MATTER_ORDER = 0

# Computed once per compile from this project's own preamble length
# registers (\paperwidth, \gothamFrametitleRightpading, \SMFooterBoxHeight,
# \SMTitleBarBottomAlign) rather than a hardcoded cm value, so it adapts
# automatically to whichever institution's logo/padding the compiling deck
# actually uses (Graz/Innsbruck/MCI each set these differently). Left-aligned
# to the .45cm text margin, scaled up until either the right edge reaches
# the logo's own right edge or the row height runs out -- whichever binds
# first (direct instruction, 2026-09-15) -- with a 2% safety margin on both
# candidates (an exact-fit first attempt produced small but real Overfull
# \hbox/\vbox warnings from font/box-metric rounding).
_GEOMETRY_TEX = r"""
\newlength{\SMAppendixThumbW}
\newlength{\SMAppendixThumbH}
\newlength{\SMAppendixWBoundTmp}
\newlength{\SMAppendixHBoundTmp}
\setlength{\tabcolsep}{2pt}
\setlength{\SMAppendixWBoundTmp}{\dimexpr\paperwidth-\gothamFrametitleRightpading-0.45cm\relax}
\setlength{\SMAppendixWBoundTmp}{0.98\SMAppendixWBoundTmp}
\setlength{\SMAppendixWBoundTmp}{\dimexpr(\SMAppendixWBoundTmp-8\tabcolsep)/5\relax}
\setlength{\SMAppendixHBoundTmp}{\dimexpr\paperheight-\SMFooterBoxHeight-\SMTitleBarBottomAlign\relax}
\setlength{\SMAppendixHBoundTmp}{0.98\SMAppendixHBoundTmp}
\setlength{\SMAppendixHBoundTmp}{\dimexpr\SMAppendixHBoundTmp/4-0.5pt\relax}
% Divide-then-multiply, not multiply-then-divide: dimexpr computes the
% *intermediate* product before applying the division, and 304 times a
% ~2cm dimension (56.7pt) alone already exceeds TeX's ~16384pt dimension
% ceiling ("Dimension too large", confirmed via a real compile) even
% though the final, post-division result is a perfectly ordinary ~2.5cm.
% Same reasoning applied to \SMAppendixThumbH below.
\setlength{\SMAppendixHBoundTmp}{\dimexpr\SMAppendixHBoundTmp/171*304\relax}
\ifdim\SMAppendixWBoundTmp<\SMAppendixHBoundTmp
  \setlength{\SMAppendixThumbW}{\SMAppendixWBoundTmp}
\else
  \setlength{\SMAppendixThumbW}{\SMAppendixHBoundTmp}
\fi
\setlength{\SMAppendixThumbH}{\dimexpr\SMAppendixThumbW/304*171\relax}
""".strip()


def _sections(deck: Deck, version: str = "instructor") -> list[tuple[int, str, list[SlideCall]]]:
    """(order, title, calls) per appendix entry, in agenda order -- a
    leading "Front matter" entry (order 0) for slides before the first
    \\section, then one entry per real chapter, each skipped entirely if it
    ends up with no visible slides."""
    # A slide shown at several places with \slidestep{} (each place possibly several
    # calls, one per deck version) gets one thumbnail, at its first visible place --
    # the place its \hypertarget{} also belongs to.
    calls = []
    step_ids: set[str] = set()
    for c in deck_editor.parse_slide_calls(deck):
        if deck_editor.is_commented_out(deck.text, c):
            continue
        if not c.included_in(version):
            continue
        if deck_editor.is_commented_out(deck.text, c):
            # A disabled "% \slide{abc-EN-Old}" is not a real slide in
            # this compile -- included anyway, it would produce a
            # thumbnail cell whose \hyperlink{} target doesn't exist in
            # the PDF (2026-09-23 review finding).
            continue
        if c.macro == "slidestep":
            if c.id in step_ids:
                continue
            step_ids.add(c.id)
        calls.append(c)
    sections: list[tuple[int, str, list[SlideCall]]] = []
    front_matter = [c for c in calls if c.chapter is None]
    if front_matter:
        sections.append((FRONT_MATTER_ORDER, "Front matter", front_matter))
    for chapter in deck.chapters:
        chapter_calls = [c for c in calls if c.chapter is chapter]
        if chapter_calls:
            sections.append((chapter.order, chapter.title, chapter_calls))
    return sections


def _chunks(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _thumb_cell(ctx: project.ProjectContext, call: SlideCall, template: str) -> str:
    png = slide_snapshot.snapshot_path(ctx, call.id, template, slide_snapshot.THUMB_SIZE)
    if png.is_file():
        inner = f"\\includegraphics[width=\\SMAppendixThumbW]{{{png.as_posix()}}}"
    else:
        # No cached preview yet (slide_snapshot's own "best-effort, never
        # guaranteed-fresh" cache) -- a plain bordered id+title box instead
        # of a broken \includegraphics, still wrapped in the same working
        # \hyperlink below.
        language, _, rest = call.slug.partition("-")
        slug = rest if language in ("EN", "DE", "mult") and rest else call.slug
        label = slug.replace("-", " ")
        inner = (
            f"\\fbox{{\\parbox[c][\\SMAppendixThumbH][c]{{\\SMAppendixThumbW}}"
            f"{{\\centering\\tiny {call.id}: {label}}}}}"
        )
    return f"\\hyperlink{{{call.id}}}{{{inner}}}"


def _grid_slide(ctx: project.ProjectContext, title: str, page_calls: list[SlideCall], template: str, hypertarget: str | None) -> str:
    rows_tex = []
    for r in range(GRID_ROWS):
        cells = []
        for c in range(GRID_COLS):
            idx = r * GRID_COLS + c
            cells.append(_thumb_cell(ctx, page_calls[idx], template) if idx < len(page_calls) else "")
        rows_tex.append(" & ".join(cells) + " \\\\[0.5pt]")
    colspec = "c" * GRID_COLS
    table = (
        "\\renewcommand{\\arraystretch}{1.0}\\setlength{\\tabcolsep}{2pt}%\n"
        f"\\begin{{tabular}}{{{colspec}}}\n" + "\n".join(rows_tex) + "\n\\end{tabular}"
    )
    target = f"\\hypertarget{{{hypertarget}}}{{}}%\n" if hypertarget else ""
    return (
        f"\\begin{{standardframe}}{{{title}}}\n"
        f"{target}\\noindent{table}\n"
        f"\\end{{standardframe}}\n"
    )


def _agenda_slide(sections: list[tuple[int, str, list[SlideCall]]]) -> str:
    # Two columns so a deck with a full chapter list (front matter + a
    # dozen-plus real chapters, e.g. IA2's own 13 entries) still fits on
    # one agenda page rather than running off the bottom -- README.md's
    # own "Available layouts" two-column pattern (beamer's `columns`
    # nested *inside* standardframe, not wrapped in a custom environment).
    def itemize(entries: list[tuple[int, str, list[SlideCall]]]) -> str:
        items = "\n".join(
            f"\\item \\hyperlink{{SMAppendixCh{order}}}{{{title}}}"
            for order, title, _calls in entries
        )
        return f"\\begin{{itemize}}\n{items}\n\\end{{itemize}}"

    half = -(-len(sections) // 2)  # ceil(n/2): left column gets the extra one
    left, right = sections[:half], sections[half:]
    right_column = f"\\begin{{column}}{{0.48\\linewidth}}\n{itemize(right)}\n\\end{{column}}\n" if right else "\\begin{column}{0.48\\linewidth}\\end{column}\n"
    columns = (
        "\\begin{columns}[t,onlytextwidth]\n"
        f"\\begin{{column}}{{0.48\\linewidth}}\n{itemize(left)}\n\\end{{column}}\n"
        f"{right_column}"
        "\\end{columns}"
    )
    return (
        "\\begin{standardframe}{Appendix}\n"
        "\\hypertarget{SMAppendixAgenda}{}%\n"
        f"{columns}\n"
        "\\end{standardframe}\n"
    )


def generate_appendix_tex(ctx: project.ProjectContext, deck: Deck, template: str, version: str = "instructor") -> str:
    """The full appendix block: \\appendix, the agenda slide, then each
    section's thumbnail grid (paginated at GRID_ROWS*GRID_COLS per page),
    for the slides the deck shows in `version` ("instructor", "during-course"
    or "after-course"). Empty string for a deck with no visible slides at all
    (shouldn't happen for a real deck)."""
    sections = _sections(deck, version)
    if not sections:
        return ""

    # standardframe's own footer template always shows whatever \slideID
    # currently holds, even on a frame that never called \setSlideID{} --
    # left unset, every appendix page would keep displaying the *last real
    # slide's* id in its own footer. Confirmed to be more than cosmetic: a
    # real compile's slide_snapshot.capture_deck() scans a PDF for exactly
    # that same footer text to key its thumbnail cache, so a stale id would
    # make it treat the appendix pages as a later, spurious occurrence of
    # that real slide and overwrite its cached thumbnail with an appendix
    # page. "appendix" can never collide with a real (3-character) bare id.
    # The last real slide's version and language must not show either
    # ("(slide id: appendix | v1.0.0EN | ...)", seen 2026-10-04 in the
    # SlideMage manual).
    reset_id = ("\\renewcommand{\\slideID}{appendix}%\n"
                "\\global\\SMSlideVersionSetfalse\\global\\SMSlideLanguageSetfalse%")
    parts = ["\\appendix", reset_id, _GEOMETRY_TEX, _agenda_slide(sections)]
    for order, title, calls in sections:
        pages = _chunks(calls, PER_PAGE)
        total = len(pages)
        for i, page_calls in enumerate(pages):
            page_title = title if total == 1 else f"{title} ({i + 1}/{total})"
            hypertarget = f"SMAppendixCh{order}" if i == 0 else None
            parts.append(_grid_slide(ctx, page_title, page_calls, template, hypertarget))
    return "\n".join(parts)
