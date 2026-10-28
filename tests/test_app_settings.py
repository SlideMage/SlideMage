# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The AI settings of this machine live in SlideMage's own folder, not in the project (v8.58.0)."""
from __future__ import annotations

from slidemage import app_settings
from slidemage.ai import ai_profile
from slidemage.fileio import read_json
from slidemage.project import ProjectContext


def _project(tmp_path):
    ctx = ProjectContext.at(tmp_path)
    ctx.settings_dir.mkdir(parents=True)
    return ctx


def _project_file(ctx):
    return read_json(ctx.settings_dir / "app_settings.json")


def test_ai_settings_go_to_the_machine_and_the_rest_stays_in_the_project(tmp_path):
    ctx = _project(tmp_path)
    ai_profile.set_model_choice(ctx, ai_profile.OLLAMA, ai_profile.CHAT, "qwen3:8b")
    app_settings.set_ollama_host(ctx, "http://gpu-box:11434")
    app_settings.set(ctx, "last_deck", "course")
    assert set(_project_file(ctx)) == {"last_deck"}
    machine = read_json(app_settings.MACHINE_STORE_PATH)
    assert machine["ai_models"] == {"ollama": {"chat": "qwen3:8b"}} and machine["ollama_host"] == "http://gpu-box:11434"
    assert app_settings.get(ctx, "last_deck") == "course"
    assert ai_profile.model_choice(ctx, ai_profile.OLLAMA, ai_profile.CHAT) == "qwen3:8b"


def test_every_project_on_this_machine_sees_the_same_ai_settings(tmp_path):
    one, two = _project(tmp_path / "one"), _project(tmp_path / "two")
    app_settings.set_ollama_host(one, "http://gpu-box:11434")
    assert app_settings.get_ollama_host(two) == "http://gpu-box:11434"


def test_a_project_s_old_ai_settings_move_out_of_it_once_and_this_machine_s_win(tmp_path):
    from slidemage.fileio import write_json

    ctx = _project(tmp_path)
    write_json(app_settings.MACHINE_STORE_PATH, {"cloud_conn": "api"})
    write_json(ctx.settings_dir / "app_settings.json",
               {"ai_models": {"local": {"chat": "old:7b"}}, "cloud_conn": "claude_code", "anthropic_api_key": "sk-x",
                "dark_mode": True})
    settings = app_settings.load(ctx)
    assert settings["ai_models"] == {"local": {"chat": "old:7b"}} and settings["cloud_conn"] == "api"
    assert _project_file(ctx) == {"dark_mode": True}                                  # nothing AI left behind
    assert read_json(app_settings.MACHINE_STORE_PATH)["anthropic_api_key"] == "sk-x"


