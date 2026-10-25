# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Short guides the agent can load on demand with read_guide (2026-10-10, UI redesign step
10a). Condensed from README.md and docs/SlideMageCommands.md; the frame skeletons come from
slide_add, so they are the ones the Add slide sheet writes. A guide is kept short on purpose:
it costs context every time it is read, and the slides of the project (find_files, search,
read_file) are the better examples for anything not covered here."""
from __future__ import annotations

from collections.abc import Callable

from .. import slide_add
from .image_instructions import IMAGE_DESCRIPTION_RULES
from ..project import ProjectContext

_SLIDES = """\
Slides, files and decks.
- A slide is slides/<id>-<LANG>-<Slug>-current.tex: a 3-character permanent id (never changes),
  the language (EN, DE or mult) and a hyphenated slug. The live content is the -current.tex file.
- slides/<id>-<LANG>-<Slug>-v1-0-0.tex files are frozen older versions: read-only records. SlideMage's
  Save asks "major/minor/patch/overwrite" and freezes the outgoing content itself. Never edit them.
- The first lines of a slide file are a comment block ("%% Included in decks: ...") that SlideMage
  maintains, and a tracked slide has a \\setSlideVersion{X-Y-Z} line. Both are protected: edits that
  touch them are refused. So are \\vbox to 0pt{...} overlay blocks.
- A slide file holds one frame (a begin/end of a frame environment), plus optional comments above it.
  Indent with tabs, like the existing slides.
- Decks are decks/<name>.tex. A deck calls slides: \\slide{id-slug} (follows -current.tex),
  \\slideversion{id-slug}{1-0-0} (pinned), \\conditionalslide{id-slug}[versions] (only in some deck
  versions), \\slidestep{id-slug}[versions]{steps} (only some reveal steps), \\omitslide{...} (left out of
  student versions). Sections are \\section{Title}. Do not hand-edit these calls unless asked;
  create_slide (full draft) or add_slide (skeleton) puts the call into the deck.
- Deck versions: instructor (everything), during-course, after-course (student versions).
- Find a slide with list_slides or search; read it before changing it. Use modify_slide with ordered
  edits (old/new, each old matches once) or full text, plus expected text if read: one call checks,
  writes and shows the preview, using the linked partner in the edited EN/DE language."""

_REVEALS = """\
Reveal steps (overlays) and deck versions.
- Plain beamer overlays work inside a slide: \\pause, \\only<2>{...}, \\uncover<3->{...},
  \\textcolor<2>{...}{...}, \\item<2->. The instructor deck shows every step; the student decks
  show what \\slidestep / \\conditionalslide in the deck select.
- \\deckitem<3-> is an item revealed in the instructor deck and a plain \\item in the student decks.
- \\slidestep{id-slug}[instructor]{1,2} in a deck typesets only those overlay steps of the slide
  in that deck version; the slide file itself stays plain. Steps are a beamer overlay list without the
  angle brackets ("1,2", "3", "2-", "1-2,4").
- \\SMFinalStateForStudents right before a frame makes every student version show only the frame's
  last overlay page.
- An absolute overlay (\\vbox to 0pt{...}, tikz) placed after a \\pause is invisible on earlier steps
  unless \\onslide<1->\\relax comes right before it. Those blocks are protected; do not edit them."""

_CITATIONS = """\
Citations and the bibliography.
- References live in SlideMage.bib at the project root, kept sorted by key. Keys are the first
  author's lowercase surname plus the year, with a letter if taken: markowitz1952, smith2024b.
- Cite in a slide with \\fullcite{key} (the full reference as a footnote line; the usual choice),
  \\textcite{key} (Author (year) in running text) or \\parencite{key} ((Author, year)).
- A deck that shows references has \\SMUseBibliography in its preamble; the format is the template's.
- Add an entry with add_bib_entry (types: article, book, online, report), then cite its key.
  Do not invent entries: only add what the user gave you or what a source they named states.
- \\source{Source: ...} in a frame sets a "Source:" line at the bottom for anything that is not a citation."""

_NOTES_IMAGES = """\
Images, notes and text helpers.
- Images are files in media/, named <type>-<slug>.<ext> (chart-, photo-, screenshot-, midjourney-).
  \\includegraphics[height=0.64\\textheight]{media/chart-x.png} inside a frame. You cannot see or edit
  image files; ask the user to put one there. Descriptions for screen readers (alt text) are
  managed on SlideMage's Images page, not in the slide source.
- \\cornerfigure[height=5cm, border]{media/x.png} puts an image in a corner as an overlay;
  \\begin{besidefigure}[height=5cm]{media/x.png} text \\end{besidefigure} puts text beside it;
  \\fitfigure{media/x.png} scales an image to the room left in the frame.
- Speaker notes: \\note{...} anywhere inside the frame body. Invisible in every normal compile.
- Code in running text: \\SMCode{text}; a command name: \\SMCmd{slide}; a source file as a code
  panel: \\SMCodeFile{snippets/<id>-1.tex}.
- Escape LaTeX specials in text: \\& \\% \\_ \\# \\$. Euro: \\EUR. Do not invent macro names: use
  standard LaTeX, beamer, or macros that appear in the project's slides (search for them)."""

_LAYOUT = """\
Layout helpers (prefer these to hand-measured shifts).
- Content is top-aligned automatically; do not add vertical shifts. [c] centres a frame.
- Two columns go inside standardframe: \\begin{columns}[t,onlytextwidth] with column{0.48\\linewidth} x2.
  Do not combine columns with \\pause reveals next to a bulky image; use an overlay or a minipage.
- Tables: \\begin{gothamtable}[gap=12pt]{lcc} with \\toprule \\midrule \\bottomrule.
- Blocks: block, exampleblock, alertblock, definitionblock, infoblock, referenceblock.
- A stacked fraction in a list: use \\tallitem instead of \\item on that line and the next.
- \\shrinklists{1|2|3} makes lists one to three sizes smaller; \\small or \\footnotesize shrink text.
- A frame that is full overflows into the footer: the lint and render_preview show it; shorten
  the text or split the slide rather than shrinking below \\footnotesize."""


def _frames(ctx: ProjectContext) -> str:
    lines = ["For free-form creation, draft one full frame body and call create_slide once with the open deck name. "
             "It checks, inserts, renders and shows it. add_slide stays for skeletons/translations in place. Frame skeletons:"]
    for frame in slide_add.FRAMES:
        body = slide_add.frame_body(ctx, frame, "Title").replace("\r\n", "\n").strip()
        if frame == slide_add.STANDARD_FRAME:
            lines.append("standardframe: the default content slide, with a title and bullets (columns, tables, blocks inside).")
        lines.append(f"\n{frame}:\n{body}")
    lines.append(
        "\nUse \\source{...} in figureframe/sideimageframe/standardframe for the Source line. highlightframe "
        "is a standardframe with a different title bar for slides the presenter must notice. sectionframe "
        "opens a part (add \\section{...} before its call in the deck). Pass [c] to centre a frame vertically.")
    return "\n".join(lines)


GUIDES: dict[str, tuple[str, str | Callable[[ProjectContext], str]]] = {
    "slides": ("file names, versions, protected parts, deck calls", _SLIDES),
    "frames": ("the frame types and their LaTeX skeletons", _frames),     # built on demand
    "layout": ("columns, tables, blocks, figures, spacing", _LAYOUT),
    "reveals": ("\\pause, \\only, \\slidestep, deck versions", _REVEALS),
    "citations": ("SlideMage.bib, \\fullcite, \\textcite", _CITATIONS),
    "images_and_text": ("images, notes, code and text helpers, escaping", _NOTES_IMAGES + "\n" + IMAGE_DESCRIPTION_RULES),
}
TOPICS = tuple(GUIDES)


def topic_overview() -> str:
    return "; ".join(f"{topic} ({about})" for topic, (about, _text) in GUIDES.items())


def guide(ctx: ProjectContext, topic: str) -> str:
    text = GUIDES[topic][1]
    return text(ctx) if callable(text) else text
