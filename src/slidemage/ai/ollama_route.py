# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Ollama route: a model on this computer (or the Ollama server the user set), the Local side of the AI switch.

It holds OllamaProvider and InstalledModel (moved here from providers.py, which keeps what every provider shares) and
OllamaRoute, the AiRoute that ai/routes.py registers at start. Nothing in core outside this module (and the Ollama
settings page, ollama_admin and the pickers that still list its models) names Ollama; the route is what phase 5
moves into the Ollama plugin.

Ollama is stdlib (``http.client``, not ``urllib.request``): a running request must be abortable from another thread by
closing its socket (providers._HttpProvider.abort).
"""
from __future__ import annotations

import base64
import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .. import app_settings
from ..plugin_api import Route
from ..project import ProjectContext
from . import ai_profile
from .agent_types import AgentMessage, AssistantMessage, ToolCall, ToolResultsMessage, ToolSpec
from .providers import (
    AGENT_NUM_CTX,
    Cancelled,
    ChatReply,
    Message,
    ProviderError,
    _error_detail,
    _HttpProvider,
)

if TYPE_CHECKING:
    import threading

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

    def __init__(self, model: str = "", host: str = app_settings.DEFAULT_OLLAMA_HOST) -> None:
        super().__init__()
        self.model = model
        self.host = host
        self._capabilities: dict[str, tuple[str, ...]] = {}     # what /api/show said, by model

    @classmethod
    def for_project(cls, ctx: ProjectContext, model: str = "") -> "OllamaProvider":
        """On the project's Ollama host, read now: a host saved later in Settings applies to the next provider."""
        return cls(model, app_settings.get_ollama_host(ctx))

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


class OllamaRoute:
    """Ollama as an AiRoute. Today's behaviour: every task, no default model (the pickers offer what is installed),
    a problem while no model is chosen."""

    id = "ollama"
    service = "Ollama"
    is_local = True
    tasks = frozenset(ai_profile.TASKS)

    def problem(self, ctx: ProjectContext, route: Route) -> str:
        if not route.model:
            return (f"Choose an Ollama model for {ai_profile.TASK_LABELS[route.task].lower()} under "
                    "AI setup (the ▾ of the AI switch).")
        return ""

    def model_choices(self, ctx: ProjectContext, task: str) -> list[str]:
        return []       # the installed models come from the server: the pickers ask OllamaProvider.list_models

    def default_choice(self, task: str) -> str:
        return ""

    def choice_label(self, choice: str) -> str:
        return choice

    def split_choice(self, choice: str) -> tuple[str, str | None]:
        return choice, None     # a model name may itself hold a colon ("qwen3:8b")

    def valid_choice(self, ctx: ProjectContext, choice: str) -> bool:
        return bool(choice)

    def work_label(self, route: Route) -> str:
        return f"{route.model or 'no model chosen'} · Ollama"

    def provider(self, ctx: ProjectContext, route: Route) -> OllamaProvider:
        return OllamaProvider.for_project(ctx, route.model)

    def draft_backend(self, ctx: ProjectContext, route: Route, cancel: "threading.Event | None" = None) -> None:
        return None     # core wraps provider() in alt_draft.ModelBackend

    def translation_backend(self, ctx: ProjectContext, route: Route, cancel: "threading.Event | None" = None) -> None:
        return None     # core wraps provider() in alt_draft.ModelTranslationBackend

    def slide_translator(self, ctx: ProjectContext, route: Route) -> None:
        return None     # core wraps provider() in slide_add.translate_body

    def task_runner(self, ctx: ProjectContext, route: Route) -> None:
        return None     # core's provider_tasks

    def chat_surface(self, *args: Any, **kwargs: Any) -> None:
        return None     # core's chat view

    def settings_section(self) -> None:
        return None     # Ollama's tab is still a tab of Settings; 3c makes it a section

