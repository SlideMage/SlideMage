# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The prompt the user typed into Claude Code and has not sent, read off the terminal's screen (2026-10-26, direct
request: Switch now lost it). Esc Esc puts it into Claude Code's input history, but only some versions do that,
and Up is not where anyone looks; ClaudeCodeView.switch_session reads it here before the restart and pastes it into
the new session's input box.

The screen comes from terminal.js's screenLines(): each line twice, as shown and with its dim cells as spaces --
Claude Code's grey placeholder ("Try ...") is dim, typed text is not. The input box is the last line that starts
with the prompt (> or ❯, inside an optional │ border) right under a rule line (─), down to the next rule or
border; transcript lines that show past prompts have no rule above them.
"""
from __future__ import annotations

import re

_PROMPT_RE = re.compile(r"^\s*│?\s*[>❯] ?")
_RULE_RE = re.compile(r"[─━]{3,}")


def _is_rule(line: str) -> bool:
    return bool(_RULE_RE.search(line))


def _box_start(shown: list[str]) -> int | None:
    """The index of the input box's first line, None while there is none on the screen."""
    for index in range(len(shown) - 1, 0, -1):
        if _PROMPT_RE.match(shown[index]) and _is_rule(shown[index - 1]):
            return index
    return None


def input_box_shown(lines: list[list[str]]) -> bool:
    """Whether Claude Code's input box is on the screen, empty (the restarted session is ready for the draft)."""
    start = _box_start([line[0] for line in lines])
    return start is not None and prompt_draft(lines) == ""


def prompt_draft(lines: list[list[str]]) -> str:
    """The unsent text in the input box of `lines` ([shown, without dim cells] per line); "" for none."""
    shown = [line[0] for line in lines]
    solid = [line[1] if len(line) > 1 else line[0] for line in lines]
    start = _box_start(shown)
    if start is None:
        return ""
    marker = _PROMPT_RE.match(shown[start]).end()      # where the text starts: continuation lines are indented to it
    parts = []
    for index in range(start, len(shown)):
        if index > start and (_is_rule(shown[index]) or shown[index].lstrip().startswith("╰")):
            break
        raw = solid[index]
        if index == start or raw[:marker].strip(" │") == "":
            text = raw[marker:]                  # the text column, past the prompt or its indentation
        else:
            text = raw.lstrip(" │")
        parts.append(text.rstrip().removesuffix("│").rstrip())
    while parts and not parts[-1]:
        parts.pop()
    return "\n".join(parts).strip("\n")


def paste_bytes(draft: str) -> bytes:
    """What types `draft` into the input box without sending it: as a bracketed paste when it has line ends (a
    line end typed would send it), as plain keystrokes otherwise."""
    text = draft.replace("\r\n", "\n")
    if "\n" in text:
        return b"\x1b[200~" + text.replace("\n", "\r").encode("utf-8") + b"\x1b[201~"
    return text.encode("utf-8")
