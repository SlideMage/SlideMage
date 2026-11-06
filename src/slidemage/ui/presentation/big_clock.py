# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The large digital clock of the presenter window (the "bigclock" element): HH:MM, 24 hours, no seconds, the
font scaled to fill the area and re-fitted whenever the area changes. Ticks on the minute."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont, QFontMetrics, QResizeEvent
from PySide6.QtWidgets import QLabel

FILL_WIDTH, FILL_HEIGHT = 0.9, 0.7      # the share of the area the text may take
MIN_PIXELS = 8
SAMPLE = "00:00"                         # wide digits: the size must not jump when the minute changes


def clock_text(now: datetime) -> str:
    return now.strftime("%H:%M")


def fitted_pixel_size(font: QFont, width: int, height: int) -> int:
    """The largest pixel size at which "00:00" in `font` fits the share of a width x height area."""
    probe = QFont(font)
    probe.setPixelSize(100)
    box = QFontMetrics(probe).boundingRect(SAMPLE)
    if box.width() <= 0 or box.height() <= 0:
        return MIN_PIXELS
    scale = min(width * FILL_WIDTH / box.width(), height * FILL_HEIGHT / box.height())
    return max(MIN_PIXELS, int(100 * scale))


class BigClock(QLabel):
    def __init__(self, now: Callable[[], datetime] = datetime.now) -> None:
        super().__init__()
        self._now = now
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(40, 20)
        font = self.font()
        font.setBold(True)
        self.setFont(font)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        """Show the time, and wake up again just after the next minute starts."""
        moment = self._now()
        self.setText(clock_text(moment))
        self._timer.start(max(250, (60 - moment.second) * 1000 - moment.microsecond // 1000 + 50))

    def fit(self) -> None:
        font = self.font()
        font.setPixelSize(fitted_pixel_size(font, self.width(), self.height()))
        self.setFont(font)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.fit()
