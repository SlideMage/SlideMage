# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""A one-off greeting: the wizard steps out of his portal, conjures a cake and a message appears.

schedule_greeting(window) is called once the main window is up. It plays the wizard overlay and, at his cast,
raises the cake over the spot his wand points to. It runs once per computer (a marker file in
project.config_dir()); SLIDEMAGE_GREETING=1 plays it again.
"""
from __future__ import annotations

import math
import os

from PySide6.QtCore import QElapsedTimer, QEvent, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ... import project
from .wizard_portal import color, ease, play_wizard

MESSAGE = "Happy birthday, Jürgen!"
MARKER = "greeting_v0.13.8"
DELAY_MS = 1500
SHOW_SECONDS = 8.0  # from the cast; the last second fades out


def _marker():
    return project.config_dir() / MARKER


class CakeOverlay(QWidget):
    """The cake and the message; painted in the wizard overlay's 1000x650 scene so they sit where his wand points."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.seconds = 0.0
        self.clock = QElapsedTimer()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        parent.installEventFilter(self)
        self.hide()

    def eventFilter(self, obj, event):
        if obj is self.parent() and event.type() == QEvent.Type.Resize:
            self.setGeometry(obj.rect())
        return super().eventFilter(obj, event)

    def play(self):
        self.seconds = 0.0
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.clock.start()
        self.timer.start()

    def _tick(self):
        self.seconds = self.clock.elapsed() / 1000
        if self.seconds >= SHOW_SECONDS:
            self.timer.stop()
            self.hide()
        else:
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        scale = min(self.width() / 1000, self.height() / 650)
        p.translate((self.width() - 1000 * scale) / 2, (self.height() - 650 * scale) / 2)
        p.scale(scale, scale)
        self.paint_scene(p, self.seconds)
        p.end()

    def paint_scene(self, p, t):
        fade = 1 - ease(t - (SHOW_SECONDS - 1))
        pop = ease(t / .7)
        # a little overshoot, then settle
        size = pop * (1 + .08 * math.sin(min(1, t / .7) * math.pi))
        p.setOpacity(fade * min(1, t / .3))
        p.save()
        p.translate(780, 470)  # the cake's plate, below the wand's target
        p.scale(size * 1.5, size * 1.5)
        self._cake(p, t)
        p.restore()
        text_in = ease((t - .6) / .8)
        if text_in > 0:
            font = QFont()
            font.setPixelSize(32)
            font.setBold(True)
            p.setFont(font)
            p.setOpacity(fade * text_in)
            box = QRectF(430, 510 + (1 - text_in) * 20, 700, 60)
            box.moveCenter(QPointF(760, box.center().y()))
            p.setPen(QColor(0, 0, 0, 150))
            p.drawText(box.translated(2, 2), Qt.AlignmentFlag.AlignCenter, MESSAGE)
            p.setPen(color("#ffd23f"))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, MESSAGE)

    @staticmethod
    def _cake(p, t):
        """Plate at (0, 0), about 140 wide and 100 tall above it."""
        def block(x, y, w, h, r, c):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(c))
            p.drawRoundedRect(QRectF(x, y, w, h), r, r)

        block(-75, -6, 150, 8, 4, "#bdbdb8")
        block(-58, -40, 116, 36, 6, "#f4a6b8")
        block(-42, -72, 84, 34, 6, "#f3efe6")
        for i in range(10):
            block(-53 + i * 11, -44, 8, 12 + (i % 3) * 4, 4, "#f3efe6")
        block(-47, -77, 94, 10, 5, "#f4a6b8")
        for dx, c in ((-24, "#ffd400"), (-8, "#6ec1e4"), (8, "#ffd400"), (24, "#6ec1e4")):
            block(dx - 2.5, -96, 5, 20, 2, c)
            flicker = 1 + .15 * math.sin(t * 14 + dx)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#ffb300"))
            p.drawEllipse(QPointF(dx, -101), 4 * flicker, 6 * flicker)
            p.setBrush(QColor("#fff7ce"))
            p.drawEllipse(QPointF(dx, -99), 1.7, 3)
        for sx, sy, c in ((-40, -26, "#ffd400"), (-20, -18, "#6ec1e4"), (0, -24, "#ffd400"),
                          (22, -16, "#6ec1e4"), (42, -24, "#ffd400"), (-10, -54, "#f4a6b8"), (15, -52, "#ffd400")):
            p.setPen(QPen(QColor(c), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(sx, sy), QPointF(sx + 4, sy - 2))


def play_greeting(window):
    """Wizard, then at his cast the cake and the message."""
    cake = getattr(window, "_greeting_cake", None)
    if cake is None:
        cake = window._greeting_cake = CakeOverlay(window)
    wizard = play_wizard(window)
    wizard.cast.connect(cake.play, Qt.ConnectionType.UniqueConnection)
    return wizard, cake


def schedule_greeting(window) -> None:
    """Once per computer, a moment after the window shows."""
    forced = os.environ.get("SLIDEMAGE_GREETING") == "1"
    if not forced and _marker().exists():
        return

    def start():
        try:
            play_greeting(window)
            _marker().parent.mkdir(parents=True, exist_ok=True)
            _marker().write_text("", encoding="utf-8")
        except (FileNotFoundError, OSError):
            pass  # optional artwork or an unwritable folder must never get in the way of starting

    QTimer.singleShot(DELAY_MS, start)
