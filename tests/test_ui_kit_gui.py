# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Structural rendering and interaction checks for the UI kit."""
from __future__ import annotations

import re
import sys
import threading
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QWidget

from conftest import pause, wait_until
from slidemage.progress import Progress
from slidemage.ui.kit import kit_qss
from slidemage.ui.kit import fonts as fonts_module
from slidemage.ui.kit.fonts import FONT_DIR, load_fonts
from slidemage.ui.kit.gallery import KitGallery
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.kit.tokens import FONT_ICONS, FONT_MONO, FONT_SANS
from slidemage.ui.kit.widgets import (
    BusyIndicator,
    BusySheet,
    Field,
    IconLabel,
    PopoverMenu,
    SegmentedControl,
    SplitButton,
    ThumbnailGrid,
    Toast,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    assert load_fonts()
    return app


@pytest.fixture
def theme(qapp):
    return ThemeManager()


def styled(widget: QWidget, theme: ThemeManager, dark: bool) -> None:
    theme.dark = dark
    widget.setStyleSheet(theme._build_qss())


def test_font_files_are_bundled_and_registered(qapp):
    files = fonts_module._FONT_FILES
    assert all((FONT_DIR / name).is_file() for name in files)
    static_count = sum("[" not in name for name in files)
    assert all("[" not in name for name in files[:static_count])
    assert all(QFontDatabase.hasFamily(family) for family in (FONT_SANS, FONT_MONO, FONT_ICONS))
    styles = QFontDatabase.styles(FONT_SANS)
    assert {"Regular", "Medium", "Bold"} <= set(styles)
    # Synthetic SemiBold shows dark gaps in w and W. Linux Qt omits variable named instances.
    if not sys.platform.startswith("linux"):
        assert "SemiBold" in styles or "SemiBold" in QFontDatabase.styles(FONT_SANS + " SemiBold")
    assert load_fonts()


@pytest.mark.parametrize("dark", [False, True], ids=["light", "dark"])
def test_form_controls_draw_their_images_from_files(theme, dark):
    theme.dark = dark
    sheet = theme._build_qss()
    urls = re.findall(r"url\(([^)]+)\)", sheet)
    assert {Path(u).name.split("-")[0] for u in urls} == set(kit_qss.KIT_ICONS)
    assert all(Path(u).is_file() and Path(u).with_name(Path(u).stem + "@2x.png").is_file() for u in urls)


def test_popover_menu_triggers_and_skips_disabled(theme):
    menu = PopoverMenu()
    menu.add_title("1 · abc")
    menu.add_item("a", "Alpha", meta="Ctrl+1", icon="school")
    menu.add_header("Compile")
    menu.add_item("off", "Off", enabled=False)
    menu.add_item("b", "Beta", tone="danger", swatch="#e4684b")
    menu.add_separator()
    menu.add_item("end", "End")
    seen = []
    menu.triggered.connect(seen.append)
    menu.popup_at(QPoint(10, 10))
    assert menu.findChild(QLabel, kit_qss.MENU_TITLE).text() == "1 · abc"
    left = [r.layout().contentsMargins().left() for r in menu._rows]
    assert left[0] == left[3] and left[1] == left[2] == left[0] + kit_qss.MENU_INDENT
    assert len(menu.findChildren(QFrame, kit_qss.MENU_SWATCH)) == 1
    QTest.keyClick(menu, Qt.Key.Key_Down)
    QTest.keyClick(menu, Qt.Key.Key_Down)  # skips the disabled row
    QTest.keyClick(menu, Qt.Key.Key_Return)
    assert seen == ["b"] and not menu.isVisible()
    menu.popup_at(QPoint(10, 10))
    QTest.mouseClick(menu._rows[0], Qt.MouseButton.LeftButton)
    assert seen == ["b", "a"]


@pytest.fixture
def submenu(qapp):
    menu = PopoverMenu()

    def build(parent):
        flyout = PopoverMenu(parent, min_width=280)
        flyout.add_item("x", "Ex")
        flyout.add_item("y", "Why")
        return flyout

    menu.add_item("a", "A")
    menu.add_submenu("sub", "Sub", build)
    menu.add_item("b", "B")
    seen = []
    menu.triggered.connect(seen.append)
    menu.popup_at(QPoint(100, 100))
    yield menu, seen
    menu.close()


def click_row(menu: PopoverMenu, key: str) -> None:
    QTest.mouseClick(next(r for r in menu._rows if r.key == key), Qt.MouseButton.LeftButton)


def test_flyout_anchors_to_its_row_and_flips_at_the_screen_edge(submenu, qapp):
    menu, seen = submenu
    row = menu._rows[1]
    assert row.findChild(QLabel, kit_qss.MENU_META).text() == "▸"
    click_row(menu, "sub")
    flyout = menu._flyout
    assert menu.isVisible() and flyout.isVisible() and seen == []
    assert flyout.geometry().left() >= menu.geometry().right() - 3
    assert flyout.y() == row.mapToGlobal(QPoint()).y()
    assert flyout.findChild(QLabel, kit_qss.MENU_HEADER).text() == "Sub"
    plain = menu._rows[0].layout().contentsMargins().left()
    assert all(r.layout().contentsMargins().left() == plain for r in flyout._rows)
    menu.close()
    assert not flyout.isVisible()

    edge = qapp.primaryScreen().availableGeometry().right()
    menu.popup_at(QPoint(edge - 230, 100))
    click_row(menu, "sub")
    assert menu._flyout.geometry().right() <= menu.geometry().left() + 3


def test_hovering_a_submenu_opens_it_and_leaving_its_row_folds_it(submenu):
    menu, _ = submenu
    menu._on_row_hovered(menu._rows[1])
    assert menu._flyout is None and menu._flyout_timer.isActive()
    menu._on_flyout_timer()
    flyout = menu._flyout
    assert flyout.isVisible()
    menu._on_row_hovered(menu._rows[1])
    assert not menu._flyout_timer.isActive() and flyout.isVisible()
    menu._on_row_hovered(menu._rows[0])
    assert menu._flyout_timer.isActive()
    menu._on_flyout_timer()
    assert menu._flyout is None and not flyout.isVisible() and menu.isVisible()


def test_one_flyout_at_a_time_and_the_same_row_again_closes_it(theme):
    seen = []
    menu = PopoverMenu()
    for key in ("one", "two"):
        menu.add_submenu(key, key, lambda m, k=key: _flyout_of(m, k))
    menu.triggered.connect(seen.append)
    menu.popup_at(QPoint(600, 100))
    try:
        click_row(menu, "one")
        first = menu._flyout
        click_row(menu, "two")
        assert not first.isVisible() and menu._flyout.isVisible() and menu._flyout is not first
        second = menu._flyout
        click_row(menu, "two")
        assert not second.isVisible() and menu.isVisible() and seen == []        # the press closes the open flyout
        click_row(menu, "two")
        assert menu._flyout.isVisible()
    finally:
        menu.close()


def _flyout_of(menu: PopoverMenu, key: str) -> PopoverMenu:
    flyout = PopoverMenu(menu, min_width=280)
    flyout.add_item(f"{key}:item", "Item")
    return flyout


def test_flyout_escape_returns_to_the_menu_and_selection_closes_both(submenu):
    menu, seen = submenu
    click_row(menu, "sub")
    flyout = menu._flyout
    QTest.keyClick(flyout, Qt.Key.Key_Escape)
    assert not flyout.isVisible() and menu.isVisible() and seen == []
    click_row(menu, "sub")
    flyout = menu._flyout
    click_row(flyout, "y")
    assert seen == ["y"] and not flyout.isVisible() and not menu.isVisible()


def test_clicking_outside_closes_both_popups(submenu, qapp):
    menu, _ = submenu
    outside = QWidget()
    outside.setGeometry(0, 0, 80, 80)
    outside.show()
    click_row(menu, "sub")
    flyout = menu._flyout
    QTest.mouseClick(outside, Qt.MouseButton.LeftButton)
    qapp.processEvents()
    assert not flyout.isVisible() and not menu.isVisible()


def test_split_button_main_and_caret(theme):
    split = SplitButton("Compile")
    menu = PopoverMenu()
    menu.add_item("x", "X")
    split.set_menu(menu)
    split.show()
    clicks = []
    split.clicked.connect(lambda: clicks.append(1))
    QTest.mouseClick(split._main, Qt.MouseButton.LeftButton)
    assert clicks == [1]
    split._caret.click()
    assert menu.isVisible() and split._caret.text() == "expand_less"
    menu.close()
    assert split._caret.text() == "expand_more"
    replacement = PopoverMenu()
    split.set_menu(replacement)
    split._caret.setText("expand_less")
    menu.closed.emit()
    assert split._caret.text() == "expand_less"  # regression: a replaced menu must be disconnected
    replacement.closed.emit()
    assert split._caret.text() == "expand_more"


def test_toast_actions_and_auto_hide(theme):
    host = QWidget()
    host.resize(500, 300)
    host.show()
    toast = Toast(host)
    seen = []
    toast.action_triggered.connect(seen.append)
    toast.show_message("Removed 1y8", [("undo", "Undo")], timeout_ms=50)
    assert toast.isVisible() and toast.geometry().bottom() < host.height()
    toast.findChild(QPushButton, kit_qss.TOAST_ACTION).click()
    assert seen == ["undo"] and not toast.isVisible()
    toast.show_message("Saved", timeout_ms=20)
    pause(120)
    assert not toast.isVisible()


def test_busy_indicator_hides_a_quick_run_and_shows_a_long_one(theme):
    busy = BusyIndicator()
    busy.start("Working…")
    QTest.qWait(100)
    busy.finish()
    QTest.qWait(BusyIndicator.SHOW_AFTER_MS + 100)
    assert busy.isHidden()                                                   # finished before it showed: never appears
    busy.start("Working…")
    QTest.qWait(BusyIndicator.SHOW_AFTER_MS + 100)
    assert not busy.isHidden() and busy._label.text() == "Working…"
    busy.finish()
    assert not busy.isHidden()                                               # stays a little once shown
    QTest.qWait(BusyIndicator.SHOW_AT_LEAST_MS + 100)
    assert busy.isHidden()


def test_busy_sheet_works_off_the_gui_thread_then_closes_and_calls_done(theme):
    threads, seen = [], []
    gate = threading.Event()

    def work(report):
        threads.append(threading.current_thread())
        report(Progress.step(1, 2, "Copying"))
        gate.wait(5)
        return "ok"

    sheet = BusySheet.run(None, "Updating…", work, lambda result, error: seen.append((result, error, sheet.isVisible())))
    sheet.reject()                                                           # Escape: the sheet stays
    wait_until(lambda: sheet.busy._label.text() == "Copying (1 of 2)")
    assert sheet.isVisible() and sheet.isModal() and seen == []
    gate.set()
    wait_until(lambda: seen)
    assert seen == [("ok", None, False)] and threads[0] is not threading.main_thread()


def test_thumbnail_grid_chooses_one_and_emits_only_for_user_clicks(theme, tmp_path):
    from PySide6.QtGui import QColor, QPixmap

    picture = tmp_path / "x.png"
    pixmap = QPixmap(16, 9)
    pixmap.fill(QColor("red"))
    pixmap.save(str(picture))
    grid = ThumbnailGrid([("a", "A", picture), ("b", "B", picture), ("c", "C", tmp_path / "missing.png")], columns=2)
    styled(grid, theme, False)
    grid.show()
    seen = []
    grid.chosen.connect(seen.append)
    assert grid.current() == "a"
    grid.set_current("b")
    assert grid.current() == "b" and seen == []
    QTest.mouseClick(grid._tiles["c"], Qt.MouseButton.LeftButton)
    assert grid.current() == "c" and seen == ["c"] and not grid._tiles["a"].property("current")
    assert grid.grab().toImage().width() > 0
    field = Field("Frame", grid)
    assert field.label.text() == "Frame"


@pytest.mark.parametrize("dark", [False, True], ids=["light", "dark"])
def test_gallery_renders(theme, dark):
    gallery = KitGallery(theme)
    styled(gallery, theme, dark)
    gallery.show()
    QApplication.processEvents()
    image = gallery.grab().toImage()
    assert not image.isNull() and image.width() > 100 and image.height() > 100
    colors = {image.pixelColor(x, y).name() for x in range(0, image.width(), 9) for y in range(0, image.height(), 9)}
    assert len(colors) > 6
    assert theme.tokens.bg in colors
    icon = gallery.findChildren(IconLabel)[0]
    assert icon.font().family() == FONT_ICONS
    assert icon.fontMetrics().horizontalAdvance(icon.text()) <= icon.width() + 4
    metrics = icon.fontMetrics()
    assert metrics.horizontalAdvance("expand_more") == metrics.horizontalAdvance("expand_less") > 0
    assert metrics.horizontalAdvance("expand_more") < metrics.horizontalAdvance("zzzzzz_nope") / 4
    gallery.close()


def test_segment_badge_shows_a_count_and_hides_at_zero(theme):
    control = SegmentedControl([("p", "Preview"), ("s", "Source")])
    styled(control, theme, False)
    control.show()
    badge = control._badges["s"]
    assert badge.isHidden()
    control.set_badge("s", 3)
    QApplication.processEvents()
    assert badge.isVisible() and badge.text() == "3" and control._buttons["s"].property("badge") is True
    control.set_badge("s", 120)
    assert badge.text() == "99+"
    control.set_badge("s", 0)
    assert badge.isHidden() and control._buttons["s"].property("badge") is False
    assert control.current() == "p"          # a badge is not a click


def test_pointer_watch_keeps_flyout_open_until_the_pointer_reaches_another_row(submenu, monkeypatch):
    from slidemage.ui.kit import widgets

    menu, _ = submenu
    click_row(menu, "sub")
    flyout = menu._flyout
    assert flyout.isVisible() and menu._flyout_watch.isActive()
    first, owner, _ = menu._rows
    monkeypatch.setattr(widgets.QCursor, "pos", staticmethod(lambda: target))
    for widget in (flyout, owner):
        target = widget.mapToGlobal(widget.rect().center())
        menu._watch_flyout()
        assert menu._flyout is flyout and flyout.isVisible()
    target = first.mapToGlobal(first.rect().center())
    menu._watch_flyout()
    assert menu._flyout is None and not flyout.isVisible() and not menu._flyout_watch.isActive()


def test_click_or_close_cancels_pending_hover(submenu):
    menu, _ = submenu
    menu._on_row_hovered(menu._rows[1])
    assert menu._flyout_timer.isActive()
    click_row(menu, "sub")
    assert menu._flyout.isVisible() and not menu._flyout_timer.isActive()
    menu._on_row_hovered(menu._rows[0])
    assert menu._flyout_timer.isActive()
    menu._flyout.close()
    assert menu._flyout is None and not menu._flyout_timer.isActive()


def test_a_current_page_stack_asks_for_the_width_of_the_page_on_show_only(qapp):
    from PySide6.QtWidgets import QWidget
    from slidemage.ui.kit.widgets import CurrentPageStack
    stack, narrow, wide = CurrentPageStack(), QWidget(), QWidget()
    narrow.setMinimumWidth(200)
    wide.setMinimumWidth(900)
    stack.addWidget(narrow)
    stack.addWidget(wide)
    stack.setCurrentWidget(narrow)
    assert stack.minimumSizeHint().width() == 200          # a QStackedWidget would say 900
    stack.setCurrentWidget(wide)
    assert stack.minimumSizeHint().width() == 900
