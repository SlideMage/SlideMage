"""The PreToolUse hook that keeps the embedded Claude Code away from what SlideMage manages (UI redesign
step 10c). Claude Code runs this command before every Edit, Write or MultiEdit, with the call as JSON on
stdin; exit code 2 blocks the call and hands stderr to Claude as the reason, any other code lets it go.

    python -m slidemage.ai.claude_hook        (from a source checkout / installed package)
    SlideMage --claude-hook                   (the PyInstaller build; cli.main handles the flag)

The rules are the chat tools' (tools/edits.py): an edit that changes a slide's protected parts (header
comment, \\setSlideVersion, \\vbox to 0pt{...} blocks) is refused, and a frozen version (-vX-Y-Z.tex) is read-only.
Everything else, and anything this hook cannot work out, is allowed: it must never get in the way of a
call that is fine, and a crash is only a warning. It cannot see what a Bash command does to a file.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from ..deck_scan import PROJECT_ROOT
from .tools.edits import protected_problem, slide_kind

BLOCK = 2
FROZEN_MESSAGE = ("{name} is a frozen version of a slide: a historical record, read-only. "
                  "Edit the slide's -current.tex file instead.")
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


def blocked_reason(event: dict) -> str | None:
    """Why the hook call `event` (Claude Code's JSON) must be blocked, or None to let it go."""
    tool, args = event.get("tool_name"), event.get("tool_input")
    raw = args.get("file_path") if isinstance(args, dict) else None
    if tool not in FILE_TOOLS or not isinstance(raw, str):
        return None
    try:
        base = Path(event["cwd"]) if isinstance(event.get("cwd"), str) else PROJECT_ROOT
        path = (Path(raw) if Path(raw).is_absolute() else base / raw).resolve()
    except (OSError, RuntimeError):
        return None
    kind = slide_kind(path)
    if kind == "frozen":
        return FROZEN_MESSAGE.format(name=path.name)
    if kind != "current":
        return None
    before = _read(path)
    after = _result(tool, args, before) if before is not None else None
    return protected_problem(before, after) if after is not None else None


def main() -> int:
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
        reason = blocked_reason(event) if isinstance(event, dict) else None
    except Exception as exc:  # noqa: BLE001 -- not the hook's business to stop a call that is fine
        print(f"SlideMage hook: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if reason:
        print(reason, file=sys.stderr)
        return BLOCK
    return 0


if __name__ == "__main__":
    sys.exit(main())
