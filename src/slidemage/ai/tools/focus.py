"""The tools only the Claude Code connection has (UI redesign step 10c): what the user is looking at, bringing
a slide into view, and the editor buffer with its unsaved edits. Claude Code reads and edits files on disk with its own tools;
these show what SlideMage's window knows beyond the disk."""
from __future__ import annotations

from ... import latex_lint
from ...selection import CONTEXT_CHARS, SelectionError
from .base import ToolContext, ToolError, tool
from .files import current_revision, may_touch, project_path, read_file, relative

LINT_SHOWN = 10


@tool("get_focus",
      "What the user is looking at in SlideMage right now: the project, the open deck, the focused slide "
      "and the file the editor shows, the 'View as' and language, whether that file has unsaved edits in the "
      "editor (then the file on disk is older: use read_buffer), and its lint errors. Call only if the "
      "prompt's scope focus is missing or stale.",
      {})
def get_focus(ctx: ToolContext, args: dict) -> str:
    focus = ctx.workspace.context()
    lines = [f"Project folder: {ctx.root}",
             f"Open deck: {f'decks/{focus.deck.path.name}' if focus.deck else 'none'}",
             f"Viewed as: {focus.view}; editing language: {focus.language}",
             f"Focused slide id: {focus.slide_id or 'none'}"]
    path = focus.path
    if path is None:
        lines.append("The editor shows no file.")
        return "\n".join(lines)
    if not may_touch(ctx.root, path):
        lines.append("The editor shows a file that is not part of what you may see (outside the project, or one of "
                     "SlideMage's own folders).")
        return "\n".join(lines)
    name = relative(ctx.root, path.resolve())
    if path.suffix == ".tex":
        text, source = current_revision(ctx.workspace, path)
        dirty = source == "editor (unsaved)"
    else:
        dirty = ctx.workspace.is_dirty(path)
    lines.append(f"File shown: {name}" + (" (unsaved edits in the editor: the file on disk is older; "
                                          "read_buffer shows them)" if dirty else ""))
    if path.suffix == ".tex":
        errors = [i for i in latex_lint.lint_text(ctx.project, text, path.name, path) if i.severity == latex_lint.ERROR]
        lines.append(f"Lint errors in {source}: "
                     + ("none" if not errors else str(len(errors))))
        lines += [f"  line {i.line}: {i.message}" for i in errors[:LINT_SHOWN]]
    return "\n".join(lines)


@tool("show_slide",
      "Bring a slide into focus in SlideMage, so the user sees its preview and source. Call it after you "
      "created a slide or changed one the user is not looking at.",
      {"path": {"type": "string", "description": "Project-relative path, e.g. slides/1y8-EN-Title-current.tex"}},
      ("path",))
def show_slide(ctx: ToolContext, args: dict) -> str:
    path = project_path(ctx.root, args["path"])
    if path.parent.name != "slides" or path.suffix != ".tex" or not path.is_file():
        raise ToolError(f"{args['path']} is no slide file: slides/<id>-<LANG>-<Slug>-current.tex.")
    ctx.workspace.show_slide(path)
    return f"SlideMage shows {relative(ctx.root, path)}."


@tool("translate_slide",
      "Translate a slide into the other language (EN <-> DE) with SlideMage's own translation, the one of its "
      "Translate bubble: the project's form of address and glossary, a new linked slide placed after the "
      "source in the deck. It runs in SlideMage, which shows its progress; do not translate by hand.",
      {"path": {"type": "string", "description": "Project-relative path, e.g. slides/1y8-EN-Title-current.tex"}},
      ("path",))
def translate_slide(ctx: ToolContext, args: dict) -> str:
    path = project_path(ctx.root, args["path"])
    if path.parent.name != "slides" or path.suffix != ".tex" or not path.is_file():
        raise ToolError(f"{args['path']} is no slide file: slides/<id>-<LANG>-<Slug>-current.tex.")
    return ctx.workspace.translate_slide(path)


@tool("switch_to_deck_mode",
      "Switch to Deck Mode: widen SlideMage's scope from the slide in focus to the whole deck, so you may "
      "add slides and change other slides of the deck. The user is asked before it runs.",
      {})
def switch_to_deck_mode(ctx: ToolContext, args: dict) -> str:
    return ctx.workspace.switch_to_deck_mode()


@tool("read_buffer",
      "Read a file as the SlideMage editor has it, unsaved edits included, with numbered lines. "
      "Only for files open in the editor; use your own Read for the rest.",
      {"path": {"type": "string", "description": "Project-relative path, e.g. slides/1y8-EN-Title-current.tex"},
       "start_line": {"type": "integer", "description": "First line to read (default 1)."},
       "max_lines": {"type": "integer", "description": "How many lines at most."}},
      ("path",))
def read_buffer(ctx: ToolContext, args: dict) -> str:
    path = project_path(ctx.root, args["path"])
    if not ctx.workspace.is_open(path):
        raise ToolError(f"{relative(ctx.root, path)} is not open in the editor, so there is no buffer: "
                        "the file on disk is what your own Read shows.")
    return read_file.run(ctx, args)


@tool("read_selection",
      "The text the user has selected in the SlideMage editor, for a request about 'this' or 'the selection': the "
      "file, the selected range (characters and lines) and the exact selected text, with some text before and after "
      "it. The selection is taken at the moment you call, from the editor's buffer (unsaved edits included). Fails "
      "when nothing is selected, the slide is a frozen version or the selection reaches into a protected part of the "
      "slide (the comment block at the top, the \\setSlideVersion line, a \\vbox to 0pt{...} block). It changes nothing; "
      "to change the selected text, use modify_slide on that slide.",
      {})
def read_selection(ctx: ToolContext, args: dict) -> str:
    try:
        chosen = ctx.workspace.selection()
    except SelectionError as exc:
        raise ToolError(str(exc)) from None
    text, start, end = chosen.text, chosen.start, chosen.end
    first, last = text.count("\n", 0, start) + 1, text.count("\n", 0, end) + 1
    return "\n".join([
        f"File: {relative(ctx.root, chosen.path)} (the editor's buffer)",
        f"Selected: characters {start}-{end}, lines {first}-{last}",
        "Text before the selection:", text[max(0, start - CONTEXT_CHARS):start], "--- the selection ---", chosen.selected,
        "--- end of the selection ---", "Text after the selection:", text[end:end + CONTEXT_CHARS]])
