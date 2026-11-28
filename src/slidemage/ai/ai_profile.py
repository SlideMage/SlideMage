# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which route answers an AI request, and with which model (workspace v6 handoff, step 1: the one resolver).

Every AI request SlideMage makes asks `resolve(ctx, task)` and runs on what it gets back; nothing picks a
provider, a model or Claude Code by itself. Pure: no Qt, no network, no process.

Concepts (the handoff README, section 2):

* `mode` ("local" | "cloud"): the side of the AI switch for all *new* AI work in this session, in memory. It is NOT
  a route id: Local is every route that keeps data on this computer (AiRoute.is_local), Cloud the others. It starts
  from the project's `policy` when the project is first asked, and only `set_mode` changes it. Requests already
  running keep the Route they captured.
* `cloud_conn`: which cloud route Cloud means, by route id ("claude_code", "anthropic_api" or a plugin's). Kept for
  this machine (app_settings.MACHINE_KEYS, SlideMage's own ai_settings.json since v8.58.0): it depends on what this
  person has installed or signed in to (Claude Code, an API key), so it must not follow the project to a
  collaborator. One cloud route is never a fallback of another. A stored "api" reads as "anthropic_api".
* `policy` ("local" | "cloud"): the project's own setting, in `.slidemage/project.json` under `"ai"`, tracked
  with the project so everyone who opens it starts on the same side. A project without one is Local: nothing
  leaves the machine until someone says so. An older `"ai": {"local_only": true}` reads as "local", an explicit
  `false` as "cloud"; set_policy replaces it.
* `cloud_seen`: the project's first-use flag for Cloud (app_settings.json, which sits inside the project
  folder). It replaces `cloud_consent`, which reads as the same flag until the next write.
* models per route and task, under "ai_models": {route id: {task: choice}}, kept for this machine like
  `cloud_conn`. What a choice looks like is the route's business (ai/routes.py): a model name, or for Claude Code
  "<model>:<effort>" ("haiku:medium"). The task models of the earlier version ("<provider>:<model>" under
  drafting_model, translation_model, chat_model and syntax_check_model) read as the Ollama and Anthropic API models
  until the first write moves them. Keys of the version before route ids, "local" and "api", read as "ollama" and
  "anthropic_api"; the next write stores the new ids.

Routes are registered objects (ai/routes.py): the ids "ollama", "claude_code" and "anthropic_api" are core's own,
and a plugin adds more. resolve() says which route and model; ai/resolver.py turns the answer into a provider or
backend and says when that is not possible.
"""
from __future__ import annotations

from pathlib import Path

from .. import app_settings, project
from ..plugin_api import Route
from ..project import ProjectContext
from . import routes

OLLAMA, CLAUDE_CODE, ANTHROPIC_API = "ollama", "claude_code", "anthropic_api"      # core's route ids
LOCAL, CLOUD = "local", "cloud"             # the two sides of the switch: a mode and a policy, not route ids
MODES = (LOCAL, CLOUD)                      # of the switch and of the project setting
CONNECTIONS = (CLAUDE_CODE, ANTHROPIC_API)  # core's cloud routes; the registry has the full list (cloud_routes)
_LEGACY_ROUTE_IDS = {"local": OLLAMA, "api": ANTHROPIC_API}     # as stored before the ids were the routes'

CHAT, IMAGE_DESCRIPTION, TRANSLATION, FIXES = "chat", "image_description", "translation", "fixes_notes_transcripts"
TASKS = (CHAT, IMAGE_DESCRIPTION, TRANSLATION, FIXES)
TASK_LABELS = {CHAT: "Chat", IMAGE_DESCRIPTION: "Image descriptions", TRANSLATION: "Translation",
               FIXES: "Fixes, notes, transcripts"}

MODELS_KEY, CONNECTION_KEY, SEEN_KEY = "ai_models", "cloud_conn", "cloud_seen"
_LEGACY_SEEN_KEY = "cloud_consent"
_LEGACY_MODEL_KEYS = {CHAT: "chat_model", IMAGE_DESCRIPTION: "drafting_model", TRANSLATION: "translation_model",
                      FIXES: "syntax_check_model"}


def route_id(stored: object) -> str:
    """A stored route id as today's: "local" is "ollama", "api" is "anthropic_api"; anything else as it is."""
    return _LEGACY_ROUTE_IDS.get(stored, stored) if isinstance(stored, str) else ""


def services() -> dict[str, str]:
    """What each registered route is called ("ollama": "Ollama", ...)."""
    return {route.id: route.service for route in routes.all()}


def local_routes() -> list[str]:
    """The ids of the routes on the Local side, in registration order."""
    return [route.id for route in routes.on_side(True)]


def cloud_routes() -> list[str]:
    """The ids of the routes on the Cloud side, in registration order."""
    return [route.id for route in routes.on_side(False)]


# -- the session: mode ---------------------------------------------------------------------

_modes: dict[Path, str] = {}       # per project folder; the app runs one project per process


def mode(ctx: ProjectContext) -> str:
    """The route family of new AI work: the project's policy until set_mode says otherwise."""
    if ctx.root not in _modes:
        _modes[ctx.root] = policy(ctx)
    return _modes[ctx.root]


def set_mode(ctx: ProjectContext, value: str) -> None:
    if value not in MODES:
        raise ValueError(f"Unknown AI mode: {value!r}")
    _modes[ctx.root] = value


def local_route(ctx: ProjectContext) -> str:
    """The route of new work on the Local side: the first registered local route ("" when none is installed)."""
    return next(iter(local_routes()), "")


def active_route(ctx: ProjectContext) -> str:
    """The route id of new work: the local route, or the cloud connection."""
    return local_route(ctx) if mode(ctx) == LOCAL else cloud_conn(ctx)


# -- persisted: connection, policy, first use --------------------------------------------------

def cloud_conn(ctx: ProjectContext) -> str:
    """Which cloud route Cloud means: the stored one while it is registered, else Claude Code, else the first cloud
    route ("" when there is none)."""
    clouds = cloud_routes()
    value = route_id(app_settings.get(ctx, CONNECTION_KEY))
    if value in clouds:
        return value
    return CLAUDE_CODE if CLAUDE_CODE in clouds or not clouds else clouds[0]


def set_cloud_conn(ctx: ProjectContext, value: str) -> None:
    value = route_id(value)
    if value not in cloud_routes():
        raise ValueError(f"Unknown cloud connection: {value!r}")
    app_settings.set(ctx, CONNECTION_KEY, value)


def _project_ai(ctx: ProjectContext) -> dict:
    ai = project.read_project_json(ctx.root).get("ai")
    return ai if isinstance(ai, dict) else {}


def policy(ctx: ProjectContext) -> str:
    ai = _project_ai(ctx)
    if ai.get("policy") in MODES:
        return ai["policy"]
    return CLOUD if ai.get("local_only") is False else LOCAL


def set_policy(ctx: ProjectContext, value: str) -> None:
    if value not in MODES:
        raise ValueError(f"Unknown project AI policy: {value!r}")
    data = project.read_project_json(ctx.root)
    ai = _project_ai(ctx)
    ai.pop("local_only", None)
    data["ai"] = {**ai, "policy": value}
    project.write_project_json(ctx.root, data)


def cloud_seen(ctx: ProjectContext) -> bool:
    settings = app_settings.load(ctx)
    return bool(settings.get(SEEN_KEY, settings.get(_LEGACY_SEEN_KEY)))


def mark_cloud_seen(ctx: ProjectContext) -> None:
    settings = app_settings.load(ctx)
    settings.pop(_LEGACY_SEEN_KEY, None)
    settings[SEEN_KEY] = True
    app_settings.save(ctx, settings)


# -- models per route and task -------------------------------------------------------------

def _legacy_models(settings: dict) -> dict[str, dict[str, str]]:
    """The models of the earlier "<provider>:<model>" settings, by route; a bare name is an Ollama model."""
    models: dict[str, dict[str, str]] = {}
    for task, key in _LEGACY_MODEL_KEYS.items():
        spec = str(settings.get(key) or "")
        head, sep, rest = spec.partition(":")
        route, model = ((ANTHROPIC_API, rest) if sep and head == "anthropic"
                        else (OLLAMA, rest if sep and head == "ollama" else spec))
        if model:
            models.setdefault(route, {})[task] = model
    return models


def _stored_models(settings: dict) -> dict[str, dict[str, str]]:
    """The saved models by route id; the keys of the version before route ids ("local", "api") read as today's."""
    stored = settings.get(MODELS_KEY)
    if not isinstance(stored, dict):
        return _legacy_models(settings)
    models: dict = {}
    for key, value in stored.items():
        current = route_id(key)
        if isinstance(value, dict) and isinstance(models.get(current), dict):
            models[current] = {**models[current], **value}
        else:
            models[current] = value     # a value that is no dict stays as it is: model_choice ignores it, a write keeps it
    return models


def model_choices(ctx: ProjectContext, route: str, task: str) -> list[str]:
    """What the route offers for `task` without asking anyone (AiRoute.model_choices): [] for an unknown route."""
    impl = routes.get(route_id(route))
    return impl.model_choices(routes.context(ctx, impl.id), task) if impl else []


def default_choice(route: str, task: str) -> str:
    """What a route runs a task on while the user has chosen nothing (its own word: nothing for Ollama, whose pickers
    offer what is installed, Claude Code's benchmarked setup for its tasks, the standard Claude model for the API)."""
    impl = routes.get(route_id(route))
    return impl.default_choice(task) if impl else ""


def choice_label(route: str, choice: str) -> str:
    """A choice as a picker shows it: the model name, for Claude Code "Sonnet · medium"."""
    impl = routes.get(route_id(route))
    return impl.choice_label(choice) if impl else choice


def model_choice(ctx: ProjectContext, route: str, task: str) -> str:
    """The saved choice of `route` for `task`, else default_choice."""
    route = route_id(route)
    stored = _stored_models(app_settings.load(ctx)).get(route)
    choice = stored.get(task) if isinstance(stored, dict) else None
    impl = routes.get(route)
    if impl is not None and isinstance(choice, str) and choice and not impl.valid_choice(routes.context(ctx, impl.id), choice):
        choice = None
    return choice if isinstance(choice, str) and choice else default_choice(route, task)


def set_model_choice(ctx: ProjectContext, route: str, task: str, choice: str) -> None:
    """Save `choice` as the default of `route` for `task` ("" goes back to default_choice). Writes the route ids
    of today; the keys of an earlier version are moved with it."""
    settings = app_settings.load(ctx)
    models = _stored_models(settings)
    models.setdefault(route_id(route), {})[task] = choice
    settings[MODELS_KEY] = models
    for key in _LEGACY_MODEL_KEYS.values():
        settings.pop(key, None)
    app_settings.save(ctx, settings)


# -- the resolver ------------------------------------------------------------------------

def route_for(ctx: ProjectContext, route: str, task: str, choice: str = "") -> Route:
    """The Route of `route` for `task`, on `choice` (a picker's pick) or else the saved choice. A pick that
    the route does not offer (a picker still filled for another route) is no pick."""
    route = route_id(route)
    impl = routes.get(route)
    if impl is not None and choice and not impl.valid_choice(routes.context(ctx, impl.id), choice):
        choice = ""
    choice = choice or model_choice(ctx, route, task)
    model, effort = impl.split_choice(choice) if impl is not None else (choice, None)
    return Route(route, task, model, effort)


def resolve(ctx: ProjectContext, task: str, choice: str = "") -> Route:
    """The Route for a new request for `task`: the one every AI dispatch asks. `choice` is what a picker of
    that route holds; it replaces the saved choice for this request only."""
    return route_for(ctx, active_route(ctx), task, choice)
