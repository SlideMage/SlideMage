# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""What runs a Route (workspace v6 handoff, step 1): ai_profile.resolve() says which route and model answer a
task; this module asks that route (ai/routes.py) for a provider or a backend, or says why it cannot.

A route that cannot run a request raises RouteUnavailable, with a message ready to show: it names the route
and what is missing or not offered there. Nothing here, and nothing that calls it, falls back to another
route or model: the user chose it, a silent swap would answer with something they did not pick, and one cloud
route is never a fallback of another.

  * A route with a ChatProvider (Ollama, the Anthropic API) runs through it for the chat, the syntax check, the slide
    translation of the Add slide sheet and the image pipeline (alt_draft's ModelBackend).
  * A route without one (Claude Code) runs the image pipeline, the slide translation and the bubble tasks
    (ui/workspace/terminal/tasks.py) itself as one-shot processes, and the chat as its own surface. provider_for()
    refuses it.

The route decides how; this module decides what is refused first: an unknown route, then the route's own problem().
"""
from __future__ import annotations

from typing import Any

from .. import alt_draft
from ..plugin_api import AiRoute
from ..project import ProjectContext
from . import ai_profile, routes
from .ai_profile import Route
from .providers import ChatProvider, RouteUnavailable


def not_offered(route: Route, what: str, instead: str = "") -> str:
    """The message for `what` that `route` has no implementation of; `instead` says what to do."""
    return " ".join([f"{what} is not available on {route.name}: nothing was sent and no other route or model "
                     "is used.", instead]).strip()


def _route(route: Route) -> AiRoute:
    """The registered route of `route`, or RouteUnavailable when none is (its plugin is off, or there is no route)."""
    found = routes.get(route.route)
    if found is None:
        raise RouteUnavailable(f"The AI route {route.route or 'for this side'!r} is not installed, so nothing was "
                               "sent and no other route or model is used.")
    return found


def api_models(ctx: ProjectContext) -> list[str]:
    """The Anthropic API models to list in the pickers: none without a key. The static list, so opening a dialog
    never waits on the network; Settings shows the live list."""
    found = routes.get(ai_profile.ANTHROPIC_API)
    return found.model_choices(routes.context(ctx, found.id), ai_profile.CHAT) if found else []


def problem(ctx: ProjectContext, route: Route) -> str:
    """Why `route` cannot run its task right now, or "" when it can: no model chosen, no API key, or the
    chat of Claude Code (the terminal)."""
    found = routes.get(route.route)
    if found is None:
        return f"The AI route {route.route or 'for this side'!r} is not installed."
    return found.problem(routes.context(ctx, found.id), route)


def provider_for(ctx: ProjectContext, route: Route) -> ChatProvider:
    """The provider of a route that has one. A new one on each call: abort() ends one request only."""
    found = _route(route)
    provider = found.provider(routes.context(ctx, found.id), route)
    if provider is None:
        raise RouteUnavailable(not_offered(route, "This feature", "Choose a route that provides this feature."))
    if reason := found.problem(routes.context(ctx, found.id), route):
        raise RouteUnavailable(reason)
    return provider


def request_provider_for(ctx: ProjectContext, route: Route) -> ChatProvider:
    """A provider for one self-contained ai.chat request; other features still use provider_for()."""
    found = _route(route)
    if not hasattr(found, "request_provider"):
        return provider_for(ctx, route)
    provider = found.request_provider(routes.context(ctx, found.id), route)
    if provider is None:
        raise RouteUnavailable(not_offered(route, "This feature", "Choose a route that provides this feature."))
    return provider


def _checked(ctx: ProjectContext, route: Route) -> AiRoute:
    """The route, once it says it can run `route`."""
    found = _route(route)
    if reason := found.problem(routes.context(ctx, found.id), route):
        raise RouteUnavailable(reason)
    return found


def slide_translator(ctx: ProjectContext, route: Route) -> Any:
    """What translates the body of a slide on `route`: slide_add.translate_body takes a provider, a route that
    runs its own Translate task (Claude Code) hands its own translator."""
    found = _checked(ctx, route)
    return found.slide_translator(routes.context(ctx, found.id), route) or provider_for(ctx, route)


def draft_backend(ctx: ProjectContext, route: Route) -> Any:
    """What describes images on `route`."""
    return _checked(ctx, route).draft_backend(routes.context(ctx, route.route), route) or alt_draft.ModelBackend(ctx, provider_for(ctx, route))


def translation_backend(ctx: ProjectContext, route: Route) -> Any:
    """What translates the descriptions of images on `route`."""
    return (_checked(ctx, route).translation_backend(routes.context(ctx, route.route), route)
            or alt_draft.ModelTranslationBackend(ctx, provider_for(ctx, route)))
