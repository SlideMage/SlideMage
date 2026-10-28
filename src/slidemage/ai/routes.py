# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The registry of AI routes (plugin plan 2.4): which AiRoute objects exist, by id.

Core asks the registry for everything route-specific (ai_profile for ids, models and labels; resolver for providers
and backends), so that no core module has to name Ollama, Claude Code or the Anthropic API. Today core registers
its three routes at start (register_builtin_routes); phases 5 and 6 move them into plugins, which register theirs
through the host (3d).

Pure: no Qt, no network. The order of registration is the order the UI lists routes in.
"""
from __future__ import annotations

from .. import plugin_api
from ..plugin_api import AiRoute

_routes: dict[str, AiRoute] = {}
_builtins_done = False


def register(route: AiRoute) -> None:
    """Add `route`. A second route with the same id raises ValueError: ids are stored in settings and in every
    Route, so two routes must never share one."""
    _ensure_builtins()
    _add(route)


def _add(route: AiRoute) -> None:
    if route.id in _routes:
        raise ValueError(f"AI route {route.id!r} is already registered")
    _routes[route.id] = route


def get(route_id: str) -> AiRoute | None:
    """The route with this id, or None (a route whose plugin is gone or off)."""
    _ensure_builtins()
    return _routes.get(route_id)


def all() -> list[AiRoute]:  # noqa: A001 -- the registry's own vocabulary
    """Every registered route, in registration order."""
    _ensure_builtins()
    return list(_routes.values())


def on_side(is_local: bool) -> list[AiRoute]:
    """The routes of the Local side of the AI switch (is_local) or of the Cloud side."""
    return [route for route in all() if route.is_local == is_local]


def clear() -> None:
    """Remove every route, the built-in ones too and for good (until register_builtin_routes is called): for tests
    that need a registry of their own."""
    global _builtins_done
    _routes.clear()
    _builtins_done = True


def register_builtin_routes() -> None:
    """Register core's three routes (Ollama, Claude Code, the Anthropic API) that are not registered yet. Called
    once where the app starts, and lazily by every registry call, so that tests and the command line, which never
    start the GUI, have them too."""
    global _builtins_done
    _builtins_done = True
    from .anthropic_api_route import AnthropicApiRoute
    from .claude_code_route import ClaudeCodeRoute
    from .ollama_route import OllamaRoute
    for route in (OllamaRoute(), ClaudeCodeRoute(), AnthropicApiRoute()):
        if route.id not in _routes:
            _add(route)


def _ensure_builtins() -> None:
    if not _builtins_done:
        register_builtin_routes()


plugin_api.set_route_lookup(get)
