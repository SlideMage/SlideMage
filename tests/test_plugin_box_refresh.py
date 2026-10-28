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
requires_slidemage = ">=8.0"
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
def ctx(tmp_path, monkeypatch):
    root = make_project(monkeypatch, tmp_path / "proj")
    return ProjectContext.at(root)


@pytest.fixture
def plugin_state():
    """The fixture module's STATE dict, reset for each test."""
    module = sys.modules["refreshplug"]
    module.STATE.update(text="first", builds=0)
    return module.STATE


@pytest.fixture
def window(qapp, monkeypatch, tmp_path, ctx):
    folder = tmp_path / "plugins" / "refreshplug"
    (folder / "refreshplug").mkdir(parents=True)
    (folder / "plugin.toml").write_text(PLUGIN_TOML, encoding="utf-8")
    (folder / "refreshplug" / "__init__.py").write_text(PLUGIN_CODE, encoding="utf-8")
    monkeypatch.setattr(loader.project, "config_dir", lambda: tmp_path / "config")
    monkeypatch.setenv(loader.PATH_ENV, str(folder))
    app_module.load_plugins(ctx)
    window = build_window(monkeypatch, ctx)
    window.show()
    window.state.set_deck(next(d for d in window.decks if d.name == "test"))
    yield window


@pytest.fixture(autouse=True)
def _no_plugins_after():
    yield
    session.set_loaded([])
    sys.modules.pop("refreshplug", None)


def host():
    return sys.modules["refreshplug"].HOST["host"]


def labels(panel) -> list[str]:
    return [label.text() for label in panel.findChildren(QLabel)]


def other_key(panels) -> str:
    return next(k for k in panels.panels if k != KEY)


def test_refresh_builds_the_shown_box_again(window, plugin_state):
    panels = window.side_panels
    panels.set_panel(KEY)
    assert panels.current == KEY and labels(panels.panels[KEY]) == ["first"]
    built = plugin_state["builds"]
    plugin_state["text"] = "second"
    host().refresh_sidebar_box("main")
    assert plugin_state["builds"] == built + 1
    assert labels(panels.panels[KEY]) == ["second"]


def test_refresh_of_a_box_not_shown_waits_until_it_is_chosen(window, plugin_state):
    panels = window.side_panels
    panels.set_panel(KEY)
    panels.set_panel(other_key(panels))
    built = plugin_state["builds"]
    plugin_state["text"] = "second"
    host().refresh_sidebar_box("main")
    assert plugin_state["builds"] == built           # not shown: nothing built now
    panels.set_panel(KEY)
    assert plugin_state["builds"] == built + 1
    assert labels(panels.panels[KEY]) == ["second"]


def test_refresh_while_the_card_is_hidden_builds_when_it_is_shown_again(window, plugin_state):
    panels = window.side_panels
    panels.set_panel(KEY)
    built = plugin_state["builds"]
    plugin_state["text"] = "second"
    panels.card.hide()                               # the assistant has the focus
    host().refresh_sidebar_box("main")
    assert plugin_state["builds"] == built
    panels._on_focus_toggled(False)                  # the card is shown again
    assert plugin_state["builds"] == built + 1
    assert labels(panels.panels[KEY]) == ["second"]


def test_the_date_change_builds_the_shown_box_again(window, plugin_state, monkeypatch):
    panels = window.side_panels
    day = [datetime(2026, 10, 27, 23, 59, 30)]
    monkeypatch.setattr(side_panels, "_now", lambda: day[0])
    panels._arm_midnight()
    assert panels._midnight.isActive() and panels._midnight.interval() == 30_000
    panels.set_panel(KEY)
    built = plugin_state["builds"]
    plugin_state["text"] = "next session: tomorrow"
    day[0] = datetime(2026, 10, 28, 0, 0, 1)
    panels._midnight.timeout.emit()                  # the timer fires at midnight
    assert plugin_state["builds"] == built + 1
    assert labels(panels.panels[KEY]) == ["next session: tomorrow"]
    assert panels._midnight.isActive() and panels._midnight.interval() == 86_400_000 - 1000


def test_ms_until_midnight():
    assert ms_until_midnight(datetime(2026, 10, 28, 23, 59, 30)) == 30_000
    assert ms_until_midnight(datetime(2026, 10, 28, 0, 0, 0)) == 86_400_000
    assert ms_until_midnight(datetime(2026, 10, 28, 23, 59, 59, 900_000)) == 1000   # never spins


def test_an_unknown_key_is_a_value_error(window, plugin_state):
    built = plugin_state["builds"]
    with pytest.raises(ValueError):
        host().refresh_sidebar_box("nope")
    assert plugin_state["builds"] == built
