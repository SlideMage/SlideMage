# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The tabs of the centre column (docs/plans/centre-tabs.md): which of them are open, which one is shown, and the
order in which they were last used; and the strip that draws them.

`CentreTabs` is the model and needs no window. Each open deck has one working tab (docs/plans/tab-contexts.md, E1): it
shows that deck's focused slide, as the one slide tab did before; closing it closes the deck (E2), except the last one.
A deck's tabs stay together, its working tab first, each tab carrying a stripe in the colour of its deck (E7). A file
tab holds a file of its own, opened on purpose (a deck's
source, SlideMage.bib, test-slides.tex, or a slide's file), until it is closed. Each tab remembers the mode (Preview,
Source, ...) it was last shown in; a file tab of a file that is no slide shows the Source view alone, a slide's file
tab has every mode.

`TabStrip` draws the tabs and says what the user did to them (activate, close with the "x", the middle button or a
tab's right-click menu: Close, Close others, Close all to the right, Reveal in Explorer, D5 of the plan); what that
means is the centre's (centre.py).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QSizePolicy

from ..kit.tokens import SPACE
from ..kit import kit_qss as q
from ..kit.widgets import ClickFrame, ElidedLabel, IconButton, PopoverMenu, Surface
from .state import DeckWork

DECK, FILE = "deck", "file"
SLIDE = DECK            # the working tab was "the slide tab" before docs/plans/tab-contexts.md step 3b
DECK_COLOURS = 6        # the stripes of the decks' tabs: one of this many hues, in the order the decks were opened
FOLLOW = "follow"       # a tab's context (docs/plans/tab-contexts.md): "whatever state.deck is"; a Path would name a deck, None no deck
TAB_HEIGHT = 34
TAB_MIN_WIDTH = 96      # narrower than their text they elide; with less room than this they scroll
TAB_MAX_WIDTH = 260


@dataclass(eq=False)
class CentreTab:
    kind: str                                       # DECK (a deck's working tab) or FILE
    path: Optional[Path] = None                     # None for a working tab, which follows its deck's focused slide
    mode: str = "preview"                           # the mode it was last shown in
    on_saved: Optional[Callable[[str], None]] = None    # runs after each save of the file (a deck's after_deck_edit)
    slide: bool = False                             # a file tab of a slide's file (current or a frozen version)
    occurrence: Optional[tuple] = None              # the deck row (SlideRow.key) it was opened from, if any
    context: object = FOLLOW                        # the deck it belongs to: a deck's Path, or None; FOLLOW (the deck on show) only before the window binds it
    work: Optional[DeckWork] = None                 # a working tab: its deck as it was left (kept when another deck is shown)
    deck_closable: bool = False                     # a working tab can be closed while another deck is open (set by CentreTabs)

    @property
    def closable(self) -> bool:
        return self.kind == FILE or (self.kind == DECK and self.deck_closable)

    @property
    def source_only(self) -> bool:
        """The tab has no Preview or Details: a deck's source or SlideMage.bib is not a slide."""
        return self.kind == FILE and not self.slide


class CentreTabs(QObject):
    """The open tabs in strip order, the one shown and the most-recently-used order (Ctrl+Tab)."""

    tabs_changed = Signal()         # a tab was added or closed
    active_changed = Signal(object)     # the CentreTab now shown

    def __init__(self, mode: str = "preview", parent: QObject | None = None) -> None:
        super().__init__(parent)
        slide = CentreTab(DECK, mode=mode)             # the first deck's working tab, bound to its deck by the window
        self._tabs: list[CentreTab] = [slide]
        self._mru: list[CentreTab] = [slide]            # most recently used first
        self._active = slide
        self._colours: dict[Path, int] = {}             # a deck's stripe, by the order the decks were opened
        self._cycle: Optional[list[CentreTab]] = None   # the MRU order while Ctrl is held through a Ctrl+Tab series
        self._cycle_at = 0

    @property
    def tabs(self) -> list[CentreTab]:
        return list(self._tabs)

    @property
    def slide_tab(self) -> CentreTab:
        """The first working tab (the only one while a single deck is open)."""
        return next(t for t in self._tabs if t.kind == DECK)

    @property
    def working_tabs(self) -> list[CentreTab]:
        return [t for t in self._tabs if t.kind == DECK]

    def working_tab(self, context) -> Optional[CentreTab]:
        """The working tab of the deck `context` (its Path)."""
        return next((t for t in self._tabs if t.kind == DECK and t.context == context), None)

    def add_deck(self, context: Path, mode: str = "preview") -> CentreTab:
        """The working tab of the deck `context`, opened after the last tab of any deck (tab-contexts.md E7) unless it
        has one; it is not shown yet."""
        tab = self.working_tab(context)
        if tab is not None:
            return tab
        tab = CentreTab(DECK, mode=mode, context=context)
        last = max((i for i, t in enumerate(self._tabs) if isinstance(t.context, Path)), default=-1)
        self._tabs.insert(last + 1, tab)
        self._mru.append(tab)
        self._sync_closable()
        self.tabs_changed.emit()
        return tab

    def deck_colour(self, context) -> Optional[int]:
        """The stripe of the deck `context`: 0 to DECK_COLOURS - 1, given in the order the decks are opened and used again
        after that; None for a tab with no deck."""
        if not isinstance(context, Path):
            return None
        if context not in self._colours:
            self._colours[context] = len(self._colours) % DECK_COLOURS
        return self._colours[context]

    def order_decks(self, contexts: list) -> None:
        """Put the working tabs in the order of `contexts` (the decks' files; restore at start), the others after them in
        their order, each deck's other tabs with it (regroup)."""
        rank = {c: i for i, c in enumerate(contexts)}
        working = sorted(self.working_tabs, key=lambda t: rank.get(t.context, len(rank)))
        self._tabs = working + [t for t in self._tabs if t.kind != DECK]
        self.regroup()
        self.tabs_changed.emit()

    def set_deck_colour(self, context: Path, colour: int) -> None:
        """A deck's stripe as it was saved (restore at start)."""
        self._colours[context] = colour % DECK_COLOURS

    def retarget_deck(self, old: Path, new: Path) -> None:
        """The deck's file was renamed or archived: its tabs and its stripe follow it."""
        if old == new:
            return
        for tab in self._tabs:
            if tab.context == old:
                tab.context = new
        if old in self._colours:
            self._colours[new] = self._colours.pop(old)

    def regroup(self) -> None:
        """Put the tabs in the order of E7: each deck's working tab, then the other tabs of that deck in their order, then
        the tabs of no deck."""
        ordered: list[CentreTab] = []
        for work in self.working_tabs:
            ordered.append(work)
            ordered += [t for t in self._tabs if t.kind == FILE and isinstance(t.context, Path) and t.context == work.context]
        ordered += [t for t in self._tabs if t not in ordered]
        if ordered != self._tabs:
            self._tabs = ordered
            self.tabs_changed.emit()

    def _sync_closable(self) -> None:
        many = len(self.working_tabs) > 1
        for tab in self._tabs:
            tab.deck_closable = many

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

    def add_file(self, path: Path, on_saved: Optional[Callable[[str], None]] = None, *, slide: bool = False,
                 occurrence: Optional[tuple] = None, mode: str = "source") -> CentreTab:
        """The file tab of `path`, opened at the end of the strip unless it has one; it is not shown yet. `slide`:
        the file is a slide's, so the tab has every mode; it starts in `mode`."""
        tab = self.tab_for(path)
        if tab is not None:
            if on_saved is not None:
                tab.on_saved = on_saved
            return tab
        tab = CentreTab(FILE, path, mode if slide else "source", on_saved, slide, occurrence)
        self._tabs.append(tab)
        self._mru.append(tab)
        self.tabs_changed.emit()
        return tab

    def activate(self, tab: CentreTab) -> None:
        """Show `tab`; it becomes the most recently used."""
        self._cycle = None
        self._set_active(tab, touch=True)

    def close(self, tab: CentreTab) -> Optional[CentreTab]:
        """Close a file tab, or a working tab while another is open (the window closes the deck's other tabs first). When
        it was the one shown, the most recently used of the others is shown instead and returned; else None."""
        if not tab.closable or tab not in self._tabs:
            raise ValueError("only an open file tab can be closed")
        self._cycle = None
        was_active = tab is self._active
        self._tabs.remove(tab)
        self._mru.remove(tab)
        self._sync_closable()
        self.tabs_changed.emit()
        if not was_active:
            return None
        self._set_active(self._mru[0], touch=False)
        return self._active

    def step(self, direction: int) -> CentreTab:
        """Ctrl+PgDn (`direction` 1) and Ctrl+PgUp (-1): the next (previous) tab in strip order, wrapping past
        either end; shown and made the most recently used, as a click does."""
        index = self._tabs.index(self._active)
        self.activate(self._tabs[(index + direction) % len(self._tabs)])
        return self._active

    def close_others(self, tab: CentreTab) -> list[CentreTab]:
        """The other file tabs (the tab strip's context menu's Close others), in strip order; a deck is closed from its
        own working tab."""
        return [t for t in self._tabs if t.kind == FILE and t is not tab]

    def close_right(self, tab: CentreTab) -> list[CentreTab]:
        """The file tabs after `tab` in strip order (Close all to the right)."""
        return [t for t in self._tabs[self._tabs.index(tab) + 1:] if t.kind == FILE]

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
    close_others_requested = Signal()
    close_right_requested = Signal()
    reveal_requested = Signal()
    show_in_deck_requested = Signal()

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
        row.setContentsMargins(SPACE.xl, 0, SPACE.xs if tab.kind in (FILE, DECK) else SPACE.xl, 0)
        self.deck_name = ""
        row.setSpacing(SPACE.s_2xs)
        self.label = ElidedLabel()
        self.label.setObjectName(q.TAB_LABEL)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(self.label, 1)
        self.close_button: Optional[IconButton] = None
        if tab.kind in (FILE, DECK):
            # Compact tab actions preserve the tab height and leave room for the filename. A working tab's is there
            # only while another deck is open (set_closable).
            self.close_button = IconButton("close", "Close tab" if tab.kind == FILE else "Close deck", size=14)
            self.close_button.clicked.connect(self.close_requested)
            row.addWidget(self.close_button)
            self.close_button.setVisible(tab.closable)

    def set_closable(self, closable: bool) -> None:
        if self.close_button is not None and self.close_button.isVisibleTo(self) != closable:
            self.close_button.setVisible(closable)
            self.updateGeometry()

    def set_deck(self, colour: Optional[int], name: str = "") -> None:
        """The stripe of the deck the tab belongs to (None: no stripe) and its name, for the menu."""
        self.deck_name = name
        value = "" if colour is None else str(colour)
        if self.property("deckColour") != value:
            self.setProperty("deckColour", value)
            self.style().unpolish(self)
            self.style().polish(self)

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
        extra = margins.left() + margins.right() + (
            self.close_button.width() + 2 if self.close_button is not None and self.close_button.isVisibleTo(self) else 0)
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

    def _menu(self) -> PopoverMenu:
        """Close, Close others, Close all to the right, Reveal in Explorer (D5 of the plan)."""
        menu = PopoverMenu(self, min_width=200)
        menu.add_item("close", "Close deck" if self.tab.kind == DECK else "Close", enabled=self.tab.closable)
        menu.add_item("close_others", "Close others")
        menu.add_item("close_right", "Close all to the right")
        menu.add_separator()
        if self.tab.kind == FILE and self.deck_name:
            menu.add_item("show_in_deck", f"Show in deck {self.deck_name}")
        menu.add_item("reveal", "Reveal in Explorer")
        menu.triggered.connect(self._on_menu_action)
        return menu

    def contextMenuEvent(self, event) -> None:
        menu = self._menu()
        menu.closed.connect(menu.deleteLater)
        menu.popup_at(self.mapToGlobal(event.pos()))
        event.accept()

    def _on_menu_action(self, key: str) -> None:
        {
            "close": self.close_requested,
            "close_others": self.close_others_requested,
            "close_right": self.close_right_requested,
            "reveal": self.reveal_requested,
            "show_in_deck": self.show_in_deck_requested,
        }[key].emit()


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
    close_others_requested = Signal(object)     # its context menu's Close others
    close_right_requested = Signal(object)      # its context menu's Close all to the right
    reveal_requested = Signal(object)           # its context menu's Reveal in Explorer
    show_in_deck_requested = Signal(object)     # its context menu's Show in deck: the deck's working tab

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName(q.TAB_STRIP)
        self._buttons: dict[CentreTab, _TabButton] = {}
        outer = QHBoxLayout(self)
        outer.setContentsMargins(SPACE.md, 0, SPACE.md, 0)
        outer.setSpacing(SPACE.s_2xs)
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
        self._row.setSpacing(SPACE.s_2xs)
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

    def set_tabs(self, tabs: list[CentreTab], labels: Callable[[CentreTab], tuple[str, str]],
                 decks: Optional[Callable[[CentreTab], Optional[tuple[int, str]]]] = None) -> None:
        """Show exactly `tabs`, in this order; `labels(tab)` is (text, tooltip) for a tab that is new, `decks(tab)` the
        (stripe, name) of the deck a tab belongs to, if any."""
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
                button.close_others_requested.connect(lambda t=tab: self.close_others_requested.emit(t))
                button.close_right_requested.connect(lambda t=tab: self.close_right_requested.emit(t))
                button.reveal_requested.connect(lambda t=tab: self.reveal_requested.emit(t))
                button.show_in_deck_requested.connect(lambda t=tab: self.show_in_deck_requested.emit(t))
                self._row.insertWidget(index, button)
        self._buttons = {tab: self._buttons[tab] for tab in tabs}
        for index, tab in enumerate(tabs):
            button = self._buttons[tab]
            if self._row.indexOf(button) != index:           # the order changed (a deck's tabs are kept together)
                self._row.removeWidget(button)
                self._row.insertWidget(index, button)
            button.set_closable(tab.closable)
            deck = decks(tab) if decks is not None else None
            button.set_deck(*(deck if deck is not None else (None, "")))
        self.set_active(self._active)
        self._settle.start()

    def set_active(self, tab: Optional[CentreTab]) -> None:
        self._active = tab
        for other, button in self._buttons.items():
            button.set_active(other is tab)
        self._settle.start()

    def set_label(self, tab: CentreTab, text: str, tooltip: str = "") -> None:
        button = self._buttons.get(tab)
        if button is not None and (button.label.full_text() != text or button.label.toolTip() != (tooltip or text)):
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
