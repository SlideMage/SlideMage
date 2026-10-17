"""Which route answers an AI request, and with which model (workspace v6 handoff, step 1: the one resolver).

Every AI request SlideMage makes asks `resolve(ctx, task)` and runs on what it gets back; nothing picks a
provider, a model or Claude Code by itself. Pure: no Qt, no network, no process.

Concepts (the handoff README, section 2):

* `mode` ("local" | "cloud"): the route of all *new* AI work in this session, in memory. It starts from the
  project's `policy` when the project is first asked, and only `set_mode` changes it. Requests already
  running keep the Route they captured.
* `cloud_conn` ("claude_code" | "api"): what Cloud means. Persisted in app_settings.json: it depends on what
  this person has installed or signed in to (Claude Code, an API key), so it must not follow the project to a
  collaborator. Anthropic API is never a fallback of Claude Code, nor the reverse.
* `policy` ("local" | "cloud"): the project's own setting, in `.slidemage/project.json` under `"ai"`, tracked
  with the project so everyone who opens it starts on the same side. A project without one is Local: nothing
  leaves the machine until someone says so. An older `"ai": {"local_only": true}` reads as "local", an explicit
  `false` as "cloud"; set_policy replaces it.
* `cloud_seen`: the project's first-use flag for Cloud (app_settings.json, which sits inside the project
  folder). It replaces `cloud_consent`, which reads as the same flag until the next write.
* models per route and task, in app_settings.json under "ai_models": {route: {task: choice}}. A choice is an
  Ollama or API model name, or for Claude Code "<model>:<effort>" ("haiku:medium"). The task models of the
  earlier version ("<provider>:<model>" under drafting_model, translation_model, chat_model and
  syntax_check_model) read as the Local (ollama) and API (anthropic) models until the first write moves them.

Routes: "local" is Ollama, "claude_code" the user's `claude` as a one-shot task or a terminal, "api" the
Anthropic API. resolve() says which; ai/resolver.py turns the answer into a provider or backend and says when
that is not possible.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .. import app_settings, project
from ..project import ProjectContext
from . import claude_runner
from .providers import DEFAULT_ANTHROPIC_MODEL

LOCAL, CLAUDE_CODE, API = "local", "claude_code", "api"
ROUTES = (LOCAL, CLAUDE_CODE, API)
CLOUD = "cloud"
MODES = (LOCAL, CLOUD)                      # of the switch and of the project setting
CONNECTIONS = (CLAUDE_CODE, API)

CHAT, IMAGE_DESCRIPTION, TRANSLATION, FIXES = "chat", "image_description", "translation", "fixes_notes_transcripts"
TASKS = (CHAT, IMAGE_DESCRIPTION, TRANSLATION, FIXES)
TASK_LABELS = {CHAT: "Chat", IMAGE_DESCRIPTION: "Image descriptions", TRANSLATION: "Translation",
               FIXES: "Fixes, notes, transcripts"}
SERVICES = {LOCAL: "Ollama", CLAUDE_CODE: "Claude Code", API: "API"}

MODELS_KEY, CONNECTION_KEY, SEEN_KEY = "ai_models", "cloud_conn", "cloud_seen"
_LEGACY_SEEN_KEY = "cloud_consent"
_LEGACY_MODEL_KEYS = {CHAT: "chat_model", IMAGE_DESCRIPTION: "drafting_model", TRANSLATION: "translation_model",
                      FIXES: "syntax_check_model"}


@dataclass(frozen=True)
class Route:
    """What one AI request runs on. Frozen: a request keeps the Route it was started with."""
    route: str                      # LOCAL, CLAUDE_CODE or API
    task: str                       # one of TASKS
    model: str = ""                 # "" when none is chosen, and for the chat of Claude Code (set in Claude Code)
    effort: str | None = None       # Claude Code tasks only

    @property
    def is_local(self) -> bool:
        return self.route == LOCAL

    @property
    def name(self) -> str:
        """The route as the assistant's header names it: "Local · Ollama", "Cloud · Claude Code", "Cloud · API"."""
        return {LOCAL: "Local · Ollama", CLAUDE_CODE: "Cloud · Claude Code", API: "Cloud · Anthropic API"}[self.route]

    @property
    def label(self) -> str:
        """What to show next to the work: "translategemma:12b · Ollama", "Claude Code · Haiku · effort medium",
        "claude-sonnet-5-5 · API"."""
        if self.route == CLAUDE_CODE:
            return " · ".join(["Claude Code", *([self.model.capitalize(), f"effort {self.effort}"] if self.model
                                                 else ["terminal"])])
        return f"{self.model or 'no model chosen'} · {SERVICES[self.route]}"


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


def active_route(ctx: ProjectContext) -> str:
    """The route key of new work: Local, or the cloud connection."""
    return LOCAL if mode(ctx) == LOCAL else cloud_conn(ctx)


# -- persisted: connection, policy, first use --------------------------------------------------

def cloud_conn(ctx: ProjectContext) -> str:
    value = app_settings.get(ctx, CONNECTION_KEY)
    return value if value in CONNECTIONS else CLAUDE_CODE


def set_cloud_conn(ctx: ProjectContext, value: str) -> None:
    if value not in CONNECTIONS:
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
        route, model = (API, rest) if sep and head == "anthropic" else (LOCAL, rest if sep and head == "ollama" else spec)
        if model:
            models.setdefault(route, {})[task] = model
    return models


def _stored_models(settings: dict) -> dict[str, dict[str, str]]:
    stored = settings.get(MODELS_KEY)
    return stored if isinstance(stored, dict) else _legacy_models(settings)


def default_choice(route: str, task: str) -> str:
    """What a route runs a task on while the user has chosen nothing: nothing for Local (the pickers offer
    what is installed), Claude Code's benchmarked setup for its tasks (its chat is the terminal's own model),
    the standard Claude model for the API."""
    if route == API:
        return DEFAULT_ANTHROPIC_MODEL
    return "" if route == LOCAL or task == CHAT else f"{claude_runner.MODEL}:{claude_runner.EFFORT}"


def claude_code_choices() -> list[str]:
    return [f"{model}:{effort}" for model in claude_runner.MODELS for effort in claude_runner.EFFORTS]


def choice_label(route: str, choice: str) -> str:
    """A choice as a picker shows it: the model name, for Claude Code "Sonnet · medium"."""
    model, _, effort = choice.partition(":")
    return f"{model.capitalize()} · {effort}" if route == CLAUDE_CODE else choice


def model_choice(ctx: ProjectContext, route: str, task: str) -> str:
    """The saved choice of `route` for `task`, else default_choice."""
    stored = _stored_models(app_settings.load(ctx)).get(route)
    choice = stored.get(task) if isinstance(stored, dict) else None
    if route == CLAUDE_CODE and choice not in claude_code_choices():
        choice = None
    return choice if isinstance(choice, str) and choice else default_choice(route, task)


def set_model_choice(ctx: ProjectContext, route: str, task: str, choice: str) -> None:
    """Save `choice` as the default of `route` for `task` ("" goes back to default_choice)."""
    settings = app_settings.load(ctx)
    models = _stored_models(settings)
    models.setdefault(route, {})[task] = choice
    settings[MODELS_KEY] = models
    for key in _LEGACY_MODEL_KEYS.values():
        settings.pop(key, None)
    app_settings.save(ctx, settings)


# -- the resolver ------------------------------------------------------------------------

def route_for(ctx: ProjectContext, route: str, task: str, choice: str = "") -> Route:
    """The Route of `route` for `task`, on `choice` (a picker's pick) or else the saved choice. A pick that
    Claude Code does not offer (a picker still filled for another route) is no pick."""
    if route == CLAUDE_CODE and choice not in claude_code_choices():
        choice = ""
    choice = choice or model_choice(ctx, route, task)
    if route == CLAUDE_CODE:
        model, _, effort = choice.partition(":")
        return Route(route, task, model, effort or None)
    return Route(route, task, choice)


def resolve(ctx: ProjectContext, task: str, choice: str = "") -> Route:
    """The Route for a new request for `task`: the one every AI dispatch asks. `choice` is what a picker of
    that route holds; it replaces the saved choice for this request only."""
    return route_for(ctx, active_route(ctx), task, choice)
