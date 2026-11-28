# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Chat provider types shared by core and the AI plugins: the ChatProvider protocol, ChatReply, the
errors (ProviderError, RouteUnavailable, Cancelled) and parse_json_object().

The HTTP transports live in the plugins (Ollama, Claude); core makes no AI HTTP requests itself. A
provider is bound to one model; callers hold prompts and result checks, never HTTP.

Failures of every kind (unreachable, HTTP error, bad key, rate limit, timeout, abort) raise
ProviderError with a message ready to show the user, so callers handle a local and a cloud model
identically.

Options that only one backend understands (``think`` and ``num_ctx`` are Ollama's) are accepted and
ignored by the other; parse_json_object() copes with whatever fencing a model puts around JSON.

The agent chat (agent.py) drives a provider through stream_turn(): one streamed model turn over
provider-neutral messages and tools (agent_types.py).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol


Message = dict[str, str]

AGENT_NUM_CTX = 16384       # Ollama's own default window (as low as 4096) would cut the agent's context

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5-5"
# Shown when no API key is set yet, or the live /v1/models call failed.
ANTHROPIC_FALLBACK_MODELS = (
    "claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-4-5-20251001")


class ProviderError(Exception):
    """A request failed; str(exc) is the message to show the user."""


class RouteUnavailable(ProviderError):
    """A route cannot run this request; str(exc) says what is missing there. Raised by ai/resolver.py and by the
    routes' backends; nothing falls back to another route or model when it is."""


class Cancelled(ProviderError):
    """abort() ended the request -- the user asked for it, not a failure."""


@dataclass
class ChatReply:
    text: str
    thinking: str = ""      # Ollama thinking models only
    truncated: bool = False  # stopped at max_tokens rather than finishing


class ChatProvider(Protocol):
    model: str
    is_local: bool

    @property
    def label(self) -> str:
        """``qwen3`` / ``claude-sonnet-5-5 · cloud`` -- what to show the
        user as the answering model."""

    def chat(
        self, messages: list[Message], *, system: str = "",
        images: list[bytes] | None = None, schema: dict | None = None,
        temperature: float = 0.2, max_tokens: int = 2048, timeout: float = 300.0,
        think: bool = False, num_ctx: int | None = None,
    ) -> ChatReply:
        """One non-streaming turn. `images` attach to the last message;
        `schema` (a JSON schema) asks for a JSON object back."""

    def list_models(self) -> list[str]:
        """Model ids to offer, best first; [] (never an error) when the
        service cannot be reached."""

    def abort(self) -> None:
        """Ends a running chat() from another thread (it raises Cancelled).
        One-shot: make a new provider for the next abortable operation."""


def parse_json_object(text: str) -> dict | None:
    """The JSON object in a model reply, or None. Tolerates a wrapping
    <think> block, a markdown code fence, or prose around the object
    (it takes the outermost brace-delimited span) -- models do this even
    when told not to and, on Ollama, constrained by `format`."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            parsed = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None
