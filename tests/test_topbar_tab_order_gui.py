# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The keyboard order of the workspace's top bar (workspace v6 follow-up): Tab and Shift+Tab walk the bar left to
right and go on into the slide list, the centre and the side panels; the deck switcher is a Tab stop that opens with
Enter, Space and Down; every stop of the bar activates from the keyboard and shows the focus ring."""
from __future__ import annotations

import pytest
import shiboken6
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from conftest import qapp as qapp  # noqa: F401 -- a fixture
from test_ai_switch_gui import window as window  # noqa: F401 -- a fixture


def focus_on(window, widget: QWidget) -> QWidget:
    window.activateWindow()
    QApplication.processEvents()
    widget.setFocus(Qt.FocusReason.TabFocusReason)
    assert QApplication.focusWidget() is widget
    return widget


def tab(times: int = 1, *, back: bool = False) -> list[QWidget]:
    reached = []
    for _ in range(times):
        QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Backtab if back else Qt.Key.Key_Tab,
                       Qt.KeyboardModifier.ShiftModifier if back else Qt.KeyboardModifier.NoModifier)
        reached.append(QApplication.focusWidget())
    return reached


def bar_order(window, *, images: bool = False) -> list[QWidget]:
    """The stops of the top bar, left to right: what the user sees. A segmented control is one stop, its selected
    segment (←/→ move inside it)."""
    bar = window.topbar
    stops = [bar._left_column, bar._deck_button, bar.ai_switch.segments.current_button(), bar.ai_switch.caret,
             bar._views.current_button(), bar._languages.current_button(),
             *([bar._autosave] if bar._autosave.isVisible() else []), bar._modes.current_button(),
             *bar._compile.buttons(), *([bar._images] if images else []), bar._right_column]
    xs = [stop.mapTo(bar, stop.rect().topLeft()).x() for stop in stops if stop.isVisible()]
    assert xs == sorted(xs) and len(xs) == len(stops)        # the list is the visual order
    return stops


@pytest.fixture
def open_window(window):
    window._set_column_hidden("left", False)
    window._set_column_hidden("right", False)
    QApplication.processEvents()
    return window


@pytest.mark.parametrize("width, density", [(2000, "full"), (1400, "narrow"), (1024, "tiny")])
def test_tab_walks_the_bar_in_visual_order_and_back(open_window, width, density):
    window = open_window
    window.resize(width, 800)
    QApplication.processEvents()
    assert window.topbar._density == density
    order = bar_order(window)
    focus_on(window, order[0])
    assert tab(len(order) - 1) == order[1:]
    assert tab()[0] is window.slide_list.find                       # the bar goes on into the slide list
    assert tab(back=True)[0] is order[-1]
    assert tab(len(order) - 1, back=True) == order[-2::-1]
    assert order[0] is window.topbar._left_column


def test_tab_order_with_images_open(open_window):
    window = open_window
    window._toggle_images()
    QApplication.processEvents()
    order = bar_order(window, images=True)
    assert window.topbar._images in order
    focus_on(window, order[0])
    assert tab(len(order) - 1) == order[1:]
    assert tab(len(order) - 1, back=True) == order[-2::-1]
    window._toggle_images()                                          # closed again: "Close images" is skipped
    QApplication.processEvents()
    order = bar_order(window)
    focus_on(window, order[0])
    assert tab(len(order) - 1) == order[1:]


def test_left_column_toggle_is_the_first_stop_of_the_window(window):
    window.activateWindow()
    QApplication.processEvents()
    chain = [window]
    while (nxt := chain[-1].nextInFocusChain()) is not window:
        chain.append(nxt)
    first = next(w for w in chain[1:] if w.isVisible() and w.isEnabled() and w.focusPolicy() & Qt.FocusPolicy.TabFocus)
    assert first is window.topbar._left_column


def test_bar_continues_into_the_centre_before_the_side_panels(open_window):
    window = open_window
    window.state.set_mode("details")
    QApplication.processEvents()
    focus_on(window, window.topbar._right_column)
    reached = tab(60)
    centre = [i for i, w in enumerate(reached) if window.centre.isAncestorOf(w)]
    side = [i for i, w in enumerate(reached) if window.side_panels.isAncestorOf(w)]
    slides = [i for i, w in enumerate(reached) if window.slide_list.isAncestorOf(w)]
    assert slides and centre and side and max(slides) < min(centre) and max(centre) < min(side)


def test_deck_switcher_is_a_stop_and_opens_with_the_keyboard(window):
    bar = window.topbar
    focus_on(window, bar._left_column)
    deck = tab()[0]
    assert deck is bar._deck_button
    for key in (Qt.Key.Key_Return, Qt.Key.Key_Space, Qt.Key.Key_Down):
        QTest.keyClick(focus_on(window, deck), key)
        menu = next(m for m in bar.findChildren(QWidget) if m.objectName() == "kitMenu" and m.isVisible())
        assert menu.isVisible()
        current = [row for row in menu._rows if row.property("current")]
        assert [row.key for row in current] == [menu.current_key] and menu.current_key   # opens on the current deck
        QTest.keyClick(menu, Qt.Key.Key_Escape)
        QApplication.processEvents()
        assert not shiboken6.isValid(menu) or not menu.isVisible()
        assert window.focusWidget() is deck                         # Esc returns to the switcher


def test_deck_switcher_menu_picks_with_the_keyboard(window):
    bar = window.topbar
    assert len(bar._decks) > 1
    deck = focus_on(window, bar._deck_button)
    before = window.state.deck
    QTest.keyClick(deck, Qt.Key.Key_Return)
    menu = next(m for m in bar.findChildren(QWidget) if m.objectName() == "kitMenu" and m.isVisible())
    QTest.keyClick(menu, Qt.Key.Key_Down)
    QTest.keyClick(menu, Qt.Key.Key_Return)
    assert window.state.deck is not before and window.focusWidget() is deck


def test_a_click_on_the_deck_switcher_does_not_take_the_focus(window):
    bar = window.topbar
    assert bar._deck_button.focusPolicy() == Qt.FocusPolicy.TabFocus


def test_every_stop_of_the_bar_activates_with_enter_or_space(open_window):
    window = open_window
    bar = window.topbar
    pressed = []
    bar.command.disconnect(window._on_command)         # Compile would run
    bar.command.connect(pressed.append)
    for control in (bar._views, bar._languages, bar._modes):
        control.changed.connect(pressed.append)
    keys = [(bar._views, Qt.Key.Key_Return), (bar._languages, Qt.Key.Key_Space), (bar._modes, Qt.Key.Key_Enter)]
    expected = [bar._views.current(), bar._languages.current(), bar._modes.current()]
    for control, key in keys:
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
        ring = QColor(window.theme.tokens.focus)
        for stop in bar_order(window):
            assert stop.focusPolicy() & Qt.FocusPolicy.TabFocus and not stop.focusPolicy() & Qt.FocusPolicy.ClickFocus
            stop.clearFocus()
            assert stop.grab().toImage().pixelColor(1, stop.height() // 2) != ring
            focus_on(window, stop)
            assert stop.grab().toImage().pixelColor(1, stop.height() // 2) == ring, type(stop).__name__
    finally:
        QApplication.instance().setStyleSheet("")
