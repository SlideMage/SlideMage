# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The one AI resolver (ai_profile.resolve) and the state it reads: the session's mode, the cloud connection,
the project's policy, the first-use flag and the models of each route, with the migration of the settings of
the earlier version; and what ai/resolver.py makes of a Route, never another route or model than the one named."""
from __future__ import annotations

import dataclasses

import pytest

from slidemage import alt_draft, app_settings, project
from slidemage.ai import ai_profile, claude_images, claude_launch, resolver
from slidemage.ai.ai_profile import API, CHAT, CLAUDE_CODE, CLOUD, FIXES, IMAGE_DESCRIPTION, LOCAL, TRANSLATION, Route
from slidemage.ai.providers import AnthropicProvider, OllamaProvider


# -- defaults ----------------------------------------------------------------------------

def test_a_fresh_project_is_local_with_claude_code_as_its_cloud(ctx):
    assert ai_profile.policy(ctx) == LOCAL and ai_profile.mode(ctx) == LOCAL
    assert ai_profile.cloud_conn(ctx) == CLAUDE_CODE and not ai_profile.cloud_seen(ctx)
    assert ai_profile.active_route(ctx) == LOCAL


def test_default_models_of_each_route(ctx):
    for task in ai_profile.TASKS:
        assert ai_profile.model_choice(ctx, LOCAL, task) == ""                       # the pickers offer what is installed
        assert ai_profile.model_choice(ctx, API, task) == "claude-sonnet-5-5"
    assert ai_profile.model_choice(ctx, CLAUDE_CODE, CHAT) == ""                     # its chat is the terminal's own model
    for task in (IMAGE_DESCRIPTION, TRANSLATION, FIXES):
        assert ai_profile.model_choice(ctx, CLAUDE_CODE, task) == "haiku:medium"


# -- the session's mode and the project's policy ---------------------------------------------

def test_the_mode_starts_from_the_policy_and_then_only_set_mode_changes_it(ctx):
    ai_profile.set_policy(ctx, CLOUD)
    assert ai_profile.mode(ctx) == CLOUD                       # the project opens on its side
    ai_profile.set_policy(ctx, LOCAL)
    assert ai_profile.mode(ctx) == CLOUD                       # a default, not a lock: the session keeps its choice
    ai_profile.set_mode(ctx, LOCAL)
    assert ai_profile.mode(ctx) == LOCAL and ai_profile.policy(ctx) == LOCAL
    with pytest.raises(ValueError):
        ai_profile.set_mode(ctx, "both")


def test_the_session_is_per_project(tmp_path):
    one, two = (project.ProjectContext.at(tmp_path / name) for name in "ab")
    ai_profile.set_mode(one, CLOUD)
    assert ai_profile.mode(two) == LOCAL


def test_the_policy_lives_in_project_json_next_to_the_other_keys(ctx):
    project.write_project_json(ctx.root, {"format": 1, "compat": {"x": 1}})
    ai_profile.set_policy(ctx, CLOUD)
    data = project.read_project_json(ctx.root)
    assert data["ai"] == {"policy": "cloud"} and data["compat"] == {"x": 1} and ai_profile.policy(ctx) == CLOUD


@pytest.mark.parametrize("stored, expected", [({"local_only": True}, LOCAL), ({"local_only": False}, CLOUD),
                                              ({}, LOCAL), ({"policy": "cloud", "local_only": True}, CLOUD),
                                              ({"policy": "nonsense"}, LOCAL), ("garbage", LOCAL)])
def test_an_older_local_only_override_reads_as_the_policy(ctx, stored, expected):
    project.write_project_json(ctx.root, {"ai": stored})
    assert ai_profile.policy(ctx) == expected


def test_setting_the_policy_replaces_the_older_override(ctx):
    project.write_project_json(ctx.root, {"ai": {"local_only": False}})
    ai_profile.set_policy(ctx, LOCAL)
    assert project.read_project_json(ctx.root)["ai"] == {"policy": "local"}


# -- the cloud connection and the first use -----------------------------------------------------

def test_the_cloud_connection_is_saved_in_the_app_settings(ctx):
    ai_profile.set_cloud_conn(ctx, API)
    assert ai_profile.cloud_conn(ctx) == API and app_settings.get(ctx, "cloud_conn") == "api"
    assert "cloud_conn" not in project.read_project_json(ctx.root)           # personal: not tracked with the project
    app_settings.set(ctx, "cloud_conn", "carrier pigeon")
    assert ai_profile.cloud_conn(ctx) == CLAUDE_CODE
    with pytest.raises(ValueError):
        ai_profile.set_cloud_conn(ctx, LOCAL)


def test_the_first_use_flag_replaces_cloud_consent(ctx):
    app_settings.set(ctx, "cloud_consent", True)                                # as the earlier version left it
    assert ai_profile.cloud_seen(ctx)
    ai_profile.mark_cloud_seen(ctx)
    settings = app_settings.load(ctx)
    assert settings["cloud_seen"] is True and "cloud_consent" not in settings


def test_marking_the_first_use_needs_no_earlier_flag(ctx):
    ai_profile.mark_cloud_seen(ctx)
    assert ai_profile.cloud_seen(ctx)


# -- models per route and task, and the migration ---------------------------------------------------

def test_each_route_keeps_its_own_model_of_a_task(ctx):
    ai_profile.set_model_choice(ctx, LOCAL, TRANSLATION, "translategemma:12b")
    ai_profile.set_model_choice(ctx, API, TRANSLATION, "claude-opus-5-5")
    ai_profile.set_model_choice(ctx, CLAUDE_CODE, TRANSLATION, "haiku:high")
    assert [ai_profile.model_choice(ctx, route, TRANSLATION) for route in ai_profile.ROUTES] == [
        "translategemma:12b", "haiku:high", "claude-opus-5-5"]
    assert ai_profile.model_choice(ctx, LOCAL, IMAGE_DESCRIPTION) == ""        # other tasks are untouched
    ai_profile.set_model_choice(ctx, LOCAL, TRANSLATION, "")                   # "" goes back to the default
    assert ai_profile.model_choice(ctx, LOCAL, TRANSLATION) == ""


def test_a_claude_code_choice_must_be_one_of_its_models_and_efforts(ctx):
    app_settings.set(ctx, "ai_models", {CLAUDE_CODE: {TRANSLATION: "gpt-9:max", FIXES: "opus:low"}})
    assert ai_profile.model_choice(ctx, CLAUDE_CODE, TRANSLATION) == "haiku:medium"
    assert ai_profile.model_choice(ctx, CLAUDE_CODE, FIXES) == "opus:low"


def test_the_models_of_the_earlier_version_read_as_local_and_api_models(ctx):
    app_settings.save(ctx, {"drafting_model": "qwen3:8b",                       # a bare name is an Ollama model
                            "translation_model": "ollama:sun_leaf/HY-MT:7b",
                            "syntax_check_model": "anthropic:claude-opus-5-5",
                            "chat_model": "anthropic:claude-haiku-4-5-20251001"})
    assert ai_profile.model_choice(ctx, LOCAL, IMAGE_DESCRIPTION) == "qwen3:8b"
    assert ai_profile.model_choice(ctx, LOCAL, TRANSLATION) == "sun_leaf/HY-MT:7b"
    assert ai_profile.model_choice(ctx, LOCAL, FIXES) == "" and ai_profile.model_choice(ctx, API, FIXES) == "claude-opus-5-5"
    assert ai_profile.model_choice(ctx, API, CHAT) == "claude-haiku-4-5-20251001"
    assert ai_profile.model_choice(ctx, LOCAL, CHAT) == ""
    assert app_settings.get(ctx, "drafting_model") == "qwen3:8b"                # reading rewrites nothing


def test_the_first_save_moves_the_earlier_models_into_the_new_place(ctx):
    app_settings.save(ctx, {"drafting_model": "qwen3:8b", "chat_model": "anthropic:claude-opus-5-5", "dark": True})
    ai_profile.set_model_choice(ctx, LOCAL, TRANSLATION, "x")
    settings = app_settings.load(ctx)
    assert settings["ai_models"] == {LOCAL: {IMAGE_DESCRIPTION: "qwen3:8b", TRANSLATION: "x"},
                                     API: {CHAT: "claude-opus-5-5"}}
    assert "drafting_model" not in settings and "chat_model" not in settings and settings["dark"] is True


# -- the resolver ----------------------------------------------------------------------------

@pytest.mark.parametrize("mode, conn, route", [(LOCAL, CLAUDE_CODE, LOCAL), (LOCAL, API, LOCAL),
                                               (CLOUD, CLAUDE_CODE, CLAUDE_CODE), (CLOUD, API, API)])
@pytest.mark.parametrize("task", ai_profile.TASKS)
def test_resolve_follows_the_mode_and_the_connection_for_every_task(ctx, mode, conn, route, task):
    ai_profile.set_mode(ctx, mode)
    ai_profile.set_cloud_conn(ctx, conn)
    resolved = ai_profile.resolve(ctx, task)
    assert resolved.route == route and resolved.task == task
    assert resolved.model == ai_profile.route_for(ctx, route, task).model
    assert resolved.is_local is (route == LOCAL)
    assert (resolved.effort is not None) == (route == CLAUDE_CODE and task != CHAT)


def test_the_labels_name_the_model_and_the_service(ctx):
    ai_profile.set_model_choice(ctx, LOCAL, TRANSLATION, "translategemma:12b")
    ai_profile.set_model_choice(ctx, CLAUDE_CODE, TRANSLATION, "haiku:medium")
    ai_profile.set_model_choice(ctx, API, TRANSLATION, "claude-sonnet-4-5")
    labels = [ai_profile.route_for(ctx, route, TRANSLATION).label for route in ai_profile.ROUTES]
    assert labels == ["translategemma:12b · Ollama", "Claude Code · Haiku · effort medium", "claude-sonnet-4-5 · API"]
    assert ai_profile.route_for(ctx, LOCAL, CHAT).label == "no model chosen · Ollama"
    assert ai_profile.route_for(ctx, CLAUDE_CODE, CHAT).label == "Claude Code · terminal"
    assert [ai_profile.route_for(ctx, route, CHAT).name for route in ai_profile.ROUTES] == [
        "Local · Ollama", "Cloud · Claude Code", "Cloud · Anthropic API"]


def test_a_picker_choice_replaces_the_saved_one_for_that_request_only(ctx):
    ai_profile.set_model_choice(ctx, LOCAL, TRANSLATION, "a")
    assert ai_profile.resolve(ctx, TRANSLATION, "b").model == "b"
    assert ai_profile.resolve(ctx, TRANSLATION).model == "a"
    ai_profile.set_mode(ctx, CLOUD)
    assert ai_profile.resolve(ctx, TRANSLATION, "opus:low") == Route(CLAUDE_CODE, TRANSLATION, "opus", "low")


def test_a_pick_that_claude_code_does_not_offer_is_no_pick(ctx):
    ai_profile.set_mode(ctx, CLOUD)
    ai_profile.set_model_choice(ctx, CLAUDE_CODE, TRANSLATION, "haiku:high")
    assert ai_profile.resolve(ctx, TRANSLATION, "qwen3:8b") == Route(CLAUDE_CODE, TRANSLATION, "haiku", "high")


def test_a_route_keeps_what_it_was_resolved_with(ctx):
    ai_profile.set_model_choice(ctx, LOCAL, TRANSLATION, "a")
    before = ai_profile.resolve(ctx, TRANSLATION)
    ai_profile.set_mode(ctx, CLOUD)
    ai_profile.set_model_choice(ctx, LOCAL, TRANSLATION, "z")
    assert before.route == LOCAL and before.model == "a"           # the request under way
    assert ai_profile.resolve(ctx, TRANSLATION).route == CLAUDE_CODE
    with pytest.raises(dataclasses.FrozenInstanceError):
        before.model = "b"


# -- from a Route to something that runs, and never another route -------------------------------------

def test_local_and_api_routes_have_providers_of_their_own_kind(ctx, monkeypatch):
    local = resolver.provider_for(ctx, Route(LOCAL, CHAT, "qwen3:8b"))
    assert isinstance(local, OllamaProvider) and local.model == "qwen3:8b"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    cloud = resolver.provider_for(ctx, Route(API, CHAT, "claude-opus-5-5"))
    assert isinstance(cloud, AnthropicProvider) and cloud.model == "claude-opus-5-5"


def test_a_route_that_is_not_ready_says_so_and_nothing_takes_its_place(ctx):
    with pytest.raises(resolver.RouteUnavailable, match="Choose an Ollama model for translation"):
        resolver.provider_for(ctx, ai_profile.route_for(ctx, LOCAL, TRANSLATION))               # no model chosen
    with pytest.raises(resolver.RouteUnavailable, match="API key"):
        resolver.provider_for(ctx, ai_profile.route_for(ctx, API, TRANSLATION))                 # an Ollama model does not stand in
    with pytest.raises(resolver.RouteUnavailable, match="not available on Cloud · Claude Code"):
        resolver.provider_for(ctx, ai_profile.route_for(ctx, CLAUDE_CODE, TRANSLATION))         # neither does the API
    assert "terminal" in resolver.problem(ctx, ai_profile.route_for(ctx, CLAUDE_CODE, CHAT))
    assert resolver.problem(ctx, ai_profile.route_for(ctx, CLAUDE_CODE, TRANSLATION)) == ""


def test_the_image_backends_of_each_route(ctx, monkeypatch, tmp_path):
    claude = tmp_path / "claude"
    monkeypatch.setattr(claude_launch, "find_claude", lambda: claude)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    local = resolver.draft_backend(ctx, Route(LOCAL, IMAGE_DESCRIPTION, "qwen3-vl:32b"))
    assert isinstance(local, alt_draft.ModelBackend) and local.provider.is_local and local.label == "qwen3-vl:32b"
    cloud = resolver.draft_backend(ctx, Route(API, IMAGE_DESCRIPTION, "claude-sonnet-5-5"))
    assert isinstance(cloud, alt_draft.ModelBackend) and isinstance(cloud.provider, AnthropicProvider)
    code = resolver.draft_backend(ctx, Route(CLAUDE_CODE, IMAGE_DESCRIPTION, "haiku", "low"))
    assert isinstance(code, claude_images.ClaudeDraftBackend) and (code.model, code.effort, code.claude) == ("haiku", "low", claude)
    assert not code.provider.is_local and code.provider is code
    translating = resolver.translation_backend(ctx, Route(CLAUDE_CODE, TRANSLATION, "opus", "high"))
    assert isinstance(translating, claude_images.ClaudeTranslationBackend) and translating.effort == "high"
    assert isinstance(resolver.translation_backend(ctx, Route(LOCAL, TRANSLATION, "m")), alt_draft.ModelTranslationBackend)


def test_claude_code_that_is_not_installed_is_an_error_not_a_swap(ctx, monkeypatch):
    monkeypatch.setattr(claude_launch, "find_claude", lambda: None)
    for make in (resolver.draft_backend, resolver.translation_backend, resolver.slide_translator):
        with pytest.raises(resolver.RouteUnavailable, match="not installed"):
            make(ctx, Route(CLAUDE_CODE, TRANSLATION, "sonnet", "medium"))


def test_the_api_models_on_offer_need_a_key(ctx, monkeypatch):
    assert resolver.api_models(ctx) == []
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert resolver.api_models(ctx)[0] == "claude-sonnet-5-5"
