# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The assistant says when the plugin behind its route has an update waiting (2026-11-16: an outdated Claude plugin
kept telling Claude Code that \\vbox to 0pt blocks were protected, long after SlideMage stopped protecting them)."""
from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtWidgets import QLabel, QWidget

from conftest import qapp as qapp  # noqa: F401
from slidemage.ai import routes
from slidemage.plugins.catalogue import Release
from slidemage.ui.workspace.assistant_header import AssistantHeader

RELEASE = Release("1.2.1", 1, ">=0.13.31", "https://example.org/claude.smplugin", "0" * 64, 1, "2026-11-07")


def test_the_note_shows_for_the_active_routes_plugin_only(qapp, monkeypatch):
    owners = {"claude-code": "claude", "ollama": "ollama"}
    monkeypatch.setattr(routes, "owner_id", lambda route_id: owners.get(route_id))
    header = SimpleNamespace(app=SimpleNamespace(plugin_updates_pending={}),
                             state=SimpleNamespace(ai_route="claude-code"),
                             update_note=QWidget(), update_note_label=QLabel())
    header.update_note.show()
    AssistantHeader.refresh_update_note(header)
    assert header.update_note.isHidden()                                     # nothing pending
    header.app.plugin_updates_pending["claude"] = ("Claude", "1.0.3", RELEASE)
    AssistantHeader.refresh_update_note(header)
    assert not header.update_note.isHidden()
    assert header.update_note_label.text().startswith("Claude 1.2.1 is available (you have 1.0.3).")
    header.state.ai_route = "ollama"                                         # another route: not its plugin
    AssistantHeader.refresh_update_note(header)
    assert header.update_note.isHidden()


def test_a_route_knows_the_plugin_that_registered_it():
    class Route:
        id = "zz-test-route"

    owner = SimpleNamespace(manifest=SimpleNamespace(id="zz-plugin"))
    routes._owners[Route.id] = owner
    try:
        assert routes.owner_id(Route.id) == "zz-plugin" and routes.owner_id("nobody") is None
    finally:
        routes._owners.pop(Route.id, None)
