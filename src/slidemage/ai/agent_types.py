# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The provider-neutral vocabulary of the agent chat (2026-10-10, UI redesign
step 10a): what the model may call, what it said and called, what came back,
and the events the loop reports to the chat UI.

The agent loop (agent.py) and the providers that run a model turn
(anthropic_provider.AnthropicProvider and providers.OllamaProvider) both speak only the message
types, so a provider never sees the loop and the loop never sees a vendor's
wire format. No Qt, no HTTP in here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    schema: dict       # JSON schema of the arguments (an "object")


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class ToolResult:
    call_id: str
    text: str
    is_error: bool = False
    images: list[bytes] = field(default_factory=list)   # PNG/JPEG bytes the model should look at


@dataclass
class UserMessage:
    text: str           # what the model is sent
    shown: str = ""     # what the user typed, if `text` carries more (the context block): what the chat shows


@dataclass
class AssistantMessage:
    """One finished model turn. `stop` is "end_turn", "tool_use", "max_tokens" or "refusal".
    `raw` is whatever the provider needs to replay this turn faithfully (Claude: the content
    blocks, thinking included); it is opaque to everyone else and never persisted."""
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop: str = "end_turn"
    raw: Any = None
    usage: dict[str, int] = field(default_factory=dict)   # input/output/cache_read/cache_write tokens


@dataclass
class ToolResultsMessage:
    results: list[ToolResult]


AgentMessage = UserMessage | AssistantMessage | ToolResultsMessage


# -- what the loop reports (agent.Agent(on_event=...)) ---------------------------------------------
# Delivered on the agent's worker thread, in order; the UI hops to its own thread.

@dataclass(frozen=True)
class TextDelta:
    text: str                     # the next piece of the model's answer


@dataclass(frozen=True)
class ToolStarted:
    call: ToolCall


@dataclass(frozen=True)
class ToolFinished:
    call: ToolCall
    result: ToolResult


@dataclass(frozen=True)
class EditProposed:
    """An edit waits for the user's Apply / Reject (mode "ask"; in mode "auto" it is only announced
    just before EditApplied). `before`/`after` are the whole file text (a new file has before "")."""
    call_id: str
    path: Path
    before: str
    after: str
    note: str = ""                # what else happens with it ("and adds it to the deck ...")


@dataclass(frozen=True)
class EditApplied:
    call_id: str
    path: Path
    before: str
    after: str
    via_buffer: bool              # went into the open editor buffer (undo there), not onto disk
    undoable: bool = True         # tools.undo_edit(...) can put `before` back
    note: str = ""


@dataclass(frozen=True)
class EditRejected:
    """The proposed edit was not made: the user refused it, or it could not be applied after all."""
    call_id: str
    path: Path


@dataclass(frozen=True)
class Done:
    """The last event of a run. `reason`: "end_turn" (the model finished), "stopped" (the user
    pressed Stop), "max_turns" (the guard ended it) or "error" (`message` says what happened)."""
    reason: str
    message: str = ""
    turns: int = 0
    usage: dict[str, int] = field(default_factory=dict)   # summed over the run's model turns


AgentEvent = TextDelta | ToolStarted | ToolFinished | EditProposed | EditApplied | EditRejected | Done

EDIT_ASK = "ask"          # every edit waits for the user (default)
EDIT_AUTO = "auto"        # edits are applied at once
