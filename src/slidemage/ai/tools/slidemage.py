"""The SlideMage tools: the deck's slides, lint, previews, new slides, citations, compiling and
the guides (2026-10-10, UI redesign step 10a). Each is a thin layer over the backend module that
does the real work for the rest of the application (deck_outline, latex_lint, preview_target,
slide_add + deck_editor, bibliography, compiler); nothing here parses or writes a file format.
"""
from __future__ import annotations

import re
from pathlib import Path

from ... import (
    bibliography,
    compile_status,
    deck_editor,
    deck_outline,
    deck_scan,
    latex_lint,
    preview_target,
    slide_add,
    slide_ids,
    slide_language,
    slide_snapshot,
)
from ...deck_editor import VIEWS
from ...deck_scan import Deck
from .. import guides
from ..agent_types import EditApplied
from .base import ToolContext, ToolError, tool
from .edits import propose
from .files import current_text, project_path, relative

LIST_LIMIT = 300
PREVIEW_WIDTH = 1280
LOG_TAIL = 15
ERROR_LIMIT = 5
_BARE_ID = re.compile(r"^[A-Za-z0-9]{3}$")


def slide_or_file(ctx: ToolContext, arg: str | None) -> Path:
    """The file `arg` names: a slide id ("1y8" -> its -current.tex) or a project path; the file
    the user is looking at when empty."""
    if arg and arg.strip():
        found = slide_language.current_path_for_bare_id(ctx.project, arg.strip()) if _BARE_ID.match(arg.strip()) else None
        return found or project_path(ctx.root, arg)
    focus = ctx.workspace.context().path
    if focus is None:
        raise ToolError("No file is in focus; give a slide id or a path.")
    return project_path(ctx.root, str(focus))


def open_deck(ctx: ToolContext, name: str | None = None) -> Deck:
    """The deck called `name`, else the one that is open, freshly read from disk."""
    wanted = (name or "").strip().removesuffix(".tex") or (
        ctx.workspace.context().deck.name if ctx.workspace.context().deck else "")
    decks = deck_scan.scan_decks(ctx.project)
    for deck in decks:
        if deck.name == wanted:
            return deck
    available = ", ".join(d.name for d in decks if not d.archived) or "none"
    raise ToolError((f"There is no deck '{wanted}'." if wanted else "No deck is open.") + f" Decks: {available}.")


@tool("list_slides",
      "List the slides of a deck in order, with section, slide id, title, file, how the deck calls it, and "
      "flags (lint error, hidden in the current view, no translation). Defaults to the open deck.",
      {"deck": {"type": "string", "description": "Deck name (decks/<name>.tex); default the open deck."},
       "section": {"type": "string", "description": "Only sections whose title contains this text."},
       "contains": {"type": "string", "description": "Only slides whose id or title contains this text."}})
def list_slides(ctx: ToolContext, args: dict) -> str:
    deck = open_deck(ctx, args.get("deck"))
    context = ctx.workspace.context()
    outline = deck_outline.build_outline(ctx.project, deck, context.view, context.language)
    section, contains = args.get("section", "").lower(), args.get("contains", "").lower()
    lines, shown, total, cut = [], 0, 0, False
    for part in outline:
        total += len(part.rows)
        if section and section not in part.title.lower():
            continue
        rows = [r for r in part.rows if contains in f"{r.call.id_slug} {r.title}".lower()]
        if not rows:
            continue
        if shown >= LIST_LIMIT:         # no heading without a slide under it
            cut = True
            continue
        lines.append(f"§ {part.title}")
        for row in rows:
            if shown >= LIST_LIMIT:
                cut = True
                break
            shown += 1
            call = row.call
            flags = [text for flag, text in ((row.lint_error, "lint error"), (row.hidden, f"hidden in {context.view}"),
                                             (row.missing_translation, f"no {context.language} version")) if flag]
            how = f"\\{call.macro}" + (f" pinned to v{call.version}" if call.version else "") + (
                f" [{','.join(call.conditions)}]" if call.conditions else "") + (f" steps {call.steps}" if call.steps else "")
            lines.append(f"  {row.position}. {call.id} | {row.title} | slides/{call.source_filename} | {how}"
                         + (f" | {', '.join(flags)}" if flags else ""))
    if not lines:
        return f"No slide matches in {deck.name}."
    head = f"Deck {deck.name} (decks/{deck.path.name}), viewed as {context.view}, {context.language}: {total} slides."
    return head + "\n" + "\n".join(lines) + (f"\n[Only the first {LIST_LIMIT}; filter with section or contains.]"
                                             if cut else "")


@tool("lint",
      "Check a file with SlideMage's static LaTeX check (unbalanced braces, unescaped characters, missing "
      "images or citation keys, layout rules ...). It reads the editor buffer if the file is open, so "
      "unsaved edits are checked. It is not a compile: it misses things and cannot see overflow.",
      {"path": {"type": "string", "description": "A slide id (1y8) or a project path; default the file in focus."}})
def lint(ctx: ToolContext, args: dict) -> str:
    path = slide_or_file(ctx, args.get("path"))
    if path.suffix.lower() != ".tex":
        raise ToolError("Only .tex files are checked.")
    issues = latex_lint.lint_text(ctx.project, current_text(ctx.workspace, path), path.name, path)
    name = relative(ctx.root, path)
    if not issues:
        return f"{name}: no problems found."
    errors = sum(1 for i in issues if i.severity == latex_lint.ERROR)
    return (f"{name}: {errors} error(s), {len(issues) - errors} warning(s).\n"
            + "\n".join(latex_lint.format_issue(i) for i in issues))


@tool("render_preview",
      "Typeset a slide and look at the result (the image comes back to you): the view and language the "
      "user has selected, from the editor buffer if the slide is open (unsaved edits included). Takes "
      "seconds. Use it to check layout after an edit: overflow, overlaps, the image on the slide.",
      {"slide": {"type": "string", "description": "A slide id (1y8) or a path; default the slide in focus."}})
def render_preview(ctx: ToolContext, args: dict) -> tuple[str, list[bytes]]:
    path = slide_or_file(ctx, args.get("slide"))
    context = ctx.workspace.context()
    target = None
    if context.deck is not None:
        deck = open_deck(ctx)
        row = deck_outline.slide_row(ctx.project, deck, slide_language.bare_id(path.name), context.view, context.language)
        if row is not None and row.call.source_filename == path.name:
            target = preview_target.for_call(ctx.project, deck, row.call, row.position)
    target = target or preview_target.for_path(ctx.project, path)
    if target is None:
        raise ToolError(f"{path.name} is not a slide file, so there is nothing to preview.")
    try:
        pdf = preview_target.render_text(
            target, current_text(ctx.workspace, path), context.view, context.language,
            footer_timestamp=context.footer_timestamp, log=lambda _line: None)
        png = slide_snapshot.page_png(pdf, PREVIEW_WIDTH)
    except RuntimeError as exc:
        raise ToolError(f"The slide did not compile:\n{str(exc)[-1500:]}") from None
    if png is None:
        raise ToolError("The rendered PDF could not be read.")
    return f"{path.name} as {context.view}, {context.language}:", [png]


@tool("add_slide",
      "Create a new slide (fresh id, header, the frame's skeleton) and put its \\slide call into the deck. "
      "Afterwards fill it in with edit_file. Frame types: see read_guide('frames'). To TRANSLATE a slide, "
      "always pass translation_of (the source slide id) and language: the new slide starts as a copy of the "
      "source, is linked to it both ways, and is then translated in place with edit_file. Never translate by "
      "creating an unlinked slide.",
      {"slug": {"type": "string", "description": "Hyphenated name, letters and digits: 'Capital-Budgeting'."},
       "title": {"type": "string", "description": "The frame title (plain text)."},
       "frame": {"type": "string", "enum": list(slide_add.FRAMES), "description": "Default standardframe."},
       "language": {"type": "string", "enum": list(slide_language.LANGUAGES), "description": "Default: the edited language."},
       "after": {"type": "string", "description": "Slide id to put it after; default the end of the deck."},
       "translation_of": {"type": "string", "description": "Slide id of the slide this is a translation of; "
                          "needs a different language. The body is copied from it; translate it with edit_file."},
       "add_to_deck": {"type": "boolean", "description": "Default true; false creates the file only."}},
      ("slug", "title"))
def add_slide(ctx: ToolContext, args: dict) -> str:
    slug, title = args["slug"].strip(), args["title"].strip()
    frame = args.get("frame", slide_add.STANDARD_FRAME)
    language = args.get("language") or ctx.workspace.context().language
    if not slide_add.SLUG_RE.match(slug):
        raise ToolError("The slug may contain only letters, digits and single hyphens, e.g. 'Capital-Budgeting'.")
    deck, insert_at, indent, where = None, 0, "", "not added to a deck"
    if args.get("add_to_deck", True):
        deck = open_deck(ctx)
        if ctx.workspace.is_dirty(deck.path):
            raise ToolError(f"{deck.path.name} has unsaved edits in the editor, so the call cannot be added "
                            "to it. Ask the user to save it, or use add_to_deck=false.")
        calls = deck_editor.parse_slide_calls(deck)
        after = (args.get("after") or "").strip()
        if after:
            anchor = next((c for c in calls if after in (c.id, c.id_slug)), None)
            if anchor is None:
                raise ToolError(f"The deck has no slide '{after}'. list_slides shows the ids.")
            insert_at, indent, where = anchor.line_end, anchor.indent, f"after {anchor.id} in {deck.name}"
        else:
            insert_at, indent = deck_editor.append_position(deck)
            where = f"at the end of {deck.name}"
    source_id_slug = ""
    if (args.get("translation_of") or "").strip():
        source = slide_or_file(ctx, args["translation_of"])
        source_id_slug = source.name.removesuffix(slide_language.CURRENT_SUFFIX)
        if not slide_add.slide_path(ctx.project, source_id_slug).exists():
            raise ToolError(f"'{args['translation_of']}' is not a slide. list_slides shows the ids.")
        if slide_language.own_language(source_id_slug) == language:
            raise ToolError(f"{source_id_slug} is already {language}; pass the target language.")
        body = slide_ids.slide_body(source).replace("\r\n", "\n")
    else:
        body = slide_add.frame_body(ctx.project, frame, title).replace("\r\n", "\n")
    planned = slide_add.slide_path(ctx.project, f"(new id)-{language}-{slug}")
    if not propose(ctx, planned, "", body, f"New slide {where}"):
        raise ToolError("The user rejected this slide. Do not repeat it; ask what they would prefer.")
    try:
        if source_id_slug:
            created = slide_add.create_copy(ctx.project, source_id_slug, slug, language)
        else:
            created = slide_add.create_new(ctx.project, slug, language, frame, title)
    except (OSError, ValueError) as exc:
        raise ToolError(f"The slide was not created: {exc}") from None
    note = ""
    if deck is not None:
        try:
            deck_editor.insert_slide_call(deck.path, deck.text, insert_at, indent, "slide", created.id_slug)
            ctx.workspace.file_changed(deck.path, deck.text)
        except (deck_editor.StaleFileError, ValueError, OSError) as exc:
            note = f" It could not be added to {deck.name} ({exc}); it exists as a slide file only."
            where = "not added to a deck"
    ctx.workspace.file_changed(created.path, None)
    ctx.emit(EditApplied(ctx.call_id, created.path, "", body, False, undoable=False, note=where))
    return (f"Created slide {created.id_slug} ({relative(ctx.root, created.path)}), {where}.{note} "
            + ("It is a copy of the source, linked to it: translate its text with edit_file."
               if source_id_slug else "It holds the frame skeleton: fill it in with edit_file."))


@tool("add_bib_entry",
      "Add a reference to Slidemaster.bib (kept sorted). Only add what the user gave you or a source they "
      "named states. article: author, title, year, journaltitle, volume, number, pages, doi; book: author, "
      "title, year, publisher, edition, location, isbn; online: author, title, year, url, organization, note; "
      "report: author, title, year, institution, type, doi. Authors as 'Family, Given and Family, Given'.",
      {"kind": {"type": "string", "enum": list(bibliography.TYPE_FIELDS)},
       "fields": {"type": "object", "description": "Field name to text; the required ones are author, title, "
                                                   "year and, for article journaltitle, book publisher, online url."},
       "key": {"type": "string", "description": "Lowercase surname + year ('markowitz1952'); default: suggested."}},
      ("kind", "fields"))
def add_bib_entry(ctx: ToolContext, args: dict) -> str:
    kind, given = args["kind"], args["fields"]
    allowed = dict(bibliography.TYPE_FIELDS[kind])
    unknown = [name for name in given if name not in allowed]
    missing = [name for name, needed in allowed.items() if needed and not str(given.get(name, "")).strip()]
    if unknown:
        raise ToolError(f"A {kind} entry has no field(s) {', '.join(unknown)}. Allowed: {', '.join(allowed)}.")
    if missing:
        raise ToolError(f"A {kind} entry needs: {', '.join(missing)}.")
    fields = {name: str(given[name]) for name in allowed if str(given.get(name, "")).strip()}
    bib = ctx.project.bibliography_path
    existing = bibliography.load(bib)
    key = (args.get("key") or bibliography.suggest_key(fields["author"], fields["year"], existing)).strip()
    if not bibliography.KEY_RE.match(key):
        raise ToolError(f"The key '{key}' should be a lowercase surname plus the year, like 'smith2024'.")
    if ctx.workspace.is_dirty(bib):
        raise ToolError(f"{bib.name} has unsaved edits in the editor, so an entry cannot be added. Ask the user to save it.")
    if key.lower() in {k.lower() for k in existing}:
        raise ToolError(f"The citation key '{key}' already exists in {bib.name}. Use it, or choose another key.")
    entry = bibliography.format_entry(kind, key, fields)
    if not propose(ctx, bib, "", entry, f"New entry in {bib.name}"):
        raise ToolError("The user rejected this entry. Do not repeat it; ask what they would prefer.")
    if ctx.workspace.is_dirty(bib):         # the user may have started typing in it while deciding
        raise ToolError(f"{bib.name} got unsaved edits in the editor meanwhile, so the entry was not added. "
                        "Ask the user to save it.")
    previous = bib.read_text(encoding="utf-8") if bib.is_file() else ""
    try:
        bibliography.add_entry(kind, key, fields, bib)
    except ValueError as exc:
        raise ToolError(str(exc)) from None
    ctx.workspace.file_changed(bib, previous)
    ctx.emit(EditApplied(ctx.call_id, bib, "", entry, False, undoable=False, note="New entry"))
    return f"Added @{kind}{{{key}}} to {bib.name}. Cite it with \\fullcite{{{key}}}."


@tool("compile_deck",
      "Typeset a whole deck to PDF with LaTeX (slow: minutes for a big deck). Reports success per PDF, "
      "or the LaTeX errors with file and line. For a look at one slide use render_preview.",
      {"deck": {"type": "string", "description": "Deck name; default the open deck."},
       "view": {"type": "string", "enum": [*VIEWS, "all"], "description": "Default: the viewed deck version."}})
def compile_deck(ctx: ToolContext, args: dict) -> str:
    deck = open_deck(ctx, args.get("deck"))
    kind = args.get("view") or ctx.workspace.context().view
    log: list[str] = []
    results = ctx.workspace.compile_deck(deck, kind, ctx.cancel, log.append)
    if ctx.cancel.is_set():
        raise ToolError("The compile was stopped by the user.")
    lines = [f"{name}: {'ok' if ok else 'FAILED'}" for name, ok in results.items()] or ["Nothing was compiled."]
    if not all(results.values()):
        errors = [e for e in (compile_status.parse_error(line, ctx.root, deck.path) for line in log) if e]
        lines += [f"{relative(ctx.root, e.path) if e.path.is_relative_to(ctx.root) else e.path.name}"
                  f"{f':{e.line}' if e.line else ''}: {e.message}" for e in errors[:ERROR_LIMIT]]
        if not errors:
            lines += ["Log (end):", *log[-LOG_TAIL:]]
    return "\n".join(lines)


@tool("read_guide",
      f"Read a short guide on SlideMage's slide conventions. Topics: {guides.topic_overview()}.",
      {"topic": {"type": "string", "enum": list(guides.TOPICS)}}, ("topic",))
def read_guide(ctx: ToolContext, args: dict) -> str:
    return guides.guide(ctx.project, args["topic"])
