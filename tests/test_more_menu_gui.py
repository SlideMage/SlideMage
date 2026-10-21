# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The ⋮ menu: one popover in two columns and a footer (menus.py, PopoverMenu's columns layout),
what it lists, its keyboard and that everything left out of it is still a ⌘K command."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFrame, QLabel

from conftest import build_window, command_context, more_menu_ids, qapp as qapp
from slidemage.ui.kit import kit_qss as q
from slidemage.ui.kit.fonts import load_fonts
from slidemage.ui.kit.widgets import PopoverMenu
from slidemage.ui.workspace.menus import MORE_NOTE, build_more_menu
from slidemage.ui.workspace.palette import command_entries

COURSE = SimpleNamespace(name="course", path="course.tex", archived=False, group="course",
                         course_url="https://example.org/course", supports_version=True)

LEFT = [("header", "This deck"), "present", "deck_settings", "submenu:export", "duplicate_deck", ("sep",), "archive_deck"]
RIGHT = [("header", "Project"), "images", "open_project", "new_deck", ("sep",), "submenu:housekeeping"]
# The flyouts: the row's key, the title of the flyout and the commands in it.
FLYOUTS = {"submenu:export": ("Export", ["export_pptx", "export_latex"]),
           "submenu:housekeeping": ("Housekeeping", ["housekeeping", "archive_unused"])}

# Every entry the old menus had and this has not: they are ⌘K commands (the first three groups are also in
# Deck settings → General → Maintenance and Settings → Project / About).
LEFT_OUT = ["create_snapshot", "rerender_deck_previews", "update_deck_versions", "edit_bib", "edit_test_slides",
            "project_compat", "version_history", "check_updates", "admin_slides", "deck_tags", "deck_source", "palette",
            "column:left", "column:right", "open_pdf", "import_presentation", "refresh_decks", "log", "empty_pdf",
            "remove_temp", "update_previews", "sync_links", "exit"]


def shape(menu) -> list:
    """The entries as a flat list: item keys, ("header", text), ("sep",), ("column",), ("footer",), ("note", text)."""
    return [e[1] if e[0] == "item" else e for e in menu._entries]


def rows_of(menu) -> dict:
    menu._build()
    return {row.key: row for row in menu._rows}


@pytest.fixture
def window(qapp, monkeypatch):
    assert load_fonts()
    window = build_window(monkeypatch)
    window.show()
    return window


def open_menu(window) -> PopoverMenu:
    window.topbar._more.click()
    menu = window.topbar.findChildren(PopoverMenu)[-1]
    assert menu.isVisible()
    return menu


# -- the layout ----------------------------------------------------------------------

def test_two_columns_with_their_sections_and_a_footer_in_order(qapp):
    menu = build_more_menu(None, command_context(COURSE))
    assert shape(menu) == [*LEFT, ("column",), *RIGHT, ("footer",), "settings", ("note", MORE_NOTE)]
    assert MORE_NOTE == "Everything here is also in ⌘K / Ctrl+K"


def test_every_listed_command_exists_once_and_a_shortcut_shows_in_place_of_a_hint(qapp):
    menu = build_more_menu(None, command_context(COURSE))
    ids = more_menu_ids()
    assert len(set(ids)) == len(ids)
    registry = command_context(COURSE).commands
    assert all(i in registry for i in ids)
    meta = {e[1]: e[3] for e in menu._entries if e[0] == "item"}
    assert meta["deck_settings"] == QKeySequence("Ctrl+,").toString(QKeySequence.SequenceFormat.NativeText)
    assert [k for k, m in meta.items() if m == "▸"] == list(FLYOUTS)
    assert [k for k, m in meta.items() if m and m != "▸"] == ["present", "deck_settings"]   # shortcuts only, no hints like "full-screen, with notes"


def test_the_popover_is_520_wide_with_the_right_column_divided_and_the_footer_below(qapp):
    menu = build_more_menu(None, command_context(COURSE))
    menu.popup_at(QPoint(10, 10))
    try:
        # 520 wide, wider only as far as its longest entry needs (Windows' text is a few px wider: 533)
        assert 520 <= menu.width() <= 560
        assert menu.property("columns")
        columns = menu.findChildren(QFrame, q.MENU_COLUMN)
        assert [c.property("divided") for c in columns] == [False, True]
        assert columns[0].width() == pytest.approx(columns[1].width(), abs=6)
        footer = menu.findChildren(QFrame, q.MENU_FOOTER)[0]
        assert footer.y() > max(c.geometry().bottom() for c in columns)
        assert footer.findChildren(type(rows_of(menu)["settings"])) and footer.findChild(QLabel, q.MENU_NOTE).text() == MORE_NOTE
        # the note is at the right end, Settings… at the left
        assert rows_of(menu)["settings"].x() < footer.findChild(QLabel, q.MENU_NOTE).x()
    finally:
        menu.close()


def test_archive_deck_is_red_and_both_columns_end_after_a_separator(qapp):
    menu = build_more_menu(None, command_context(COURSE))
    rows = rows_of(menu)
    assert rows["archive_deck"].property("tone") == "danger"
    assert [r.property("tone") for k, r in rows.items() if k != "archive_deck"] == [""] * (len(rows) - 1)
    for after, before in (("archive_deck", "duplicate_deck"), ("submenu:housekeeping", "new_deck")):
        layout = rows[after].parentWidget().layout()
        index = layout.indexOf(rows[after])
        separator = layout.itemAt(index - 2).widget()      # spacing, separator, spacing, the row
        assert separator.objectName() == q.MENU_SEPARATOR and separator.height() == 1
        assert layout.itemAt(index - 4).widget() is rows[before]


def test_commands_not_available_now_are_disabled(qapp):
    rows = rows_of(build_more_menu(None, command_context(None)))
    assert [k for k, r in rows.items() if not r.isEnabled()] == [
        "present", "deck_settings", "submenu:export", "duplicate_deck", "archive_deck"]


def test_each_submenu_is_a_row_with_a_flyout_titled_and_filled_by_its_commands(qapp):
    menu = build_more_menu(None, command_context(COURSE))
    menu.popup_at(QPoint(600, 100))
    try:
        for key, (title, ids) in FLYOUTS.items():
            QTest.mouseClick(rows_of_open(menu)[key], Qt.MouseButton.LeftButton)
            flyout = menu._flyout
            assert [e[0] for e in flyout._entries][:1] == ["header"] and flyout._entries[0][1] == title
            assert shape(flyout)[1:] == ids and flyout.minimumWidth() == 280
            assert all(r.isEnabled() for r in flyout._rows)
    finally:
        menu.close()


def rows_of_open(menu) -> dict:
    return {row.key: row for row in menu._rows}


def test_a_submenu_without_a_visible_command_is_left_out_and_one_without_an_available_one_is_disabled(qapp):
    ctx = command_context(COURSE)

    def patch(command_id: str, **changes) -> None:
        ctx.commands._commands[command_id] = replace(ctx.commands[command_id], **changes)

    patch("export_pptx", visible=lambda _ctx: False)
    assert "submenu:export" in shape(build_more_menu(None, ctx))                  # Export LaTeX is still there
    patch("export_latex", visible=lambda _ctx: False)
    assert "submenu:export" not in shape(build_more_menu(None, ctx))
    assert "submenu:housekeeping" in shape(build_more_menu(None, ctx))
    patch("housekeeping", enabled=lambda _ctx: False)
    assert rows_of(build_more_menu(None, ctx))["submenu:housekeeping"].isEnabled()      # one command is still on
    patch("archive_unused", enabled=lambda _ctx: False)
    menu = build_more_menu(None, ctx)
    menu.popup_at(QPoint(600, 100))
    try:
        row = rows_of(menu)["submenu:housekeeping"]
        assert not row.isEnabled()
        QTest.mouseClick(row, Qt.MouseButton.LeftButton)
        assert menu._flyout is None                  # disabled: nothing opens
    finally:
        menu.close()


# -- using it ------------------------------------------------------------------------

def test_clicking_each_item_closes_the_menu_and_runs_that_command(window, monkeypatch):
    ran: list = []
    monkeypatch.setattr(window.commands, "run", lambda command_id, _ctx: ran.append(command_id) or True)
    course = next(d for d in window.decks if d.group == "course")
    window.state.set_deck(replace(course, course_url="https://example.org/course"))
    for key in more_menu_ids():
        menu = open_menu(window)
        for submenu, (_title, ids) in FLYOUTS.items():
            if key in ids:                                                        # an item of a flyout: open it first
                QTest.mouseClick(next(r for r in menu._rows if r.key == submenu), Qt.MouseButton.LeftButton)
                menu = menu._flyout
        QTest.mouseClick(next(r for r in menu._rows if r.key == key), Qt.MouseButton.LeftButton)
        assert ran[-1] == key and not menu.isVisible() and not window.topbar.findChildren(PopoverMenu)[-1].isVisible()
    assert ran == more_menu_ids()


def test_it_opens_on_the_first_item_and_the_arrows_move_within_and_between_the_columns(qapp):
    menu = build_more_menu(None, command_context(COURSE))
    menu.popup_at(QPoint(10, 10))
    try:
        def current():
            return menu._rows[menu._current].key

        assert current() == "present"                                     # focus on the first item
        QTest.keyClick(menu, Qt.Key.Key_Down)
        QTest.keyClick(menu, Qt.Key.Key_Down)
        assert current() == "submenu:export"
        QTest.keyClick(menu, Qt.Key.Key_Right)                            # the same position, one column on
        assert current() == "new_deck"
        QTest.keyClick(menu, Qt.Key.Key_Up)
        assert current() == "open_project"
        QTest.keyClick(menu, Qt.Key.Key_Left)
        assert current() == "deck_settings"
        QTest.keyClick(menu, Qt.Key.Key_Up)
        QTest.keyClick(menu, Qt.Key.Key_Up)                               # wraps round within the column
        assert current() == "archive_deck"
        QTest.keyClick(menu, Qt.Key.Key_Right)
        QTest.keyClick(menu, Qt.Key.Key_Right)                            # the footer is a third stop
        assert current() == "settings"
        QTest.keyClick(menu, Qt.Key.Key_Right)                            # and the first column follows it
        assert current() == "present"
        QTest.keyClick(menu, Qt.Key.Key_Left)
        assert current() == "settings"
    finally:
        menu.close()


def test_the_arrows_skip_disabled_items(qapp):
    menu = build_more_menu(None, command_context(None))                    # no deck: nothing on the left is on
    menu.popup_at(QPoint(10, 10))
    try:
        assert menu._rows[menu._current].key == "images"
        QTest.keyClick(menu, Qt.Key.Key_Down)
        assert menu._rows[menu._current].key == "open_project"
        QTest.keyClick(menu, Qt.Key.Key_Left)                              # the empty left column is skipped
        assert menu._rows[menu._current].key == "settings"
    finally:
        menu.close()


def test_enter_activates_the_current_item(qapp):
    menu = build_more_menu(None, command_context(COURSE))
    seen: list = []
    menu.triggered.connect(seen.append)
    menu.popup_at(QPoint(10, 10))
    QTest.keyClick(menu, Qt.Key.Key_Down)
    QTest.keyClick(menu, Qt.Key.Key_Return)
    assert seen == ["deck_settings"] and not menu.isVisible()


def test_escape_closes_it(window):
    menu = open_menu(window)
    QTest.keyClick(menu, Qt.Key.Key_Escape)
    assert not menu.isVisible()


def test_a_click_outside_closes_it(window, qapp):
    menu = open_menu(window)
    QTest.mouseClick(window.centre, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
    qapp.processEvents()
    assert not menu.isVisible()


# -- what is left out ----------------------------------------------------------------

def test_every_entry_the_old_menu_had_and_this_has_not_is_a_command_in_the_palette(window):
    in_menu = set(more_menu_ids())
    assert not in_menu & set(LEFT_OUT)
    listed = {e.label for e in command_entries(window, [])}
    for command_id in LEFT_OUT:
        assert window.commands[command_id].title(window) in listed, command_id
