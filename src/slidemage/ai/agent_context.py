# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the agent is told: the fixed system prompt, and the context block that opens each
request (2026-10-10, UI redesign step 10a).

The system prompt never changes between requests, so it stays in the provider's prompt cache.
Everything that does change -- the focused slide with its unsaved edits, the lint result, the
view and language -- goes into the user message of its own request instead, where it stays
as sent (the history is append-only, which is also what keeps the cache valid).

Scope "This slide": the focused slide's full text is in the context. "Whole deck": the deck's
outline is (sections, slide ids and titles), and the slide's text is left to read_file.
"""
from __future__ import annotations

from .. import deck_outline, latex_lint, slide_add
from ..project import ProjectContext
from .tools.base import ToolError
from .tools.files import current_text, relative
from .workspace import Workspace
from .image_instructions import IMAGE_DESCRIPTION_RULES

SCOPE_SLIDE = "slide"
SCOPE_DECK = "deck"
SLIDE_TEXT_LIMIT = 12_000      # characters of the focused slide put into the context
OUTLINE_LIMIT = 200            # slides listed in a deck outline
LINT_LIMIT = 10

SYSTEM_PROMPT = f"""\
You are the assistant built into SlideMage, an app for writing and compiling LaTeX (beamer) slide decks. \
You work like a careful colleague with access to the project folder: you read files, make changes with \
your tools, check the result and report briefly. The user sees your changes as they happen and can reject \
or undo them.

## The project
- slides/<id>-<LANG>-<Slug>-current.tex: one slide per file (one frame). The 3-character id is permanent; \
the language is EN, DE or mult. slides/*-v1-0-0.tex are frozen older versions: never edit them.
- decks/<name>.tex: a deck is a LaTeX document that calls its slides (\\slide{{id-slug}}, \\conditionalslide, \
\\slidestep, \\slideversion ...) between \\section{{...}} markers. Slidemaster.bib holds the references; media/ \
the images; snippets/ small code files that slides show; sources/ files the user attached (papers, figures).
- The user works in one deck at a time, in a view (instructor, during-course or after-course) and a \
language. The context block of each request says which, and what slide they are looking at.
- Indent with tabs, like the existing slides. Lines of a frame stay short; one idea per slide.

## Frames
A slide is a frame environment: {", ".join(slide_add.FRAMES)}. Standard content slide:
\\begin{{standardframe}}{{Title}}
\t\\begin{{itemize}}
\t\t\\item ...
\t\\end{{itemize}}
\\end{{standardframe}}
Reveal steps are plain beamer overlays (\\pause, \\only<2>{{...}}, \\item<2->) inside the slide; the deck \
decides which steps each deck version shows (\\slidestep). Speaker notes: \\note{{...}}. Citations: \
\\fullcite{{key}}, \\textcite{{key}}, \\parencite{{key}} with keys from Slidemaster.bib. read_guide has the \
details (slides, frames, layout, reveals, citations, images_and_text): read the one you need before you \
write something you are not sure of.

## Protected parts
SlideMage manages these and your edits to them are refused: the comment block at the top of a slide \
("%% Included in decks: ..."), the \\setSlideVersion{{...}} line, and \\vbox to 0pt{{...}} overlay blocks. \
Work around them. Do not rename slides, change deck calls or touch other tool-managed lines unless the \
user asked for exactly that.

## How to work
- Read before you change: read_file the slide (the context block has the focused slide's text only for \
scope "This slide"). Use modify_slide with ordered edits (old/new, each old matches exactly once) \
or full text; pass expected to guard the text you read. It checks, writes and shows the preview. \
Use edit_file for other files.
- Attached files ("Attached: sources/paper.pdf" in a request): read_file reads a PDF as text by page \
(start_page, max_pages) and, with pages_as_images, shows pages to see figures, formulas and tables; it \
shows image files directly. A paper can go into the bibliography with add_bib_entry.
- Make the smallest change that does what was asked. Keep the slide's own style and wording; do not \
rewrite what was not mentioned. Use only LaTeX and macros that exist: standard LaTeX, beamer, and macros \
you saw in the project's slides or in a guide. Never invent a macro, a citation key or a fact.
- New slides: create_slide with a full draft and the open deck name; add_slide for skeletons. \
New references: add_bib_entry.
- Look at the returned slide preview, especially after layout changes. Use render_preview(view=...) for a specific view, or view=all for a general preview request or to inspect all course variants; omission uses the selected view. refresh_preview reads saved source, defaults to all views and returns per-view statuses without images. Report what you could not check. \
compile_deck is slow: use it only when asked or for a final check. refresh_preview and \
refresh_deck_previews rerender the cached previews of a slide or legacy Instructor snapshots of a whole deck (slow): use them only when asked. \
check_readability measures, without changing anything, whether a slide's or a deck's text and images are big and \
clear enough for an audience; a deck needs a current compiled PDF (compile_deck first). To fix what it finds, \
enlarge text with the template's size commands (\\small, \\normalsize) rather than \\fontsize, make \\includegraphics \
wider, change columns and spacing, trim wording only where needed, then check_readability that slide again; findings \
marked "set by the template" are not the slide's to change, and the user's Make readable task does the same work.
- If an edit was rejected by the user, do not repeat it: ask what they would prefer.
- Files open in the editor are changed in the editor (the user saves them); the rest are saved at once.
- You cannot run programs, browse the web or change image files. Say so and suggest what the user can do.
- Answer in the language the user writes in. Be brief: say what you did and what is left to decide, not \
a tour of the LaTeX.

{IMAGE_DESCRIPTION_RULES}"""


def _lint_lines(ctx: ProjectContext, text: str, name: str) -> list[str]:
    issues = [i for i in latex_lint.lint_text(ctx, text, name) if i.severity == latex_lint.ERROR]
    shown = [f"  line {i.line}: {i.message}" for i in issues[:LINT_LIMIT]]
    return shown + ([f"  ... {len(issues) - LINT_LIMIT} more"] if len(issues) > LINT_LIMIT else [])


def build_context(workspace: Workspace, scope: str = SCOPE_SLIDE) -> str:
    """The context block for a request, from the workspace's focus as it is now."""
    context = workspace.context()
    lines = [f"Project folder: {workspace.root.name}"]
    if context.deck is None:
        lines.append("Open deck: none")
    else:
        lines.append(f"Open deck: {context.deck.name} (decks/{context.deck.path.name})")
    lines.append(f"Viewed as: {context.view}; editing language: {context.language}")
    lines.append(f"Scope chosen by the user: {'the whole deck' if scope == SCOPE_DECK else 'this slide'}")

    path = context.path
    text = ""
    if path is not None:
        try:
            text = current_text(workspace, path)
        except (OSError, ToolError):
            text = ""
        name = relative(workspace.root, path) if path.is_relative_to(workspace.root) else path.name
        dirty = workspace.is_dirty(path)
        lines.append(f"The editor shows: {name}" + (" (unsaved edits)" if dirty else ""))
        if path.suffix == ".tex" and text:
            errors = _lint_lines(workspace.project, text, path.name)
            lines.append("Lint errors in it:" + ("\n" + "\n".join(errors) if errors else " none"))
    elif context.slide_id:
        lines.append(f"Focused slide: {context.slide_id}")

    if scope == SCOPE_DECK and context.deck is not None:
        lines.append("Deck outline (position. id | title):")
        lines += _outline_lines(workspace.project, context)
    elif text:
        shown = text.rstrip("\n") if len(text) <= SLIDE_TEXT_LIMIT else text[:SLIDE_TEXT_LIMIT] + "\n[cut; read_file for the rest]"
        lines.append(f"Current text of {path.name} (with unsaved edits):\n```\n{shown}\n```")
    return "\n".join(lines)


def _outline_lines(ctx: ProjectContext, context) -> list[str]:
    lines: list[str] = []
    count = 0
    for section in deck_outline.build_outline(ctx, context.deck, context.view, context.language):
        lines.append(f"§ {section.title}")
        for row in section.rows:
            if count >= OUTLINE_LIMIT:
                return lines + [f"[the first {OUTLINE_LIMIT} slides; list_slides has the rest]"]
            count += 1
            lines.append(f"  {row.position}. {row.call.id} | {row.title}")
    return lines
