# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The AI-free host's plugin compatibility contracts."""
import json

from slidemage import app_settings, plugin_api, project
from slidemage.ai import routes, tasks
from slidemage.plugins import migrate
from slidemage.project import ProjectContext


def test_no_builtin_routes():
    assert routes.all() == []


def test_legacy_readers_do_not_migrate_settings(tmp_path, monkeypatch):
    ctx = ProjectContext.at(tmp_path / "project")
    ctx.settings_dir.mkdir(parents=True)
    path = ctx.settings_dir / "app_settings.json"
    old = json.dumps({"anthropic_api_key": "key", "ollama_host": "http://old"})
    path.write_text(old)
    machine = tmp_path / "machine.json"
    monkeypatch.setattr(app_settings, "MACHINE_STORE_PATH", machine)
    monkeypatch.setattr(migrate, "_keyring", lambda: None)
    route_ctx = routes.context(ctx, "test")
    assert route_ctx.legacy_secret("anthropic_api_key") == "key"
    assert route_ctx.legacy_ollama_host() == "http://old"
    assert path.read_text() == old and not machine.exists()


def test_route_context_task_and_prompt_helpers(tmp_path):
    ctx = ProjectContext.at(tmp_path)
    route_ctx = routes.context(ctx, "test")
    assert plugin_api.check(route_ctx, tasks.SUMMARISE, "text", {"summary": "answer"}) == ("answer", [])
    assert plugin_api.effective_system_prompt(route_ctx)
    assert plugin_api.get_effective_prompt(route_ctx, "model", "EN", "DE")


def test_project_policy_has_a_compat_finding(tmp_path):
    from slidemage import compat
    project.write_project_json(tmp_path, {"ai": {"policy": "cloud"}})
    assert compat._detect_ai_settings(tmp_path)
