"""A QTabBar that shows a permanent close "x" on every closable tab
(2026-08-25 direct instruction: only appears on hover, does not always
take up room; 2026-08-26, direct instruction: reversed -- shown
permanently, tabs widened to make room for it).

Qt's built-in `QTabWidget.setTabsClosable(True)` was considered first and
does almost exactly this (an always-visible close button that widens the
tab), but it's a real QToolButton child widget per tab, styled through a
different QSS path (`QTabBar::close-button`) than the rest of this app's
QSS theming -- painting the glyph directly here keeps it themed the same
simple way as everything else in ui/kit/theme.py's stylesheet, and keeps the
hit-test/close-request wiring in one place (_is_closable/_on_close_requested
callbacks, not a signal this class would otherwise need to route through).
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QStyle, QStyleOptionTab, QTabBar

_CLOSE_BOX = 17  # px square hit/paint target for the "x"
_CLOSE_RIGHT_INSET = 5  # gap from the tab's own right edge to the box
# Extra tab width reserved for the close box, beyond the tab's own natural
# (text-only) width. Confirmed directly (measuring the label's actual
# right edge against the close box's left edge) that this allowance and
# the resulting visual gap between them do NOT move 1:1 -- the tab's own
# natural width already includes some built-in right-side slack before
# _CLOSE_BOX/_CLOSE_RIGHT_INSET are even added, so the old value
# (_CLOSE_BOX + 2 * _CLOSE_RIGHT_INSET = 27px) measured as a 16px visual
# gap, not 27px. 19 measures as 8px -- half of that -- which is what was
# actually asked for (2026-08-26, direct report: the gap looked too wide).
_CLOSE_WIDTH_ALLOWANCE = 19


class ClosableTabBar(QTabBar):
    def __init__(
        self,
        is_closable: Callable[[int], bool],
        on_close_requested: Callable[[int], None],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._is_closable = is_closable
        self._on_close_requested = on_close_requested
        # Qt's own default (2026-08-26, direct report: a 2-tab bar in a
        # normal-width window showed the last tab stretched wildly wide,
        # its text left looking oddly off-center in the leftover space) --
        # expanding stretches tabs to fill any leftover width in the bar
        # beyond what their own tabSizeHint()s need, which fights directly
        # with tabSizeHint() being deliberately widened above for the
        # close glyph: with expanding on, that +27px was lost in a much
        # bigger, uneven stretch driven by whatever room happened to be
        # left in the window, not by this tab's own actual content. Off,
        # every tab sizes to exactly what it needs (still capped by
        # ui/kit/theme.py's own `max-width: 220px` QSS for a long title).
        self.setExpanding(False)

    def _close_rect(self, index: int) -> QRect:
        tab_rect = self.tabRect(index)
        return QRect(
            tab_rect.right() - _CLOSE_RIGHT_INSET - _CLOSE_BOX,
            tab_rect.center().y() - _CLOSE_BOX // 2,
            _CLOSE_BOX,
            _CLOSE_BOX,
        )

    def tabSizeHint(self, index: int) -> QSize:
        hint = super().tabSizeHint(index)
        if self._is_closable(index):
            hint.setWidth(hint.width() + _CLOSE_WIDTH_ALLOWANCE)
        return hint

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.tabAt(event.position().toPoint())
            if (
                index != -1 and self._is_closable(index)
                and self._close_rect(index).contains(event.position().toPoint())
            ):
                self._on_close_requested(index)
                return
        super().mousePressEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        style = self.style()
        # Paint each tab's shape (background/border, still fully
        # QSS-themed) via the style directly, then draw the label
        # ourselves left-aligned -- letting the default paintEvent()/
        # CE_TabBarTab draw the label (2026-08-26, direct report: still
        # visibly centered after adding `text-align: left` to
        # QTabBar::tab's QSS) doesn't work: confirmed directly that Qt's
        # tab styles hardcode centered label painting and simply ignore
        # text-align there, unlike most other QSS-styled controls.
        for index in range(self.count()):
            option = QStyleOptionTab()
            self.initStyleOption(option, index)
            style.drawControl(QStyle.ControlElement.CE_TabBarTabShape, option, painter, self)

            text_rect = style.subElementRect(QStyle.SubElement.SE_TabBarTabText, option, self)
            color = self.tabTextColor(index)
            if not color.isValid():
                color = self.palette().text().color()
            painter.setPen(color)
            font = self.font()
            font.setUnderline(index == self.currentIndex())
            painter.setFont(font)
            elided = painter.fontMetrics().elidedText(
                self.tabText(index), Qt.TextElideMode.ElideRight, text_rect.width()
            )
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)

        pen = painter.pen()
        pen.setColor(self.palette().text().color())
        pen.setWidthF(1.7)
        painter.setPen(pen)
        pad = 4
        for index in range(self.count()):
            if not self._is_closable(index):
                continue
            rect = self._close_rect(index)
            painter.drawLine(
                QPoint(rect.left() + pad, rect.top() + pad),
                QPoint(rect.right() - pad, rect.bottom() - pad),
            )
            painter.drawLine(
                QPoint(rect.left() + pad, rect.bottom() - pad),
                QPoint(rect.right() - pad, rect.top() + pad),
            )
        painter.end()
