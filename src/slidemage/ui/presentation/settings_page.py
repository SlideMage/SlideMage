# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Presentation tab of the Settings sheet (plan 4.11): everything about presenting in one place. Like the
other tabs, a control applies and is saved when it changes."""
from __future__ import annotations

from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QPushButton, QSpinBox

from ...presentation import layout
from ...presentation.screens import ScreenInfo
from ...presentation.settings import TIMER_DURATION, TIMER_END, PresentationSettings
from ..kit.widgets import Field, Page, caption, columns, row

TIMER_MODES = ((TIMER_END, "End time of day"), (TIMER_DURATION, "Duration"))
CLOCK_FORMATS = (("system", "System setting"), ("24", "24 hours"), ("12", "12 hours"))


def _swatch(button: QPushButton, color: str) -> None:
    button.setText(QColor(color).name(QColor.NameFormat.HexArgb) if QColor(color).alpha() != 255 else QColor(color).name())
    button.setStyleSheet(f"border-left: 22px solid {QColor(color).name()};")


class PresentationTab(Page):
    def __init__(self) -> None:
        super().__init__()
        self.values = PresentationSettings.load()
        values, body = self.values, self.body

        self.profile_combo = QComboBox()
        for profile in layout.BUILTINS:
            self.profile_combo.addItem(profile.name)
        self.profile_combo.setCurrentIndex(max(self.profile_combo.findText(values.profile), 0))
        self.profile_combo.currentTextChanged.connect(lambda text: self._set("profile", text))
        body.addWidget(Field("Presenter window layout", self.profile_combo))
        body.addWidget(caption(
            "Which screen elements the presenter window shows and where. P switches the layout while presenting. "
            "The projector always shows only the slide."))

        self.laser_button, self.pen_button = QPushButton(), QPushButton()
        for button, key, alpha in ((self.laser_button, "laser_color", False), (self.pen_button, "pen_color", True)):
            _swatch(button, getattr(values, key))
            button.clicked.connect(lambda _checked=False, b=button, k=key, a=alpha: self._pick(b, k, a))
        self.pen_width = QDoubleSpinBox()
        self.pen_width.setRange(0.2, 5.0)
        self.pen_width.setSingleStep(0.2)
        self.pen_width.setSuffix(" % of the slide height")
        self.pen_width.setValue(values.pen_width * 100)
        self.pen_width.valueChanged.connect(lambda v: self._set("pen_width", round(v / 100, 4)))
        self.laser_size = QDoubleSpinBox()
        self.laser_size.setRange(0.5, 6.0)
        self.laser_size.setSingleStep(0.5)
        self.laser_size.setSuffix(" % of the slide height")
        self.laser_size.setValue(values.laser_size * 100)
        self.laser_size.valueChanged.connect(lambda v: self._set("laser_size", round(v / 100, 4)))
        body.addWidget(columns(Field("Laser pointer colour", self.laser_button), Field("Laser pointer size", self.laser_size)))
        body.addWidget(columns(Field("Pen colour", self.pen_button), Field("Pen width", self.pen_width)))
        body.addWidget(caption("The laser shows while you hold Ctrl and the left mouse button on the current slide. "
                               "While presenting, the Pen button changes the pen's colour and width for that "
                               "presentation only."))

        self.confirm_links = QCheckBox("Ask before opening a web link")
        self.confirm_links.setChecked(values.confirm_links)
        self.confirm_links.toggled.connect(lambda on: self._set("confirm_links", bool(on)))
        body.addWidget(Field("Links in slides", self.confirm_links))

        self.offer_resume = QCheckBox("Offer to continue where the last talk stopped")
        self.offer_resume.setChecked(values.offer_resume)
        self.offer_resume.toggled.connect(lambda on: self._set("offer_resume", bool(on)))
        body.addWidget(Field("Continuing a talk", self.offer_resume))

        self.timer_mode = QComboBox()
        for key, label in TIMER_MODES:
            self.timer_mode.addItem(label, key)
        self.timer_mode.setCurrentIndex(self.timer_mode.findData(values.timer_mode))
        self.timer_mode.currentIndexChanged.connect(lambda _i: self._set("timer_mode", self.timer_mode.currentData()))
        self.timer_minutes = QSpinBox()
        self.timer_minutes.setRange(1, 600)
        self.timer_minutes.setSuffix(" min")
        self.timer_minutes.setValue(values.timer_duration_minutes)
        self.timer_minutes.valueChanged.connect(lambda v: self._set("timer_duration_minutes", v))
        body.addWidget(columns(Field("Timer counts down to", self.timer_mode), Field("Default duration", self.timer_minutes)))
        self.timer_start = QCheckBox("A duration starts at the first slide change")
        self.timer_flash = QCheckBox("Flash red when time is up (otherwise solid red)")
        self.timer_warn = QCheckBox("Turn amber five minutes before the end")
        for check, key in ((self.timer_start, "timer_start_on_navigation"), (self.timer_flash, "timer_flash"),
                           (self.timer_warn, "timer_warn")):
            check.setChecked(getattr(values, key))
            check.toggled.connect(lambda on, k=key: self._set(k, bool(on)))
        body.addWidget(Field("Timer behaviour", row(self.timer_start, self.timer_flash, self.timer_warn)))
        body.addWidget(caption(
            "The timer is optional: click it in the presenter window to set an end time or a duration. T starts or "
            "pauses it, Shift+T resets it."))

        self.clock_format = QComboBox()
        for key, label in CLOCK_FORMATS:
            self.clock_format.addItem(label, key)
        self.clock_format.setCurrentIndex(self.clock_format.findData(values.clock_format))
        self.clock_format.currentIndexChanged.connect(lambda _i: self._set("clock_format", self.clock_format.currentData()))
        self.audience_screen = QComboBox()
        self.audience_screen.addItem("Automatic (the other screen)", "")
        for screen in QGuiApplication.screens():
            geometry = screen.geometry()
            info = ScreenInfo(screen.name(), geometry.x(), geometry.y(), geometry.width(), geometry.height(), screen.serialNumber())
            self.audience_screen.addItem(f"{screen.name()} ({geometry.width()}x{geometry.height()})", info.key)
        self.audience_screen.setCurrentIndex(max(self.audience_screen.findData(values.audience_screen), 0))
        self.audience_screen.currentIndexChanged.connect(
            lambda _i: self._set("audience_screen", self.audience_screen.currentData()))
        body.addWidget(columns(Field("Clock", self.clock_format), Field("Projector screen", self.audience_screen)))
        body.addWidget(caption("With one screen, or duplicated screens, only the full-screen slide is shown."))

        reset = QPushButton("Reset presentation settings")
        reset.clicked.connect(self._reset)
        body.addWidget(reset)
        body.addStretch(1)

    def _set(self, key: str, value) -> None:
        setattr(self.values, key, value)
        self.values.save()

    def _pick(self, button: QPushButton, key: str, alpha: bool) -> None:
        options = QColorDialog.ColorDialogOption.ShowAlphaChannel if alpha else QColorDialog.ColorDialogOption(0)
        color = QColorDialog.getColor(QColor(getattr(self.values, key)), self, "Colour", options)
        if color.isValid():
            self._set(key, color.name(QColor.NameFormat.HexArgb) if alpha else color.name())
            _swatch(button, getattr(self.values, key))

    def _reset(self) -> None:
        defaults = PresentationSettings()
        defaults.save()
        self.values = defaults
        for combo, value in ((self.profile_combo, defaults.profile),):
            combo.setCurrentIndex(max(combo.findText(value), 0))
        _swatch(self.laser_button, defaults.laser_color)
        _swatch(self.pen_button, defaults.pen_color)
        self.pen_width.setValue(defaults.pen_width * 100)
        self.laser_size.setValue(defaults.laser_size * 100)
        self.confirm_links.setChecked(defaults.confirm_links)
        self.offer_resume.setChecked(defaults.offer_resume)
        self.timer_mode.setCurrentIndex(self.timer_mode.findData(defaults.timer_mode))
        self.timer_minutes.setValue(defaults.timer_duration_minutes)
        for check, key in ((self.timer_start, "timer_start_on_navigation"), (self.timer_flash, "timer_flash"),
                           (self.timer_warn, "timer_warn")):
            check.setChecked(getattr(defaults, key))
        self.clock_format.setCurrentIndex(self.clock_format.findData(defaults.clock_format))
        self.audience_screen.setCurrentIndex(0)
