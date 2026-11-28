# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Keyboard focus, activation and visual order in the workspace top bar."""
from __future__ import annotations

import pytest
import shiboken6
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from conftest import focus_on, qapp as qapp
from test_ai_routes_ui_gui import window as window  # noqa: F401 -- a fixture


def tab(times: int = 1, *, back: bool = False) -> list[QWidget]:
    reached = []
    for _ in range(times):
        QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Backtab if back else Qt.Key.Key_Tab,
                       Qt.KeyboardModifier.ShiftModifier if back else Qt.KeyboardModifier.NoModifier)
        reached.append(QApplication.focusWidget())
    return reached


def bar_order(window, *, images: bool = False) -> list[QWidget]:
    bar = window.topbar
    stops = [bar._left_column, bar._deck_button,
             bar._views.current_button(), bar._languages.current_button(), bar._modes.current_button(),
             *bar._compile.buttons(), *([bar._images] if images else []), bar._library, bar._right_column]
    xs = [stop.mapTo(bar, stop.rect().topLeft()).x() for stop in stops if stop.isVisible()]
    assert xs == sorted(xs) and len(xs) == len(stops)        # the list is the visual order
    return stops


@pytest.fixture(autouse=True)
def _routes(fake_routes):
    return fake_routes


@pytest.fixture
def open_window(window):
    window._set_column_hidden("left", False)
    window._set_column_hidden("right", False)
    QApplication.processEvents()
    return window


@pytest.mark.parametrize("width, density, images", [
    (2000, "full", False), (1300, "narrow", True), (1024, "tight", False),
])
def test_tab_walks_the_bar_in_visual_order_and_back(open_window, width, density, images):
    window = open_window
    window.resize(width, 800)
    if images:
        window._toggle_images()
    QApplication.processEvents()
    assert window.topbar._density == density
    order = bar_order(window, images=images)
    focus_on(window, order[0])
    assert tab(len(order) - 1) == order[1:]
    if images:
        assert tab(len(order) - 1, back=True) == order[-2::-1]
        window._toggle_images()
        QApplication.processEvents()
        order = bar_order(window)
        focus_on(window, order[0])
        assert tab(len(order) - 1) == order[1:]
    assert tab()[0] is window.slide_list.find
    assert tab(back=True)[0] is order[-1]
    assert tab(len(order) - 1, back=True) == order[-2::-1]


def test_bar_continues_into_the_centre_before_the_side_panels(open_window):
    window = open_window
    window.state.set_mode("details")
    QApplication.processEvents()
    focus_on(window, window.topbar._right_column)
    reached = []
    for _ in range(60):
        stop, = tab()
        reached.append(stop)
        if window.side_panels.isAncestorOf(stop):
            break
    centre = [i for i, w in enumerate(reached) if window.centre.isAncestorOf(w)]
    side = [i for i, w in enumerate(reached) if window.side_panels.isAncestorOf(w)]
    slides = [i for i, w in enumerate(reached) if window.slide_list.isAncestorOf(w)]
    assert slides and centre and side and max(slides) < min(centre) and max(centre) < min(side)


def test_deck_switcher_menu_opens_on_the_current_deck_and_picks_with_the_keyboard(window):
    bar = window.topbar
    deck = bar._deck_button
    before = window.state.deck
    for key in (Qt.Key.Key_Space, Qt.Key.Key_Down, Qt.Key.Key_Return):
        QTest.keyClick(focus_on(window, deck), key)
        menu = next(m for m in bar.findChildren(QWidget) if m.objectName() == "kitMenu" and m.isVisible())
        assert [row.key for row in menu._rows if row.property("current")] == [menu.current_key]
        if key == Qt.Key.Key_Return:
            QTest.keyClick(menu, Qt.Key.Key_Down)
            QTest.keyClick(menu, Qt.Key.Key_Return)
        else:
            QTest.keyClick(menu, Qt.Key.Key_Escape)
        QApplication.processEvents()
        assert not shiboken6.isValid(menu) or not menu.isVisible()
        assert window.focusWidget() is deck
    assert window.state.deck is not before


def test_every_stop_of_the_bar_activates_with_enter_or_space(open_window):
    window = open_window
    bar = window.topbar
    pressed = []
    bar.command.disconnect(window._on_command)         # Compile would run
    bar.command.connect(pressed.append)
    for control in (bar._views, bar._languages, bar._modes):
        control.changed.connect(pressed.append)
    expected = [bar._views.current(), bar._languages.current(), bar._modes.current()]
    for control, key in ((bar._views, Qt.Key.Key_Return), (bar._languages, Qt.Key.Key_Space),
                         (bar._modes, Qt.Key.Key_Enter)):
        QTest.keyClick(focus_on(window, control.current_button()), key)
    for button, key in ((bar._left_column, Qt.Key.Key_Return), (bar._right_column, Qt.Key.Key_Space),
                        (bar._compile.buttons()[0], Qt.Key.Key_Return)):
        QTest.keyClick(focus_on(window, button), key)
    assert pressed == [*expected, "column:left", "column:right", f"compile:{window.state.view}"]
    QTest.keyClick(focus_on(window, bar._compile.buttons()[1]), Qt.Key.Key_Return)
    menu = bar._compile_menu
    assert menu.isVisible()
    QTest.keyClick(menu, Qt.Key.Key_Escape)


def test_the_bar_takes_the_focus_from_tab_only_and_shows_the_ring(open_window):
    window = open_window
    window.theme.apply()
    try:
        window.show()
        window.activateWindow()
        QApplication.processEvents()
        first = window.nextInFocusChain()
        while not (first.isVisible() and first.isEnabled() and first.focusPolicy() & Qt.FocusPolicy.TabFocus):
            assert first is not window
            first = first.nextInFocusChain()
        assert first is window.topbar._left_column
        ring = QColor(window.theme.tokens.focus)
        for stop in bar_order(window):
            assert stop.focusPolicy() & Qt.FocusPolicy.TabFocus and not stop.focusPolicy() & Qt.FocusPolicy.ClickFocus
            stop.clearFocus()
            assert stop.grab().toImage().pixelColor(1, stop.height() // 2) != ring
            focus_on(window, stop)
            assert stop.grab().toImage().pixelColor(1, stop.height() // 2) == ring, type(stop).__name__
    finally:
        QApplication.instance().setStyleSheet("")
