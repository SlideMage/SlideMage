# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The widget that shows one slide (or one note page) with the laser and drawings over it (plan 4.1)."""
from __future__ import annotations

from typing import Optional, Protocol

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from ...presentation.pdf_source import SLIDE, PresentationDeck
from ...presentation.session import Point, Stroke
from .slide_input import SlideInput

BADGE_COLORS = {"black": "#d32f2f", "frozen": "#ef9a1a", "both": "#d32f2f"}


class View(Protocol):
    """What a canvas shows; the controller gives each canvas the view of its role."""
    def page(self) -> Optional[int]: ...
    def strokes(self) -> list[Stroke]: ...
    def pointer(self) -> Optional[Point]: ...
    def status(self) -> Optional[tuple[str, str]]: ...


class SlideCanvas(QWidget):
    def __init__(self, deck: PresentationDeck, view: View, *, part: str = SLIDE, laser_color: str = "#ff2020",
                 laser_size: float = 0.02, background: str = "#000000", empty_text: str = "", top: bool = False,
                 slide_input: Optional[SlideInput] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.deck, self.view, self.part, self.laser_size = deck, view, part, laser_size
        self.laser_color, self.background, self.empty_text, self.top = laser_color, background, empty_text, top
        self.input = slide_input
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMinimumSize(40, 30)
        if slide_input is not None:
            self.setMouseTracking(True)

    # -- geometry ---------------------------------------------------------------------

    def target(self) -> QRect:
        """The slide's rectangle inside the widget: as large as fits, centred (or at the top)."""
        width, height = self.width(), self.height()
        aspect = self.deck.aspect
        w = min(width, int(height * aspect))
        h = int(w / aspect)
        return QRect((width - w) // 2, 0 if self.top else (height - h) // 2, w, h)

    def _fraction(self, event) -> Optional[Point]:
        rect = self.target()
        if rect.width() < 1 or rect.height() < 1:
            return None
        position = event.position()
        return ((position.x() - rect.x()) / rect.width(), (position.y() - rect.y()) / rect.height())

    # -- painting ---------------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(self.background))
        page = self.view.page()
        rect = self.target()
        image = None
        if page is not None:
            ratio = self.devicePixelRatioF()
            image = self.deck.render(page, self.part, int(rect.width() * ratio), int(rect.height() * ratio))
        if image is None:
            if page is not None and self.empty_text:
                painter.setPen(QColor("#9e9e9e"))
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.empty_text)
            elif page is None and self.empty_text:
                painter.setPen(QColor("#9e9e9e"))
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.empty_text)
            self._badge(painter)
            return
        painter.drawImage(QRectF(rect), image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for stroke in self.view.strokes():
            self._stroke(painter, rect, stroke)
        pointer = self.view.pointer()
        if pointer is not None:
            self._laser(painter, rect, pointer)
        self._badge(painter)

    def _stroke(self, painter: QPainter, rect: QRect, stroke: Stroke) -> None:
        pen = QPen(QColor(stroke.color), max(2.0, stroke.width * rect.height()))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        path = QPainterPath()
        points = [QPointF(rect.x() + x * rect.width(), rect.y() + y * rect.height()) for x, y in stroke.points]
        path.moveTo(points[0])
        if len(points) == 1:
            path.lineTo(points[0] + QPointF(0.01, 0))
        for point in points[1:]:
            path.lineTo(point)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    def _laser(self, painter: QPainter, rect: QRect, pointer: Point) -> None:
        centre = QPointF(rect.x() + pointer[0] * rect.width(), rect.y() + pointer[1] * rect.height())
        radius = max(3.0, self.laser_size * rect.height())
        color = QColor(self.laser_color)
        halo = QColor(color)
        halo.setAlpha(0)
        glow = QColor(color)
        glow.setAlpha(110)
        gradient = QRadialGradient(centre, radius * 2.2)
        gradient.setColorAt(0.0, glow)
        gradient.setColorAt(1.0, halo)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(centre, radius * 2.2, radius * 2.2)
        painter.setBrush(color)
        painter.drawEllipse(centre, radius, radius)

    def _badge(self, painter: QPainter) -> None:
        status = self.view.status()
        if status is None:
            return
        text, kind = status
        color = QColor(BADGE_COLORS[kind])
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QPen(color, 6))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.rect().adjusted(3, 3, -3, -3))
        font = painter.font()
        font.setBold(True)
        font.setPointSize(max(9, font.pointSize()))
        painter.setFont(font)
        box = painter.fontMetrics().boundingRect(text).adjusted(-8, -3, 8, 3)
        box.moveTopLeft(self.rect().topLeft() + QPointF(6, 6).toPoint())
        painter.fillRect(box, color)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    # -- mouse ------------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        point = self._fraction(event)
        if self.input is None or event.button() != Qt.MouseButton.LeftButton or point is None:
            return event.ignore()
        self.input.press(*point, bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier))

    def mouseMoveEvent(self, event) -> None:
        point = self._fraction(event)
        if self.input is None or point is None:
            return event.ignore()
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.input.move(*point, bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier))
        else:
            inside = 0 <= point[0] <= 1 and 0 <= point[1] <= 1
            self.setCursor(Qt.CursorShape.PointingHandCursor if inside and self.input.over_link(*point)
                           else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event) -> None:
        point = self._fraction(event)
        if self.input is None or event.button() != Qt.MouseButton.LeftButton or point is None:
            return event.ignore()
        self.input.release(*point)

    def leaveEvent(self, event) -> None:
        if self.input is not None:
            self.input.leave()
        super().leaveEvent(event)
