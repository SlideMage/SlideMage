# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""An outdated plugin is flagged when its route is active."""
from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtWidgets import QLabel, QWidget

from conftest import qapp as qapp  # noqa: F401
from slidemage.ai import routes
from slidemage.plugins.catalogue import Release
from slidemage.ui.workspace.assistant_header import AssistantHeader

RELEASE = Release("1.2.1", 1, ">=0.13.31", "https://example.org/claude.smplugin", "0" * 64, 1, "2026-11-07")


def test_the_note_shows_for_the_active_routes_plugin_only(qapp, monkeypatch):
    owner = SimpleNamespace(manifest=SimpleNamespace(id="claude"))
    monkeypatch.setitem(routes._owners, "claude-code", owner)
    header = SimpleNamespace(app=SimpleNamespace(plugin_updates_pending={}),
                             state=SimpleNamespace(ai_route="claude-code"),
                             update_note=QWidget(), update_note_label=QLabel())
    header.update_note.show()
    AssistantHeader.refresh_update_note(header)
    assert header.update_note.isHidden()                                     # nothing pending
    header.app.plugin_updates_pending["claude"] = ("Claude", "1.0.3", RELEASE)
    AssistantHeader.refresh_update_note(header)
    assert not header.update_note.isHidden()
    assert "1.2.1" in header.update_note_label.text() and "1.0.3" in header.update_note_label.text()
    header.state.ai_route = "ollama"                                         # another route: not its plugin
    AssistantHeader.refresh_update_note(header)
    assert header.update_note.isHidden()
