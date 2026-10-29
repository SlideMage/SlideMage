# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The registry and resolver over plugin-provided routes."""
from pathlib import Path

import pytest

from fake_routes import FakeProvider, FakeRoute
from slidemage import alt_draft, app_settings, plugin_api
from slidemage.ai import ai_profile, resolver, routes
from slidemage.ai.ai_profile import CHAT, CLOUD, FIXES, LOCAL, TRANSLATION, Route
from slidemage.ai.providers import RouteUnavailable


@pytest.fixture
def fake_route(fake_routes):
    return fake_routes.local


def test_registry_starts_empty():
    assert routes.all() == [] and routes.get("missing") is None


def test_registry_sides_and_duplicate_ids(fake_routes):
    assert routes.on_side(True) == [fake_routes.local]
    assert routes.on_side(False) == [fake_routes.cloud]
    assert ai_profile.services() == {"fake_local": "Fake local", "fake_cloud": "Fake cloud"}
    with pytest.raises(ValueError, match="fake_local"):
        routes.register(FakeRoute(is_local=True, id="fake_local"))
    routes.clear()
    assert routes.all() == [] and routes.get("fake_local") is None


def test_route_properties_come_from_registry(fake_routes):
    assert plugin_api._route_lookup is routes.get
    assert Route("fake_local", CHAT, "fake-1").is_local
    assert not Route("fake_cloud", CHAT, "fake-1").is_local
    assert Route("unknown", CHAT, "m").name == "unknown"


def test_route_choices_and_provider_backends(ctx, fake_routes):
    assert ai_profile.model_choice(ctx, "fake_local", CHAT) == "fake-1"
    ai_profile.set_model_choice(ctx, "fake_local", CHAT, "fake-2")
    assert ai_profile.model_choice(ctx, "fake_local", CHAT) == "fake-2"
    ai_profile.set_model_choice(ctx, "fake_local", CHAT, "stale")
    assert ai_profile.model_choice(ctx, "fake_local", CHAT) == "fake-1"
    route = ai_profile.route_for(ctx, "fake_local", CHAT, "fake-2")
    assert route == Route("fake_local", CHAT, "fake-2") and route.is_local
    assert route.name == "Local · Fake local" and route.label == "fake-2"
    assert isinstance(resolver.provider_for(ctx, route), FakeProvider)
    assert isinstance(resolver.draft_backend(ctx, route), alt_draft.ModelBackend)
    assert isinstance(resolver.translation_backend(ctx, route), alt_draft.ModelTranslationBackend)
    assert isinstance(resolver.slide_translator(ctx, route), FakeProvider)


def test_cloud_connection_and_removed_route(ctx, fake_routes):
    ai_profile.set_cloud_conn(ctx, "fake_cloud")
    ai_profile.set_mode(ctx, CLOUD)
    assert ai_profile.resolve(ctx, CHAT) == Route("fake_cloud", CHAT, "fake-1")
    assert app_settings.get(ctx, ai_profile.CONNECTION_KEY) == "fake_cloud"
    routes.clear()
    with pytest.raises(RouteUnavailable, match="not installed"):
        resolver.provider_for(ctx, ai_profile.resolve(ctx, CHAT))


def test_problem_is_never_replaced_by_another_route(ctx, fake_routes):
    fake_routes.local.problem_text = "Fake is asleep."
    route = Route("fake_local", CHAT, "fake-1")
    for make in (resolver.provider_for, resolver.draft_backend, resolver.translation_backend, resolver.slide_translator):
        with pytest.raises(RouteUnavailable, match="Fake is asleep"):
            make(ctx, route)


def test_empty_local_side_never_falls_back_to_cloud(ctx, fake_routes):
    routes.clear()
    routes.register(fake_routes.cloud)
    assert ai_profile.mode(ctx) == LOCAL and ai_profile.active_route(ctx) == ""
    with pytest.raises(RouteUnavailable):
        resolver.provider_for(ctx, ai_profile.resolve(ctx, CHAT))


def test_legacy_model_ids_read_and_migrate_without_routes(ctx):
    app_settings.set(ctx, ai_profile.MODELS_KEY, {"local": {TRANSLATION: "old"}, "api": {TRANSLATION: "remote"}})
    assert ai_profile.model_choice(ctx, "ollama", TRANSLATION) == "old"
    assert ai_profile.model_choice(ctx, "anthropic_api", TRANSLATION) == "remote"
    ai_profile.set_model_choice(ctx, "ollama", CHAT, "new")
    assert app_settings.get(ctx, ai_profile.MODELS_KEY) == {"ollama": {TRANSLATION: "old", CHAT: "new"},
                                                         "anthropic_api": {TRANSLATION: "remote"}}


def test_route_calls_receive_a_public_project_context(ctx, fake_route, monkeypatch):
    seen = []

    def capture(context, *args):
        seen.append(context)
        return ["fake-1"] if args and args[0] == CHAT else ""

    monkeypatch.setattr(fake_route, "model_choices", capture)
    monkeypatch.setattr(fake_route, "valid_choice", lambda context, choice: seen.append(context) or True)
    monkeypatch.setattr(fake_route, "problem", capture)
    ai_profile.model_choices(ctx, fake_route.id, CHAT)
    ai_profile.route_for(ctx, fake_route.id, CHAT, "fake-1")
    resolver.problem(ctx, Route(fake_route.id, FIXES, "fake-1"))
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


def test_task_refusal_checks_support_and_route_problem(ctx, fake_routes):
    from types import SimpleNamespace

    from slidemage.ai import tasks
    from slidemage.ui.workspace.task_bubbles import TaskRunner

    runner = SimpleNamespace(_window=SimpleNamespace(project=ctx))
    route = Route("fake_local", FIXES, "fake-1")
    assert "not available on Local · Fake local" in TaskRunner.refusal(runner, tasks.FIX_LATEX, route)
    assert "not installed" in TaskRunner.refusal(runner, tasks.FIX_LATEX, Route("missing", FIXES))
    fake_routes.local.runner = lambda *args: None
    fake_routes.local.problem_text = "Fake route needs setup."
    assert TaskRunner.refusal(runner, tasks.FIX_LATEX, route) == "Fake route needs setup."


def test_legacy_cloud_alias_is_read_and_saved_for_a_registered_route(ctx):
    cloud = FakeRoute(id="anthropic_api")
    routes.register(cloud)
    app_settings.set(ctx, ai_profile.CONNECTION_KEY, "api")
    assert ai_profile.cloud_conn(ctx) == "anthropic_api"
    ai_profile.set_cloud_conn(ctx, "api")
    assert app_settings.get(ctx, ai_profile.CONNECTION_KEY) == "anthropic_api"
    with pytest.raises(ValueError):
        ai_profile.set_cloud_conn(ctx, "local")


def test_fake_route_can_script_provider_runner_and_surface(ctx, fake_routes):
    fake = fake_routes.local
    fake.reply = "scripted"
    fake.runner = lambda *args: "task result"
    fake.surface_factory = lambda *args, **kwargs: "surface"
    route = Route(fake.id, CHAT, "fake-1")
    provider = resolver.provider_for(ctx, route)
    assert provider.chat([{"role": "user", "content": "hello"}]).text == "scripted"
    assert provider.requests[0][0] == [{"role": "user", "content": "hello"}]
    assert fake.task_runner(routes.context(ctx, fake.id), route)() == "task result"
    assert fake.chat_surface() == "surface"
