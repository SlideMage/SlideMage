"""The right column (UI_REDESIGN_PLAN.md, steps 6 and 10): a panel picker and the chosen panel for
the focused slide, and below them, in the same splitter, the assistant area (chat/assistant.py).

The picker (▾) names the shown panel and lists the others with a few facts about the
slide. The choice is remembered across sessions (app_settings, like the centre's mode).
The panels themselves are in panels/; they follow WorkspaceState's deck, slide, view and
language, and the window calls `refresh()` after anything that changed the project, because
a rescan of the open deck is no state change. A panel's pending edit (`SidePanel.flush`) is saved
before anything it belongs to changes, and counts as an unsaved edit of the workspace."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QSplitter, QVBoxLayout

from ... import app_settings
from ...project import ProjectContext
from .. import layout_settings
from ..kit import kit_qss as q
from ..kit.widgets import Card, DropdownButton, PopoverMenu, Surface
from .chat.assistant import AssistantArea
from .panels import PANELS
from .panels.base import PanelActions, SidePanel
from .state import WorkspaceState

WIDTH = 340   # the prototype's width of the column; the least it may be dragged to, and the default
MAX_WIDTH = 900
WIDTH_SETTING = "right_column_width"
SETTING = "side_panel"
ASSISTANT_SPLIT = (300, 500)   # starting heights of the panels and of the assistant area
SPLIT_SETTING = "right_column_split"
PANEL_MIN_HEIGHT = 128   # 24 px padding, 32 px picker, 8 px gap and a 64 px content row


def remembered_width(project: ProjectContext) -> int:
    """The width the user dragged the column to, within its limits (WIDTH if never)."""
    value = layout_settings.get(WIDTH_SETTING)
    if value is None:   # once: this project's old width becomes the user's
        value = app_settings.get(project, WIDTH_SETTING)
        layout_settings.set(WIDTH_SETTING, value if isinstance(value, int) else WIDTH)
    return min(max(value, WIDTH), MAX_WIDTH) if isinstance(value, int) else WIDTH


class SidePanels(QSplitter):
    def __init__(self, app, state: WorkspaceState, actions: PanelActions) -> None:
        super().__init__(Qt.Orientation.Vertical)
        self.setMinimumWidth(WIDTH)
        self.setMaximumWidth(MAX_WIDTH)
        self.setChildrenCollapsible(False)
        self.project = state.project
        ratio = layout_settings.get(SPLIT_SETTING)
        self._split_ratio = (ratio if isinstance(ratio, (int, float)) and not isinstance(ratio, bool)
                             and 0 < ratio < 1 else ASSISTANT_SPLIT[0] / sum(ASSISTANT_SPLIT))
        self._split_restored = False
        self.panels: dict[str, SidePanel] = {cls.key: cls(app, state, actions) for cls in PANELS}
        remembered = app_settings.get(state.project, SETTING)
        self.current = remembered if remembered in self.panels else next(iter(self.panels))

        card = Card()
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
        self.addWidget(card)
        self.assistant = AssistantArea(app, state)
        self.addWidget(self.assistant)
        self.splitterMoved.connect(self._remember_split)

        for panel in self.panels.values():
            panel.dirty_changed.connect(lambda _dirty: state.set_dirty(bool(self.dirty_panels()), "panels"))
        for signal in (state.deck_changed, state.focused_slide_changed, state.view_changed, state.language_changed):
            signal.connect(lambda _value: self.refresh())
        self.refresh()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._split_restored:
            self._split_restored = True
            # Use weights so an initially short column keeps the ratio when it grows.
            self.setSizes([round(10_000 * self._split_ratio), round(10_000 * (1 - self._split_ratio))])

    def _remember_split(self, _position: int, _index: int) -> None:
        panel, assistant = self.sizes()
        if panel + assistant:
            self._split_ratio = panel / (panel + assistant)
            layout_settings.set(SPLIT_SETTING, self._split_ratio)

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

    def refresh(self) -> None:
        """Bring the shown panel up to date."""
        self.flush()   # an edit belongs to the slide, deck and panel it was made in
        for key, panel in self.panels.items():
            panel.setVisible(key == self.current)
        panel = self.panels[self.current]
        self.picker.set_text(panel.title)
        self.suffix.setText(panel.suffix())
        panel.refresh()

    def _open_menu(self) -> None:
        menu = PopoverMenu(self, min_width=270)
        for key, panel in self.panels.items():
            menu.add_item(key, panel.title, meta=panel.meta(), icon="check" if key == self.current else "")
        menu.triggered.connect(self.set_panel)
        menu.closed.connect(lambda: self.picker.set_active(False))
        menu.closed.connect(menu.deleteLater)
        self.picker.set_active(True)
        menu.popup_below(self.picker)
