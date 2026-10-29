# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The AI route registry (ai/routes.py), the three routes core registers, and ai_profile / resolver over it: ids,
labels, problems, choices, a fourth route registered by a plugin, the stored ids of earlier versions, and never a
fallback to another route."""
from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from slidemage import alt_draft, app_settings, plugin_api
from slidemage.ai import ai_profile, claude_launch, resolver, routes
from slidemage.ai.ai_profile import (
    ANTHROPIC_API, CHAT, CLAUDE_CODE, CLOUD, FIXES, IMAGE_DESCRIPTION, LOCAL, OLLAMA, TRANSLATION, Route,
)
from slidemage.ai.anthropic_api_route import NO_KEY, AnthropicApiRoute
from slidemage.ai.claude_code_route import CHAT_IN_TERMINAL, ClaudeCodeRoute
from slidemage.ai.ollama_route import OllamaProvider, OllamaRoute
from slidemage.ai.providers import ProviderError, RouteUnavailable


class FakeProvider:
    is_local = True
    label = "fake"

    def __init__(self, model: str) -> None:
        self.model = model

    def abort(self) -> None:
        pass


class FakeRoute:
    """A route as a plugin would register it: local, its own choices, a chat provider, no setting of its own."""
    id = "fake_local"
    service = "Fake"
    is_local = True
    tasks = frozenset({ai_profile.CHAT})
    blocked = ""

    def problem(self, ctx, route):
        return self.blocked

    def model_choices(self, ctx, task):
        return ["tiny", "big"]

    def default_choice(self, task):
        return "tiny"

    def choice_label(self, choice):
        return choice.upper()

    def split_choice(self, choice):
        return choice, None

    def valid_choice(self, ctx, choice):
        return choice in ("tiny", "big")

    def work_label(self, route):
        return f"{route.model} via Fake"

    def provider(self, ctx, route):
        return FakeProvider(route.model)

    def draft_backend(self, ctx, route, cancel=None):
        return None

    def translation_backend(self, ctx, route, cancel=None):
        return None

    def slide_translator(self, ctx, route):
        return None

    def task_runner(self, ctx, route):
        return None

    def chat_surface(self, *args, **kwargs):
        return None

    def settings_section(self):
        return None


@pytest.fixture
def fake_route(monkeypatch):
    """Core's three routes plus FakeRoute, in a registry that the test leaves as it found it."""
    routes.register_builtin_routes()
    monkeypatch.setattr(routes, "_routes", dict(routes._routes))
    fake = FakeRoute()
    routes.register(fake)
    return fake


# -- the registry ------------------------------------------------------------------------

def test_core_registers_its_three_routes_in_a_fixed_order_without_being_asked():
    assert [route.id for route in routes.all()] == [OLLAMA, CLAUDE_CODE, ANTHROPIC_API]
    assert (OLLAMA, CLAUDE_CODE, ANTHROPIC_API) == ("ollama", "claude_code", "anthropic_api")
    assert isinstance(routes.get("ollama"), OllamaRoute) and isinstance(routes.get("claude_code"), ClaudeCodeRoute)
    assert isinstance(routes.get("anthropic_api"), AnthropicApiRoute) and routes.get("nothing") is None


def test_routes_are_local_or_cloud_by_their_own_word():
    assert [route.id for route in routes.on_side(True)] == [OLLAMA]
    assert [route.id for route in routes.on_side(False)] == [CLAUDE_CODE, ANTHROPIC_API]
    assert ai_profile.local_routes() == [OLLAMA] and ai_profile.cloud_routes() == [CLAUDE_CODE, ANTHROPIC_API]
    assert ai_profile.services() == {OLLAMA: "Ollama", CLAUDE_CODE: "Claude Code", ANTHROPIC_API: "Anthropic API"}


def test_a_duplicate_id_is_refused_and_registering_the_builtins_again_changes_nothing(fake_route):
    with pytest.raises(ValueError, match="fake_local"):
        routes.register(FakeRoute())
    with pytest.raises(ValueError, match="ollama"):
        routes.register(OllamaRoute())
    routes.register_builtin_routes()
    assert [route.id for route in routes.all()] == [OLLAMA, CLAUDE_CODE, ANTHROPIC_API, "fake_local"]


def test_clear_empties_the_registry_for_good_until_the_builtins_are_asked_for(monkeypatch):
    monkeypatch.setattr(routes, "_routes", dict(routes._routes))
    monkeypatch.setattr(routes, "_builtins_done", True)
    routes.clear()
    assert routes.all() == [] and routes.get(OLLAMA) is None
    routes.register_builtin_routes()
    assert len(routes.all()) == 3


def test_route_properties_come_from_the_registry():
    assert plugin_api._route_lookup is routes.get
    assert Route(OLLAMA, CHAT, "m").is_local and not Route(CLAUDE_CODE, CHAT).is_local
    assert Route("unknown", CHAT, "m").name == "unknown" and not Route("unknown", CHAT).is_local


# -- the three routes ---------------------------------------------------------------------

def test_the_names_and_labels_of_the_three_routes(ctx):
    ai_profile.set_model_choice(ctx, OLLAMA, TRANSLATION, "translategemma:12b")
    ai_profile.set_model_choice(ctx, CLAUDE_CODE, TRANSLATION, "haiku:medium")
    ai_profile.set_model_choice(ctx, ANTHROPIC_API, TRANSLATION, "claude-sonnet-5-5")
    found = [ai_profile.route_for(ctx, route.id, TRANSLATION) for route in routes.all()]
    assert [r.name for r in found] == ["Local · Ollama", "Cloud · Claude Code", "Cloud · Anthropic API"]
    assert [r.label for r in found] == ["translategemma:12b · Ollama", "Claude Code · Haiku · effort medium",
                                        "claude-sonnet-5-5 · API"]
    assert ai_profile.route_for(ctx, CLAUDE_CODE, CHAT).label == "Claude Code · terminal"


def test_the_problems_of_the_three_routes(ctx, monkeypatch):
    assert "Choose an Ollama model for fixes, notes, transcripts" in resolver.problem(ctx, Route(OLLAMA, FIXES))
    assert resolver.problem(ctx, Route(OLLAMA, FIXES, "m")) == ""
    assert resolver.problem(ctx, Route(ANTHROPIC_API, CHAT, "m")) == NO_KEY
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert resolver.problem(ctx, Route(ANTHROPIC_API, CHAT, "m")) == ""
    assert resolver.problem(ctx, Route(CLAUDE_CODE, CHAT)) == CHAT_IN_TERMINAL
    assert resolver.problem(ctx, Route(CLAUDE_CODE, TRANSLATION, "haiku", "low")) == ""


def test_task_refusal_reports_unsupported_tasks_before_model_setup(ctx, fake_route, monkeypatch):
    from slidemage.ai import tasks
    from slidemage.ui.workspace.task_bubbles import TaskRunner

    runner = SimpleNamespace(_window=SimpleNamespace(project=ctx))
    refusal = lambda task, route: TaskRunner.refusal(runner, task, route)  # noqa: E731
    assert "not available on Local · Ollama" in refusal(tasks.FIX_LATEX, Route(OLLAMA, FIXES))
    assert "Choose an Ollama model for translation" in refusal(tasks.TRANSLATE, Route(OLLAMA, TRANSLATION))
    assert "not installed" in refusal(tasks.FIX_LATEX, Route("missing", FIXES))

    fake_route.blocked = "Fake route needs setup."
    monkeypatch.setattr(fake_route, "task_runner", lambda ctx, route: lambda *args: None)
    assert refusal(tasks.FIX_LATEX, Route(fake_route.id, FIXES)) == fake_route.blocked


def test_the_model_choices_of_the_three_routes(ctx, monkeypatch):
    assert ai_profile.model_choices(ctx, OLLAMA, CHAT) == []                       # the server lists them, not the registry
    assert ai_profile.model_choices(ctx, ANTHROPIC_API, CHAT) == []                # no key
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert ai_profile.model_choices(ctx, ANTHROPIC_API, CHAT)[0] == "claude-sonnet-5-5"
    choices = ai_profile.model_choices(ctx, CLAUDE_CODE, CHAT)
    assert len(choices) == 9 and "haiku:medium" in choices
    assert ai_profile.model_choices(ctx, "unknown", CHAT) == []
    assert [ai_profile.default_choice(r, TRANSLATION) for r in (OLLAMA, CLAUDE_CODE, ANTHROPIC_API)] == [
        "", "haiku:medium", "claude-sonnet-5-5"]
    assert ai_profile.default_choice(CLAUDE_CODE, CHAT) == ""
    assert ai_profile.choice_label(CLAUDE_CODE, "sonnet:medium") == "Sonnet · medium"
    assert ai_profile.choice_label(OLLAMA, "qwen3:8b") == "qwen3:8b"


def test_a_claude_code_choice_it_does_not_offer_is_no_choice(ctx):
    assert ai_profile.route_for(ctx, CLAUDE_CODE, TRANSLATION, "qwen3:8b") == Route(CLAUDE_CODE, TRANSLATION, "haiku", "medium")
    assert ai_profile.route_for(ctx, CLAUDE_CODE, TRANSLATION, "opus:high") == Route(CLAUDE_CODE, TRANSLATION, "opus", "high")
    assert ai_profile.route_for(ctx, OLLAMA, TRANSLATION, "qwen3:8b") == Route(OLLAMA, TRANSLATION, "qwen3:8b")


def test_the_routes_make_the_providers_and_backends_they_always_made(ctx, monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    claude = tmp_path / "claude"
    monkeypatch.setattr(claude_launch, "find_claude", lambda: claude)
    ollama, api, code = routes.get(OLLAMA), routes.get(ANTHROPIC_API), routes.get(CLAUDE_CODE)
    oc, ac, cc = (routes.context(ctx, r.id) for r in (ollama, api, code))
    assert isinstance(ollama.provider(oc, Route(OLLAMA, CHAT, "m")), OllamaProvider)
    assert api.provider(ac, Route(ANTHROPIC_API, CHAT, "m")).model == "m"
    assert code.provider(cc, Route(CLAUDE_CODE, CHAT)) is None
    assert ollama.slide_translator(oc, Route(OLLAMA, TRANSLATION, "m")) is None and ollama.task_runner(oc, Route(OLLAMA, FIXES, "m")) is None
    assert ollama.draft_backend(oc, Route(OLLAMA, IMAGE_DESCRIPTION, "m")) is None and api.translation_backend(ac, Route(ANTHROPIC_API, TRANSLATION, "m")) is None
    assert ollama.chat_surface() is None and api.chat_surface() is None
    stop = threading.Event()
    backend = code.draft_backend(cc, Route(CLAUDE_CODE, IMAGE_DESCRIPTION, "haiku", "low"), stop)
    assert backend.cancel is stop and backend.claude == claude
    assert callable(code.task_runner(cc, Route(CLAUDE_CODE, FIXES, "haiku", "low")))
    assert code.slide_translator(cc, Route(CLAUDE_CODE, TRANSLATION, "haiku", "low")).effort == "low"


def test_the_old_import_path_of_the_ollama_provider_still_works():
    from slidemage.ai import ollama_route, providers
    assert providers.OllamaProvider is ollama_route.OllamaProvider
    assert providers.InstalledModel is ollama_route.InstalledModel
    with pytest.raises(AttributeError):
        providers.NoSuchThing  # noqa: B018


# -- a fourth route -----------------------------------------------------------------------

def test_a_route_a_plugin_registers_is_resolved_like_the_builtin_ones(ctx, fake_route):
    assert ai_profile.local_routes() == [OLLAMA, "fake_local"]
    ai_profile.set_cloud_conn(ctx, ANTHROPIC_API)
    assert ai_profile.model_choice(ctx, "fake_local", CHAT) == "tiny"                  # its own default
    ai_profile.set_model_choice(ctx, "fake_local", CHAT, "big")
    assert ai_profile.model_choice(ctx, "fake_local", CHAT) == "big"
    ai_profile.set_model_choice(ctx, "fake_local", CHAT, "stale")                      # one it does not offer is ignored
    assert ai_profile.model_choice(ctx, "fake_local", CHAT) == "tiny"
    route = ai_profile.route_for(ctx, "fake_local", CHAT, "big")
    assert route == Route("fake_local", CHAT, "big") and route.is_local
    assert route.name == "Local · Fake" and route.label == "big via Fake"
    assert isinstance(resolver.provider_for(ctx, route), FakeProvider)
    assert isinstance(resolver.draft_backend(ctx, route), alt_draft.ModelBackend)            # no backend of its own:
    assert isinstance(resolver.translation_backend(ctx, route), alt_draft.ModelTranslationBackend)   # the provider's
    assert isinstance(resolver.slide_translator(ctx, route), FakeProvider)             # no translator of its own: the provider


def test_a_plugin_route_on_the_cloud_side_can_be_the_cloud_connection(ctx, fake_route, monkeypatch):
    fake_route.is_local = False
    ai_profile.set_cloud_conn(ctx, "fake_local")
    ai_profile.set_mode(ctx, CLOUD)
    assert ai_profile.cloud_conn(ctx) == "fake_local" and ai_profile.resolve(ctx, CHAT) == Route("fake_local", CHAT, "tiny")
    assert app_settings.get(ctx, ai_profile.CONNECTION_KEY) == "fake_local"
    monkeypatch.setattr(routes, "_routes", {r.id: r for r in routes.all() if r.id != "fake_local"})
    assert ai_profile.cloud_conn(ctx) == CLAUDE_CODE                                   # its plugin is gone: the default again


def test_the_problem_of_a_route_stops_the_request_and_nothing_takes_its_place(ctx, fake_route):
    fake_route.blocked = "Fake is asleep."
    route = Route("fake_local", CHAT, "tiny")
    for make in (resolver.provider_for, resolver.draft_backend, resolver.translation_backend, resolver.slide_translator):
        with pytest.raises(RouteUnavailable, match="Fake is asleep"):
            make(ctx, route)


def test_a_route_that_is_not_registered_is_an_error_not_a_swap(ctx):
    gone = Route("removed_plugin", CHAT, "m")
    for make in (resolver.provider_for, resolver.draft_backend, resolver.translation_backend, resolver.slide_translator):
        with pytest.raises(resolver.RouteUnavailable, match="removed_plugin"):
            make(ctx, gone)
    assert "not installed" in resolver.problem(ctx, gone)
    assert issubclass(RouteUnavailable, ProviderError)


def test_an_empty_local_side_resolves_to_no_route_instead_of_another(ctx, monkeypatch):
    monkeypatch.setattr(routes, "_routes", {r.id: r for r in routes.all() if not r.is_local})
    assert ai_profile.mode(ctx) == LOCAL and ai_profile.active_route(ctx) == ""
    with pytest.raises(RouteUnavailable):
        resolver.provider_for(ctx, ai_profile.resolve(ctx, CHAT))


# -- the stored ids of earlier versions ---------------------------------------------------------------

def test_stored_local_reads_as_ollama_and_api_as_anthropic_api_until_the_next_write(ctx):
    app_settings.set(ctx, ai_profile.MODELS_KEY, {"local": {TRANSLATION: "qwen3"}, "api": {TRANSLATION: "claude-opus-5-5"}})
    app_settings.set(ctx, ai_profile.CONNECTION_KEY, "api")
    assert ai_profile.model_choice(ctx, OLLAMA, TRANSLATION) == "qwen3"
    assert ai_profile.model_choice(ctx, ANTHROPIC_API, TRANSLATION) == "claude-opus-5-5"
    assert ai_profile.model_choice(ctx, "local", TRANSLATION) == "qwen3"           # an old id asked for is the new one
    assert ai_profile.cloud_conn(ctx) == ANTHROPIC_API
    assert app_settings.get(ctx, ai_profile.MODELS_KEY) == {"local": {TRANSLATION: "qwen3"},
                                                           "api": {TRANSLATION: "claude-opus-5-5"}}     # reading wrote nothing
    ai_profile.set_model_choice(ctx, OLLAMA, CHAT, "m")
    assert app_settings.get(ctx, ai_profile.MODELS_KEY) == {OLLAMA: {TRANSLATION: "qwen3", CHAT: "m"},
                                                           ANTHROPIC_API: {TRANSLATION: "claude-opus-5-5"}}


def test_the_cloud_connection_is_written_with_the_new_id(ctx):
    ai_profile.set_cloud_conn(ctx, "api")
    assert app_settings.get(ctx, ai_profile.CONNECTION_KEY) == "anthropic_api"
    with pytest.raises(ValueError):
        ai_profile.set_cloud_conn(ctx, "local")                                        # Ollama is not a cloud route
    with pytest.raises(ValueError):
        ai_profile.set_cloud_conn(ctx, "nonsense")


def test_ollama_choices_use_only_the_background_cache(ctx, monkeypatch):
    from slidemage.ai import ollama_route

    ollama_route._installed.clear()
    monkeypatch.setattr(OllamaProvider, 'installed', lambda *args, **kwargs: pytest.fail('network listing'))
    ollama_route.cache_installed(ctx, [
        ollama_route.InstalledModel('chat', 1, '', ('tools',)),
        ollama_route.InstalledModel('vision', 1, '', ('vision',)),
    ])
    assert ai_profile.model_choices(ctx, OLLAMA, CHAT) == ['chat']
    assert ai_profile.model_choices(ctx, OLLAMA, IMAGE_DESCRIPTION) == ['vision']
    assert ai_profile.model_choices(ctx, OLLAMA, TRANSLATION) == ['chat', 'vision']


def test_route_calls_receive_a_public_project_context(ctx, fake_route, monkeypatch):
    seen = []

    def capture(context, *args):
        seen.append(context)
        return ["tiny"] if args and args[0] == CHAT else ""

    monkeypatch.setattr(fake_route, "model_choices", capture)
    monkeypatch.setattr(fake_route, "valid_choice", lambda context, choice: seen.append(context) or True)
    monkeypatch.setattr(fake_route, "problem", capture)
    ai_profile.model_choices(ctx, fake_route.id, CHAT)
    ai_profile.route_for(ctx, fake_route.id, CHAT, "tiny")
    resolver.problem(ctx, Route(fake_route.id, FIXES, "tiny"))
    assert len(seen) >= 3
    assert all(isinstance(context, plugin_api.RouteContext) and context.root == ctx.root for context in seen)
    assert all(not hasattr(context, "slides_dir") for context in seen)


def test_route_context_uses_plugin_namespace_and_current_project(ctx, tmp_path, monkeypatch):
    from slidemage import project
    from slidemage.ai import translation_style
    from slidemage.plugins.host import PluginHost
    from slidemage.plugins.manifest import read_manifest
    from slidemage.project import ProjectContext

    monkeypatch.setattr(routes, "_routes", dict(routes._routes))
    monkeypatch.setattr(routes, "_owners", dict(routes._owners))
    monkeypatch.setattr(project, "config_dir", lambda: tmp_path / "config")
    monkeypatch.setattr(project, "cache_dir", lambda: tmp_path / "cache")
    manifest = read_manifest(Path(__file__).parent / "fixtures" / "plugins" / "hello")
    host = PluginHost(manifest, ctx)
    route = FakeRoute()
    routes.register(route, host)
    other = ProjectContext.at(tmp_path / "other")
    other.root.mkdir()
    translation_style.set_de_address(other, "du")
    (other.root / ".slidemage" / "glossary.md").write_text("hello = hallo", encoding="utf-8")
    context = routes.context(other, route.id)
    assert context.root == other.root and context.de_address == "du" and context.glossary == "hello = hallo"
    assert context.settings is host.settings()
    context.settings.set("value", 3)
    assert host.settings().get("value") == 3
    assert context.cache_dir == tmp_path / "cache" / "plugins" / "hello"
    assert context.credentials(None).plugin_id == "hello"
    with pytest.raises(ValueError):
        context.legacy_secret("unknown")
