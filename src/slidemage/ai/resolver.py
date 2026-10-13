"""What runs a Route (workspace v6 handoff, step 1): ai_profile.resolve() says which route and model answer a
task; this module turns that Route into a provider or a backend, or says why it cannot.

A route that cannot run a request raises RouteUnavailable, with a message ready to show: it names the route
and what is missing or not offered there. Nothing here, and nothing that calls it, falls back to another
route or model: the user chose it, a silent swap would answer with something they did not pick, and
"Anthropic API is never a fallback" of Claude Code, nor the reverse.

  * Local and API run through a ChatProvider (providers.py), for the chat, the syntax check, the slide
    translation of the Add slide sheet and the image pipeline (alt_draft's ModelBackend).
  * Claude Code runs the image pipeline (claude_images' backends), the slide translation and the bubble tasks
    (ui/workspace/terminal/tasks.py) as one-shot `claude -p` processes, and the chat as the terminal.
    It has no ChatProvider: provider_for() refuses it.
"""
from __future__ import annotations

from pathlib import Path

from .. import alt_draft
from ..project import ProjectContext
from . import ai_profile, claude_launch, credentials
from .ai_profile import API, CLAUDE_CODE, LOCAL, Route
from .claude_images import ClaudeDraftBackend, ClaudeTranslationBackend
from .claude_runner import SlideTranslator
from .providers import (
    ANTHROPIC_FALLBACK_MODELS,
    AnthropicProvider,
    ChatProvider,
    OllamaProvider,
    ProviderError,
)

NO_KEY = "No Anthropic API key yet. Add one under Settings → Cloud."
NO_CLAUDE = "Claude Code is not installed on this computer, so nothing was sent and no other model is used."
CHAT_IN_TERMINAL = ("On Cloud · Claude Code the conversation is the terminal in the Claude Code tab; the chat "
                    "with Ollama or the API is not available on this route.")


class RouteUnavailable(ProviderError):
    """A route cannot run this request; str(exc) says what is missing there."""


def not_offered(route: Route, what: str, instead: str = "") -> str:
    """The message for `what` that `route` has no implementation of; `instead` says what to do."""
    return " ".join([f"{what} is not available on {route.name}: nothing was sent and no other route or model "
                     "is used.", instead]).strip()


def api_models(ctx: ProjectContext) -> list[str]:
    """The API models to list in the pickers: none without a key. The static list, so opening a dialog never
    waits on the network; Settings shows the live list."""
    return [] if credentials.get_api_key(ctx) is None else list(ANTHROPIC_FALLBACK_MODELS)


def problem(ctx: ProjectContext, route: Route) -> str:
    """Why `route` cannot run its task right now, or "" when it can: no model chosen, no API key, or the
    chat of Claude Code (the terminal)."""
    if route.route == CLAUDE_CODE:
        return CHAT_IN_TERMINAL if route.task == ai_profile.CHAT else ""
    if route.route == API:
        return "" if credentials.get_api_key(ctx) is not None else NO_KEY
    if not route.model:
        return (f"Choose an Ollama model for {ai_profile.TASK_LABELS[route.task].lower()} under "
                "AI setup (the ▾ of the AI switch).")
    return ""


def provider_for(ctx: ProjectContext, route: Route) -> ChatProvider:
    """The provider of a Local or API route. A new one on each call: abort() ends one request only."""
    if route.route == CLAUDE_CODE:
        raise RouteUnavailable(not_offered(route, "This feature", "It needs an Ollama or an API model: switch the route."))
    if reason := problem(ctx, route):
        raise RouteUnavailable(reason)
    if route.route == LOCAL:
        return OllamaProvider.for_project(ctx, route.model)
    return AnthropicProvider.for_project(ctx, route.model)


def claude_path() -> Path:
    claude = claude_launch.find_claude()
    if claude is None:
        raise RouteUnavailable(NO_CLAUDE)
    return claude


def slide_translator(ctx: ProjectContext, route: Route) -> ChatProvider | SlideTranslator:
    """What translates the body of a slide on `route`: slide_add.translate_body takes the provider of Local and
    the API, Claude Code runs its Translate task."""
    if route.route == CLAUDE_CODE:
        return SlideTranslator(ctx, claude_path(), route.model, route.effort)
    return provider_for(ctx, route)


def draft_backend(ctx: ProjectContext, route: Route) -> alt_draft.ModelBackend | ClaudeDraftBackend:
    """What describes images on `route`."""
    if route.route == CLAUDE_CODE:
        return ClaudeDraftBackend(ctx, claude_path(), route.model, route.effort)
    return alt_draft.ModelBackend(ctx, provider_for(ctx, route))


def translation_backend(ctx: ProjectContext, route: Route) -> alt_draft.ModelTranslationBackend | ClaudeTranslationBackend:
    """What translates the descriptions of images on `route`."""
    if route.route == CLAUDE_CODE:
        return ClaudeTranslationBackend(ctx, claude_path(), route.model, route.effort)
    return alt_draft.ModelTranslationBackend(ctx, provider_for(ctx, route))
