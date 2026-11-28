# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""AI preferences are machine-wide, while deck preferences follow the project."""
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


def test_ai_settings_are_shared_across_projects_but_deck_settings_are_local(tmp_path):
    ctx = _project(tmp_path / "one")
    other = _project(tmp_path / "two")
    ai_profile.set_model_choice(ctx, ai_profile.OLLAMA, ai_profile.CHAT, "qwen3:8b")
    app_settings.set(ctx, app_settings.OLLAMA_HOST_SETTING_KEY, "http://gpu-box:11434")
    app_settings.set(ctx, "last_deck", "course")
    assert set(_project_file(ctx)) == {"last_deck"}
    machine = read_json(app_settings.machine_store_path())
    assert machine["ai_models"] == {"ollama": {"chat": "qwen3:8b"}} and machine["ollama_host"] == "http://gpu-box:11434"
    assert app_settings.get(ctx, "last_deck") == "course"
    assert ai_profile.model_choice(other, ai_profile.OLLAMA, ai_profile.CHAT) == "qwen3:8b"
    assert app_settings.peek_ollama_host(other) == "http://gpu-box:11434"


def test_a_project_folder_that_refuses_new_files_does_not_stop_a_setting_change(tmp_path, monkeypatch, caplog):
    """Nextcloud virtual files can reject writes with EINVAL, including during deck switches."""
    from slidemage import fileio

    ctx = _project(tmp_path)
    real = fileio.atomic_write

    def refusing(path, *args, **kwargs):
        if ctx.settings_dir in path.parents:
            raise OSError(22, "Invalid argument")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(fileio, "atomic_write", refusing)
    app_settings.set(ctx, "last_deck", "course")                       # no exception
    # This machine's file is still written.
    app_settings.set(ctx, app_settings.OLLAMA_HOST_SETTING_KEY, "http://gpu-box:11434")
    assert read_json(app_settings.machine_store_path())["ollama_host"] == "http://gpu-box:11434"
    assert "couldn't save settings" in caplog.text
