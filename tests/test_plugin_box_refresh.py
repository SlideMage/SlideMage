# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""A plugin's side-panel box is built again when the plugin says its data changed (Host.refresh_sidebar_box), and
when the calendar date changes: at once when it is shown, when it is next chosen otherwise."""
from __future__ import annotations

import sys
from datetime import datetime

import pytest
from PySide6.QtWidgets import QLabel

from conftest import build_window, make_project, qapp as qapp
from slidemage.plugins import loader, session
from slidemage.project import ProjectContext
from slidemage.ui import app as app_module
from slidemage.ui.workspace import side_panels
from slidemage.ui.workspace.side_panels import ms_until_midnight

KEY = "plugin:refreshplug:main"

PLUGIN_TOML = """\
id = "refreshplug"
name = "Refresh fixture"
version = "0.1.0"
api_version = 1
requires_slidemage = ">=0.8.0"
summary = "Fixture plugin whose box shows data that changes."
author = "Test"
homepage = "https://example.org/refreshplug"
license = "GPL-3.0-or-later"
needs = []
network = []
"""

PLUGIN_CODE = '''\
"""Fixture: a box whose text the test changes; HOST keeps the host for the test."""
from slidemage.plugin_api import Host

STATE = {"text": "first", "builds": 0}
HOST = {}


def activate(host: Host):
    HOST["host"] = host

    def box(deck):
        STATE["builds"] += 1
        page = host.Page()
        page.body.addWidget(host.caption(STATE["text"]))
        return page

    host.add_sidebar_box("main", "Refresh box", box)
'''


@pytest.fixture
def box(qapp, monkeypatch, tmp_path, request):
    ctx = ProjectContext.at(make_project(monkeypatch, tmp_path / "proj"))
    folder = tmp_path / "plugins" / "refreshplug"
    (folder / "refreshplug").mkdir(parents=True)
    (folder / "plugin.toml").write_text(PLUGIN_TOML, encoding="utf-8")
    (folder / "refreshplug" / "__init__.py").write_text(PLUGIN_CODE, encoding="utf-8")
    monkeypatch.setattr(loader.project, "config_dir", lambda: tmp_path / "config")
    monkeypatch.setenv(loader.PATH_ENV, str(folder))
    def reset_plugins():
        session.set_loaded([])
        sys.modules.pop("refreshplug", None)

    request.addfinalizer(reset_plugins)
    app_module.load_plugins(ctx)
    window = build_window(monkeypatch, ctx)
    window.show()
    window.state.set_deck(next(d for d in window.decks if d.name == "test"))
    module = sys.modules["refreshplug"]
    return window.side_panels, module.STATE, module.HOST["host"]


def labels(panel) -> list[str]:
    return [label.text() for label in panel.findChildren(QLabel)]


def test_refresh_rebuilds_a_visible_box_and_defers_a_hidden_one(box):
    panels, state, host = box
    panels.set_panel(KEY)
    assert labels(panels.panels[KEY]) == ["first"]

    def refresh(text):
        state["text"] = text
        host.refresh_sidebar_box("main")

    built = state["builds"]
    refresh("visible")
    assert state["builds"] == built + 1
    assert labels(panels.panels[KEY]) == ["visible"]

    panels.set_panel(next(key for key in panels.panels if key != KEY))
    refresh("unselected")
    assert state["builds"] == built + 1
    panels.set_panel(KEY)
    assert state["builds"] == built + 2
    assert labels(panels.panels[KEY]) == ["unselected"]

    panels.card.hide()
    refresh("hidden")
    assert state["builds"] == built + 2
    panels._on_focus_toggled(False)
    assert state["builds"] == built + 3
    assert labels(panels.panels[KEY]) == ["hidden"]


def test_the_date_change_builds_the_shown_box_again(box, monkeypatch):
    assert ms_until_midnight(datetime(2026, 10, 27, 23, 59, 59, 900_000)) == 1000
    panels, state, _host = box
    day = [datetime(2026, 10, 27, 23, 59, 30)]
    monkeypatch.setattr(side_panels, "_now", lambda: day[0])
    panels._arm_midnight()
    assert panels._midnight.isActive() and panels._midnight.interval() == 30_000
    panels.set_panel(KEY)
    built = state["builds"]
    state["text"] = "next session: tomorrow"
    day[0] = datetime(2026, 10, 28, 0, 0, 1)
    panels._midnight.timeout.emit()                  # the timer fires at midnight
    assert state["builds"] == built + 1
    assert labels(panels.panels[KEY]) == ["next session: tomorrow"]
    assert panels._midnight.isActive() and panels._midnight.interval() == 86_400_000 - 1000


def test_an_unknown_key_is_a_value_error(box):
    _panels, state, host = box
    built = state["builds"]
    with pytest.raises(ValueError):
        host.refresh_sidebar_box("nope")
    assert state["builds"] == built
