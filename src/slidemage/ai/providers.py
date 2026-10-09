"""Chat providers: the only code in SlideMage that makes AI HTTP requests
(2026-10-09, UI redesign step 2; before this ai_draft, alt_draft,
syntax_check and the Settings dialog each carried their own Ollama calls).

Everything is stdlib (``http.client`` -- not ``urllib.request`` -- because a
running request must be abortable from another thread by closing its
socket, which urlopen() gives no handle for; see abort()). A provider is
bound to one model; callers hold prompts and result checks, never HTTP.

Failures of every kind (unreachable, HTTP error, bad key, rate limit,
timeout, abort) raise ProviderError with a message ready to show the user,
so callers handle a local and a cloud model identically.

Options that only one backend understands are accepted and ignored by the
other: ``think`` and ``num_ctx`` are Ollama's, while the Claude path sends
neither ``temperature`` (some current models reject it) nor any
prefill -- JSON mode there is an instruction in the system prompt, and
parse_json_object() copes with whatever fencing comes back.
"""
from __future__ import annotations

import base64
import http.client
import json
import re
import socket
import sys
import urllib.parse
from dataclasses import dataclass
from typing import ClassVar, Protocol

from .. import app_settings
from . import credentials

Message = dict[str, str]

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5-5"
# Shown when no API key is set yet, or the live /v1/models call failed.
ANTHROPIC_FALLBACK_MODELS = (
    "claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-4-5-20251001")
ANTHROPIC_VERSION = "2023-06-01"


class ProviderError(Exception):
    """A request failed; str(exc) is the message to show the user."""


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
        self._conn: http.client.HTTPConnection | None = None
        self._cancelled = False

    def _send(self, method: str, base_url: str, endpoint: str, *, headers: dict[str, str],
              payload: dict | None, timeout: float) -> tuple[int, bytes]:
        """(status, body) of one request; transport failures become
        ProviderError. abort() closes the socket under a blocked read."""
        parts = urllib.parse.urlsplit(base_url)
        connection_class = (http.client.HTTPSConnection if parts.scheme == "https"
                            else http.client.HTTPConnection)
        conn = connection_class(parts.hostname or "localhost", parts.port, timeout=timeout)
        self._conn = conn
        try:
            if self._cancelled:
                raise Cancelled("Aborted.")
            body = None if payload is None else json.dumps(payload).encode("utf-8")
            conn.request(method, parts.path.rstrip("/") + endpoint, body=body, headers=headers)
            response = conn.getresponse()
            return response.status, response.read()
        except (OSError, http.client.HTTPException) as exc:
            if self._cancelled:
                raise Cancelled("Aborted.") from exc
            if isinstance(exc, (ConnectionError, socket.gaierror)):
                raise ProviderError(f"{self.service} unreachable: {exc}") from exc
            raise ProviderError(f"{self.service} request failed: {exc}") from exc
        finally:
            self._conn = None
            conn.close()

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
        conn = self._conn
        sock = conn.sock if conn is not None else None
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


@dataclass
class InstalledModel:
    name: str
    size_bytes: int
    modified_at: str
    capabilities: tuple[str, ...] = ()


class OllamaProvider(_HttpProvider):
    """Local Ollama. No API key, no per-image cost, nothing leaves the machine."""

    service = "Ollama"
    is_local = True

    def __init__(self, model: str = "", host: str | None = None) -> None:
        super().__init__()
        self.model = model
        # Resolved now rather than at import: a host saved later in Settings
        # must apply without a restart.
        self.host = host or app_settings.get_ollama_host()

    @property
    def label(self) -> str:
        return self.model

    def chat(
        self, messages: list[Message], *, system: str = "",
        images: list[bytes] | None = None, schema: dict | None = None,
        temperature: float = 0.2, max_tokens: int = 2048, timeout: float = 300.0,
        think: bool = False, num_ctx: int | None = None,
    ) -> ChatReply:
        turns: list[dict] = ([{"role": "system", "content": system}] if system else [])
        turns += [dict(m) for m in messages]
        if images:
            turns[-1]["images"] = [base64.b64encode(i).decode("ascii") for i in images]
        options: dict = {"temperature": temperature, "num_predict": max_tokens}
        if num_ctx:
            options["num_ctx"] = num_ctx
        payload: dict = {"model": self.model, "stream": False, "options": options,
                         "messages": turns}
        if schema:
            payload["format"] = schema
        # `think` is sent ONLY when enabled -- never as an explicit false.
        # On qwen3-vl:32b, `format` + `think: false` makes the model put its
        # JSON answer in the response's `thinking` field and return an empty
        # `content`, so every image fails with "non-JSON output: ''". Omitting
        # the key entirely produces correct, well-formed output. (It does not
        # even suppress thinking on that model -- `think: false` still
        # returned 1000 characters of it, literal <think> tag included; it
        # only breaks the channel separation.) Measured 2026-08-14 across the
        # whole five-slide bake-off, where it failed all six images on the one
        # model this was meant to run.
        if think:
            payload["think"] = True
        status, raw = self._send(
            "POST", self.host, "/api/chat", headers={"Content-Type": "application/json"},
            payload=payload, timeout=timeout)
        body = self._json(
            status, raw, lambda s, detail: f"Ollama returned HTTP {s}: {detail}")
        message = body.get("message") or {}
        return ChatReply(
            text=message.get("content") or "",
            thinking=message.get("thinking") or "",
            truncated=body.get("done_reason") == "length",
        )

    def installed(self) -> list[InstalledModel]:
        """Every installed model, newest first; [] when unreachable."""
        try:
            status, raw = self._send("GET", self.host, "/api/tags", headers={},
                                     payload=None, timeout=10)
            body = self._json(status, raw, lambda s, detail: detail)
        except ProviderError:
            return []
        entries = sorted(body.get("models", []), key=lambda e: e.get("modified_at", ""),
                         reverse=True)
        return [
            InstalledModel(
                name=entry["name"], size_bytes=entry.get("size", 0),
                modified_at=entry.get("modified_at", ""),
                capabilities=tuple(entry.get("capabilities") or ()),
            )
            for entry in entries
        ]

    def list_models(self, *, vision_only: bool = False) -> list[str]:
        """Every model Ollama has, or (translation is text-only and takes
        any model; image description needs one) only vision-capable ones."""
        return [m.name for m in self.installed()
                if not vision_only or "vision" in m.capabilities]


def _image_media_type(data: bytes) -> str:
    for magic, media_type in ((b"\x89PNG", "image/png"), (b"\xff\xd8", "image/jpeg"),
                              (b"GIF8", "image/gif")):
        if data.startswith(magic):
            return media_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise ProviderError("Claude reads PNG, JPEG, GIF and WebP images only.")


class AnthropicProvider(_HttpProvider):
    """Claude through the Messages API. Whatever is sent here leaves the
    machine -- callers get the user's per-project consent first (see
    resolver.py)."""

    service = "Anthropic"
    is_local = False
    base_url = "https://api.anthropic.com"

    def __init__(self, model: str = DEFAULT_ANTHROPIC_MODEL, api_key: str | None = None) -> None:
        super().__init__()
        self.model = model or DEFAULT_ANTHROPIC_MODEL
        self._api_key = api_key

    @property
    def label(self) -> str:
        return f"{self.model} · cloud"

    def _headers(self) -> dict[str, str]:
        key = self._api_key
        if key is None:
            stored = credentials.get_api_key()
            key = stored.value if stored else ""
        if not key:
            raise ProviderError(
                "No Anthropic API key set. Add one in Settings, or set ANTHROPIC_API_KEY.")
        return {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json"}

    @staticmethod
    def _describe_error(status: int, detail: str) -> str:
        if status == 401:
            return "Anthropic rejected the API key (HTTP 401). Check it in Settings."
        if status == 429:
            return f"Anthropic rate limit reached (HTTP 429), try again shortly: {detail}"
        if status == 529:
            return f"Anthropic is overloaded (HTTP 529), try again shortly: {detail}"
        return f"Anthropic returned HTTP {status}: {detail}"

    def chat(
        self, messages: list[Message], *, system: str = "",
        images: list[bytes] | None = None, schema: dict | None = None,
        temperature: float = 0.2, max_tokens: int = 2048, timeout: float = 300.0,
        think: bool = False, num_ctx: int | None = None,
    ) -> ChatReply:
        turns: list[dict] = [dict(m) for m in messages]
        if images:
            last = turns[-1]
            blocks: list[dict] = [
                {"type": "image", "source": {
                    "type": "base64", "media_type": _image_media_type(data),
                    "data": base64.b64encode(data).decode("ascii")}}
                for data in images
            ]
            turns[-1] = {"role": last["role"],
                         "content": blocks + [{"type": "text", "text": last["content"]}]}
        if schema:
            system = (system + "\n\n" if system else "") + (
                "Answer with a single JSON object and nothing else -- no prose, no "
                "code fences. It must conform to this JSON schema:\n" + json.dumps(schema))
        payload: dict = {"model": self.model, "max_tokens": max_tokens, "messages": turns}
        if system:
            payload["system"] = system
        status, raw = self._send(
            "POST", self.base_url, "/v1/messages", headers=self._headers(),
            payload=payload, timeout=timeout)
        body = self._json(status, raw, self._describe_error)
        text = "".join(block.get("text", "") for block in body.get("content") or []
                       if block.get("type") == "text")
        return ChatReply(text=text, truncated=body.get("stop_reason") == "max_tokens")

    def list_models(self) -> list[str]:
        try:
            status, raw = self._send("GET", self.base_url, "/v1/models?limit=1000",
                                     headers=self._headers(), payload=None, timeout=10)
            body = self._json(status, raw, self._describe_error)
        except ProviderError:
            return []
        return [entry["id"] for entry in body.get("data") or [] if "id" in entry]
