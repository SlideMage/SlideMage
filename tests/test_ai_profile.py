# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Project AI policy, stored model choices and resolution through fake routes."""
import dataclasses

import pytest

from slidemage import app_settings, project
from slidemage.ai import ai_profile
from slidemage.ai.ai_profile import ANTHROPIC_API, CHAT, CLOUD, FIXES, IMAGE_DESCRIPTION, LOCAL, OLLAMA, TRANSLATION


def test_the_mode_starts_from_the_policy_and_then_only_set_mode_changes_it(ctx):
    project.write_project_json(ctx.root, {"format": 1, "compat": {"x": 1}})
    ai_profile.set_policy(ctx, CLOUD)
    assert ai_profile.mode(ctx) == CLOUD
    data = project.read_project_json(ctx.root)
    assert data["ai"] == {"policy": "cloud"} and data["compat"] == {"x": 1}
    other = project.ProjectContext.at(ctx.root / "other")
    assert ai_profile.mode(other) == LOCAL and ai_profile.active_route(other) == ""
    ai_profile.set_policy(ctx, LOCAL)
    assert ai_profile.mode(ctx) == CLOUD
    ai_profile.set_mode(ctx, LOCAL)
    assert ai_profile.mode(ctx) == LOCAL and ai_profile.policy(ctx) == LOCAL
    with pytest.raises(ValueError):
        ai_profile.set_mode(ctx, "both")


def test_the_first_use_flag_replaces_cloud_consent(ctx):
    app_settings.set(ctx, "cloud_consent", True)                                # as the earlier version left it
    assert ai_profile.cloud_seen(ctx)
    ai_profile.mark_cloud_seen(ctx)
    settings = app_settings.load(ctx)
    assert settings["cloud_seen"] is True and "cloud_consent" not in settings


def test_the_first_save_moves_the_earlier_models_into_the_new_place(ctx):
    app_settings.save(ctx, {"drafting_model": "qwen3:8b", "translation_model": "ollama:mt",
                            "syntax_check_model": "anthropic:opus", "chat_model": "anthropic:claude-opus-5-5",
                            "dark": True})
    assert ai_profile.model_choice(ctx, OLLAMA, IMAGE_DESCRIPTION) == "qwen3:8b"
    assert ai_profile.model_choice(ctx, ANTHROPIC_API, CHAT) == "claude-opus-5-5"
    assert ai_profile.model_choice(ctx, OLLAMA, TRANSLATION) == "mt"
    assert ai_profile.model_choice(ctx, ANTHROPIC_API, FIXES) == "opus"
    assert ai_profile.model_choice(ctx, OLLAMA, CHAT) == ""
    assert app_settings.get(ctx, "drafting_model") == "qwen3:8b"
    ai_profile.set_model_choice(ctx, OLLAMA, TRANSLATION, "x")
    settings = app_settings.load(ctx)
    assert settings["ai_models"] == {OLLAMA: {IMAGE_DESCRIPTION: "qwen3:8b", TRANSLATION: "x"},
                                     ANTHROPIC_API: {CHAT: "claude-opus-5-5", FIXES: "opus"}}
    assert "drafting_model" not in settings and "chat_model" not in settings and settings["dark"] is True


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


def test_each_route_keeps_its_own_model_and_a_pick_is_per_request(ctx, fake_routes):
    ai_profile.set_model_choice(ctx, "fake_local", TRANSLATION, "fake-2")
    ai_profile.set_model_choice(ctx, "fake_cloud", TRANSLATION, "fake-1")
    before = ai_profile.resolve(ctx, TRANSLATION)
    assert before.model == "fake-2"
    assert ai_profile.resolve(ctx, TRANSLATION, "fake-1").model == "fake-1"
    assert ai_profile.resolve(ctx, TRANSLATION, "invalid").model == "fake-2"
    ai_profile.set_mode(ctx, CLOUD)
    assert ai_profile.resolve(ctx, TRANSLATION).route == "fake_cloud"
    assert not ai_profile.resolve(ctx, TRANSLATION).is_local and before.is_local
    assert before.route == "fake_local" and before.model == "fake-2"
    with pytest.raises(dataclasses.FrozenInstanceError):
        before.model = "changed"
