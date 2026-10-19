# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Plain-text helpers of the chat's cards: the rows of a diff and the one-line summary of a tool call.
No Qt, so they are tested without a window."""
from __future__ import annotations

import difflib

from ....ai.agent_types import ToolCall

DIFF_CONTEXT = 2           # unchanged lines shown around a change
SUMMARY_CHARS = 60
_SUMMARY_KEYS = ("path", "slide", "pattern", "query", "slug", "topic", "deck", "kind")


def diff_rows(before: str, after: str, context: int = DIFF_CONTEXT) -> list[tuple[str, str]]:
    """The change from `before` to `after` as (kind, line) rows: "del", "add", "ctx" (unchanged, near a
    change) and "gap" (line "": more unchanged text is left out). Tabs are shown as two spaces."""
    old, new = before.splitlines(), after.splitlines()
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=len(old) + len(new) > 5000)
    groups = list(matcher.get_grouped_opcodes(context))
    rows: list[tuple[str, str]] = []
    for index, group in enumerate(groups):
        if index or group[0][1] > 0:
            rows.append(("gap", ""))
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                rows += [("ctx", line) for line in old[i1:i2]]
            else:
                rows += [("del", line) for line in old[i1:i2]] + [("add", line) for line in new[j1:j2]]
    if groups and groups[-1][-1][2] < len(old):
        rows.append(("gap", ""))
    return [(kind, line.replace("\t", "  ")) for kind, line in rows]


def clip(text: str, limit: int = SUMMARY_CHARS) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def summarize_call(call: ToolCall) -> str:
    """What a tool call is about, in a few words: its path, query, slide ... or its first arguments."""
    for key in _SUMMARY_KEYS:
        value = call.input.get(key)
        if isinstance(value, str) and value:
            return clip(value)
    return clip(", ".join(f"{name}={value}" for name, value in call.input.items()))
