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
from ..plugin_api import AiRoute, RouteContext
from ..project import ProjectContext

_routes: dict[str, AiRoute] = {}
_builtins_done = False
_owners: dict[str, object] = {}
_settings: dict[object, object] = {}


def register(route: AiRoute, owner: object | None = None) -> None:
    """Add `route`. A second route with the same id raises ValueError: ids are stored in settings and in every
    Route, so two routes must never share one."""
    _ensure_builtins()
    _add(route)
    if owner is not None:
        _owners[route.id] = owner
    else:
        _owners.pop(route.id, None)


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
    _owners.clear()
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


def context(ctx: ProjectContext, route_id: str) -> RouteContext:
    """Build the public context for a route, using its registering plugin's namespace."""
    from .. import app_settings, project
    from ..plugins.credentials import PluginCredentials
    from ..plugins.host import PluginSettings
    from ..plugins.migrate import legacy_anthropic_key
    from . import translation_style

    owner = _owners.get(route_id)
    plugin_id = owner.manifest.id if owner is not None else route_id
    if owner is not None and hasattr(owner, "ctx"):
        settings = owner.settings()
    else:
        path = project.config_dir() / "plugins" / "settings" / f"{plugin_id}.json"
        if path not in _settings:
            _settings[path] = PluginSettings(path)
        settings = _settings[path]

    def legacy_secret(name):
        if name != "anthropic_api_key":
            raise ValueError(f"unknown legacy secret: {name}")
        return legacy_anthropic_key(ctx)

    return RouteContext(
        root=ctx.root, settings=settings, cache_dir=project.cache_dir() / "plugins" / plugin_id,
        legacy_cache_dir=project.cache_dir() if project.cache_dir().is_dir() else None,
        credentials=lambda env_var=None: PluginCredentials(plugin_id, env_var),
        legacy_secret=legacy_secret, legacy_ollama_host=lambda: app_settings.get_ollama_host(ctx),
        de_address=translation_style.de_address(ctx), glossary=translation_style.glossary(ctx),
    )
