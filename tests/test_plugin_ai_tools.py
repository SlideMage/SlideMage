# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Host.ai_tools(), Host.focus() and the lazily re-exported AI types of plugin_api."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import make_project

from slidemage import plugin_api, project
from slidemage.ai.tools import CLAUDE_CODE_TOOLS, ToolBox
from slidemage.plugins.host import PluginHost
from slidemage.plugins.manifest import read_manifest

FIXTURES = Path(__file__).parent / "fixtures" / "plugins"


@pytest.fixture
def host(tmp_path, monkeypatch):
    monkeypatch.setattr(project, "config_dir", lambda: tmp_path / "config")
    ctx = project.ProjectContext.at(make_project(monkeypatch, tmp_path / "project"))
    return PluginHost(read_manifest(FIXTURES / "hello"), ctx)


def test_ai_tools_is_the_claude_code_toolbox(host):
    box = host.ai_tools()
    assert isinstance(box, ToolBox)
    assert [s.name for s in box.specs] == [t.spec.name for t in CLAUDE_CODE_TOOLS]
    assert box.ctx.scope == "slide" and box.ctx.focus_slide is None


def test_scope_and_focus_slide_reach_the_tools(host):
    slide = host.ctx.slides_dir / "abc-EN-Hello-current.tex"
    box = host.ai_tools("deck", focus_slide=slide, mode="ask")
    assert box.ctx.scope == "deck" and box.ctx.focus_slide == slide
    assert box.ctx.mode == "ask"
    with pytest.raises(ValueError):
        host.ai_tools("everything")
    with pytest.raises(ValueError):
        host.ai_tools(mode="sometimes")


def test_the_toolbox_runs_a_tool(host):
    from slidemage.ai.agent_types import ToolCall

    result = host.ai_tools().execute(ToolCall("1", "list_slides", {}))
    assert "Decks: test" in result.text        # the tool ran on the project's files


def test_focus_without_a_window(host):
    assert host.focus() == plugin_api.Focus(None, None, "slide")


def test_focus_from_the_window(host):
    class Ui:
        def focus(self):
            return plugin_api.Focus(Path("d.tex"), None, "deck")

    host.ui = Ui()
    assert host.focus().scope == "deck"


def test_the_ai_types_come_from_the_core():
    from slidemage.ai import agent_types, providers
    from slidemage.protected_regions import protected_spans

    assert plugin_api.ChatProvider is providers.ChatProvider
    assert plugin_api.ChatReply is providers.ChatReply
    assert issubclass(plugin_api.Cancelled, plugin_api.ProviderError)
    assert plugin_api.parse_json_object('x {"a": 1} y') == {"a": 1}
    assert plugin_api.UserMessage is agent_types.UserMessage
    assert plugin_api.EDIT_AUTO == "auto"
    assert plugin_api.ToolBox is ToolBox
    assert plugin_api.protected_spans is protected_spans
    with pytest.raises(AttributeError):
        plugin_api.Nothing  # noqa: B018


def test_importing_plugin_api_stays_light():
    code = ("import sys, slidemage.plugin_api\n"
            "heavy = [m for m in sys.modules if m.startswith(('PySide6', 'slidemage.ai', 'slidemage.ui', "
            "'slidemage.protected_regions'))]\n"
            "print(heavy)\n"
            "from slidemage.plugin_api import ChatReply\n"
            "print('slidemage.ai.providers' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         env={**os.environ, "PYTHONPATH": str(Path(__file__).parent.parent / "src")})
    first, second = out.stdout.split("\n")[:2]
    assert first == "[]"
    assert second == "True"
