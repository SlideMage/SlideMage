# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The right column (UI_REDESIGN_PLAN.md, steps 6 and 10; workspace v6 handoff, section 3): a panel picker and the
chosen panel for the focused slide, and below them, 12 px apart, the assistant card (assistant.py). The panels
take 38 % of the column and the assistant the rest, but the assistant is never shorter than 380 px, so the panels
give way first (down to 128 px). "Focus assistant" in the assistant's header hides the panels' card and brings it
back; it is not remembered.

The picker (▾) names the shown panel and lists the others with a few facts about the
slide. The choice is remembered across sessions (app_settings, like the centre's mode).
The panels themselves are in panels/; they follow WorkspaceState's deck, slide, view and
language, and the window calls `refresh()` after anything that changed the project, because
a rescan of the open deck is no state change. A panel's pending edit (`SidePanel.flush`) is saved
before anything it belongs to changes, and counts as an unsaved edit of the workspace."""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QScrollArea, QSplitter, QSplitterHandle, QVBoxLayout, QWidget)

from ... import app_settings
from ...project import ProjectContext
from .. import layout_settings
from ..kit import kit_qss as q
from ..kit.widgets import Card, DropdownButton, PopoverMenu, Surface
from .assistant import AssistantArea
from .panels import PANELS
from .panels.base import PanelActions, SidePanel
from .state import SETTLE_MS, WorkspaceState

WIDTH = 360   # the prototype's width of the column: the default, and what a double-click on the handle gives back
# The least it may be dragged to: the widest content still fits (the Visibility panel's card, 311 px; the
# assistant's controls) -- the model chip shortens its name rather than widen the column.
MIN_WIDTH = 312
MAX_WIDTH = 900
WIDTH_SETTING = "right_column_width"
SETTING = "side_panel"
GAP = 12   # between the two cards
DEFAULT_PANELS_SHARE = 0.38   # the panels' part of the column's height; the assistant gets the rest
SHARE_SETTING = "panels_share"
PANEL_MIN_HEIGHT = 128   # 24 px padding, 32 px picker, 8 px gap and a 64 px content row


def remembered_width(project: ProjectContext) -> int:
    """The width the user dragged the column to, within its limits (WIDTH if never)."""
    value = layout_settings.get(WIDTH_SETTING)
    if value is None:   # once: this project's old width becomes the user's
        value = app_settings.get(project, WIDTH_SETTING)
        layout_settings.set(WIDTH_SETTING, value if isinstance(value, int) else WIDTH)
    return min(max(value, MIN_WIDTH), MAX_WIDTH) if isinstance(value, int) else WIDTH


class _ResetHandle(QSplitterHandle):
    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.splitter().reset_requested.emit()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)


class _ColumnSplit(QSplitter):
    """The panels' card above the assistant; a double-click on the divider gives each its default height again."""
    reset_requested = Signal()

    def createHandle(self) -> QSplitterHandle:
        return _ResetHandle(self.orientation(), self)


class SidePanels(QWidget):
    def __init__(self, app, state: WorkspaceState, actions: PanelActions) -> None:
        super().__init__()
        self.setMinimumWidth(MIN_WIDTH)
        self.setMaximumWidth(MAX_WIDTH)
        self.project = state.project
        self._state = state
        self._stale = False     # the shown panel is behind the state, as the card was hidden when it was due
        self._built_for: tuple | None = None    # the state the shown panel was last built for
        # Laid over the shown panel while its rebuild waits: it takes the clicks meant for the content of the slide
        # that was left, without greying that content out on every click (or for as long as an arrow key is held).
        self._shield = QWidget(self)
        self._shield.hide()
        self.panels: dict[str, SidePanel] = {cls.key: cls(app, state, actions) for cls in PANELS}
        remembered = app_settings.get(state.project, SETTING)
        self.current = remembered if remembered in self.panels else next(iter(self.panels))

        self.card = card = Card()
        card.setMinimumHeight(PANEL_MIN_HEIGHT)
        outer = card.layout()
        header = QHBoxLayout()
        self.picker = DropdownButton(q.PANEL_PICKER)
        self.picker.clicked.connect(self._open_menu)
        self.suffix = QLabel()
        self.suffix.setObjectName(q.DETAILS_LABEL)
        header.addWidget(self.picker)
        header.addWidget(self.suffix, 1)
        outer.addLayout(header)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setObjectName(q.SURFACE)
        scroll.viewport().setObjectName(q.SURFACE)
        content = Surface()
        stack = QVBoxLayout(content)
        stack.setContentsMargins(0, 0, 0, 0)
        for panel in self.panels.values():
            stack.addWidget(panel)
        stack.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        self.assistant = AssistantArea(app, state)
        share = layout_settings.get(SHARE_SETTING)
        self._share = share if isinstance(share, float) and 0.1 <= share <= 0.9 else DEFAULT_PANELS_SHARE
        self._split = _ColumnSplit(Qt.Orientation.Vertical)
        self._split.setObjectName(q.SURFACE)
        self._split.setChildrenCollapsible(False)
        self._split.setHandleWidth(GAP)     # the gap between the cards is the handle: drag it to resize them
        self._split.addWidget(card)
        self._split.addWidget(self.assistant)
        self._split.splitterMoved.connect(self._remember_share)
        self._split.reset_requested.connect(self._reset_share)
        self._apply_share()
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(self._split)
        self.assistant.focus_toggled.connect(self._on_focus_toggled)

        for panel in self.panels.values():
            panel.dirty_changed.connect(lambda _dirty: state.set_dirty(bool(self.dirty_panels()), "panels"))
        # A pending edit is saved and the old content stops answering at once; the rebuild (a project scan for
        # Used in decks) waits for the selection to rest, so a held arrow key does not rebuild per row. A deck
        # change and choosing a panel rebuild at once: they are single, deliberate steps.
        self._rebuild = QTimer(self)
        self._rebuild.setSingleShot(True)
        self._rebuild.setInterval(SETTLE_MS)
        self._rebuild.timeout.connect(self.refresh)
        state.deck_changed.connect(lambda _value: self.refresh())
        for signal in (state.focused_slide_changed, state.view_changed, state.language_changed):
            signal.connect(lambda _value: self._defer())
        state.ai_route_changed.connect(lambda _route: [panel.refresh_route() for panel in self.panels.values()])
        self.refresh()

    def _apply_share(self) -> None:
        # Weights, so the share holds when the window is resized.
        self._split.setSizes([round(10_000 * self._share), round(10_000 * (1 - self._share))])

    def _remember_share(self, _position: int = 0, _index: int = 0) -> None:
        panels, assistant = self._split.sizes()
        if panels and assistant:
            self._share = panels / (panels + assistant)
            layout_settings.set(SHARE_SETTING, self._share)

    def _reset_share(self) -> None:
        self._share = DEFAULT_PANELS_SHARE
        layout_settings.set(SHARE_SETTING, self._share)
        self._apply_share()

    def set_panel(self, key: str) -> None:
        if key in self.panels and key != self.current:
            self.current = key
            app_settings.set(self.project, SETTING, key)
            self.refresh()

    def dirty_panels(self) -> list[SidePanel]:
        return [panel for panel in self.panels.values() if panel.dirty]

    def flush(self) -> None:
        """Save every pending edit of the panels (before closing, too)."""
        for panel in self.panels.values():
            panel.flush()

    def _on_focus_toggled(self, focused: bool) -> None:
        self.card.setVisible(not focused)
        if self._stale and not focused:
            self.refresh()

    def _defer(self) -> None:
        """The slide, view or language changed: save pending edits against the old content, switch its actions
        off so a quick click cannot change the slide that was left, and rebuild once the changes stop. When the
        panel already shows this state (a deck switch rebuilds at once and then reports the focus, view and
        language it reset; or the user came back before the pause), it answers again and nothing is rebuilt."""
        if self._panel_state() == self._built_for:
            self._rebuild.stop()
            self._shield.hide()
            return
        self.flush()
        panel = self.panels[self.current]
        self._shield.setParent(panel)
        self._shield.setGeometry(panel.rect())
        self._shield.raise_()
        self._shield.show()
        self._rebuild.start()

    def refresh(self) -> None:
        """Bring the shown panel up to date (at once; a hidden card is brought up to date when it is shown)."""
        self._rebuild.stop()
        self._shield.hide()
        self.flush()   # an edit belongs to the slide, deck and panel it was made in
        self._stale = self.card.isHidden()
        if self._stale:
            return
        for key, panel in self.panels.items():
            panel.setVisible(key == self.current)
        panel = self.panels[self.current]
        self.picker.set_text(panel.title)
        self.suffix.setText(panel.suffix())
        panel.refresh()
        self._built_for = self._panel_state()

    def _panel_state(self) -> tuple:
        s = self._state
        return s.deck, s.focused_slide, s.focused_occurrence, s.view, s.language

    def _open_menu(self) -> None:
        menu = PopoverMenu(self, min_width=270)
        for key, panel in self.panels.items():
            menu.add_item(key, panel.title, meta=panel.meta(), icon="check" if key == self.current else "")
        menu.triggered.connect(self.set_panel)
        menu.closed.connect(lambda: self.picker.set_active(False))
        menu.closed.connect(menu.deleteLater)
        self.picker.set_active(True)
        menu.popup_below(self.picker)
