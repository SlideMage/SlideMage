# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Plugin contributions and UI kit behavior in the workspace."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QLabel

from conftest import DECK_TEXT, build_window, filled_menu, make_project, qapp as qapp
from slidemage import app_settings
from slidemage import project as project_module
from slidemage.plugins import loader, session
from slidemage.plugins.host import PluginHost, deck_snapshot
from slidemage.plugins.manifest import read_manifest
from slidemage.project import ProjectContext
from slidemage.ui import app as app_module
from slidemage.ui.dialogs.deck_settings import DeckSettingsSheet
from slidemage.ui.dialogs.settings import SettingsSheet
from slidemage.ui.kit import kit_qss as q
from slidemage.ui.kit import widgets as w
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.kit.tokens import FONT_SANS, tokens_for
from slidemage.ui.kit.widgets import PopoverMenu
from slidemage.ui.plugin_ui import HOST_UI
from slidemage.ui.workspace.palette import command_entries

FIXTURES = Path(__file__).parent / "fixtures" / "plugins"


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    root = make_project(monkeypatch, tmp_path / "proj")
    (root / "decks" / "hidden.tex").write_bytes(DECK_TEXT.encode())
    return ProjectContext.at(root)


def load(monkeypatch, tmp_path, ctx, *names):
    monkeypatch.setattr(loader.project, "config_dir", lambda: tmp_path / "config")
    monkeypatch.setenv(loader.PATH_ENV, os.pathsep.join(str(FIXTURES / n) for n in names))
    app_module.load_plugins(ctx)


@pytest.fixture(autouse=True)
def _no_plugins_after():
    yield
    session.set_loaded([])
    for name in ("uiplugin", "raises"):
        sys.modules.pop(name, None)


@pytest.fixture
def window(qapp, monkeypatch, tmp_path, ctx):
    load(monkeypatch, tmp_path, ctx, "raises", "uiplugin")
    window = build_window(monkeypatch, ctx)
    window.show()
    window.state.set_deck(next(d for d in window.decks if d.name == "test"))
    return window


def calls():
    return sys.modules["uiplugin"].CALLS


def test_enabled_follows_the_open_deck(window):
    command = window.commands["uiplugin.run"]
    assert command.enabled(window)
    # An open working tab restores its deck, so empty the project first.
    for deck in window.decks:
        deck.path.unlink()
    window.reload_decks()
    assert window.state.deck is None
    assert not command.enabled(window)


def test_plugin_commands_reach_the_palette_and_deck_menu_and_report_errors(window, monkeypatch):
    assert {p.id: p.state for p in session.loaded()} == {"raises": "failed", "uiplugin": "loaded"}
    assert {e.label for e in command_entries(window, ["fixture"]) if e.group == "UI fixture"} == {
        "Run fixture", "Break fixture",
    }
    shown = Mock()
    monkeypatch.setattr(window.toast, "show_message", shown)
    assert window.commands.run("uiplugin.boom", window)
    assert "kaboom" in shown.call_args.args[0] and shown.call_args.kwargs["error"] is True

    menu = filled_menu(window, "Deck")
    separator, heading, run, fail = menu.actions()[-4:]
    assert separator.isSeparator() and heading.defaultWidget().text() == "UI fixture"
    assert [run.objectName(), fail.objectName()] == ["uiplugin.run", "uiplugin.boom"]
    run.trigger()
    assert calls() == [("run", "test")]

def test_deck_settings_uses_the_plugin_action_and_shows_failed_tabs(window, monkeypatch):
    opened = []
    monkeypatch.setattr(DeckSettingsSheet, "exec", lambda sheet: opened.append(sheet))
    HOST_UI.open_deck_settings(deck_snapshot(window.state.deck), "Fixture")
    (sheet,) = opened
    assert sheet.deck.path == window.state.deck.path
    fixture, broken = (sheet.tab_titles.index(name) for name in ("Fixture", "Broken"))
    assert sheet.current_tab() == fixture
    assert not sheet.plugin_button.isHidden() and sheet.save_button.isHidden()
    assert not sheet.plugin_button.isEnabled()
    sheet.plugin_tabs[fixture][1].edit.setText("x")
    assert sheet.plugin_button.isEnabled()
    sheet.plugin_button.click()
    assert calls() == [("footer", "x")]
    sheet.set_current_tab(broken)
    assert "no tab" in sheet.plugin_tabs[broken][1].findChild(QLabel).text()
    assert sheet.plugin_button.isHidden() and not sheet.save_button.isHidden()
    sheet.set_current_tab(0)
    assert sheet.plugin_button.isHidden() and not sheet.save_button.isHidden()

@pytest.mark.parametrize("with_route", [False, True])
def test_settings_tab_is_added_after_slidemages_own(window, request, with_route):
    if with_route:
        request.getfixturevalue("fake_routes")
    sheet = SettingsSheet(window)
    labels = [sheet._tabs.tabText(i) for i in range(sheet._tabs.count())]
    assert labels[-2:] == ["Extensions", "Fixture"]
    assert ("AI" in labels) is with_route
    sheet.set_current_tab(len(labels) - 1 + (not with_route))
    assert any(label.text() == "fixture settings" for label in sheet._stack.currentWidget().findChildren(QLabel))


def test_plugin_box_is_listed_built_and_hidden_according_to_the_deck(window, monkeypatch):
    panels = window.side_panels
    shown = []
    monkeypatch.setattr(PopoverMenu, "popup_below", lambda self, anchor: shown.extend(self._entries))
    panels._open_menu()
    key = "plugin:uiplugin:main"
    start = shown.index(("header", "Plugins"))
    assert [entry[1:3] for entry in shown[start + 1:]] == [(key, "Fixture box")]
    box = panels.panels[key]
    assert box.offered()
    panels.set_panel(key)
    assert panels.current == key and any(label.text() == "box for test" for label in box.findChildren(QLabel))
    window.state.set_deck(next(d for d in window.decks if d.name == "hidden"))
    assert not box.offered() and panels.current != key

def test_a_broken_loading_machinery_does_not_stop_the_app(qapp, monkeypatch, ctx):
    monkeypatch.setattr(app_module.loader, "load_all", lambda make_host: 1 / 0)
    app_module.load_plugins(ctx)
    assert session.loaded() == []
    assert build_window(monkeypatch, ctx) is not None


def test_render_priority_is_set_on_the_background_renderer(window):
    soon = window.background.renderer._soon
    assert {deck.name: soon(deck) for deck in window.decks} == {"test": True, "hidden": False}

# -- UI kit

@pytest.fixture
def kit_host(qapp, ctx):
    return PluginHost(read_manifest(FIXTURES / "hello"), ctx, HOST_UI)


def test_host_widgets_are_the_kit_widgets_with_their_object_names(kit_host):
    h = kit_host
    made = [(h.Card(), w.Card, q.CARD), (h.SegmentedControl([("a", "A")]), w.SegmentedControl, q.SEGMENTED),
            (h.Chip("c"), w.Chip, q.CHIP), (h.Badge("3"), w.Badge, q.BADGE), (h.ElidedLabel("e"), w.ElidedLabel, ""),
            (h.RowButton("r"), w.RowButton, q.ROW_BUTTON), (h.ModalSheet("s"), w.ModalSheet, q.SHEET),
            (h.PlainList(), w.PlainList, q.PLAIN_LIST),
            (h.Window("t"), w.ToolWindow, q.TOOL_WINDOW)]
    for widget, kind, name in made:
        assert isinstance(widget, kind) and widget.objectName() == name
        assert widget.styleSheet() == ""


def test_label_roles(kit_host):
    names = {role: kit_host.Label("x", role).objectName()
             for role in ("title", "heading", "body", "secondary", "caption", "mono")}
    assert names["title"] == q.SHEET_TITLE and names["caption"] == q.PANEL_CAPTION and len(set(names.values())) == 6
    assert kit_host.Label("x").objectName() == names["body"]
    with pytest.raises(ValueError, match="role"):
        kit_host.Label("x", "huge")


def test_segmented_control_says_a_click_but_not_set_current(kit_host):
    control = kit_host.SegmentedControl([("a", "A"), ("b", "B")], current="b")
    heard = []
    control.changed.connect(heard.append)
    assert control.current() == "b"
    control.set_current("a")
    assert heard == []
    control.buttons()[1].click()
    assert heard == ["b"] and control.current() == "b"
    control.clear_current()
    assert control.current() is None and heard == ["b"]
    control.buttons()[0].click()
    assert control.current() == "a" and not control.buttons()[1].isChecked()


def test_row_fits_its_text_and_restyles_when_selected(kit_host, qapp):
    ThemeManager(dark=False).apply()
    row = kit_host.RowButton("Title", "Subtitle", selectable=True)
    row.ensurePolished()
    row.resize(200, row.sizeHint().height())
    row.show()
    assert row.height() >= 2 * row.fontMetrics().height()
    before = row.grab().toImage().pixelColor(5, 5).name()
    row.clicked.emit()
    assert row.selected()
    assert row.grab().toImage().pixelColor(5, 5).name() == tokens_for(False).info_bg != before
    row.set_selected(False)
    assert not row.selected()
    row.close()

def test_a_toast_stays_in_the_plugin_window_and_is_reused(kit_host):
    window = kit_host.Window("Forge")
    window.show()
    kit_host.toast(window, "one")
    kit_host.toast(window, "two")
    toasts = window.findChildren(w.Toast)
    assert window.font().family() == FONT_SANS and window.body is window.layout()
    assert len(toasts) == 1 and toasts[0].isVisible()
    window.close()


def test_theme_tracks_the_window_and_notifies_after_styling(kit_host, window, qapp):
    window.theme.set_dark(True)
    heard = []
    unsubscribe = kit_host.on_theme_changed(lambda tokens: heard.append((tokens.dark, tokens.bg in qapp.styleSheet())))
    for dark in (False, True):
        window.theme.set_dark(dark)
        tokens = kit_host.theme()
        assert tokens.dark is dark and tokens.bg == tokens_for(dark).bg
        assert kit_host.theme_color("info") == tokens_for(dark).info
    assert heard == [(False, True), (True, True)]
    unsubscribe()
    unsubscribe()
    window.theme.toggle()
    assert len(heard) == 2

def test_saved_theme_and_listener_work_before_the_window(kit_host, monkeypatch, ctx):
    app_settings.set(ctx, "dark_mode", False)
    monkeypatch.setattr(HOST_UI, "_window", None)
    tokens = kit_host.theme()
    assert not tokens.dark and tokens.bg == tokens_for(False).bg
    heard = []
    unsubscribe = kit_host.on_theme_changed(heard.append)
    window = build_window(monkeypatch, ctx)
    window.theme.toggle()
    unsubscribe()
    assert len(heard) == 1

def test_a_listener_that_raises_is_logged_and_the_others_run(kit_host, window, caplog):
    heard = []

    def bad(_tokens):
        raise RuntimeError("no such widget")

    subscriptions = [kit_host.on_theme_changed(bad), kit_host.on_theme_changed(heard.append)]
    window.theme.toggle()
    for unsubscribe in subscriptions:
        unsubscribe()
    assert len(heard) == 1 and "a theme listener raised" in caplog.text


class _Refuses(w.ToolWindow):
    def closeEvent(self, event):
        event.ignore()


def test_a_plugin_window_that_refuses_keeps_slidemage_open(window, monkeypatch):
    forge = _Refuses("Forge")
    HOST_UI.track_plugin_window(forge)
    forge.show()
    relaunched = []
    monkeypatch.setattr(project_module, "relaunch_with_project", relaunched.append)
    window.close()
    assert window.isVisible() and forge.isVisible()
    window.relaunch_with_project(Path("elsewhere"))
    assert relaunched == [] and window.isVisible()      # the new process would have run beside this one
    assert window.restart_after_update() is False
    forge.hide()
    window.close()
    assert not window.isVisible()


class _Raises(w.ToolWindow):
    def closeEvent(self, event):
        raise RuntimeError("bug")


def test_main_window_closes_plugin_windows_even_when_one_raises(kit_host, window):
    broken, normal = _Raises("Broken"), kit_host.Window("Forge")
    HOST_UI.track_plugin_window(broken)
    broken.show()
    normal.show()
    window.close()
    assert not broken.isVisible() and not normal.isVisible() and not window.isVisible()
