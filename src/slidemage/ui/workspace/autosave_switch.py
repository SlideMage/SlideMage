# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""AutoSave [On|Off]: a segmented switch like View as, right after the menu bar's Help (v8.58.0; before, a chip in
the top bar). A QMenuBar holds no widgets between its menus, and the window must keep a real QMenuBar
(QMainWindow.menuBar() replaces anything else), so the switch is a child of the bar placed after its last menu
whenever the bar lays itself out. A native menu bar (macOS) is not in the window: there the window puts the switch
in the top bar instead (attach_to_topbar)."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenuBar, QWidget

from ..kit import kit_qss as q
from ..kit.widgets import SegmentedControl
from .source_file import autosave_on

ON, OFF = "on", "off"
GAP = 16           # px between Help and the switch
TOOLTIP = "On: edits are saved as you type. Off: Ctrl+S saves."


class AutoSaveSwitch(QWidget):
    """The label and the [On|Off] control; `set_autosave(bool)` is called for a click."""

    def __init__(self, set_autosave: Callable[[bool], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.label = QLabel("AutoSave")
        self.label.setObjectName(q.TOPBAR_LABEL)
        layout.addWidget(self.label)
        self.control = SegmentedControl([(ON, "On"), (OFF, "Off")], current=ON if autosave_on() else OFF, roving=True)
        self.control.setToolTip(TOOLTIP)
        self.control.setAccessibleName("AutoSave")
        self.control.changed.connect(lambda key: set_autosave(key == ON))
        layout.addWidget(self.control)
        self.setToolTip(TOOLTIP)

    def refresh(self) -> None:
        """Show the setting as it is now (after Settings, File or Ctrl+K changed it)."""
        self.control.set_current(ON if autosave_on() else OFF)

    def add_trailing(self, widget: QWidget) -> None:
        """A small indicator after the switch, which rides with it (the debug log's chip, debug_log_ui.py)."""
        self.layout().addSpacing(GAP // 2)
        self.layout().addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
        self.relayout()

    def relayout(self) -> None:
        """Take the size the visible parts need now (an indicator shown or hidden)."""
        self.layout().invalidate()
        self.adjustSize()
        self.updateGeometry()
        placer = getattr(self, "_placer", None)
        if placer is not None:
            placer.place()

    def is_on(self) -> bool:
        return self.control.current() == ON

    def attach_to(self, bar: QMenuBar) -> None:
        """Ride on `bar`, after its last menu."""
        self.setParent(bar)
        # Slimmer segments than the top bar's, so that the bar keeps its own height (the window's 640 px minimum).
        room = bar.sizeHint().height() - 4
        self.control.layout().setContentsMargins(2, 2, 2, 2)
        for button in self.control.buttons():
            button.setFixedHeight(room - 4)
            # The kit's segment padding (and its focus ring's) is for the top bar's taller segments.
            button.setStyleSheet("QPushButton { padding-top: 0px; padding-bottom: 0px; }")
        self._placer = _Placer(self, bar)
        bar.installEventFilter(self._placer)
        self._placer.place()
        self.show()


class _Placer(QObject):
    """Keeps the switch just after the bar's last menu: the bar's own layout moves its menus on every resize, font
    or style change. Hidden while the last menu is in the bar's overflow (a narrow window)."""

    def __init__(self, switch: AutoSaveSwitch, bar: QMenuBar) -> None:
        super().__init__(switch)
        self._switch, self._bar = switch, bar

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 -- Qt's name
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.LayoutRequest, QEvent.Type.FontChange,
                            QEvent.Type.StyleChange, QEvent.Type.Polish):
            self.place()
        return False

    def place(self) -> None:
        actions = [a for a in self._bar.actions() if a.isVisible()]
        last = self._bar.actionGeometry(actions[-1]) if actions else None
        size = self._switch.sizeHint()
        if last is None or last.isEmpty() or last.right() + GAP + size.width() > self._bar.width():
            self._switch.hide()
            return
        self._switch.setGeometry(last.right() + GAP, (self._bar.height() - size.height()) // 2,
                                 size.width(), size.height())
        self._switch.show()
