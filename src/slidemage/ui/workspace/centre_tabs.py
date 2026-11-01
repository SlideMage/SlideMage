# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The tabs of the centre column (docs/plans/centre-tabs.md): which of them are open, which one is shown, and the
order in which they were last used; and the strip that draws them.

`CentreTabs` is the model and needs no window. The first tab is the slide tab, always there and never closed: it
shows the focused slide, as the centre always did. A file tab holds a file of its own, opened on purpose (a deck's
source, SlideMage.bib, test-slides.tex), until it is closed. Each tab remembers the mode (Preview, Source, ...) it
was last shown in; a file tab shows the Source view alone.

`TabStrip` draws the tabs and says what the user did to them (activate, close with the "x" or the middle button);
what that means is the centre's (centre.py).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QSizePolicy

from ..kit import kit_qss as q
from ..kit.widgets import ClickFrame, ElidedLabel, IconButton, Surface

SLIDE, FILE = "slide", "file"
TAB_HEIGHT = 34
TAB_MIN_WIDTH = 96      # narrower than their text they elide; with less room than this they scroll
TAB_MAX_WIDTH = 260


@dataclass(eq=False)
class CentreTab:
    kind: str                                       # SLIDE or FILE
    path: Optional[Path] = None                     # None for the slide tab, which follows the focused slide
    mode: str = "preview"                           # the mode it was last shown in
    on_saved: Optional[Callable[[str], None]] = None    # runs after each save of the file (a deck's after_deck_edit)

    @property
    def closable(self) -> bool:
        return self.kind == FILE

    @property
    def source_only(self) -> bool:
        """The tab has no Preview or Details: a deck's source or SlideMage.bib is not a slide."""
        return self.kind == FILE


class CentreTabs(QObject):
    """The open tabs in strip order, the one shown and the most-recently-used order (Ctrl+Tab)."""

    tabs_changed = Signal()         # a tab was added or closed
    active_changed = Signal(object)     # the CentreTab now shown

    def __init__(self, mode: str = "preview", parent: QObject | None = None) -> None:
        super().__init__(parent)
        slide = CentreTab(SLIDE, mode=mode)
        self._tabs: list[CentreTab] = [slide]
        self._mru: list[CentreTab] = [slide]            # most recently used first
        self._active = slide
        self._cycle: Optional[list[CentreTab]] = None   # the MRU order while Ctrl is held through a Ctrl+Tab series
        self._cycle_at = 0

    @property
    def tabs(self) -> list[CentreTab]:
        return list(self._tabs)

    @property
    def slide_tab(self) -> CentreTab:
        return self._tabs[0]

    @property
    def active(self) -> CentreTab:
        return self._active

    @property
    def mru(self) -> list[CentreTab]:
        return list(self._mru)

    @property
    def cycling(self) -> bool:
        """A Ctrl+Tab series is under way (cycle() without end_cycle())."""
        return self._cycle is not None

    def tab_for(self, path: Path) -> Optional[CentreTab]:
        return next((t for t in self._tabs if t.kind == FILE and t.path == path), None)

    def add_file(self, path: Path, on_saved: Optional[Callable[[str], None]] = None) -> CentreTab:
        """The file tab of `path`, opened at the end of the strip unless it has one; it is not shown yet."""
        tab = self.tab_for(path)
        if tab is not None:
            if on_saved is not None:
                tab.on_saved = on_saved
            return tab
        tab = CentreTab(FILE, path, "source", on_saved)
        self._tabs.append(tab)
        self._mru.append(tab)
        self.tabs_changed.emit()
        return tab

    def activate(self, tab: CentreTab) -> None:
        """Show `tab`; it becomes the most recently used."""
        self._cycle = None
        self._set_active(tab, touch=True)

    def close(self, tab: CentreTab) -> Optional[CentreTab]:
        """Close a file tab. When it was the one shown, the most recently used of the others is shown instead and
        returned; else None."""
        if not tab.closable or tab not in self._tabs:
            raise ValueError("only an open file tab can be closed")
        self._cycle = None
        was_active = tab is self._active
        self._tabs.remove(tab)
        self._mru.remove(tab)
        self.tabs_changed.emit()
        if not was_active:
            return None
        self._set_active(self._mru[0], touch=False)
        return self._active

    def cycle(self, step: int = 1) -> CentreTab:
        """Ctrl+Tab (`step` 1) and Ctrl+Shift+Tab (-1): show the next (previous) tab in most-recently-used order.
        A series of calls walks on through that order; end_cycle() (Ctrl released) makes the tab it stopped at the
        most recently used, so that a single Ctrl+Tab goes back and forth between the last two tabs."""
        if self._cycle is None:
            self._cycle, self._cycle_at = list(self._mru), 0
        self._cycle_at = (self._cycle_at + step) % len(self._cycle)
        self._set_active(self._cycle[self._cycle_at], touch=False)
        return self._active

    def end_cycle(self) -> None:
        if self._cycle is not None:
            self._cycle = None
            self._touch(self._active)

    def _set_active(self, tab: CentreTab, *, touch: bool) -> None:
        if tab not in self._tabs:
            raise ValueError("not an open tab")
        if touch:
            self._touch(tab)
        if tab is not self._active:
            self._active = tab
            self.active_changed.emit(tab)

    def _touch(self, tab: CentreTab) -> None:
        self._mru.remove(tab)
        self._mru.insert(0, tab)


class _TabButton(ClickFrame):
    """One tab: its name, elided to the room it gets, and for a file tab an "x". The left button activates it, the
    middle button closes a file tab."""

    close_requested = Signal()

    def __init__(self, tab: CentreTab) -> None:
        super().__init__()
        self.tab = tab
        self.setObjectName(q.TAB)
        self.setProperty("active", False)
        self.setFixedHeight(TAB_HEIGHT)
        self.setMinimumWidth(TAB_MIN_WIDTH)
        self.setMaximumWidth(TAB_MAX_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 0, 4 if tab.closable else 12, 0)
        row.setSpacing(2)
        self.label = ElidedLabel()
        self.label.setObjectName(q.TAB_LABEL)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(self.label, 1)
        self.close_button: Optional[IconButton] = None
        if tab.closable:
            self.close_button = IconButton("close", "Close tab", size=14)
            self.close_button.clicked.connect(self.close_requested)
            row.addWidget(self.close_button)

    def set_label(self, text: str, tooltip: str) -> None:
        self.label.set_full_text(text)
        self.label.setToolTip(tooltip or text)
        self.setAccessibleName(text)
        self.updateGeometry()

    def set_active(self, active: bool) -> None:
        if self.property("active") != active:
            self.setProperty("active", active)
            for widget in (self, self.label):
                widget.style().unpolish(widget)
                widget.style().polish(widget)

    def sizeHint(self):
        hint = super().sizeHint()
        self.label.ensurePolished()
        room = self.label.fontMetrics().horizontalAdvance(self.label.full_text()) + 10
        margins = self.layout().contentsMargins()
        extra = margins.left() + margins.right() + (self.close_button.width() + 2 if self.close_button else 0)
        hint.setWidth(min(TAB_MAX_WIDTH, max(TAB_MIN_WIDTH, room + extra)))
        return hint

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton and self.tab.closable and self.rect().contains(
                event.position().toPoint()):
            self.close_requested.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
        elif event.key() == Qt.Key.Key_Delete and self.tab.closable:
            self.close_requested.emit()
        else:
            super().keyPressEvent(event)


class _TabScroll(QScrollArea):
    """The tabs' row: the wheel moves it sideways."""

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta()
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - (delta.x() or delta.y()))
        event.accept()


class TabStrip(Surface):
    """The tabs above the centre column's views. It draws what the centre tells it (set_tabs, set_active,
    set_label) and reports clicks; with more tabs than fit, they shrink to TAB_MIN_WIDTH, then the row scrolls."""

    activate_requested = Signal(object)     # the CentreTab clicked
    close_requested = Signal(object)        # the CentreTab whose "x" or middle button was pressed

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName(q.TAB_STRIP)
        self._buttons: dict[CentreTab, _TabButton] = {}
        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 0, 8, 0)
        outer.setSpacing(2)
        self._left = IconButton("chevron_left", "Scroll the tabs left", size=16)
        self._right = IconButton("chevron_right", "Scroll the tabs right", size=16)
        self._left.clicked.connect(lambda: self._scroll_by(-1))
        self._right.clicked.connect(lambda: self._scroll_by(1))
        self._scroll = _TabScroll()
        self._scroll.setObjectName(q.SURFACE)
        self._scroll.viewport().setObjectName(q.SURFACE)
        self._scroll.setFrameShape(_TabScroll.Shape.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFixedHeight(TAB_HEIGHT)
        inner = Surface()
        self._row = QHBoxLayout(inner)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(2)
        self._row.addStretch(1)
        self._scroll.setWidget(inner)
        outer.addWidget(self._left)
        outer.addWidget(self._scroll, 1)
        outer.addWidget(self._right)
        self._active: Optional[CentreTab] = None
        # Once the layout has the new sizes: the arrows, and the tab on show scrolled into view.
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(0)
        self._settle.timeout.connect(self._settled)
        self._scroll.horizontalScrollBar().valueChanged.connect(lambda _value: self._arrows())
        self._scroll.horizontalScrollBar().rangeChanged.connect(lambda _low, _high: self._arrows())
        self._arrows()

    def tab_buttons(self) -> list[_TabButton]:
        """The tabs' widgets in strip order (tests, and the centre's labels)."""
        return list(self._buttons.values())

    def set_tabs(self, tabs: list[CentreTab], labels: Callable[[CentreTab], tuple[str, str]]) -> None:
        """Show exactly `tabs`, in this order; `labels(tab)` is (text, tooltip) for a tab that is new."""
        for tab in [t for t in self._buttons if t not in tabs]:
            button = self._buttons.pop(tab)
            self._row.removeWidget(button)
            button.hide()
            button.deleteLater()
        for index, tab in enumerate(tabs):
            button = self._buttons.get(tab)
            if button is None:
                button = self._buttons[tab] = _TabButton(tab)
                button.set_label(*labels(tab))
                button.clicked.connect(lambda t=tab: self.activate_requested.emit(t))
                button.close_requested.connect(lambda t=tab: self.close_requested.emit(t))
                self._row.insertWidget(index, button)
        self._buttons = {tab: self._buttons[tab] for tab in tabs}
        self.set_active(self._active)
        self._settle.start()

    def set_active(self, tab: Optional[CentreTab]) -> None:
        self._active = tab
        for other, button in self._buttons.items():
            button.set_active(other is tab)
        self._settle.start()

    def set_label(self, tab: CentreTab, text: str, tooltip: str = "") -> None:
        button = self._buttons.get(tab)
        if button is not None and button.label.full_text() != text:
            button.set_label(text, tooltip)
            self._settle.start()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._arrows()

    def _settled(self) -> None:
        button = self._buttons.get(self._active)
        if button is not None and button.isVisibleTo(self):
            self._scroll.ensureWidgetVisible(button, 24, 0)
        self._arrows()

    def _scroll_by(self, direction: int) -> None:
        bar = self._scroll.horizontalScrollBar()
        bar.setValue(bar.value() + direction * max(1, self._scroll.viewport().width() * 3 // 4))

    def _arrows(self) -> None:
        """The scroll arrows are there only when the tabs do not fit."""
        bar = self._scroll.horizontalScrollBar()
        overflow = bar.maximum() > 0
        self._left.setVisible(overflow)
        self._right.setVisible(overflow)
        self._left.setEnabled(bar.value() > 0)
        self._right.setEnabled(bar.value() < bar.maximum())
