# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The plugin host in the window (step 6): a fixture plugin, loaded through the real loader, contributes a command
(registry, palette, Deck menu), a Deck settings tab with a footer action, a Settings tab and a side panel box; a
command that raises is a message, and a plugin that fails to load does not stop the window."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QLabel

from conftest import DECK_TEXT, build_window, command_context, filled_menu, make_project, qapp as qapp
from slidemage.plugins import loader, session
from slidemage.plugins.host import deck_snapshot
from slidemage.project import ProjectContext
from slidemage.ui import app as app_module
from slidemage.ui.dialogs.deck_settings import DeckSettingsSheet
from slidemage.ui.dialogs.settings import SettingsSheet
from slidemage.ui.plugin_ui import HOST_UI
from slidemage.ui.kit.widgets import PopoverMenu
from slidemage.ui.workspace import deck_actions
from slidemage.ui.workspace.actions import build_registry
from slidemage.ui.workspace.panels.plugin_box import PluginBoxPanel
from slidemage.ui.workspace.menus import menu_bar_ids
from slidemage.ui.workspace.palette import command_entries

FIXTURES = Path(__file__).parent / "fixtures" / "plugins"


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    root = make_project(monkeypatch, tmp_path / "proj")
    (root / "decks" / "hidden.tex").write_bytes(DECK_TEXT.encode())
    return ProjectContext.at(root)


def load(monkeypatch, tmp_path, ctx, *names):
    monkeypatch.setattr(loader.project, "config_dir", lambda: tmp_path / "config")
    monkeypatch.setenv(loader.PATH_ENV, __import__("os").pathsep.join(str(FIXTURES / n) for n in names))
    app_module.load_plugins(ctx)


@pytest.fixture(autouse=True)
def _no_plugins_after():
    yield
    session.set_loaded([])
    sys.modules.pop("uiplugin", None)


@pytest.fixture
def window(qapp, monkeypatch, tmp_path, ctx):
    load(monkeypatch, tmp_path, ctx, "uiplugin")
    window = build_window(monkeypatch, ctx)
    window.show()
    window.state.set_deck(next(d for d in window.decks if d.name == "test"))
    return window


def calls():
    return sys.modules["uiplugin"].CALLS


def messages(window, monkeypatch):
    shown = []
    monkeypatch.setattr(window.toast, "show_message", lambda text, *a, **kw: shown.append((text, kw.get("error"))))
    return shown


def test_without_plugins_nothing_is_added(qapp, monkeypatch, ctx):
    before = menu_bar_ids(command_context())
    window = build_window(monkeypatch, ctx)
    assert [c.id for c in window.commands] == [c.id for c in build_registry()]
    assert menu_bar_ids(window) == before
    assert not any(isinstance(p, PluginBoxPanel) for p in window.side_panels.panels.values())


def test_command_is_in_the_registry_and_the_palette(window):
    command = window.commands["uiplugin.run"]
    assert (command.title(window), command.group) == ("Run fixture", "UI fixture")
    assert [e.label for e in command_entries(window, ["fixture"]) if e.group == "UI fixture"] == [
        "Run fixture", "Break fixture"]
    assert "uiplugin.run" in menu_bar_ids(window)


def test_the_deck_menu_ends_with_a_section_named_after_the_plugin(window):
    menu = filled_menu(window, "Deck")
    actions = menu.actions()
    tail = actions[-4:]
    assert tail[0].isSeparator()
    assert tail[1].defaultWidget().text() == "UI fixture"
    assert [a.objectName() for a in tail[2:]] == ["uiplugin.run", "uiplugin.boom"]
    tail[2].trigger()
    assert calls() == [("run", "test")]


def test_enabled_follows_the_open_deck(window):
    command = window.commands["uiplugin.run"]
    assert command.enabled(window)
    window.state.set_deck(None)
    assert not command.enabled(window)


def test_a_raising_command_shows_an_error_and_the_app_survives(window, monkeypatch):
    shown = messages(window, monkeypatch)
    assert window.commands.run("uiplugin.boom", window)
    assert shown and shown[0][1] is True and "kaboom" in shown[0][0]
    assert window.commands.run("uiplugin.run", window)      # still works


def sheet_for(window, tab="Fixture"):
    return DeckSettingsSheet(window, window.state.deck, [], tab=tab)


def test_deck_settings_tab_replaces_save_with_the_footer_action(window):
    sheet = sheet_for(window)
    assert sheet.tab_titles[2:] == ["Fixture", "Broken"]
    assert sheet.current_tab() == 2
    assert sheet.plugin_button.text() == "Do it"
    assert not sheet.plugin_button.isHidden() and sheet.save_button.isHidden()
    assert not sheet.plugin_button.isEnabled()           # enabled(page): the field is empty
    page = sheet.plugin_tabs[2][1]
    page.edit.setText("x")                               # the page's changed signal asks again
    assert sheet.plugin_button.isEnabled()
    sheet.plugin_button.click()
    assert calls() == [("footer", "x")]
    sheet.set_current_tab(0)                             # SlideMage's own tab: Save is back
    assert sheet.plugin_button.isHidden() and not sheet.save_button.isHidden()


def test_a_failing_tab_build_shows_an_error_caption(window):
    sheet = sheet_for(window, "Broken")
    assert sheet.current_tab() == 3
    page = sheet.plugin_tabs[3][1]
    assert "no tab" in page.findChild(QLabel).text()
    assert sheet.plugin_button.isHidden() and not sheet.save_button.isHidden()      # its footer action is dropped


def test_host_ui_opens_deck_settings_on_a_named_tab(window, monkeypatch):
    opened = []

    class Sheet:
        def __init__(self, parent, deck, templates, tab):
            opened.append((deck.name, tab))

        def exec(self):
            return 0

    monkeypatch.setattr(deck_actions, "DeckSettingsSheet", Sheet)
    HOST_UI.open_deck_settings(deck_snapshot(window.state.deck), "Fixture")
    assert opened == [("test", "Fixture")]


@pytest.mark.parametrize("with_route", [False, True])
def test_settings_tab_is_added_after_slidemages_own(window, request, with_route):
    if with_route:
        request.getfixturevalue("fake_routes")
    sheet = SettingsSheet(window)
    labels = [sheet._tabs.tabText(i) for i in range(sheet._tabs.count())]
    assert labels[-2:] == ["Plugins", "Fixture"]
    assert ("AI" in labels) is with_route
    sheet.set_current_tab(len(labels) - 1 + (not with_route))
    assert any(label.text() == "fixture settings" for label in sheet._stack.currentWidget().findChildren(QLabel))


def test_the_box_is_offered_where_when_says_so_and_is_built(window):
    panels = window.side_panels
    key = "plugin:uiplugin:main"
    assert key in panels.panels and panels.panels[key].offered()
    panels.set_panel(key)
    assert panels.current == key
    assert any(l.text() == "box for test" for l in panels.panels[key].findChildren(QLabel))
    window.state.set_deck(next(d for d in window.decks if d.name == "hidden"))
    assert not panels.panels[key].offered()
    assert panels.current != key                          # back to a panel of SlideMage's own


def test_the_picker_lists_the_box_under_plugins(window, monkeypatch):
    seen = []
    monkeypatch.setattr(PopoverMenu, "popup_below", lambda self, anchor: seen.append(list(self._entries)))
    window.side_panels._open_menu()
    entries = seen[0]
    at = entries.index(("header", "Plugins"))
    assert entries[at - 1] == ("sep",)
    assert [e[1:3] for e in entries[at + 1:]] == [("plugin:uiplugin:main", "Fixture box")]


def test_a_failing_plugin_does_not_stop_the_window(qapp, monkeypatch, tmp_path, ctx):
    load(monkeypatch, tmp_path, ctx, "raises", "uiplugin")
    states = {p.id: p.state for p in session.loaded()}
    assert states["raises"] == "failed" and states["uiplugin"] == "loaded"
    window = build_window(monkeypatch, ctx)
    assert "uiplugin.run" in window.commands


def test_a_broken_loading_machinery_does_not_stop_the_app(qapp, monkeypatch, ctx):
    monkeypatch.setattr(app_module.loader, "load_all", lambda make_host: 1 / 0)
    app_module.load_plugins(ctx)
    assert session.loaded() == []
    assert build_window(monkeypatch, ctx) is not None


def test_render_priority_is_set_on_the_background_renderer(qapp, monkeypatch, tmp_path, ctx):
    load(monkeypatch, tmp_path, ctx, "uiplugin")
    window = build_window(monkeypatch, ctx)
    renderer = window.background.renderer
    test, hidden = (next(d for d in window.decks if d.name == n) for n in ('test', 'hidden'))
    assert (renderer.plugin_soon(test), renderer.plugin_soon(hidden)) == (True, False)
