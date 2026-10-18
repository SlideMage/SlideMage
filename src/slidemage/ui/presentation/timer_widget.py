"""The timer element of the presenter window and the small dialog that sets it (plan 4.5)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import QTime, QTimer, Qt, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QPushButton, QRadioButton, QSpinBox, QTimeEdit,
                               QVBoxLayout, QWidget)

from ...presentation.settings import TIMER_DURATION, TIMER_END, PresentationSettings
from ...presentation.timer import PresentationTimer, end_time_after

LEVEL_STYLE = {
    "off": "", "ok": "",
    "warn": "background: #ef9a1a; color: #000000;",
    "over": "background: #d32f2f; color: #ffffff;",
}


class TimerDialog(QDialog):
    """Mode, end time or minutes; OK sets the timer, "Remove timer" clears it."""
    def __init__(self, settings: PresentationSettings, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Timer")
        self.clear_requested = False
        layout = QVBoxLayout(self)
        self.end_radio = QRadioButton("Until a time of day")
        self.end_edit = QTimeEdit(QTime.fromString(end_time_after(settings.timer_duration_minutes).strftime("%H:%M"), "HH:mm"))
        self.end_edit.setDisplayFormat("HH:mm")
        self.duration_radio = QRadioButton("For a duration (minutes)")
        self.minutes = QSpinBox()
        self.minutes.setRange(1, 600)
        self.minutes.setValue(settings.timer_duration_minutes)
        (self.end_radio if settings.timer_mode == TIMER_END else self.duration_radio).setChecked(True)
        for radio, field in ((self.end_radio, self.end_edit), (self.duration_radio, self.minutes)):
            row = QHBoxLayout()
            row.addWidget(radio, 1)
            row.addWidget(field)
            layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        remove = buttons.addButton("Remove timer", QDialogButtonBox.ButtonRole.DestructiveRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        remove.clicked.connect(self._remove)
        layout.addWidget(buttons)

    def _remove(self) -> None:
        self.clear_requested = True
        self.accept()

    def mode(self) -> str:
        return TIMER_END if self.end_radio.isChecked() else TIMER_DURATION


class TimerButton(QPushButton):
    """Shows the time left; a click opens the dialog. Flashes red when time is up."""
    changed = Signal()

    def __init__(self, timer: PresentationTimer, settings: PresentationSettings, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.timer, self.settings = timer, settings
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMinimumWidth(110)
        self.clicked.connect(self.edit)
        self._tick = QTimer(self)
        self._tick.setInterval(250)
        self._tick.timeout.connect(self.refresh)
        self._tick.start()
        self.refresh()

    def refresh(self) -> None:
        timer = self.timer
        if not timer.is_set:
            self.setText("Timer…")
            self.setStyleSheet("")
            self.setToolTip("Set a timer: an end time of day or a duration")
            return
        suffix = f"  {timer.target_text()}" if timer.target_text() else ("" if timer.running else "  ⏸")
        self.setText(timer.text() + suffix)
        level = timer.level(self.settings.timer_warn)
        red = level == "over" and timer.flash_on(self.settings.timer_flash)
        self.setStyleSheet(LEVEL_STYLE["over"] if red else ("" if level == "over" else LEVEL_STYLE[level]))
        self.setToolTip("T starts or pauses, Shift+T resets")

    def edit(self) -> None:
        dialog = TimerDialog(self.settings, self.window())
        if not dialog.exec():
            return
        if dialog.clear_requested:
            self.timer.clear()
        elif dialog.mode() == TIMER_END:
            when = dialog.end_edit.time().toPython()
            if not self.timer.set_end_time(when):
                self.setToolTip("That time has already passed today")
                return
        else:
            self.timer.set_duration(dialog.minutes.value() * 60)
            if not self.settings.timer_start_on_navigation:
                self.timer.start()
        self.refresh()
        self.changed.emit()


def format_clock(now: datetime, fmt: str) -> str:
    return now.strftime("%I:%M %p").lstrip("0") if fmt == "12" else now.strftime("%H:%M")
