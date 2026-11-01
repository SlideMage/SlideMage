# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The window's menu bar (menus.py MENU_BAR): its menus and sections, that every command is in it, the keys it
shows for the system SlideMage runs on, its radio items and the deck submenu, and the commands that came with it
(Help → SlideMage manual and Keyboard shortcuts, Edit → Find / Replace in source, Build → Compile current view)."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication

from conftest import build_window, command_context, filled_menu, menu_actions, menu_bar_ids, qapp as qapp
from slidemage.ui.dialogs.shortcuts import OWN_KEYS, ShortcutsSheet, shortcut_rows
from slidemage.ui.kit.fonts import load_fonts
from slidemage.ui.workspace import compile_actions
from slidemage.ui.workspace.actions import MAC_KEYS, build_registry
from slidemage.ui.workspace.menus import DECKS, MENU_BAR, MENU_ROLES, Submenu, expand
from slidemage.ui.workspace.source_file import REPLACE_KEY
from test_workspace_window import COURSE as COURSE_DECK

COURSE = SimpleNamespace(name="course", path="course.tex", archived=False, group="course", groups=("course",),
                         supports_version=True)
TITLES = ["File", "Edit", "Deck", "Slide", "View", "Build", "AI", "Housekeeping", "Help"]


def native(key: str) -> str:
    return QKeySequence(key).toString(QKeySequence.SequenceFormat.NativeText)


def names(menu) -> list:
    """The items of a filled menu in order: command ids, "submenu:<title>", "|" for a separator, "#<text>" for a header."""
    out = []
    for action in menu.actions():
        if action.isSeparator():
            out.append("|")
        elif action.menu() is not None:
            out.append(action.menu().objectName())
        elif action.objectName():
            out.append(action.objectName())
        else:
            out.append("#" + action.defaultWidget().text())
    return out


@pytest.fixture
def window(qapp, monkeypatch):
    assert load_fonts()
    window = build_window(monkeypatch)
    window.show()
    return window


# -- the layout ----------------------------------------------------------------------

def test_nine_menus_with_one_alt_key_each(qapp):
    assert [t.replace("&", "") for t, _s in MENU_BAR] == TITLES
    keys = [t[t.index("&") + 1].lower() for t, _s in MENU_BAR]
    assert len(set(keys)) == len(keys)


def test_every_command_is_in_the_menu_bar_once_per_place_and_every_listed_id_exists(qapp):
    registry = build_registry()
    ids = menu_bar_ids()
    assert [i for i in ids if i not in registry] == []
    assert {c.id for c in registry} - set(ids) == {"switch_deck"}      # Deck → Switch deck is the submenu of the decks
    assert [i for i in ids if ids.count(i) > 1] == ["palette", "palette"]   # Find anything… is in Edit and in Help


def test_the_deck_menu_in_order_with_its_separators(qapp):
    ctx = command_context(COURSE, decks=[COURSE])
    assert names(filled_menu(ctx, "Deck")) == [
        "submenu:switch deck", "refresh_decks", "|", "present", "open_pdf", "|",
        "deck_settings", "deck_tags", "deck_source", "|",
        "add_slide", "duplicate_deck", "submenu:export", "create_snapshot", "|",
        "update_deck_versions", "rerender_deck_previews", "deck:readability", "|", "archive_deck"]


def test_the_file_edit_housekeeping_and_help_menus(qapp):
    ctx = command_context(COURSE)
    assert names(filled_menu(ctx, "File")) == [
        "open_project", "new_deck", "import_presentation", "|", "save", "autosave", "|", "edit_bib", "edit_test_slides", "|",
        "settings", "|", "exit"]
    assert names(filled_menu(ctx, "Housekeeping")) == [
        "housekeeping", "|", "#Cleanup", "empty_pdf", "remove_temp", "archive_unused", "|", "#Updating",
        "update_previews", "sync_links"]
    assert names(filled_menu(ctx, "Help")) == [
        "open_manual", "shortcuts", "palette", "|", "version_history", "check_updates", "plugins", "project_compat", "|",
        "debug_log", "debug_report", "open_logs"]


def test_view_has_radio_groups_that_follow_the_state(window):
    view = menu_actions(filled_menu(window, "View"))
    radios = [k for k, a in view.items() if a.isCheckable()]
    assert radios == ["view:instructor", "view:during-course", "view:after-course", "language:EN", "language:DE",
                      "mode:preview", "mode:split", "mode:source", "mode:details"]
    assert all(view[k].actionGroup() is not None and view[k].actionGroup().isExclusive() for k in radios)
    window.state.set_mode("source")
    view = menu_actions(filled_menu(window, "View"))
    assert [k for k in radios if view[k].isChecked() and k.startswith("mode:")] == ["mode:source"]


def test_a_submenu_without_a_visible_command_is_left_out_and_one_without_an_available_one_is_disabled(qapp):
    ctx = command_context(COURSE)

    def patch(command_id: str, **changes) -> None:
        ctx.commands._commands[command_id] = replace(ctx.commands[command_id], **changes)

    patch("export_pptx", visible=lambda _ctx: False)
    assert "submenu:export" in names(filled_menu(ctx, "Deck"))
    patch("export_latex", enabled=lambda _ctx: False)
    assert not menu_actions(filled_menu(ctx, "Deck"))["submenu:export"].isEnabled()
    patch("export_latex", visible=lambda _ctx: False)
    assert "submenu:export" not in names(filled_menu(ctx, "Deck"))


def test_the_deck_submenu_groups_the_decks_checks_the_current_one_and_switches(window):
    deck = menu_actions(filled_menu(window, "Deck"))
    decks = deck["submenu:switch deck"].menu()
    picks = [a for a in decks.actions() if a.isCheckable()]
    assert sorted(a.objectName() for a in picks) == sorted(str(d.path) for d in window.decks)
    assert [a.objectName() for a in picks if a.isChecked()] == [str(window.state.deck.path)]
    other = next(a for a in picks if not a.isChecked())
    other.trigger()
    assert str(window.state.deck.path) == other.objectName()


# -- keys --------------------------------------------------------------------------

def test_an_item_shows_its_key_after_a_tab_and_binds_none(window):
    file = menu_actions(filled_menu(window, "File"))
    assert file["save"].text() == "Save source\t" + native("Ctrl+S")
    assert file["exit"].text() == "Exit SlideMage\t" + native("Alt+F4")
    assert all(a.shortcut().isEmpty() for a in file.values())         # the window's QShortcuts are the only bindings
    build = menu_actions(filled_menu(window, "Build"))
    assert build["compile:current"].text().endswith("\t" + native("Ctrl+Shift+B"))
    view = menu_actions(filled_menu(window, "View"))
    assert [view[f"view:{v}"].text().split("\t")[1] for v in ("instructor", "during-course", "after-course")] == [
        native("Ctrl+1"), native("Ctrl+2"), native("Ctrl+3")]


@pytest.mark.parametrize("mac", [False, True])
def test_no_key_is_used_twice_or_taken_from_the_source_view(qapp, mac):
    registry = build_registry(mac=mac)
    keys = [QKeySequence(c.shortcut or c.hint).toString() for c in registry if c.shortcut or c.hint]
    assert len(set(keys)) == len(keys)
    taken = {QKeySequence(k).toString() for _h, own in OWN_KEYS for _w, k in own}
    assert not taken & set(keys)


def test_a_mac_gets_its_own_keys_and_windows_keeps_the_others(qapp):
    windows, mac = build_registry(mac=False), build_registry(mac=True)
    assert [(windows[i].shortcut, mac[i].shortcut) for i in ("settings", "deck_settings", "present", "open_manual")] == [
        ("", "Ctrl+,"), ("Ctrl+,", "Ctrl+Alt+,"), ("F5", "Ctrl+Alt+P"), ("F1", "")]
    assert (windows["exit"].hint, mac["exit"].hint) == ("Alt+F4", "")
    assert {c.id for c in windows if c.shortcut != mac[c.id].shortcut or c.hint != mac[c.id].hint} == set(MAC_KEYS)
    assert REPLACE_KEY == "Ctrl+H"                                      # the tests run on Windows/Linux
    assert {i: r for i, r in MENU_ROLES.items()} == {"settings": QAction.MenuRole.PreferencesRole,
                                                     "exit": QAction.MenuRole.QuitRole,
                                                     "version_history": QAction.MenuRole.AboutRole}


# -- the commands that came with it ---------------------------------------------------

def test_the_manual_opens_the_manual_deck(window):
    manual = next(d for d in window.decks if d.group == "manual")
    assert window.commands.run("open_manual", window)
    assert window.state.deck.path == manual.path


def test_find_and_replace_open_the_source_views_find_bar_from_the_preview(window):
    window.state.set_mode("preview")
    shown = []
    window.centre.source.show_find = lambda replace=False: shown.append(replace)
    assert window.commands.run("find", window) and window.commands.run("replace", window)
    assert shown == [False, True] and window.state.mode == "split"


def test_compile_current_view_compiles_the_view_shown(window, monkeypatch):
    seen = []
    monkeypatch.setattr(compile_actions, "compile_current", lambda _w, view: seen.append(view))
    window.state.set_deck(COURSE_DECK)
    window.state.set_view("after-course")
    assert window.commands.run("compile:current", window)
    assert seen == ["after-course"]


def test_the_shortcuts_sheet_lists_the_commands_keys_and_the_editors_own(window):
    rows = dict(shortcut_rows(window.commands, window))
    assert ("Find anything…", native("Ctrl+K")) in rows["Project"]
    assert ("Compile PDF · current view", native("Ctrl+Shift+B")) in rows["View & build"]
    assert ("Bold", native("Ctrl+B")) in rows["Source view"]
    sheet = ShortcutsSheet(window.commands, window)
    assert "Find anything" in sheet.browser.toPlainText()
    sheet.close()


def test_expand_keeps_ids_and_submenus_and_spreads_a_prefix(qapp):
    ctx = command_context()
    assert expand(ctx, ["log", DECKS, "view:*"]) == ["log", DECKS, "view:instructor", "view:during-course",
                                                    "view:after-course"]
    sub = Submenu("Export", ("export_pptx",))
    assert expand(ctx, [sub]) == [sub]


def test_autosave_is_an_on_off_switch_right_after_help(window):
    """v8.58.0: AutoSave [On|Off] after the menu bar's last menu, styled like View as; clicks set it, and it follows
    a change made elsewhere (Settings, File, Ctrl+K)."""
    from slidemage.ui import layout_settings
    from slidemage.ui.workspace import source_file

    layout_settings.set(source_file.AUTOSAVE_KEY, True)
    bar, switch = window.menuBar(), window.autosave_switch
    window.autosave_switch.refresh()
    window.resize(1600, 900)
    QApplication.processEvents()
    help_right = bar.actionGeometry(bar.actions()[-1]).right()
    assert switch.parent() is bar and switch.isVisible()
    assert help_right < switch.geometry().left() <= help_right + 40
    assert [b.text() for b in switch.control.buttons()] == ["On", "Off"] and switch.is_on()
    switch.control.buttons()[1].click()
    assert not source_file.autosave_on() and not switch.is_on()
    window.set_autosave(True)
    assert switch.is_on()


def test_a_debug_log_chip_follows_the_autosave_switch_while_the_log_is_on(window, tmp_path, monkeypatch):
    from slidemage import diagnostics
    from slidemage.ui.workspace import debug_log_ui

    monkeypatch.setenv(diagnostics.DIR_ENV, str(tmp_path / "logs"))
    monkeypatch.delenv(diagnostics.DEBUG_ENV, raising=False)
    diagnostics.setup("app")
    window.resize(1600, 900)
    QApplication.processEvents()
    chip, switch = window.debug_chip, window.autosave_switch
    assert not chip.isVisible() and window.commands["debug_log"].title(window) == "Turn debug log on"
    width = switch.width()
    window.commands.run("debug_log", window)
    QApplication.processEvents()
    assert diagnostics.debug_enabled() and chip.isVisible() and chip.parent() is switch
    assert switch.width() > width and window.commands["debug_log"].title(window) == "Turn debug log off"
    opened = []
    monkeypatch.setattr(debug_log_ui.open_path, "open_in_default_app", opened.append)
    chip.clicked.emit()
    assert opened == [diagnostics.debug_log_path().parent]
    debug_log_ui.set_debug(window, False)
    QApplication.processEvents()
    assert not chip.isVisible() and switch.width() == width


def test_save_debug_report_writes_the_zip_where_chosen(window, tmp_path, monkeypatch):
    import zipfile

    from slidemage import diagnostics
    from slidemage.ui.workspace import debug_log_ui

    monkeypatch.setenv(diagnostics.DIR_ENV, str(tmp_path / "logs"))
    monkeypatch.setenv(diagnostics.DEBUG_ENV, "1")
    diagnostics.setup("app")
    monkeypatch.setattr(debug_log_ui.QFileDialog, "getSaveFileName",
                        lambda *args: (str(tmp_path / "out" / "report"), ""))
    window.commands.run("debug_report", window)
    target = tmp_path / "out" / "report.zip"
    names = zipfile.ZipFile(target).namelist()
    assert "report.txt" in names and any(n.startswith("debug/app_") for n in names)
    assert window.toast.isVisible()
    monkeypatch.setattr(debug_log_ui.QFileDialog, "getSaveFileName", lambda *args: ("", ""))
    window.commands.run("debug_report", window)               # cancelled: nothing happens


def test_changes_of_deck_view_and_language_are_in_the_debug_log(window, caplog):
    import logging

    caplog.set_level(logging.DEBUG, logger="slidemage.ui")
    window.state.set_language("DE" if window.state.language != "DE" else "EN")
    other = next(view for view in ("instructor", "during-course") if view != window.state.view)
    window.state.set_view(other)
    said = [r.getMessage() for r in caplog.records if r.name == "slidemage.ui"]
    assert any(s.startswith("language language=") for s in said) and f"view view={other}" in said
