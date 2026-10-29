# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Project AI policy, stored model choices and resolution through fake routes."""
import dataclasses

import pytest

from slidemage import app_settings, project
from slidemage.ai import ai_profile, resolver
from slidemage.ai.ai_profile import ANTHROPIC_API, CHAT, CLOUD, FIXES, IMAGE_DESCRIPTION, LOCAL, OLLAMA, TRANSLATION, Route
from slidemage.ai.providers import RouteUnavailable


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


def test_the_first_use_flag_replaces_cloud_consent(ctx):
    app_settings.set(ctx, "cloud_consent", True)                                # as the earlier version left it
    assert ai_profile.cloud_seen(ctx)
    ai_profile.mark_cloud_seen(ctx)
    settings = app_settings.load(ctx)
    assert settings["cloud_seen"] is True and "cloud_consent" not in settings


def test_marking_the_first_use_needs_no_earlier_flag(ctx):
    ai_profile.mark_cloud_seen(ctx)
    assert ai_profile.cloud_seen(ctx)


def test_the_models_of_the_earlier_version_read_as_local_and_api_models(ctx):
    app_settings.save(ctx, {"drafting_model": "qwen3:8b",                       # a bare name is an Ollama model
                            "translation_model": "ollama:sun_leaf/HY-MT:7b",
                            "syntax_check_model": "anthropic:claude-opus-5-5",
                            "chat_model": "anthropic:claude-haiku-4-5-20251001"})
    assert ai_profile.model_choice(ctx, OLLAMA, IMAGE_DESCRIPTION) == "qwen3:8b"
    assert ai_profile.model_choice(ctx, OLLAMA, TRANSLATION) == "sun_leaf/HY-MT:7b"
    assert ai_profile.model_choice(ctx, OLLAMA, FIXES) == "" and ai_profile.model_choice(ctx, ANTHROPIC_API, FIXES) == "claude-opus-5-5"
    assert ai_profile.model_choice(ctx, ANTHROPIC_API, CHAT) == "claude-haiku-4-5-20251001"
    assert ai_profile.model_choice(ctx, OLLAMA, CHAT) == ""
    assert app_settings.get(ctx, "drafting_model") == "qwen3:8b"                # reading rewrites nothing


def test_the_first_save_moves_the_earlier_models_into_the_new_place(ctx):
    app_settings.save(ctx, {"drafting_model": "qwen3:8b", "chat_model": "anthropic:claude-opus-5-5", "dark": True})
    ai_profile.set_model_choice(ctx, OLLAMA, TRANSLATION, "x")
    settings = app_settings.load(ctx)
    assert settings["ai_models"] == {OLLAMA: {IMAGE_DESCRIPTION: "qwen3:8b", TRANSLATION: "x"},
                                     ANTHROPIC_API: {CHAT: "claude-opus-5-5"}}
    assert "drafting_model" not in settings and "chat_model" not in settings and settings["dark"] is True


def test_a_fresh_project_has_no_active_route(ctx):
    assert ai_profile.policy(ctx) == LOCAL and ai_profile.mode(ctx) == LOCAL
    assert ai_profile.active_route(ctx) == "" and not ai_profile.cloud_seen(ctx)


def test_registered_routes_supply_defaults_and_choices(ctx, fake_routes):
    for task in ai_profile.TASKS:
        assert ai_profile.model_choice(ctx, fake_routes.local.id, task) == "fake-1"
        assert ai_profile.model_choices(ctx, fake_routes.cloud.id, task) == ["fake-1", "fake-2"]
    fake_routes.local.choices.clear()
    assert ai_profile.model_choice(ctx, fake_routes.local.id, CHAT) == ""


def test_cloud_connection_is_saved_and_must_be_registered(ctx, fake_routes):
    ai_profile.set_cloud_conn(ctx, fake_routes.cloud.id)
    assert ai_profile.cloud_conn(ctx) == fake_routes.cloud.id
    assert app_settings.get(ctx, "cloud_conn") == fake_routes.cloud.id
    with pytest.raises(ValueError):
        ai_profile.set_cloud_conn(ctx, fake_routes.local.id)


@pytest.mark.parametrize("mode, route_id", [(LOCAL, "fake_local"), (CLOUD, "fake_cloud")])
@pytest.mark.parametrize("task", ai_profile.TASKS)
def test_resolve_follows_mode_for_every_task(ctx, fake_routes, mode, route_id, task):
    ai_profile.set_mode(ctx, mode)
    resolved = ai_profile.resolve(ctx, task)
    assert resolved == Route(route_id, task, "fake-1")
    assert resolved.is_local is (mode == LOCAL)


def test_each_route_keeps_its_own_model_and_a_pick_is_per_request(ctx, fake_routes):
    ai_profile.set_model_choice(ctx, "fake_local", TRANSLATION, "fake-2")
    ai_profile.set_model_choice(ctx, "fake_cloud", TRANSLATION, "fake-1")
    before = ai_profile.resolve(ctx, TRANSLATION)
    assert before.model == "fake-2"
    assert ai_profile.resolve(ctx, TRANSLATION, "fake-1").model == "fake-1"
    assert ai_profile.resolve(ctx, TRANSLATION, "invalid").model == "fake-2"
    ai_profile.set_mode(ctx, CLOUD)
    assert ai_profile.resolve(ctx, TRANSLATION).route == "fake_cloud"
    assert before.route == "fake_local" and before.model == "fake-2"
    with pytest.raises(dataclasses.FrozenInstanceError):
        before.model = "changed"


def test_unavailable_route_is_not_replaced(ctx, fake_routes):
    fake_routes.local.problem_text = "Local route is unavailable"
    with pytest.raises(RouteUnavailable, match="Local route is unavailable"):
        resolver.provider_for(ctx, ai_profile.resolve(ctx, TRANSLATION))
    assert not fake_routes.cloud.providers
