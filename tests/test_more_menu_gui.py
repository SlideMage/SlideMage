"""The ⋮ menu: one popover in two columns and a footer (menus.py, PopoverMenu's columns layout),
what it lists, its keyboard and that everything left out of it is still a ⌘K command."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFrame, QLabel

from conftest import build_window, command_context, qapp as qapp
from slidemage.ui.kit import kit_qss as q
from slidemage.ui.kit.fonts import load_fonts
from slidemage.ui.kit.widgets import PopoverMenu
from slidemage.ui.workspace.menus import MORE_COLUMNS, MORE_FOOTER, MORE_NOTE, build_more_menu
from slidemage.ui.workspace.palette import command_entries

COURSE = SimpleNamespace(name="course", path="course.tex", archived=False, group="course",
                         course_url="https://example.org/course", supports_version=True)

LEFT = [("header", "This deck"), "deck_settings", "admin_slides", "deck_source", "deck_tags", "duplicate_deck",
        "export_pptx", "create_snapshot", "rerender_deck_previews", "update_deck_versions", ("sep",), "archive_deck"]
RIGHT = [("header", "Project"), "palette", "images", "edit_bib", "edit_test_slides", "open_project", "new_deck",
         ("header", "Housekeeping"), "housekeeping", "archive_unused",
         ("header", "Info"), "version_history", "check_updates", "project_compat"]

# Every entry the old one-column menu had and the new one has not: they are ⌘K commands.
LEFT_OUT = ["column:left", "column:right", "open_pdf", "import_presentation", "refresh_decks", "log", "empty_pdf",
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
    keys = [e[1] for e in menu._entries if e[0] == "item"]
    ids = [i for sections in MORE_COLUMNS for _header, ids in sections for i in ids] + list(MORE_FOOTER)
    assert keys == ids and len(set(keys)) == len(keys)
    meta = {e[1]: e[3] for e in menu._entries if e[0] == "item"}
    assert meta["palette"] == "Ctrl+K" and [k for k, m in meta.items() if m] == ["palette"]   # no hints like "course page"


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


def test_archive_deck_is_red_after_a_separator_in_the_left_column(qapp):
    menu = build_more_menu(None, command_context(COURSE))
    rows = rows_of(menu)
    assert rows["archive_deck"].property("tone") == "danger"
    assert [r.property("tone") for k, r in rows.items() if k != "archive_deck"] == [""] * (len(rows) - 1)
    layout = rows["archive_deck"].parentWidget().layout()
    index = layout.indexOf(rows["archive_deck"])
    separator = layout.itemAt(index - 2).widget()      # spacing, separator, spacing, the row
    assert separator.objectName() == q.MENU_SEPARATOR and separator.height() == 1
    assert layout.itemAt(index - 4).widget() is rows["update_deck_versions"]


def test_commands_not_available_now_are_disabled(qapp):
    rows = rows_of(build_more_menu(None, command_context(None)))
    assert [k for k, r in rows.items() if not r.isEnabled()] == [
        "deck_settings", "admin_slides", "deck_source", "deck_tags", "duplicate_deck", "export_pptx", "rerender_deck_previews", "update_deck_versions", "archive_deck"]


# -- using it ------------------------------------------------------------------------

def test_clicking_each_item_closes_the_menu_and_runs_that_command(window, monkeypatch):
    ran: list = []
    monkeypatch.setattr(window.commands, "run", lambda command_id, _ctx: ran.append(command_id) or True)
    course = next(d for d in window.decks if d.group == "course")
    window.state.set_deck(replace(course, course_url="https://example.org/course"))   # Admin slides needs the page
    keys = [i for sections in MORE_COLUMNS for _h, ids in sections for i in ids] + list(MORE_FOOTER)
    for key in keys:
        menu = open_menu(window)
        QTest.mouseClick(next(r for r in menu._rows if r.key == key), Qt.MouseButton.LeftButton)
        assert ran[-1] == key and not menu.isVisible()
    assert ran == keys


def test_it_opens_on_the_first_item_and_the_arrows_move_within_and_between_the_columns(qapp):
    menu = build_more_menu(None, command_context(COURSE))
    menu.popup_at(QPoint(10, 10))
    try:
        def current():
            return menu._rows[menu._current].key

        assert current() == "deck_settings"                               # focus on the first item
        QTest.keyClick(menu, Qt.Key.Key_Down)
        QTest.keyClick(menu, Qt.Key.Key_Down)
        assert current() == "deck_source"
        QTest.keyClick(menu, Qt.Key.Key_Right)                            # the same position, one column on
        assert current() == "edit_bib"
        QTest.keyClick(menu, Qt.Key.Key_Up)
        assert current() == "images"
        QTest.keyClick(menu, Qt.Key.Key_Left)
        assert current() == "admin_slides"
        QTest.keyClick(menu, Qt.Key.Key_Up)
        QTest.keyClick(menu, Qt.Key.Key_Up)                               # wraps round within the column
        assert current() == "archive_deck"
        QTest.keyClick(menu, Qt.Key.Key_Right)
        QTest.keyClick(menu, Qt.Key.Key_Right)                            # the footer is a third stop
        assert current() == "settings"
        QTest.keyClick(menu, Qt.Key.Key_Right)                            # and the first column follows it
        assert current() == "deck_settings"
        QTest.keyClick(menu, Qt.Key.Key_Left)
        assert current() == "settings"
    finally:
        menu.close()


def test_the_arrows_skip_disabled_items(qapp):
    menu = build_more_menu(None, command_context(None))                    # no deck: only the snapshot is on, on the left
    menu.popup_at(QPoint(10, 10))
    try:
        assert menu._rows[menu._current].key == "create_snapshot"
        QTest.keyClick(menu, Qt.Key.Key_Down)
        assert menu._rows[menu._current].key == "create_snapshot"
        QTest.keyClick(menu, Qt.Key.Key_Right)
        assert menu._rows[menu._current].key == "palette"
    finally:
        menu.close()


def test_enter_activates_the_current_item(qapp):
    menu = build_more_menu(None, command_context(COURSE))
    seen: list = []
    menu.triggered.connect(seen.append)
    menu.popup_at(QPoint(10, 10))
    QTest.keyClick(menu, Qt.Key.Key_Down)
    QTest.keyClick(menu, Qt.Key.Key_Return)
    assert seen == ["admin_slides"] and not menu.isVisible()


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
    in_menu = {i for sections in MORE_COLUMNS for _h, ids in sections for i in ids} | set(MORE_FOOTER)
    assert not in_menu & set(LEFT_OUT)
    listed = {e.label for e in command_entries(window, [])}
    for command_id in LEFT_OUT:
        assert window.commands[command_id].title(window) in listed, command_id
