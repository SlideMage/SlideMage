# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Chat providers: the only code in SlideMage that makes AI HTTP requests
(2026-10-09, UI redesign step 2; before this ai_draft, alt_draft,
syntax_check and the Settings dialog each carried their own Ollama calls).

Ollama is stdlib (``http.client`` -- not ``urllib.request`` -- because a
running request must be abortable from another thread by closing its
socket, which urlopen() gives no handle for; see abort()). Claude goes
through the official ``anthropic`` SDK (imported on first use: it takes a
second to load), streaming even for a one-shot chat() so that abort() has a
connection to end. A provider is bound to one model; callers hold prompts
and result checks, never HTTP.

Failures of every kind (unreachable, HTTP error, bad key, rate limit,
timeout, abort) raise ProviderError with a message ready to show the user,
so callers handle a local and a cloud model identically.

Options that only one backend understands are accepted and ignored by the
other: ``think`` and ``num_ctx`` are Ollama's, while the Claude path sends
neither ``temperature`` (some current models reject it) nor any
prefill -- JSON mode there is an instruction in the system prompt, and
parse_json_object() copes with whatever fencing comes back.

The agent chat (agent.py) drives a provider through stream_turn(): one
streamed model turn over provider-neutral messages and tools
(agent_types.py).
"""
from __future__ import annotations

import http.client
import json
import re
import socket
import sys
import urllib.parse
from contextlib import contextmanager
from dataclasses import dataclass
from typing import ClassVar, Protocol


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


class _HttpProvider:
    """The abortable JSON-over-HTTP plumbing both providers share."""

    service: ClassVar[str]  # "Ollama" / "Anthropic", for messages

    def __init__(self) -> None:
        self._sock: socket.socket | None = None     # of the running request, for abort()
        self._cancelled = False

    @staticmethod
    def _connection(parts: urllib.parse.SplitResult, timeout: float) -> http.client.HTTPConnection:
        """A not yet connected connection to the URL `parts` (http or https)."""
        connection_class = (http.client.HTTPSConnection if parts.scheme == "https"
                            else http.client.HTTPConnection)
        return connection_class(parts.hostname or "localhost", parts.port, timeout=timeout)

    @contextmanager
    def _request(self, method: str, base_url: str, endpoint: str, *, headers: dict[str, str],
                 payload: dict | None, timeout: float):
        """The response of one request, to read inside the ``with`` (a stream line by line);
        transport failures, while sending or reading, become ProviderError. abort() closes the
        socket under a blocked read."""
        parts = urllib.parse.urlsplit(base_url)
        conn = self._connection(parts, timeout)
        connected = False
        try:
            if self._cancelled:
                raise Cancelled("Aborted.")
            conn.connect()
            connected = True
            self._sock = conn.sock      # published before anything is sent, so that abort() reaches an upload too;
            if self._cancelled:         # kept here: a response that ends with the connection takes it from conn
                raise Cancelled("Aborted.")
            body = None if payload is None else json.dumps(payload).encode("utf-8")
            conn.request(method, parts.path.rstrip("/") + endpoint, body=body, headers=headers)
            yield conn.getresponse()
        except (OSError, http.client.HTTPException) as exc:
            if self._cancelled:
                raise Cancelled("Aborted.") from exc
            if not connected and isinstance(exc, (ConnectionError, socket.gaierror)):
                raise ProviderError(f"{self.service} unreachable: {exc}") from exc
            if isinstance(exc, (ConnectionError, http.client.RemoteDisconnected)):
                raise ProviderError(f"{self.service} dropped the connection: {exc}") from exc
            raise ProviderError(f"{self.service} request failed: {exc}") from exc
        finally:
            self._sock = None
            conn.close()

    def _send(self, method: str, base_url: str, endpoint: str, *, headers: dict[str, str],
              payload: dict | None, timeout: float) -> tuple[int, bytes]:
        """(status, body) of one request."""
        with self._request(method, base_url, endpoint, headers=headers, payload=payload,
                           timeout=timeout) as response:
            return response.status, response.read()

    def _json(self, status: int, raw: bytes, describe_error) -> dict:
        if status != 200:
            raise ProviderError(describe_error(status, _error_detail(raw)))
        try:
            body = json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise ProviderError(f"{self.service} sent an unreadable response: {exc}") from exc
        return body if isinstance(body, dict) else {}

    def abort(self) -> None:
        self._cancelled = True
        _shutdown_socket(self._sock)


def _shutdown_socket(sock: socket.socket | None) -> None:
    """Wake a read blocked on `sock` in another thread."""
    if sock is None:
        return
    try:
        if sys.platform == "win32":
            # Measured 2026-09-26: on Windows neither socket.shutdown()
            # nor socket.close() wakes a recv() blocked in another
            # thread (the read just carries on until the server
            # answers); closing the handle itself with Winsock's
            # closesocket() does, at once. detach() first so Python's
            # own socket object no longer owns the handle and never
            # closes it a second time (by then possibly reused).
            import ctypes
            ctypes.windll.ws2_32.closesocket(ctypes.c_size_t(sock.detach()))
        else:
            sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


def _error_detail(raw: bytes) -> str:
    """The server's own error text from a non-200 body (Ollama sends
    {"error": "..."}, Anthropic {"error": {"message": "..."}})."""
    text = raw.decode("utf-8", errors="replace")
    try:
        error = json.loads(text).get("error")
    except (ValueError, AttributeError):
        return text[:200]
    if isinstance(error, dict):
        error = error.get("message")
    return str(error or text[:200])


def _image_media_type(data: bytes) -> str:
    for magic, media_type in ((b"\x89PNG", "image/png"), (b"\xff\xd8", "image/jpeg"),
                              (b"GIF8", "image/gif")):
        if data.startswith(magic):
            return media_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise ProviderError("Claude reads PNG, JPEG, GIF and WebP images only.")


def __getattr__(name: str):
    """OllamaProvider and InstalledModel moved to ai/ollama_route.py (this module keeps what every provider shares);
    the old import path still works so that tests and older plugins need no change."""
    if name in ("OllamaProvider", "InstalledModel"):
        from . import ollama_route
        return getattr(ollama_route, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
