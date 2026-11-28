# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tools → Pick color from screen: click a pixel anywhere on the screen, get its hex color.

The screen under the pointer is photographed once and shown full screen, frozen, with a crosshair and a magnifier
that follows the pointer (so what is picked is exactly what the magnifier shows, even from a video or a menu that
would close). A click picks, the arrow keys move the pointer one pixel, Esc or a right click cancels. The color is
reported as "#RRGGBB" and copied to the clipboard by the caller.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QImage, QKeyEvent, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

LOUPE_PIXELS = 11          # the magnifier shows this many pixels across (odd: the picked one is in the middle)
LOUPE_ZOOM = 12            # screen pixels per picked pixel in the magnifier
LOUPE_GAP = 24             # distance of the magnifier from the pointer


def hex_of(color: QColor) -> str:
    """"#RRGGBB" of `color`, upper case."""
    return f"#{color.red():02X}{color.green():02X}{color.blue():02X}"


def color_at(image: QImage, x: int, y: int) -> Optional[QColor]:
    """The color of the pixel (x, y) of `image` (device pixels), None outside it."""
    if 0 <= x < image.width() and 0 <= y < image.height():
        return image.pixelColor(x, y)
    return None


class ColorPickerOverlay(QWidget):
    picked = Signal(str)       # "#RRGGBB"
    cancelled = Signal()

    def __init__(self, screen, pixmap: QPixmap) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self._screen = screen
        self._pixmap = pixmap
        self._image = pixmap.toImage()
        self._ratio = pixmap.devicePixelRatio() or 1.0
        self._cursor = QPoint(-1, -1)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setGeometry(screen.geometry())
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    # -- what is under the pointer -------------------------------------------------------

    def color_under(self, point: QPoint) -> Optional[QColor]:
        return color_at(self._image, int(point.x() * self._ratio), int(point.y() * self._ratio))

    # -- events ------------------------------------------------------------------------------

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._cursor = event.position().toPoint()
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self._finish(None)
            return
        if event.button() == Qt.MouseButton.LeftButton:
            color = self.color_under(event.position().toPoint())
            self._finish(color)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        step = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0), Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._finish(None)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._finish(self.color_under(self._cursor))
        elif key in step:
            # one device pixel per key press, so a pixel in a detail of the slide can be chosen exactly
            dx, dy = step[key]
            self._cursor = self._cursor + QPoint(round(dx / self._ratio) or dx, round(dy / self._ratio) or dy)
            QCursor.setPos(self.mapToGlobal(self._cursor))
            self.update()

    def _finish(self, color: Optional[QColor]) -> None:
        self.releaseMouse()
        self.releaseKeyboard()
        self.close()
        if color is None:
            self.cancelled.emit()
        else:
            self.picked.emit(hex_of(color))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.grabMouse()
        self.grabKeyboard()
        self._cursor = self.mapFromGlobal(QCursor.pos())

    # -- drawing -----------------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self._pixmap)
        color = self.color_under(self._cursor)
        if color is None:
            return
        size = LOUPE_PIXELS * LOUPE_ZOOM
        x, y = self._cursor.x() + LOUPE_GAP, self._cursor.y() + LOUPE_GAP
        if x + size > self.width():
            x = self._cursor.x() - LOUPE_GAP - size
        if y + size + 26 > self.height():
            y = self._cursor.y() - LOUPE_GAP - size - 26
        box = QRect(x, y, size, size)
        # the magnifier: the pixels around the pointer, enlarged without smoothing
        half = LOUPE_PIXELS // 2
        cx, cy = int(self._cursor.x() * self._ratio), int(self._cursor.y() * self._ratio)
        source = QRect(cx - half, cy - half, LOUPE_PIXELS, LOUPE_PIXELS)
        painter.fillRect(box, QColor("#202020"))
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.drawImage(box, self._image, source)
        painter.setPen(QPen(QColor("#FFFFFF"), 1))
        painter.drawRect(box)
        centre = QRect(box.x() + half * LOUPE_ZOOM, box.y() + half * LOUPE_ZOOM, LOUPE_ZOOM, LOUPE_ZOOM)
        painter.setPen(QPen(QColor("#000000"), 2))
        painter.drawRect(centre.adjusted(-1, -1, 1, 1))
        painter.setPen(QPen(QColor("#FFFFFF"), 1))
        painter.drawRect(centre)
        # the readout under the magnifier: a swatch and the hex
        label = QRect(x, y + size, size, 26)
        painter.fillRect(label, QColor("#202020"))
        painter.fillRect(QRect(label.x() + 5, label.y() + 5, 16, 16), color)
        painter.setPen(QPen(QColor("#FFFFFF"), 1))
        painter.drawRect(QRect(label.x() + 5, label.y() + 5, 16, 16))
        font = QFont("Consolas")
        font.setPixelSize(14)
        painter.setFont(font)
        painter.drawText(QRectF(label.x() + 28, label.y(), size - 30, 26),
                         int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), hex_of(color))


def pick_color(on_done: Callable[[Optional[str]], None]) -> Optional[ColorPickerOverlay]:
    """Photograph the screen under the pointer and let the user click a pixel; `on_done` gets "#RRGGBB", or None
    when cancelled. Returns the overlay (kept alive by the caller until it ends)."""
    screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
    if screen is None:
        on_done(None)
        return None
    overlay = ColorPickerOverlay(screen, screen.grabWindow(0))
    overlay.picked.connect(on_done)
    overlay.cancelled.connect(lambda: on_done(None))
    overlay.showFullScreen()
    return overlay
