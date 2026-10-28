# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The hooks that record Claude writes and keep the embedded Claude Code away from what SlideMage manages (UI redesign
step 10c). Claude Code runs this command before every Edit, Write or MultiEdit, with the call as JSON on
stdin; exit code 2 blocks the call and hands stderr to Claude as the reason, any other code lets it go.

    python -m slidemage.ai.claude_hook        (from a source checkout / installed package)
    SlideMage --claude-hook                   (the PyInstaller build; cli.main handles the flag)

The rules are the chat tools' (tools/edits.py): an edit that changes a slide's protected parts (header
comment, \\setSlideVersion, \\vbox to 0pt{...} blocks) is refused, and a frozen version (-vX-Y-Z.tex) is read-only.
Everything else, and anything this hook cannot work out (except a slide that exists but cannot be read), is allowed: it must never get in the way of a
call that is fine, and a crash is only a warning. It cannot see what a Bash command does to a file.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .. import project, timing
from ..plugins.hook import HookContext
from ..project import ProjectContext
from . import claude_scope
from ..slide_protection import protected_problem

BLOCK = 2
FROZEN_MESSAGE = ("{name} is a frozen version of a slide: a historical record, read-only. "
                  "Edit the slide's -current.tex file instead.")
UNREADABLE_MESSAGE = ("{name} cannot be read as UTF-8 text, so SlideMage cannot check that the edit leaves the "
                      "slide's protected parts alone. Ask the user to look at the file.")
FILE_TOOLS = ("Edit", "Write", "MultiEdit")


def _read(path: Path) -> str | None:
    try:
        with open(path, encoding="utf-8", newline="") as f:
            return f.read().replace("\r\n", "\n")
    except (OSError, UnicodeDecodeError):
        return None


def _lf(value: object) -> str | None:
    return value.replace("\r\n", "\n") if isinstance(value, str) else None


def _replace(text: str, old: str, new: str, everywhere: bool) -> str | None:
    """`text` after Claude Code's Edit of old -> new; None when that edit would fail on its own."""
    count = text.count(old)
    if not old or count == 0 or (count > 1 and not everywhere):
        return None
    return text.replace(old, new) if everywhere else text.replace(old, new, 1)


def _result(tool: str, args: dict, before: str) -> str | None:
    """The file's text after the call, or None if it cannot be worked out."""
    if tool == "Write":
        return _lf(args.get("content"))
    edits = args.get("edits") if tool == "MultiEdit" else [args]
    text = before
    for edit in edits if isinstance(edits, list) else []:
        old, new = _lf(edit.get("old_string")), _lf(edit.get("new_string"))
        if old is None or new is None:
            return None
        text = _replace(text, old, new, bool(edit.get("replace_all")))
        if text is None:
            return None
    return text


def blocked_reason(ctx: ProjectContext, event: dict) -> str | None:
    """Why the hook call `event` (Claude Code's JSON) must be blocked, or None to let it go."""
    tool, args = event.get("tool_name"), event.get("tool_input")
    raw = args.get("file_path") if isinstance(args, dict) else None
    if tool not in FILE_TOOLS or not isinstance(raw, str):
        return None
    try:
        base = Path(event["cwd"]) if isinstance(event.get("cwd"), str) else ctx.root
        path = (Path(raw) if Path(raw).is_absolute() else base / raw).resolve()
    except (OSError, RuntimeError):
        return None
    outside = claude_scope.edit_problem(claude_scope.load(os.environ.get(claude_scope.FOCUS_ENV)), ctx.root, path)
    if outside:
        return outside
    kind = HookContext(ctx).slide_kind(path)
    if kind == "frozen":
        return FROZEN_MESSAGE.format(name=path.name)
    if kind != "current":
        return None
    before = _read(path)
    if before is None:
        # A slide that exists but cannot be read (not UTF-8, no permission): its protected parts cannot be
        # compared, so the call is refused rather than let through blind.
        return UNREADABLE_MESSAGE.format(name=path.name) if path.exists() else None
    after = _result(tool, args, before)
    return protected_problem(before, after) if after is not None else None


def record_write(ctx: ProjectContext, event: dict) -> None:
    """Pre captures text; successful Post records the slide and inserted calls, and sends a citation
    changed in the image descriptions store (media/alt-text.json) to review.

    Tool ids isolate simultaneous calls. The temporary pre snapshot is only
    needed to identify deck insertions and no-op writes; the review store itself is locked.
    """
    args = event.get("tool_input")
    raw = args.get("file_path") if isinstance(args, dict) else None
    if event.get("tool_name") not in FILE_TOOLS or not isinstance(raw, str):
        return
    base = Path(event.get("cwd") or ctx.root)
    path = (Path(raw) if Path(raw).is_absolute() else base / raw).resolve()
    if not path.is_relative_to(ctx.root.resolve()):
        return
    hook = HookContext(ctx)
    slide = hook.slide_kind(path) == "current"
    deck = hook.is_deck(path)
    store = hook.is_image_store(path)
    if not slide and not deck and not store:
        return
    identity = str(event.get("tool_use_id") or f"{event.get('session_id', '')}:{path}")
    if event.get("hook_event_name") == "PreToolUse":
        hook.write_snapshot(identity, {"new": not path.exists(), "before": _read(path)})
        return
    saved = hook.read_snapshot(identity)
    hook.delete_snapshot(identity)
    response = event.get("tool_response")
    if isinstance(response, dict) and (response.get("isError") or response.get("is_error")):
        return
    source = f"Claude Code terminal: {event['tool_name']}"
    if store:
        hook.flag_edited_sources(path, saved.get("before") or "")   # a changed citation is to review
    elif slide and ("before" not in saved or saved["before"] != _read(path)):
        hook.mark_review(path, "draft" if saved.get("new") else "edit", source, before=saved.get("before"))
    elif deck and path.is_file() and "before" in saved:
        hook.record_inserted_slides(path, saved["before"] or "", hook.read_text(path), source)


def main() -> int:
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
        if isinstance(event, dict) and event.get("hook_event_name") == "UserPromptSubmit":
            if timing.enabled():
                HookContext(project.from_environment()).timing_event("prompt")
            data = claude_scope.load(os.environ.get(claude_scope.FOCUS_ENV))
            if data:
                print(claude_scope.prompt_context(data))   # stdout becomes context for this prompt
            return 0
        ctx = project.from_environment()
        if isinstance(event, dict) and event.get("hook_event_name") == "PostToolUse":
            record_write(ctx, event)
            return 0
        reason = blocked_reason(ctx, event) if isinstance(event, dict) else None
        if not reason and isinstance(event, dict) and event.get("hook_event_name") == "PreToolUse":
            record_write(ctx, event)
    except Exception as exc:  # noqa: BLE001 -- not the hook's business to stop a call that is fine
        print(f"SlideMage hook: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if reason:
        print(reason, file=sys.stderr)
        return BLOCK
    return 0


if __name__ == "__main__":
    sys.exit(main())
