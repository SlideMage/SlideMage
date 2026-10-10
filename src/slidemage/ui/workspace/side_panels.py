"""The right column (UI_REDESIGN_PLAN.md, step 6): a panel picker and the chosen panel for
the focused slide. The lower part is left to step 10's AI chat, which is added to this
splitter below the panels.

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
from ..kit import kit_qss as q
from ..kit.widgets import Card, DropdownButton, PopoverMenu, Surface
from .panels import PANELS
from .panels.base import SidePanel
from .state import WorkspaceState

WIDTH = 340   # the prototype's width of the column
SETTING = "side_panel"


class SidePanels(QSplitter):
    def __init__(self, app, state: WorkspaceState) -> None:
        super().__init__(Qt.Orientation.Vertical)
        self.setFixedWidth(WIDTH)
        self.setChildrenCollapsible(False)
        self.panels: dict[str, SidePanel] = {cls.key: cls(app, state) for cls in PANELS}
        remembered = app_settings.get(SETTING)
        self.current = remembered if remembered in self.panels else next(iter(self.panels))

        card = Card()
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

        for panel in self.panels.values():
            panel.dirty_changed.connect(lambda _dirty: state.set_dirty(bool(self.dirty_panels()), "panels"))
        for signal in (state.deck_changed, state.focused_slide_changed, state.view_changed, state.language_changed):
            signal.connect(lambda _value: self.refresh())
        self.refresh()

    def set_panel(self, key: str) -> None:
        if key in self.panels and key != self.current:
            self.current = key
            app_settings.set(SETTING, key)
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
