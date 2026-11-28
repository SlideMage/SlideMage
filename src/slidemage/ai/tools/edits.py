# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Changing files: `edit_file` and `write_file`, and the rules every change follows
(2026-10-10, UI redesign step 10a).

* A file that is open in an editor buffer is changed in the buffer (one undo step, unsaved
  until the user saves it, with the version prompt and the deck questions of the normal save).
  Any other file is written straight away through slide_source.save_slide_source(): a backup
  in slides/.backups/ first, the file's own line ends kept, nothing written if the file
  changed since it was read. A slide's current file written that way gets the "+" on its
  version line (slide_versioning.save_slide()); making a version stays the user's decision.
* A slide's protected parts are never edited: the `%%` lines of its leading comment block (the ordinary `%` notes
  there are editable since v0.14.40), the \\setSlideVersion line -- the parts protected_regions masks from a rewrite
  (\\vbox to 0pt{...} overlay blocks are editable since 2026-10-30) -- and a frozen version (-vX-Y-Z.tex) is a
  historical record and read-only.
* Mode "ask": every change is shown (EditProposed, Workspace.confirm_edit) and waits for the
  user; a rejection is reported to the model. Mode "auto": applied at once. Either way an
  applied change is announced with its before and after text (EditApplied), which is what the
  chat's diff card and Undo need (undo_edit).
"""
from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from ... import ai_review, alt_images, slide_source, slide_versioning
from ...fileio import StaleFileError, write_texts
from ...project import ProjectContext
from ...slide_protection import protected_problem, slide_kind
from ..agent_types import EDIT_ASK, EditApplied, EditProposed, EditRejected
from ..workspace import Workspace
from .base import ToolContext, ToolError, tool
from .files import current_revision, project_path, relative

EDITABLE_SUFFIXES = (".tex", ".bib", ".md", ".txt", ".csv", ".json", ".sty", ".cls", ".yaml", ".yml")
MAX_NEW_FILE_CHARS = 200_000
_log = logging.getLogger(__name__)


def not_frozen(ctx: ProjectContext, path: Path) -> None:
    if slide_kind(ctx, path) == "frozen":
        raise ToolError(f"{path.name} is a frozen version of a slide: a historical record, read-only. "
                        "Edit the slide's -current.tex file instead.")


def _editable(ctx: ToolContext, arg: str) -> Path:
    path = project_path(ctx.root, arg)
    if path.suffix.lower() not in EDITABLE_SUFFIXES:
        raise ToolError(f"{path.name}: only text files can be changed ({', '.join(EDITABLE_SUFFIXES)}).")
    not_frozen(ctx.project, path)
    return path


def propose(ctx: ToolContext, path: Path, before: str, after: str, note: str = "") -> bool:
    """Announce a change; in mode "ask" wait for the user. False (EditRejected sent) when refused."""
    ctx.emit(EditProposed(ctx.call_id, path, before, after, note))
    if ctx.mode != EDIT_ASK or ctx.workspace.confirm_edit(ctx.call_id, path, before, after):
        return True
    ctx.emit(EditRejected(ctx.call_id, path))
    return False


def write_text(workspace: Workspace, path: Path, before: str, after: str, *,
               kind: str = "edit", source: str = "chat agent", review: bool = True,
               expected_raw: str | None = None) -> EditApplied:
    """Apply an editor change or guard a disk write with the raw text captured alongside the proposal."""
    not_frozen(workspace.project, path)
    via_buffer = workspace.is_open(path)
    disk_edit = None
    proposed = after
    if via_buffer:
        problem = workspace.apply_to_buffer(path, before, after)
        if problem:
            raise ToolError(f"{path.name} was not changed: {problem}")
    else:
        try:
            # An undo or rollback (review=False) puts the earlier text back exactly; an edit gets the "+".
            raw = before if expected_raw is None else expected_raw
            _, eol = slide_source.editor_text(raw)
            after = slide_versioning.save_slide(workspace.project, path, after, eol, raw, mark=review)[0]
            disk_edit = (raw, after.replace("\n", eol))
        except slide_source.StaleFileError as exc:
            raise ToolError(f"{path.name} was not changed: {exc}") from None
        if review:
            alt_images.flag_edited_sources(workspace.project, path, before)   # a changed citation is to review
    if review and before != after:
        ai_review.mark(workspace.project, path, kind, source, text=after, before=before)
        ai_review.inserted_slides(workspace.project, path, before, after, source)
        workspace.review_changed()
    if not via_buffer:
        workspace.file_changed(path, before)
    return EditApplied("", path, before, proposed, via_buffer, disk_edit=disk_edit)


def undo_edit(workspace: Workspace, applied: EditApplied) -> str:
    """Put back what an applied edit replaced. "" on success, else why not (the file changed since,
    so the user's later work would be lost)."""
    changed = f"{applied.path.name} has changed since, so the edit cannot be undone automatically."
    if workspace.is_open(applied.path):
        try:
            now = workspace.buffer_text(applied.path)
        except OSError as exc:
            return str(exc)
        if slide_versioning.without_plus(now) != slide_versioning.without_plus(applied.after):
            return changed
        return workspace.apply_to_buffer(applied.path, now, applied.before) or ""
    if applied.disk_edit is None:
        return f"The editor that held the edit to {applied.path.name} has closed."
    before, after = applied.disk_edit
    try:
        slide_source.commit_slide(workspace.project, applied.path, {applied.path: (after, before)})
    except slide_source.StaleFileError:
        return changed
    except OSError as exc:
        return str(exc)
    workspace.file_changed(applied.path, applied.after)
    return ""


@tool("edit_file",
      "Replace one exact piece of text in a project file. old_text must occur exactly once in the "
      "file (include enough surrounding lines to make it unique) and must match it character for "
      "character, tabs included -- read_file first. If the file is open in the editor the change "
      "goes into its buffer (the user can undo it there and saves it themselves). Refused: the "
      "protected parts of a slide, frozen slide versions, non-text files.",
      {"path": {"type": "string", "description": "Project-relative path."},
       "old_text": {"type": "string", "description": "The text to replace, exactly as in the file."},
       "new_text": {"type": "string", "description": "The replacement (may be empty to delete)."}},
      ("path", "old_text", "new_text"))
def edit_file(ctx: ToolContext, args: dict) -> str:
    path = _editable(ctx, args["path"])
    ctx.check_scope(path)
    old, new = args["old_text"], args["new_text"]
    if not old:
        raise ToolError("old_text is empty. To create a file use write_file.")
    raw, _ = current_revision(ctx.workspace, path, exact=True)
    text = raw.replace("\r\n", "\n")
    count = text.count(old)
    if count == 0:
        hint = (" The text exists with different spacing or line breaks: copy it from read_file exactly."
                if " ".join(old.split()) in " ".join(text.split()) else "")
        raise ToolError(f"old_text was not found in {relative(ctx.root, path)}.{hint}")
    if count > 1:
        raise ToolError(f"old_text occurs {count} times in {relative(ctx.root, path)}; add surrounding "
                        "text so that it matches exactly once.")
    after = text.replace(old, new, 1)
    if after == text:
        return "old_text and new_text are the same; nothing to change."
    if slide_kind(ctx.project, path) == "current" and (problem := protected_problem(text, after)):
        raise ToolError(problem)
    if not propose(ctx, path, text, after):
        raise ToolError("The user rejected this edit. Do not repeat it; ask what they would prefer.")
    try:
        applied = write_text(ctx.workspace, path, text, after, expected_raw=raw)
    except ToolError:
        ctx.emit(EditRejected(ctx.call_id, path))      # the card was waiting for the outcome of the user's Apply
        raise
    ctx.emit(replace(applied, call_id=ctx.call_id))
    name = relative(ctx.root, path)
    return (f"Changed {name} in the open editor (not saved yet; the user saves it)." if applied.via_buffer
            else f"Changed {name} and saved it (a backup is kept).")


@tool("write_file",
      "Create a new text file in the project (not for slides: use create_slide or add_slide; never overwrites -- an "
      "existing file is changed with edit_file).",
      {"path": {"type": "string", "description": "Project-relative path of the new file."},
       "content": {"type": "string", "description": "The file's text."}},
      ("path", "content"))
def write_file(ctx: ToolContext, args: dict) -> str:
    path = _editable(ctx, args["path"])
    ctx.check_scope(path)
    content = args["content"].replace("\r\n", "\n")
    if path.exists():
        raise ToolError(f"{relative(ctx.root, path)} exists already. Change it with edit_file.")
    if path.parent == ctx.project.slides_dir.resolve():
        raise ToolError("New slides are created with add_slide (it mints the id and writes the header).")
    if len(content) > MAX_NEW_FILE_CHARS:
        raise ToolError("The file is too large for write_file.")
    if not propose(ctx, path, "", content):
        raise ToolError("The user rejected this file. Do not repeat it; ask what they would prefer.")
    if ctx.workspace.is_dirty(path):
        raise ToolError(f"{relative(ctx.root, path)} has unsaved edits. Ask the user to save them first.")
    try:
        write_texts({path: (None, content)})
    except (StaleFileError, FileExistsError):
        raise ToolError(f"{relative(ctx.root, path)} was created while the user was deciding; it was not overwritten.") from None
    result = f"Created {relative(ctx.root, path)}."
    try:
        alt_images.flag_edited_sources(ctx.project, path, "")
        ai_review.inserted_slides(ctx.project, path, "", content, "chat agent: write_file")
        ctx.workspace.review_changed()
    except Exception as exc:
        _log.exception("Could not update review status after creating %s", path)
        result += f"\nWarning: Review update failed: {exc}"
    try:
        ctx.workspace.file_changed(path, None)
        ctx.emit(EditApplied(ctx.call_id, path, "", content, False, undoable=False))
    except Exception as exc:
        _log.exception("Could not refresh after creating %s", path)
        result += f"\nWarning: Refresh failed: {exc}"
    return result
