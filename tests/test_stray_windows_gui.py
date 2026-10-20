# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""No widget flashes up as a window of its own while the workspace changes slides: a widget without a parent
that is shown, even for one event, is a small top-level window in the middle of the screen."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from slidemage import deck_scan
from slidemage.ui.kit.widgets import clear_layout
from conftest import EXAMPLE_PROJECT, build_window


class _TopLevelShows(QObject):
    """Every widget shown as a window, except the ones listed as expected."""

    def __init__(self, *expected: QWidget) -> None:
        super().__init__()
        self.expected = expected
        self.shown: list[str] = []

    def eventFilter(self, obj, event) -> bool:      # noqa: N802 -- Qt's name
        if (event.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow()
                and obj not in self.expected):
            self.shown.append(f"{type(obj).__name__} {obj.objectName()!r}")
        return False


def test_clear_layout_never_shows_a_widget_it_removes(qapp):
    """A widget built and replaced before its parent was ever painted is not shown once its parent is gone."""
    parent = QWidget()
    layout = QVBoxLayout(parent)
    parent.show()
    label = QLabel("built, never shown")
    layout.addWidget(label)
    spy = _TopLevelShows(parent)
    qapp.installEventFilter(spy)
    try:
        clear_layout(layout)
        QTest.qWait(50)
    finally:
        qapp.removeEventFilter(spy)
        parent.close()
    assert spy.shown == []


def test_an_eliding_chip_shortens_its_text_instead_of_asking_for_room(qapp):
    from slidemage.ui.kit.widgets import Chip

    name = "qwen3-coder-next:32k · Ollama, a very long local model name"
    plain, eliding = Chip(name), Chip(name, elide=True)
    assert eliding.minimumSizeHint().width() < 120 < plain.minimumSizeHint().width()
    assert eliding.text() == name


def test_clicking_slides_opens_no_window_of_its_own(qapp, monkeypatch):
    """The real window, in the Source view (no renders): a click on a slide rebuilds the Source view's status
    line and the side panel; none of their pieces may be shown before it has a parent."""
    window = build_window(monkeypatch)
    window.show()
    deck = next(d for d in deck_scan.scan_decks(EXAMPLE_PROJECT) if d.name == "slidemage-manual")
    window.state.set_deck(deck)
    window.state.set_mode("source")
    QTest.qWait(200)
    spy = _TopLevelShows(window, *QApplication.topLevelWidgets())
    qapp.installEventFilter(spy)
    try:
        tree = window.slide_list.tree
        for item in tree.slide_items()[:4]:
            tree.setCurrentItem(item)
            tree.itemClicked.emit(item, 0)
            QTest.qWait(100)
    finally:
        qapp.removeEventFilter(spy)
    assert spy.shown == []
