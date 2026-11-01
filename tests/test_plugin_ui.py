# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The plugin host in the window (step 6): a fixture plugin, loaded through the real loader, contributes a command
(registry, palette, Deck menu), a Deck settings tab with a footer action, a Settings tab and a side panel box; a
command that raises is a message, and a plugin that fails to load does not stop the window."""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QLabel

from slidemage import app_settings
from slidemage import project as project_module
from slidemage.plugins.host import PluginHost
from slidemage.plugins.manifest import read_manifest
from slidemage.ui.kit import kit_qss as q
from slidemage.ui.kit import widgets as w
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.kit.tokens import FONT_MONO, FONT_SANS, RADIUS_MD, tokens_for
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
    assert labels[-2:] == ["Extensions", "Fixture"]
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


# -- the UI kit for plugins (API v1 additions) -------------------------------------------------------------------

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


def test_chip_keywords(kit_host):
    chip = kit_host.Chip("A long text", "ok", icon="lock", elide=True, pressable=True)
    assert chip.text() == "A long text" and chip.property("tone") == "ok" and chip.property("pressable") is True
    assert chip._icon.text() == "lock"


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


def test_a_row_is_as_tall_as_its_fonts_and_selects(kit_host, qapp):
    row = kit_host.RowButton("No questions yet", "typography", selectable=True)
    plain = kit_host.RowButton("Plain")
    row.ensurePolished()
    assert row.minimumHeight() == 0 and row.maximumHeight() > 10000
    assert row.sizeHint().height() >= 2 * row.fontMetrics().height()
    assert not row.selected()
    row.clicked.emit()
    plain.clicked.emit()
    assert row.selected() and not plain.selected()
    row.set_selected(False)
    assert not row.selected()


def test_a_selected_row_is_restyled(kit_host, qapp):
    ThemeManager(dark=False).apply()
    row = kit_host.RowButton("Row", selectable=True)
    row.resize(200, 60)
    row.show()
    before = row.grab().toImage().pixelColor(5, 5).name()
    row.set_selected(True)
    after = row.grab().toImage().pixelColor(5, 5).name()
    row.close()
    assert before != after and after == tokens_for(False).info_bg


def test_the_window_has_the_kit_font_and_a_body(kit_host):
    window = kit_host.Window("Forge")
    assert window.windowTitle() == "Forge" and window.isWindow() and not window.isModal()
    assert window.font().family() == FONT_SANS and window.body is window.layout()


def test_a_toast_stays_in_the_plugin_window_and_is_reused(kit_host):
    window = kit_host.Window("Forge")
    window.show()
    kit_host.toast(window, "one")
    kit_host.toast(window, "two")
    toasts = window.findChildren(w.Toast)
    assert len(toasts) == 1 and toasts[0].isVisible()
    window.close()


@pytest.mark.parametrize("dark", [True, False])
def test_theme_is_the_tokens_of_the_saved_choice_before_a_window(ctx, dark):
    app_settings.set(ctx, "dark_mode", dark)
    HOST_UI._window = None
    tokens = PluginHost(read_manifest(FIXTURES / "hello"), ctx, HOST_UI).theme()
    t = tokens_for(dark)
    assert tokens.dark is dark and (tokens.bg, tokens.info_fg, tokens.on_solid) == (t.bg, t.info_fg, t.on_solid)
    assert tokens.radius_md == RADIUS_MD and tokens.font_mono == FONT_MONO


def test_theme_follows_the_window_and_theme_color_stays(kit_host, window):
    for dark in (True, False):
        window.theme.set_dark(dark)
        assert kit_host.theme() == dataclasses.replace(kit_host.theme(), dark=dark)
        assert kit_host.theme().bg == tokens_for(dark).bg
        assert kit_host.theme_color("info") == tokens_for(dark).info


def test_on_theme_changed_fires_once_after_the_stylesheet_and_stops_when_unsubscribed(kit_host, window, qapp):
    heard = []
    window.theme.set_dark(True)
    unsubscribe = kit_host.on_theme_changed(lambda tokens: heard.append((tokens.dark, tokens.bg in qapp.styleSheet())))
    window.theme.set_dark(False)
    window.theme.toggle()
    assert heard == [(False, True), (True, True)]
    unsubscribe()
    unsubscribe()
    window.theme.toggle()
    assert len(heard) == 2


def test_a_listener_subscribed_before_the_window_is_heard(qapp, monkeypatch, ctx):
    HOST_UI._window = None
    heard = []
    unsubscribe = PluginHost(read_manifest(FIXTURES / "hello"), ctx, HOST_UI).on_theme_changed(heard.append)
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


def test_closing_the_main_window_closes_plugin_windows_so_the_process_can_end(kit_host, window, qapp):
    forge = kit_host.Window("Forge")
    forge.show()
    window.close()
    assert not forge.isVisible() and not window.isVisible()


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


def test_a_plugin_window_whose_close_raises_does_not_keep_slidemage_open(window):
    forge = _Raises("Forge")
    HOST_UI.track_plugin_window(forge)
    forge.show()
    window.close()
    assert not window.isVisible()
