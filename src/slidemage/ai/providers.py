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

import base64
import http.client
import json
import re
import socket
import sys
import urllib.parse
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from typing import ClassVar, Protocol

from .. import app_settings, project
from . import credentials
from .agent_types import AgentMessage, AssistantMessage, ToolCall, ToolResultsMessage, ToolSpec

Message = dict[str, str]

AGENT_NUM_CTX = 16384       # Ollama's own default window (as low as 4096) would cut the agent's context

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5-5"
# Shown when no API key is set yet, or the live /v1/models call failed.
ANTHROPIC_FALLBACK_MODELS = (
    "claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-4-5-20251001")


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
        self._sock: socket.socket | None = None     # of the running request, for abort()
        self._cancelled = False

    @contextmanager
    def _request(self, method: str, base_url: str, endpoint: str, *, headers: dict[str, str],
                 payload: dict | None, timeout: float):
        """The response of one request, to read inside the ``with`` (a stream line by line);
        transport failures, while sending or reading, become ProviderError. abort() closes the
        socket under a blocked read."""
        parts = urllib.parse.urlsplit(base_url)
        connection_class = (http.client.HTTPSConnection if parts.scheme == "https"
                            else http.client.HTTPConnection)
        conn = connection_class(parts.hostname or "localhost", parts.port, timeout=timeout)
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


# Ollama older than 0.6.4 reports no capabilities; these model families call tools (checked by name).
_TOOL_FAMILIES_RE = re.compile(
    r"^(?:qwen2\.5|qwen3|qwq|llama3\.[123]|llama4|mistral|mixtral|command-r|firefunction|hermes3|granite3|"
    r"gpt-oss|devstral|magistral|smollm2|nemotron|functiongemma)", re.IGNORECASE)


@dataclass
class InstalledModel:
    name: str
    size_bytes: int
    modified_at: str
    capabilities: tuple[str, ...] = ()

    @property
    def supports_tools(self) -> bool:
        """Whether the model can call tools (the agent chat needs that): Ollama's own word for it,
        else -- an Ollama too old to give capabilities -- the model's family name."""
        if self.capabilities:
            return "tools" in self.capabilities
        return bool(_TOOL_FAMILIES_RE.match(self.name.rsplit("/", 1)[-1]))


class OllamaProvider(_HttpProvider):
    """Local Ollama. No API key, no per-image cost, nothing leaves the machine."""

    service = "Ollama"
    is_local = True

    def __init__(self, model: str = "", host: str | None = None) -> None:
        super().__init__()
        self.model = model
        # Resolved now rather than at import: a host saved later in Settings
        # must apply without a restart.
        self.host = host or app_settings.get_ollama_host(project.transitional_context())
        self._capabilities: dict[str, tuple[str, ...]] = {}     # what /api/show said, by model

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

    def stream_turn(
        self, system: str, messages: list[AgentMessage], tools: list[ToolSpec],
        on_text: Callable[[str], None], *, max_tokens: int = 16000, timeout: float = 300.0,
    ) -> AssistantMessage:
        """One model turn of the agent loop (see AnthropicProvider.stream_turn): /api/chat streams
        one JSON object per line, text in pieces, each tool call whole."""
        sees_images = any(isinstance(m, ToolResultsMessage) and any(r.images for r in m.results)
                          for m in messages) and "vision" in self.capabilities()
        payload: dict = {"model": self.model, "stream": True,
                         "messages": _ollama_messages(system, messages, sees_images),
                         "options": {"num_predict": max_tokens, "num_ctx": AGENT_NUM_CTX}}
        if tools:
            payload["tools"] = [{"type": "function", "function": {
                "name": t.name, "description": t.description, "parameters": t.schema}} for t in tools]
        text: list[str] = []
        calls: list[ToolCall] = []
        last: dict = {}
        with self._request("POST", self.host, "/api/chat", headers={"Content-Type": "application/json"},
                           payload=payload, timeout=timeout) as response:
            if response.status != 200:
                raise ProviderError(self._chat_error(_error_detail(response.read()), response.status))
            for line in response:
                if self._cancelled:
                    raise Cancelled("Aborted.")
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                except ValueError as exc:
                    raise ProviderError(f"Ollama sent an unreadable response: {exc}") from exc
                if chunk.get("error"):
                    raise ProviderError(self._chat_error(str(chunk["error"])))
                message = chunk.get("message") or {}
                if message.get("content"):
                    text.append(message["content"])
                    on_text(message["content"])
                for entry in message.get("tool_calls") or ():
                    function = entry.get("function") or {}
                    calls.append(ToolCall(entry.get("id") or f"call_{uuid.uuid4().hex[:12]}",
                                          function.get("name", ""), _arguments(function.get("arguments"))))
                if chunk.get("done"):
                    last = chunk
                    break
        if self._cancelled:
            raise Cancelled("Aborted.")
        if not last:
            raise ProviderError("Ollama ended the answer early (the model may have crashed or run out of memory).")
        return AssistantMessage(
            text="".join(text), tool_calls=calls,
            stop="tool_use" if calls else "max_tokens" if last.get("done_reason") == "length" else "end_turn",
            usage={"input": last.get("prompt_eval_count", 0), "output": last.get("eval_count", 0)})

    def _chat_error(self, detail: str, status: int = 0) -> str:
        """The message for an /api/chat failure `detail` (Ollama's own error text)."""
        if "does not support tools" in detail:
            return f"{self.model} cannot call tools, so it cannot be used for the chat. Choose another model."
        if "not found" in detail:
            return f"Ollama has no model '{self.model}'. Install it (ollama pull {self.model}) or choose another."
        return f"Ollama returned HTTP {status}: {detail}" if status else f"Ollama: {detail}"

    def installed(self, *, detailed: bool = False) -> list[InstalledModel]:
        """Every installed model, newest first; [] when unreachable. /api/tags does not say what a
        model can do: `detailed` asks /api/show for each one (a request per model; for a worker
        thread) so that `capabilities` is filled, for an Ollama whose /api/tags does not say."""
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
                capabilities=tuple(entry.get("capabilities") or (
                    self.capabilities(entry["name"]) if detailed else ())),
            )
            for entry in entries
        ]

    def capabilities(self, model: str | None = None) -> tuple[str, ...]:
        """What `model` (default: this provider's) can do -- "completion", "tools", "vision", ... --
        according to /api/show; () when unknown (unreachable, or an Ollama too old to say). An answer is kept
        for the life of this provider (the agent asks again on every turn)."""
        model = model or self.model
        if model in self._capabilities:
            return self._capabilities[model]
        try:
            status, raw = self._send("POST", self.host, "/api/show", headers={"Content-Type": "application/json"},
                                     payload={"model": model}, timeout=10)
            body = self._json(status, raw, lambda s, detail: detail)
        except ProviderError:
            return ()
        found = tuple(body.get("capabilities") or ())
        if found:
            self._capabilities[model] = found
        return found

    def tool_models(self) -> list[str]:
        """The installed models the agent chat can use: the ones that call tools."""
        return [m.name for m in self.installed(detailed=True) if m.supports_tools]

    def list_models(self, *, vision_only: bool = False) -> list[str]:
        """Every model Ollama has, or (translation is text-only and takes
        any model; image description needs one) only vision-capable ones."""
        return [m.name for m in self.installed()
                if not vision_only or "vision" in m.capabilities]


def _arguments(value) -> dict:
    """A tool call's arguments as a dict (some Ollama versions send them as a JSON string)."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def _ollama_messages(system: str, messages: list[AgentMessage], sees_images: bool) -> list[dict]:
    """The agent's neutral history as /api/chat messages. A tool result is a "tool" message naming its
    tool; the images it carries follow in a user message (only for a model that sees images)."""
    wire: list[dict] = [{"role": "system", "content": system}] if system else []
    names: dict[str, str] = {}      # the tool calls of the last assistant message, by id
    for message in messages:
        if isinstance(message, AssistantMessage):
            names = {c.id: c.name for c in message.tool_calls}
            turn: dict = {"role": "assistant", "content": message.text}
            if message.tool_calls:
                turn["tool_calls"] = [{"function": {"name": c.name, "arguments": c.input}}
                                      for c in message.tool_calls]
            wire.append(turn)
        elif isinstance(message, ToolResultsMessage):
            images: list[str] = []
            for result in message.results:
                text = ("Error: " if result.is_error else "") + result.text
                if result.images and not sees_images:
                    text += "\n(An image was rendered, but this model cannot look at images.)"
                wire.append({"role": "tool", "content": text, "tool_name": names.get(result.call_id, "")})
                if sees_images:
                    images += [base64.b64encode(i).decode("ascii") for i in result.images]
            if images:
                wire.append({"role": "user", "content": "The image from the tool above:", "images": images})
        else:
            wire.append({"role": "user", "content": message.text})
    return wire


def _image_media_type(data: bytes) -> str:
    for magic, media_type in ((b"\x89PNG", "image/png"), (b"\xff\xd8", "image/jpeg"),
                              (b"GIF8", "image/gif")):
        if data.startswith(magic):
            return media_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise ProviderError("Claude reads PNG, JPEG, GIF and WebP images only.")


# Models whose API takes output_config.effort (older ones answer 400 to it).
_EFFORT_MODELS_RE = re.compile(r"^claude-(?:(?:sonnet|opus)-(?:5|4-[6-9])|fable-|mythos-|haiku-5)")
AGENT_EFFORT = "medium"     # Anthropic's start for agentic, multi-step tool use


def _sdk():
    """The ``anthropic`` module, imported on first use (about a second to load)."""
    import anthropic
    return anthropic


class AnthropicProvider:
    """Claude through the official SDK. Whatever is sent here leaves the
    machine -- callers get the user's per-project consent first (see
    resolver.py)."""

    service = "Anthropic"
    is_local = False
    base_url = "https://api.anthropic.com"
    max_retries = 2     # the SDK's own backoff for 429 / 5xx / dropped connections

    def __init__(self, model: str = DEFAULT_ANTHROPIC_MODEL, api_key: str | None = None) -> None:
        self.model = model or DEFAULT_ANTHROPIC_MODEL
        self._api_key = api_key
        self._cancelled = False
        self._stream = None     # the running request, for abort()
        self._client = None     # its SDK client, for abort() while the request is still being made (or retried)

    @property
    def label(self) -> str:
        return f"{self.model} · cloud"

    def _key(self) -> str:
        key = self._api_key
        if key is None:
            stored = credentials.get_api_key()
            key = stored.value if stored else ""
        if not key:
            raise ProviderError(
                "No Anthropic API key set. Add one in Settings, or set ANTHROPIC_API_KEY.")
        return key

    def _translate(self, exc: Exception) -> ProviderError:
        """The ProviderError (with a message for the user) an SDK failure stands for."""
        sdk = _sdk()
        if self._cancelled:
            return Cancelled("Aborted.")
        if isinstance(exc, ProviderError):
            return exc
        if isinstance(exc, sdk.APIStatusError):
            status, detail = exc.status_code, _error_detail(exc.response.content)
            if status == 401:
                return ProviderError("Anthropic rejected the API key (HTTP 401). Check it in Settings.")
            if status == 429:
                return ProviderError(f"Anthropic rate limit reached (HTTP 429), try again shortly: {detail}")
            if status == 529:
                return ProviderError(f"Anthropic is overloaded (HTTP 529), try again shortly: {detail}")
            return ProviderError(f"Anthropic returned HTTP {status}: {detail}")
        if isinstance(exc, sdk.APITimeoutError):
            return ProviderError("Anthropic request timed out.")
        if isinstance(exc, sdk.APIConnectionError):
            return ProviderError(f"Anthropic unreachable: {exc.__cause__ or exc}")
        return ProviderError(f"Anthropic request failed: {exc}")

    @contextmanager
    def _session(self, timeout: float):
        """An SDK client for one request; every failure leaves as a ProviderError."""
        client = _sdk().Anthropic(
            api_key=self._key(), base_url=self.base_url, timeout=timeout, max_retries=self.max_retries)
        self._client = client
        try:
            yield client
        except Exception as exc:  # noqa: BLE001 -- whatever the SDK or its HTTP layer raises
            raise self._translate(exc) from exc
        finally:
            self._stream = self._client = None
            client.close()

    def _stream_message(self, client, on_text: Callable[[str], None] | None, **request):
        with client.messages.stream(**request) as stream:
            self._stream = stream
            if self._cancelled:
                raise Cancelled("Aborted.")
            for text in stream.text_stream:
                if self._cancelled:
                    raise Cancelled("Aborted.")
                if on_text is not None:
                    on_text(text)
            return stream.get_final_message()

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
        with self._session(timeout) as client:
            message = self._stream_message(client, None, **request)
        return ChatReply(text=_message_text(message), truncated=message.stop_reason == "max_tokens")

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
        with self._session(timeout) as client:
            message = self._stream_message(client, on_text, **request)
        calls = [ToolCall(b.id, b.name, b.input if isinstance(b.input, dict) else {})
                 for b in message.content if b.type == "tool_use"]
        usage = message.usage
        return AssistantMessage(
            text=_message_text(message), tool_calls=calls,
            stop=message.stop_reason if message.stop_reason in ("tool_use", "max_tokens", "refusal")
            else "end_turn",
            raw=message.content,
            usage={"input": usage.input_tokens, "output": usage.output_tokens,
                   "cache_read": usage.cache_read_input_tokens or 0,
                   "cache_write": usage.cache_creation_input_tokens or 0})

    def list_models(self) -> list[str]:
        try:
            with self._session(10) as client:
                return [model.id for model in client.models.list(limit=1000)]
        except ProviderError:
            return []

    def abort(self) -> None:
        """Ends a running chat() / stream_turn() from another thread (it raises Cancelled)."""
        self._cancelled = True
        stream, client = self._stream, self._client
        if stream is not None:
            # The socket first: closing the response alone does not wake a read blocked in another thread.
            network = stream.response.extensions.get("network_stream")
            _shutdown_socket(network.get_extra_info("socket") if network is not None else None)
        # Closing what is open also ends a request that has not started streaming yet: its connect or
        # its retry then fails at once instead of going on to answer nobody.
        for closable in (stream, client):
            if closable is not None:
                try:
                    closable.close()
                except Exception:  # noqa: BLE001 -- the request is being torn down under the reader
                    pass


def _message_text(message) -> str:
    return "".join(block.text for block in message.content if block.type == "text")


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
