# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Claude over the Anthropic Messages API with the standard library only
(2026-10-27, plugins plan phase 4; before this the official ``anthropic``
SDK, which brought pydantic and httpx with it and took a second to import).

Like Ollama's, the connection is ``http.client`` (providers._HttpProvider),
so that abort() can end a running request from another thread by shutting
its socket. Every request streams (``stream: true``), chat() too: a long
answer then never sits behind one blocked read the user cannot interrupt.
The answer arrives as server-sent events; they are put together per content
block index into the plain JSON blocks of the Messages API, which is also
what AssistantMessage.raw holds, so the next turn replays them unchanged
(thinking blocks with their signatures included).

What the SDK did for us and is done here: two retries with a jittered
backoff on HTTP 408/409/429/5xx and on connection errors, or after the
server's ``retry-after`` -- only while no body has been read, so a text
already shown is never repeated; the waiting ends at once on abort().
Events and deltas of a type this file does not know are ignored: the API
adds some now and then, and an old SlideMage must keep working.

Whatever is sent here leaves the machine -- callers get the user's
per-project consent first (see ai_profile.cloud_seen).
"""
from __future__ import annotations

import base64
import http.client
import json
import random
import re
import threading
import urllib.parse
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from ..project import ProjectContext
from . import credentials
from .agent_types import AgentMessage, AssistantMessage, ToolCall, ToolResultsMessage, ToolSpec
from .providers import (
    DEFAULT_ANTHROPIC_MODEL,
    Cancelled,
    ChatReply,
    Message,
    ProviderError,
    _error_detail,
    _HttpProvider,
    _image_media_type,
)

API_VERSION = "2023-06-01"
_RETRY_STATUSES = frozenset({408, 409, 429}) | frozenset(range(500, 600))
_MAX_RETRY_AFTER = 60.0     # seconds; a server asking for more is not waited for

# Models whose API takes output_config.effort (older ones answer 400 to it).
_EFFORT_MODELS_RE = re.compile(r"^claude-(?:(?:sonnet|opus)-(?:5|4-[6-9])|fable-|mythos-|haiku-5)")
AGENT_EFFORT = "medium"     # Anthropic's start for agentic, multi-step tool use

# The `type` of an error event, as the HTTP status it stands for (same messages as the status).
_ERROR_STATUS = {"authentication_error": 401, "rate_limit_error": 429, "overloaded_error": 529}


def _status_error(status: int, detail: str) -> ProviderError:
    """The ProviderError (with a message for the user) an HTTP status stands for."""
    if status == 401:
        return ProviderError("Anthropic rejected the API key (HTTP 401). Check it in Settings.")
    if status == 429:
        return ProviderError(f"Anthropic rate limit reached (HTTP 429), try again shortly: {detail}")
    if status == 529:
        return ProviderError(f"Anthropic is overloaded (HTTP 529), try again shortly: {detail}")
    return ProviderError(f"Anthropic returned HTTP {status}: {detail}")


class _Assembly:
    """The message a stream of events adds up to: content blocks as wire dicts by index, stop
    reason and usage."""

    def __init__(self, on_text: Callable[[str], None] | None) -> None:
        self.on_text = on_text
        self.blocks: dict[int, dict] = {}
        self.json_pieces: dict[int, list[str]] = {}     # a tool_use block's input, as streamed
        self.stop_reason: str | None = None
        self.usage = {"input_tokens": 0, "output_tokens": 0,
                      "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        self.finished = False

    def feed(self, event: dict) -> None:
        kind = event.get("type")
        if kind == "message_start":
            self._add_usage((event.get("message") or {}).get("usage"))
        elif kind == "content_block_start":
            self._start(event.get("index"), event.get("content_block") or {})
        elif kind == "content_block_delta":
            self._delta(event.get("index"), event.get("delta") or {})
        elif kind == "content_block_stop":
            self._finish(event.get("index"))
        elif kind == "message_delta":
            self.stop_reason = (event.get("delta") or {}).get("stop_reason") or self.stop_reason
            self._add_usage(event.get("usage"))
        elif kind == "message_stop":
            self.finished = True
        elif kind == "error":
            error = event.get("error") or {}
            detail = str(error.get("message") or error)
            status = _ERROR_STATUS.get(error.get("type"))
            raise _status_error(status, detail) if status else ProviderError(f"Anthropic: {detail}")
        # ping and any event of a type not known here: nothing to do

    def _add_usage(self, usage: dict | None) -> None:
        for key in self.usage:
            if (usage or {}).get(key) is not None:      # message_delta repeats some, null for others
                self.usage[key] = usage[key]

    def _start(self, index, block: dict) -> None:
        kind = block.get("type")
        if kind == "text":
            wire = {"type": "text", "text": block.get("text") or ""}
        elif kind == "thinking":
            wire = {"type": "thinking", "thinking": block.get("thinking") or "",
                    "signature": block.get("signature") or ""}
        elif kind == "redacted_thinking":
            wire = {"type": "redacted_thinking", "data": block.get("data") or ""}
        elif kind == "tool_use":
            wire = {"type": "tool_use", "id": block.get("id") or "", "name": block.get("name") or "",
                    "input": block.get("input") if isinstance(block.get("input"), dict) else {}}
        else:
            wire = dict(block)      # a block type from the future: handed back as the API began it
        self.blocks[index] = wire
        self.json_pieces[index] = []

    def _delta(self, index, delta: dict) -> None:
        block = self.blocks.get(index)
        if block is None:
            return
        kind = delta.get("type")
        if kind == "text_delta" and block["type"] == "text":
            text = delta.get("text") or ""
            block["text"] += text
            if text and self.on_text is not None:
                self.on_text(text)
        elif kind == "input_json_delta" and "input" in block:
            self.json_pieces[index].append(delta.get("partial_json") or "")
        elif kind == "thinking_delta" and block["type"] == "thinking":
            block["thinking"] += delta.get("thinking") or ""
        elif kind == "signature_delta" and block["type"] == "thinking":
            block["signature"] = delta.get("signature") or ""

    def _finish(self, index) -> None:
        """The input of a tool call is complete: parse the pieces (an answer cut off at max_tokens
        may leave unparsable ones; that call then has no arguments)."""
        block, pieces = self.blocks.get(index), self.json_pieces.get(index)
        if block is None or not pieces:
            return
        try:
            parsed = json.loads("".join(pieces))
        except ValueError:
            parsed = {}
        block["input"] = parsed if isinstance(parsed, dict) else {}
        pieces.clear()

    @property
    def content(self) -> list[dict]:
        for index in self.blocks:
            self._finish(index)
        return [self.blocks[i] for i in sorted(self.blocks)]


class AnthropicProvider(_HttpProvider):
    """Claude through the Messages API, standard library only."""

    service = "Anthropic"
    is_local = False
    base_url = "https://api.anthropic.com"
    max_retries = 2     # as the SDK had it: for 408/409/429/5xx and dropped connections

    def __init__(self, model: str = DEFAULT_ANTHROPIC_MODEL, api_key: str = "") -> None:
        super().__init__()
        self.model = model or DEFAULT_ANTHROPIC_MODEL
        self._api_key = api_key
        self._wake = threading.Event()      # set by abort(): ends a backoff wait at once

    @classmethod
    def for_project(cls, ctx: ProjectContext, model: str = "") -> "AnthropicProvider":
        """With the key the environment, the keychain or the project's settings holds now."""
        stored = credentials.get_api_key(ctx)
        return cls(model or DEFAULT_ANTHROPIC_MODEL, stored.value if stored else "")

    @property
    def label(self) -> str:
        return f"{self.model} · cloud"

    def _key(self) -> str:
        if not self._api_key:
            raise ProviderError(
                "No Anthropic API key set. Add one in Settings, or set ANTHROPIC_API_KEY.")
        return self._api_key

    # -- the connection, with retries -----------------------------------------------------------

    def _wait(self, seconds: float) -> None:
        """Sleeps `seconds`, or less when abort() comes. (A method of its own so that tests need not wait.)"""
        self._wake.wait(seconds)

    def _backoff(self, attempt: int, retry_after: str | None) -> None:
        """Waits before retry number `attempt` + 1: as long as the server's ``retry-after`` (seconds)
        says, else 0.5 s, 1 s, 2 s ... up to 8 s, each shortened by up to a quarter at random."""
        try:
            delay = min(max(float(retry_after), 0.0), _MAX_RETRY_AFTER) if retry_after else None
        except ValueError:
            delay = None        # an HTTP date; the plain backoff will do
        if delay is None:
            delay = min(0.5 * 2 ** attempt, 8.0) * (1 - 0.25 * random.random())
        self._wait(delay)
        if self._cancelled:
            raise Cancelled("Aborted.")

    def _transport_error(self, exc: Exception) -> ProviderError:
        if isinstance(exc, TimeoutError):
            return ProviderError("Anthropic request timed out.")
        return ProviderError(f"Anthropic unreachable: {exc}")

    def _open(self, parts: urllib.parse.SplitResult, method: str, path: str, body: bytes | None,
              headers: dict[str, str], timeout: float):
        """(connection, response) of one attempt; the socket is published for abort() before anything
        is sent, so that it reaches an upload too."""
        conn = self._connection(parts, timeout)
        try:
            if self._cancelled:
                raise Cancelled("Aborted.")
            conn.connect()
            self._sock = conn.sock
            if self._cancelled:
                raise Cancelled("Aborted.")
            conn.request(method, path, body=body, headers=headers)
            return conn, conn.getresponse()
        except BaseException:
            self._sock = None
            conn.close()
            raise

    @contextmanager
    def _call(self, method: str, endpoint: str, payload: dict | None, timeout: float):
        """The 200 response of a request, to read inside the ``with``. A failed attempt that nothing
        was read from is retried (max_retries times); every other failure leaves as a ProviderError."""
        headers = {"x-api-key": self._key(), "anthropic-version": API_VERSION,
                   "content-type": "application/json"}
        parts = urllib.parse.urlsplit(self.base_url)
        path = parts.path.rstrip("/") + endpoint
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        for attempt in range(self.max_retries + 1):
            last = attempt == self.max_retries
            try:
                conn, response = self._open(parts, method, path, body, headers, timeout)
            except (OSError, http.client.HTTPException) as exc:
                if self._cancelled:
                    raise Cancelled("Aborted.") from exc
                if last:
                    raise self._transport_error(exc) from exc
                self._backoff(attempt, None)
                continue
            if response.status in _RETRY_STATUSES and not last:
                self._close(conn)
                self._backoff(attempt, response.getheader("retry-after"))
                continue
            break
        try:
            if response.status != 200:
                raise _status_error(response.status, _error_detail(response.read()))
            yield response
        except (OSError, http.client.HTTPException) as exc:
            if self._cancelled:
                raise Cancelled("Aborted.") from exc
            raise self._transport_error(exc) from exc
        finally:
            self._close(conn)

    def _close(self, conn: http.client.HTTPConnection) -> None:
        self._sock = None
        conn.close()

    def abort(self) -> None:
        """Ends a running chat() / stream_turn() from another thread (it raises Cancelled), whether it
        is connecting, waiting to retry, or blocked in a read."""
        super().abort()
        self._wake.set()

    # -- streaming --------------------------------------------------------------------------------

    def _events(self, response) -> Iterator[dict]:
        """The data of each server-sent event as a dict (its `type` filled from the ``event:`` line
        when the data lacks it)."""
        name, data = "", []

        def decode() -> dict:
            try:
                event = json.loads("\n".join(data))
            except ValueError as exc:
                raise ProviderError(f"Anthropic sent an unreadable response: {exc}") from exc
            if not isinstance(event, dict):
                return {}
            event.setdefault("type", name)
            return event

        for raw in response:
            if self._cancelled:
                raise Cancelled("Aborted.")
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if not line:
                if data:
                    yield decode()
                name, data = "", []
            elif not line.startswith(":"):      # a line starting with a colon is a comment
                field, _, value = line.partition(":")
                value = value.removeprefix(" ")
                if field == "event":
                    name = value
                elif field == "data":
                    data.append(value)
        if data:
            yield decode()

    def _stream_message(self, request: dict, timeout: float,
                        on_text: Callable[[str], None] | None) -> _Assembly:
        request = {**request, "stream": True}
        message = _Assembly(on_text)
        with self._call("POST", "/v1/messages", request, timeout) as response:
            for event in self._events(response):
                message.feed(event)
                if message.finished:
                    break
        if self._cancelled:
            raise Cancelled("Aborted.")
        if not message.finished:
            raise ProviderError("Anthropic ended the answer early.")
        return message

    # -- the ChatProvider interface ------------------------------------------------------------------

    def chat(
        self, messages: list[Message], *, system: str = "",
        images: list[bytes] | None = None, schema: dict | None = None,
        temperature: float = 0.2, max_tokens: int = 2048, timeout: float = 300.0,
        think: bool = False, num_ctx: int | None = None,
    ) -> ChatReply:
        turns: list[dict] = [dict(m) for m in messages]
        if images:
            last = turns[-1]
            blocks: list[dict] = [_image_block(data) for data in images]
            turns[-1] = {"role": last["role"],
                         "content": blocks + [{"type": "text", "text": last["content"]}]}
        if schema:
            system = (system + "\n\n" if system else "") + (
                "Answer with a single JSON object and nothing else -- no prose, no "
                "code fences. It must conform to this JSON schema:\n" + json.dumps(schema))
        request: dict = {"model": self.model, "max_tokens": max_tokens, "messages": turns}
        if system:
            request["system"] = system
        message = self._stream_message(request, timeout, None)
        return ChatReply(text=_message_text(message.content), truncated=message.stop_reason == "max_tokens")

    def stream_turn(
        self, system: str, messages: list[AgentMessage], tools: list[ToolSpec],
        on_text: Callable[[str], None], *, max_tokens: int = 16000, timeout: float = 300.0,
    ) -> AssistantMessage:
        """One model turn of the agent loop: `on_text` gets the answer as it streams; the result
        carries the tool calls. The system prompt, tools and history are cached as a prefix (the
        top-level cache_control follows the end of the history), so a loop of tool calls pays for
        its context once."""
        request: dict = {"model": self.model, "max_tokens": max_tokens,
                         "messages": _wire_messages(messages), "cache_control": {"type": "ephemeral"}}
        if system:
            request["system"] = system
        if tools:
            request["tools"] = [{"name": t.name, "description": t.description, "input_schema": t.schema}
                                for t in tools]
        if _EFFORT_MODELS_RE.match(self.model):
            request["output_config"] = {"effort": AGENT_EFFORT}
        message = self._stream_message(request, timeout, on_text)
        content, usage = message.content, message.usage
        calls = [ToolCall(b["id"], b["name"], b["input"]) for b in content if b["type"] == "tool_use"]
        return AssistantMessage(
            text=_message_text(content), tool_calls=calls,
            stop=message.stop_reason if message.stop_reason in ("tool_use", "max_tokens", "refusal")
            else "end_turn",
            raw=content,
            usage={"input": usage["input_tokens"], "output": usage["output_tokens"],
                   "cache_read": usage["cache_read_input_tokens"],
                   "cache_write": usage["cache_creation_input_tokens"]})

    def list_models(self) -> list[str]:
        """Every model id the account can use, newest first as the API lists them; [] on any failure."""
        ids: list[str] = []
        after = ""
        try:
            while True:
                endpoint = "/v1/models?limit=1000" + (f"&after_id={urllib.parse.quote(after)}" if after else "")
                with self._call("GET", endpoint, None, 10) as response:
                    try:
                        page = json.loads(response.read().decode("utf-8"))
                    except ValueError as exc:
                        raise ProviderError(f"Anthropic sent an unreadable response: {exc}") from exc
                page = page if isinstance(page, dict) else {}
                ids += [m["id"] for m in page.get("data") or () if isinstance(m, dict) and "id" in m]
                last = page.get("last_id") or ""
                if not page.get("has_more") or not last or last == after:
                    return ids
                after = last
        except ProviderError:
            return []


def _message_text(content: list[dict]) -> str:
    return "".join(block["text"] for block in content if block["type"] == "text")


def _image_block(data: bytes) -> dict:
    return {"type": "image", "source": {
        "type": "base64", "media_type": _image_media_type(data),
        "data": base64.b64encode(data).decode("ascii")}}


def _wire_messages(messages: list[AgentMessage]) -> list[dict]:
    """The agent's neutral history as Messages API turns."""
    wire: list[dict] = []
    for message in messages:
        if isinstance(message, AssistantMessage):
            content = message.raw if message.raw is not None else (
                ([{"type": "text", "text": message.text}] if message.text else [])
                + [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.input}
                   for c in message.tool_calls])
            wire.append({"role": "assistant", "content": content})
        elif isinstance(message, ToolResultsMessage):
            wire.append({"role": "user", "content": [_tool_result_block(r) for r in message.results]})
        else:
            wire.append({"role": "user", "content": message.text})
    return wire


def _tool_result_block(result) -> dict:
    block: dict = {"type": "tool_result", "tool_use_id": result.call_id}
    block["content"] = ([{"type": "text", "text": result.text}] + [_image_block(i) for i in result.images]
                        if result.images else result.text)
    if result.is_error:
        block["is_error"] = True
    return block
