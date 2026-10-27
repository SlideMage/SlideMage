# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The SlideMage tools: the deck's slides, lint, previews, new slides, citations, compiling and
the guides (2026-10-10, UI redesign step 10a), QR codes (2026-10-25). Each is a thin layer over
the backend module that does the real work for the rest of the application (deck_outline, latex_lint, preview_target,
slide_add + deck_editor, bibliography, qr_code, compiler); nothing here parses or writes a file format.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from ... import (
    ai_review,
    alt_blocks,
    bibliography,
    compile_status,
    deck_editor,
    deck_headers,
    deck_outline,
    deck_scan,
    latex_lint,
    preview_target,
    qr_code,
    slide_add,
    slide_ids,
    slide_language,
    slide_versioning,
    timing,
)
from ...deck_editor import VIEWS
from ...deck_scan import Deck
from ...slide_protection import protected_problem, slide_kind
from .. import guides
from ..agent_types import EditApplied
from .base import ToolContext, ToolError, tool
from ...tex_source import blanked_verbatim, braced_argument
from .edits import not_frozen, propose, write_text
from .files import current_revision, current_text, project_path, relative

LIST_LIMIT = 300
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


def _insertion(ctx: ToolContext, deck: Deck, after: str) -> tuple[int, str, str]:
    if ctx.workspace.is_dirty(deck.path):
        raise ToolError(f"{deck.path.name} has unsaved edits in the editor; ask the user to save it first.")
    if after:
        anchor = next((c for c in deck_editor.parse_slide_calls(deck) if after in (c.id, c.id_slug)), None)
        if anchor is None:
            raise ToolError(f"The deck has no slide '{after}'. list_slides shows the ids.")
        return anchor.line_end, anchor.indent, f"after {anchor.id} in {deck.name}"
    insert_at, indent = deck_editor.append_position(deck)
    return insert_at, indent, f"at the end of {deck.name}"


def _translation_placement(deck: Deck, source_id_slug: str, after: str) -> tuple[str, slide_add.CallSpec]:
    """(the slide a call goes after, the call) for a new slide: an explicit `after` wins; a translation otherwise
    goes directly after the first call of its source in the deck (slide_add.translation_call) and is called the
    way the source is; elsewhere the end of the deck (`after` empty) and a plain \\slide."""
    anchor = slide_add.translation_call(deck, source_id_slug) if source_id_slug else None
    if anchor is None:
        return after, slide_add.CallSpec("slide")
    return after or anchor.id, slide_add.translation_spec(anchor)


def _insert_call(deck: Deck, insert_at: int, indent: str, id_slug: str, spec: slide_add.CallSpec) -> str:
    return deck_editor.insert_slide_call(deck.path, deck.text, insert_at, indent, spec.macro, id_slug,
                                         spec.version, spec.conditions, spec.steps)


def _insertion_error(ctx: ToolContext, created: slide_add.CreatedSlide, deck: Deck, after: str, exc: Exception) -> str:
    anchor = f", after={after!r}" if after else ""
    return (f"Slide {created.id_slug} already exists at {relative(ctx.root, created.path)}, "
            f"but could not be inserted into {deck.name}: {exc}. "
            f"Retry insertion only with insert_slide(slide={created.id_slug!r}{anchor}) "
            f"once {deck.name} is ready and open; do not create another slide.")


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
    text, source = current_revision(ctx.workspace, path)
    issues = latex_lint.lint_text(ctx.project, text, path.name, path)
    name = f"{relative(ctx.root, path)} ({source})"
    if not issues:
        return f"{name}: no problems found."
    errors = sum(1 for i in issues if i.severity == latex_lint.ERROR)
    return (f"{name}: {errors} error(s), {len(issues) - errors} warning(s).\n"
            + "\n".join(latex_lint.format_issue(i) for i in issues))


PREVIEW_VIEW = {"type": "string", "enum": [*VIEWS, "all"],
                "description": "instructor, during-course, after-course, or all (in that order)."}


@tool("render_preview",
      "Typeset a slide and return labelled images for visual inspection: check layout, overflow and overlaps. "
      "view may be instructor, during-course, after-course, or all. Omitted view uses the selected workspace "
      "view. Includes unsaved editor source. Hidden views have no image; successful views survive partial "
      "failures. Publishes the current view when still current, without changing slide/view selection.",
      {"slide": {"type": "string", "description": "A slide id (1y8) or a path; default the slide in focus."},
       "view": {**PREVIEW_VIEW, "description": PREVIEW_VIEW["description"] + " Default: selected workspace view."}})
def render_preview(ctx: ToolContext, args: dict) -> tuple[str, list[bytes]]:
    return preview_batch_output(ctx, slide_or_file(ctx, args.get("slide")), args.get("view"))


def preview_batch_output(ctx: ToolContext, path: Path, view: str | None, *, saved=False,
                         language: str | None = None, show: bool = False) -> tuple[str, list[bytes]]:
    """One captured batch for chat and MCP; image numbers refer to returned image order."""
    context = ctx.workspace.context()
    if language is None:
        language = slide_language.own_language(path.name) if saved else context.language
        language = language if language in slide_language.TRANSLATION_LANGUAGES else context.language
    context = replace(context, language=language,
                      deck=open_deck(ctx) if context.deck is not None else None)
    try:
        requests = ctx.workspace.prepare_preview_batch(path, view, saved=saved, force=saved, context=context)
    except ValueError as exc:
        raise ToolError(str(exc)) from None
    if saved and any(spec.target.is_frozen_alone for spec in requests):
        raise ToolError(f"{path.name} is a frozen version; only the current slide has a cached preview.")
    if show and any(not spec.target.hidden for spec in requests):
        # Preparation keeps the focused occurrence for the same bare id, otherwise the first occurrence.
        ctx.workspace.show_slide(path)
    results = ctx.workspace.render_preview_batch(path, view, saved=saved, force=saved,
                                                 cancel=ctx.cancel, requests=requests)
    lines, images = [], []
    source = "saved source" if saved else "captured source (including open editor buffers)"
    for result in results:
        spec = result.request
        label = f"{spec.target.bare_id}: {spec.view}, {spec.language}"
        if result.status == 'hidden':
            lines.append(f"{label}: hidden; no preview rendered, no image.")
            continue
        if result.status in ('failed', 'cancelled'):
            error = result.error or result.status
            lines.append(f"{label}: {result.status}; {error[-1500:]}; no image.")
            continue
        publication = result.publication_status
        detail = {'cached': f"cached for {spec.view}", 'displayed': 'displayed in the visible pane',
                  'superseded': 'publication superseded; visible pane unchanged',
                  'failed': f"publication failed: {result.error}"}.get(publication, publication)
        image = result.secondary_png or result.display_png
        if not saved and image is not None:
            images.append(image)
            detail += f"; image #{len(images)} = {spec.view}, {spec.language}"
        elif not saved:
            detail += '; no image available'
        lines.append(f"{label}: {result.status}; {detail}.")
    text = f"{path.name} ({source}):\n" + "\n".join(lines)
    if results and all(result.status in ('failed', 'cancelled') or (saved and result.publication_status == 'failed')
                       for result in results):
        raise ToolError(text)
    timing.event(ctx.root, "render_done", file=path.name)
    return text, images


def slide_target(project, deck: Deck | None, path: Path, view: str, language: str, *,
                 occurrence_key: tuple | None = None) -> preview_target.PreviewTarget | None:
    """The slide file `path` as a preview renders it: as `deck` calls it in `view` and `language`, else alone
    (None when it is no slide file)."""
    try:
        return preview_target.resolve_views(project, deck, path, view, language,
                                            occurrence_key=occurrence_key)[0][1]
    except ValueError:
        return None


def apply_slide(ctx: ToolContext, path: Path, before: str, after: str, *,
                commit: Callable[[], Path] | None = None, protected_before: str | None = None,
                kind: str = "edit", source: str = "modify_slide", note: str = "",
                deck: Path | None = None) -> tuple[str, list[bytes]]:
    """Check/propose, write (or commit a creation), mark, render once and show; shared with C3b.

    Creation passes a planned path and an atomic commit returning the real path. Edits use
    write_text's expected-text, backup and buffer undo path. Validation always precedes writes.
    """
    findings = latex_lint.lint_text(ctx.project, after, "body" if commit else path.name, path)
    problems = [latex_lint.format_issue(i) for i in findings if i.severity == latex_lint.ERROR]
    protected = protected_before if protected_before is not None else (before if commit is None else None)
    if protected is not None and (problem := protected_problem(protected, after)):
        problems.append(problem)
    frames = []
    for name, _, end in alt_blocks.iter_tex_commands(blanked_verbatim(after)):
        if name in ("documentclass", "usepackage", "RequirePackage", "input", "include", *deck_editor.ALL_MACROS):
            problems.append(f"A slide body cannot contain \\{name}.")
        if name in ("begin", "end"):
            cursor = end
            while cursor < len(after) and after[cursor].isspace():
                cursor += 1
            env, _ = braced_argument(after, cursor)
            if env == "document":
                problems.append("A slide body cannot contain a document environment.")
            if name == "begin" and (env == "frame" or env in slide_add.FRAMES):
                frames.append(env)
        elif name in ("titleframe", "quoteframe", "fullbleedframe", "frame"):
            frames.append(name)
    if len(frames) != 1:
        problems.append(f"A slide body needs exactly one frame; found {len(frames)}.")
    if problems:
        raise ToolError("Slide not written:\n" + "\n".join(problems))
    if not propose(ctx, path, before, after, note):
        raise ToolError("The user rejected this slide. Do not repeat it; ask what they would prefer.")
    via_buffer = False
    if commit is None:
        via_buffer = write_text(ctx.workspace, path, before, after, kind=kind, source=source)
    else:
        path = commit()
        ai_review.mark(ctx.project, path, kind, source, deck=deck)
        ctx.workspace.review_changed()
        ctx.workspace.file_changed(path, None)
    timing.event(ctx.root, "slide_written", file=path.name)
    ctx.emit(EditApplied(ctx.call_id, path, before, current_text(ctx.workspace, path), via_buffer,
                         undoable=commit is None, note=note))
    status = f"Slide {path.name.removesuffix(slide_language.CURRENT_SUFFIX)} ({relative(ctx.root, path)})"
    status += (f", {note}" if note else "") + "; Not reviewed."
    warnings = "\n".join(latex_lint.format_issue(i) for i in findings if i.severity != latex_lint.ERROR)
    status += "\nLint: " + (warnings or "no problems found.")
    try:
        language = slide_language.own_language(path.name)
        rendered, images = preview_batch_output(ctx, path, view=None,
                                                language=language if language in slide_language.TRANSLATION_LANGUAGES else None,
                                                show=True)
    except ToolError as exc:
        raise ToolError(f"{status}\nThe slide stays in place; edit this file to fix it.\nThe slide did not compile:\n{exc}") from None
    return f"{status}\n{rendered}", images


@tool("modify_slide",
      "Change an existing slide with ordered exact replacements or full text. "
      "Checks, writes (open editor or file), marks Not reviewed, renders once and shows the preview. "
      "Frozen versions and protected changes are refused; a compile failure keeps the change.",
      {"slide": {"type": "string", "description": "A bare slide id follows the EN/DE switch to its linked partner; an explicit path is used as given."},
       "edits": {"type": "array", "minItems": 1, "description": "Ordered replacements; each old must match exactly once.",
                 "items": {"type": "object", "properties": {"old": {"type": "string", "minLength": 1},
                                                          "new": {"type": "string"}},
                           "required": ["old", "new"], "additionalProperties": False}},
       "body": {"type": "string", "description": "Full new slide text, including unchanged protected parts; instead of edits."},
       "expected": {"type": "string", "description": "Text you read; refuse if the current text differs."}},
      ("slide",))
def modify_slide(ctx: ToolContext, args: dict) -> str | tuple[str, list[bytes]]:
    if ("edits" in args) == ("body" in args):
        raise ToolError("Pass exactly one of edits or body.")
    path = project_path(ctx.root, str(slide_or_file(ctx, args["slide"])))
    not_frozen(ctx.project, path)
    if slide_kind(ctx.project, path) != "current" or not path.is_file():
        raise ToolError("modify_slide needs an existing live slide id or slides/*-current.tex path.")
    note = ""
    slide = args["slide"].strip()
    if _BARE_ID.match(slide):
        language = ctx.workspace.context().language
        links = slide_language.TranslationLinks(ctx.project.slides_dir)
        if partner := links.find(path.name.removesuffix(slide_language.CURRENT_SUFFIX), language):
            path = project_path(ctx.root, str(ctx.project.slides_dir / slide_language.current_name(partner)))
            note = f"{slide} in {language} is its partner {partner}"
    ctx.check_scope(path)
    before, revision = current_revision(ctx.workspace, path)
    if "expected" in args and (slide_versioning.without_plus(args["expected"])
                               != slide_versioning.without_plus(before)):      # the "+" is no change
        raise ToolError(f"{relative(ctx.root, path)} changed since you read it; nothing written. "
                        f"Read it again and retry. Current text ({revision}, first 1500 characters):\n{before[:1500]}")
    after = args.get("body", before)
    if "edits" in args:
        for index, edit in enumerate(args["edits"], 1):      # their shape is the schema's (check_arguments)
            count = after.count(edit["old"])
            if count != 1:
                raise ToolError(f"Edit {index}: old occurs {count} times in {relative(ctx.root, path)}; "
                                "nothing written. Copy enough current text to match exactly once.")
            after = after.replace(edit["old"], edit["new"], 1)
    if after == before:
        return f"{note + '. ' if note else ''}{relative(ctx.root, path)} ({revision}): nothing to change."
    kind = "translation" if slide_language.TRANSLATION_OF_RE.search(before) else "edit"
    return apply_slide(ctx, path, before, after, kind=kind, note=f"{note + '; ' if note else ''}base: {revision}")


@tool("add_slide",
      "Create a new slide (fresh id, header, the frame's skeleton) and put its \\slide call into the deck. "
      "Fill in its body afterwards. Use insert_slide for an existing slide. "
      "Frame types: see read_guide('frames'). To TRANSLATE a slide, "
      "always pass translation_of (the source slide id) and language: the new slide starts as a copy of the "
      "source, is linked to it both ways, and is then translated in place. Never translate by "
      "creating an unlinked slide.",
      {"slug": {"type": "string", "description": "Required for creation: hyphenated letters and digits, e.g. 'Capital-Budgeting'."},
       "title": {"type": "string", "description": "Required for creation: the frame title (plain text)."},
       "frame": {"type": "string", "enum": list(slide_add.FRAMES), "description": "Default standardframe."},
       "language": {"type": "string", "enum": list(slide_language.LANGUAGES), "description": "Default: the edited language."},
       "after": {"type": "string", "description": "Slide id to put it after; default the end of the deck, "
                 "or directly after the source slide for a translation."},
       "translation_of": {"type": "string", "description": "Slide id of the slide this is a translation of; "
                          "needs a different language. The body is copied from it; translate it in place."},
       "add_to_deck": {"type": "boolean", "description": "Default true; false creates the file only."}})
def add_slide(ctx: ToolContext, args: dict) -> str:
    ctx.check_scope()
    for name in ("slug", "title"):
        if name not in args:
            raise ToolError(f"Missing required argument '{name}' for creation; use insert_slide to insert a slide.")
    slug, title = args.get("slug", "").strip(), args.get("title", "").strip()
    frame = args.get("frame", slide_add.STANDARD_FRAME)
    language = args.get("language") or ctx.workspace.context().language
    if not slide_add.SLUG_RE.match(slug):
        raise ToolError("The slug may contain only letters, digits and single hyphens, e.g. 'Capital-Budgeting'.")
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
    deck, insert_at, indent, where, spec, after = None, 0, "", "not added to a deck", slide_add.CallSpec("slide"), ""
    if args.get("add_to_deck", True):
        deck = open_deck(ctx)
        after, spec = _translation_placement(deck, source_id_slug, (args.get("after") or "").strip())
        insert_at, indent, where = _insertion(ctx, deck, after)
    planned = slide_add.slide_path(ctx.project, f"(new id)-{language}-{slug}")
    if not propose(ctx, planned, "", body, f"New slide {where}"):
        raise ToolError("The user rejected this slide. Do not repeat it; ask what they would prefer.")
    try:
        created = (slide_add.create_copy(ctx.project, source_id_slug, slug, language) if source_id_slug
                   else slide_add.create_new(ctx.project, slug, language, frame, title))
    except (OSError, ValueError) as exc:
        raise ToolError(f"The slide was not created: {exc}") from None
    ai_review.mark(ctx.project, created.path, "translation" if source_id_slug else "draft", "add_slide")
    if source_id_slug:
        ai_review.mark(ctx.project, source, "translation", "add_slide: translation partner")
    ctx.workspace.review_changed()
    failure = ""
    if deck is not None:
        try:
            if ctx.workspace.is_dirty(deck.path):
                raise ToolError("the deck has unsaved edits in the editor; ask the user to save it first")
            updated = _insert_call(deck, insert_at, indent, created.id_slug, spec)
            ai_review.inserted_slides(ctx.project, deck.path, deck.text, updated, "add_slide")
            ctx.workspace.review_changed()
            ctx.workspace.file_changed(deck.path, deck.text)
        except (deck_editor.StaleFileError, ValueError, OSError, ToolError) as exc:
            failure = _insertion_error(ctx, created, deck, after, exc)
            where = "not added to a deck"
    ctx.workspace.file_changed(created.path, None)
    ctx.emit(EditApplied(ctx.call_id, created.path, "", body, False, undoable=False, note=where))
    if failure:
        raise ToolError(failure)
    detail = ("It is a copy of the source, linked to it: translate its text in place." if source_id_slug
              else "It holds the frame skeleton: fill in its body.")
    return f"Created slide {created.id_slug} ({relative(ctx.root, created.path)}), {where}. {detail}"


@tool("insert_slide",
      "Insert an existing live slide into the open deck; if it is already present, do nothing.",
      {"slide": {"type": "string", "description": "Existing live slide id or slides/*-current.tex path."},
       "after": {"type": "string", "description": "Slide id to insert after; default the end of the deck, "
                 "or directly after the translation source."}}, required=("slide",))
def insert_slide(ctx: ToolContext, args: dict) -> str:
    ctx.check_scope()
    slide = args["slide"].strip()
    path = (slide_or_file(ctx, slide) if _BARE_ID.match(slide) or slide.endswith(".tex")
            else project_path(ctx.root, str(slide_add.slide_path(ctx.project, slide))))
    if path.parent != ctx.project.slides_dir.resolve() or not path.name.endswith(slide_language.CURRENT_SUFFIX) or not path.is_file():
        raise ToolError(f"'{slide}' is not an existing live slide; pass its id or slides/*-current.tex path.")
    created = slide_add.CreatedSlide(path.name.removesuffix(slide_language.CURRENT_SUFFIX), path)
    deck = open_deck(ctx)
    if any(c.source_filename == path.name for c in deck_editor.parse_slide_calls(deck)):
        return f"Slide {created.id_slug} ({relative(ctx.root, path)}) is already in {deck.name}; no change."
    source = slide_language.TRANSLATION_OF_RE.search(current_text(ctx.workspace, path))
    after, spec = _translation_placement(deck, source.group(1) if source else "", (args.get("after") or "").strip())
    insert_at, indent, where = _insertion(ctx, deck, after)
    if not propose(ctx, deck.path, "", deck_editor.format_call(spec.macro, created.id_slug, spec.version, spec.conditions, spec.steps), f"Insert slide {where}"):
        raise ToolError("The user rejected this slide. Do not repeat it; ask what they would prefer.")
    try:
        if ctx.workspace.is_dirty(deck.path):
            raise ToolError("the deck has unsaved edits in the editor; ask the user to save it first")
        updated = _insert_call(deck, insert_at, indent, created.id_slug, spec)
        ai_review.inserted_slides(ctx.project, deck.path, deck.text, updated, "insert_slide")
        ctx.workspace.review_changed()
        ctx.workspace.file_changed(deck.path, deck.text)
        ctx.emit(EditApplied(ctx.call_id, deck.path, deck.text, updated, False, undoable=False, note=where))
    except (deck_editor.StaleFileError, ValueError, OSError, ToolError) as exc:
        raise ToolError(_insertion_error(ctx, created, deck, after, exc)) from None
    return f"Inserted slide {created.id_slug} ({relative(ctx.root, path)}), {where}."


@tool("create_slide",
      "Draft the complete LaTeX frame body yourself, then create, insert, mark Not reviewed, render and "
      "show it in one call. deck defaults to the open deck; if given, it must name it. Invalid bodies write "
      "nothing; a compile failure keeps the slide for one edit. Use add_slide for skeletons or translations in place.",
      {"title": {"type": "string", "description": "Slide title (plain text)."},
       "slug": {"type": "string", "description": "Hyphenated letters and digits, e.g. Capital-Budgeting."},
       "body": {"type": "string", "description": "Complete LaTeX frame, without a document wrapper or managed header."},
       "deck": {"type": "string", "description": "Default: the open deck; if given, must name it."},
       "language": {"type": "string", "enum": list(slide_language.LANGUAGES), "description": "Default edited language."},
       "after": {"type": "string", "description": "Slide id; default end of deck, or directly after the source for a translation."},
       "translation_of": {"type": "string", "description": "Source slide id; preserve its protected body regions."},
       "frame": {"type": "string", "enum": list(slide_add.FRAMES), "description": "Optional frame type."}},
      ("title", "slug", "body"))
def create_slide(ctx: ToolContext, args: dict) -> tuple[str, list[bytes]]:
    ctx.check_scope()
    deck = open_deck(ctx)

    def check_deck() -> None:
        wanted = args["deck"].strip() if "deck" in args else ""
        matches = "deck" not in args or wanted in (deck.name, deck.path.name) or (
            bool(wanted) and project_path(ctx.root, wanted) == deck.path.resolve())
        if not matches or not ctx.workspace.is_open_deck(deck.path):
            raise ToolError(f"Requested deck '{wanted}' is not the open deck {deck.name}; no slide created.")

    check_deck()
    slug, title = args["slug"].strip(), args["title"].strip()
    if not slide_add.SLUG_RE.fullmatch(slug):
        raise ToolError("The slug may contain only letters, digits and single hyphens.")
    language = args.get("language") or ctx.workspace.context().language
    body = args["body"].replace("\r\n", "\n")
    source, source_text, source_id_slug, protected = None, "", "", None
    if args.get("translation_of", "").strip():
        source = slide_or_file(ctx, args["translation_of"])
        if source.parent != ctx.project.slides_dir.resolve() or not source.name.endswith(slide_language.CURRENT_SUFFIX) or not source.is_file():
            raise ToolError("translation_of must name a live slide.")
        source_id_slug = source.name.removesuffix(slide_language.CURRENT_SUFFIX)
        if slide_language.own_language(source_id_slug) == language:
            raise ToolError(f"{source_id_slug} is already {language}; pass the target language.")
        source_text = current_text(ctx.workspace, source)
        protected = slide_ids.body_of(source_text)
    after, spec = _translation_placement(deck, source_id_slug, args.get("after", "").strip())
    insert_at, indent, where = _insertion(ctx, deck, after)

    def commit() -> Path:
        check_deck()
        _insertion(ctx, deck, after)  # recheck dirtiness after confirmation, before creating anything
        created = (slide_add.create_translation(ctx.project, source_id_slug, slug, language, slide_versioning.strip_marker(body)) if source
                   else slide_add.create_new(ctx.project, slug, language, args.get("frame", slide_add.STANDARD_FRAME), title, body=body))
        linked = slide_ids.with_translation_backreference(source_text, language, created.id_slug) if source else ""
        source_changed = False
        try:
            if source:
                write_text(ctx.workspace, source, source_text, linked, review=False)
                source_changed = True
            check_deck()
            _insertion(ctx, deck, after)
            updated = _insert_call(deck, insert_at, indent, created.id_slug, spec)
        except (OSError, ValueError, deck_editor.StaleFileError, ToolError) as exc:
            try:
                if source_changed:
                    write_text(ctx.workspace, source, linked, source_text, review=False)
                slide_add.remove_created(ctx.project, created)
            except (OSError, ValueError, deck_editor.StaleFileError, ToolError) as rollback:
                ai_review.mark(ctx.project, created.path, "translation" if source else "draft", "create_slide")
                if source_changed:
                    ai_review.mark(ctx.project, source, "translation", "create_slide: translation partner",
                                   text=current_text(ctx.workspace, source))
                ctx.workspace.review_changed()
                ctx.workspace.file_changed(created.path, None)
                raise ToolError(_insertion_error(ctx, created, deck, after, exc) + f" Rollback failed: {rollback}.") from None
            raise ToolError(f"Slide not created: {exc}. File and id rolled back; retry create_slide.") from None
        if source:
            ai_review.mark(ctx.project, source, "translation", "create_slide: translation partner", text=linked)
        # The header that names the deck, now: the header sync after the deck edit would otherwise rewrite the
        # new file while its preview renders, and the Preview drops a render of a file that changed meanwhile.
        deck_headers.regenerate_header(ctx.project, created.path)
        ctx.workspace.file_changed(deck.path, deck.text)
        ctx.emit(EditApplied(ctx.call_id, deck.path, deck.text, updated, False, undoable=False, note=where))
        return created.path

    planned = slide_add.slide_path(ctx.project, f"(new id)-{language}-{slug}")
    return apply_slide(ctx, planned, "", body, commit=commit, protected_before=protected,
                       kind="translation" if source else "draft", source="create_slide", note=where, deck=deck.path)


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


@tool("make_qr_code",
      "Make a QR code file in media/ (PDF; never overwrites one) and get the \\SMQRCode call that shows it, "
      "for you to put on a slide with modify_slide or an edit. Fields by kind -- url: url; email: to, subject, "
      "body; contact (vCard): name, organization, title, email, phone, website, street, postcode, city, country; "
      "event: title, start ('2026-12-14 10:00', or '2026-12-14' with all_day 'true'), end, all_day, location, "
      "description, url; location: place (address, 'lat, lng' or a map link), label, map_link (google, geo, osm). "
      "With several codes on one slide give each a caption such as 'QR 1' that the text refers to.",
      {"kind": {"type": "string", "enum": list(qr_code.KINDS)},
       "fields": {"type": "object", "additionalProperties": {"type": "string"},
                  "description": "Field name to text, as listed for the kind."},
       "caption": {"type": "string", "description": "Text under the code; default none. 'auto' for the link, "
                                                    "address, name, event or place."},
       "height": {"type": "number", "description": "Share of \\textheight, default 0.6 (a lecture hall's back row); "
                                                   "the result gives the recommended heights."},
       "corner": {"type": "string", "enum": [c for c in qr_code.CORNERS if c],
                  "description": "Put the code in this corner of the content area (\\cornerfigure); default: "
                                 "where the call is put."},
       "name": {"type": "string", "description": "File name in media/ without suffix; default from the caption."}},
      ("kind", "fields"))
def make_qr_code(ctx: ToolContext, args: dict) -> str:
    kind, given = args["kind"], args["fields"]
    unknown = [name for name in given if name not in qr_code.FIELDS[kind]]
    if unknown:
        raise ToolError(f"A {kind} code has no field(s) {', '.join(unknown)}. Fields: {', '.join(qr_code.FIELDS[kind])}.")
    spec = qr_code.QRSpec(kind, {name: str(value) for name, value in given.items()}, qr_code.default_error(kind))
    caption = (args.get("caption") or "").strip()
    mode = qr_code.CAPTION_CONTENT if caption == "auto" else qr_code.CAPTION_CUSTOM if caption else qr_code.CAPTION_NONE
    height = args.get("height", qr_code.DEFAULT_HEIGHT)
    if not 0 < height <= qr_code.MAX_HEIGHT:
        raise ToolError(f"The height is a share of \\textheight between 0 and {qr_code.MAX_HEIGHT}.")
    try:
        made = qr_code.create(ctx.project, spec, height=float(height), caption_mode=mode,
                              caption=caption if mode == qr_code.CAPTION_CUSTOM else "", name=args.get("name", ""),
                              corner=args.get("corner", ""))
    except ValueError as exc:
        raise ToolError(str(exc)) from None
    ctx.workspace.file_changed(made.path, None)
    return f"Made {made.image}. {made.note}\nPut this on the slide:\n{made.snippet}"


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
