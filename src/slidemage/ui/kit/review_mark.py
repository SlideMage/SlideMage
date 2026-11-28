# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The watermark over a slide that its deck marks as under review (\\SMReview{...}, deck_editor.py).

Drawn by the app over the preview page and the slide list's thumbnail: it is not part of the slide's render or of
the compiled PDF.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter

ANGLE = -24.0               # degrees, rising to the right
COLOR = (200, 30, 30, 96)   # a red a slide's own content stays readable under
NOTE_MIN_HEIGHT = 120       # a page lower than this (a thumbnail) shows the text only
NOTE_WIDTH = 0.6            # of the page's width
NOTE_MARGIN = 0.03          # of the page's height, kept free under the note
NOTE_LINES = 3              # a note wraps onto this many lines before its type gets smaller
NOTE_MIN_SIZE = 7           # px


def paint_review_mark(painter: QPainter, page: QRectF, text: str, note: str = "") -> None:
    """Draw `text` across `page`, and `note` in small type under it when the page is large enough to read it.
    A note wraps onto up to NOTE_LINES lines and only then gets smaller; text and note are centered together."""
    if not text or page.width() < 8 or page.height() < 8:
        return
    painter.save()
    painter.setClipRect(page)
    font = QFont(painter.font())
    font.setBold(True)
    font.setPixelSize(100)
    width = QFontMetricsF(font).horizontalAdvance(text) or 1.0
    # as wide as 70 % of the page, and never taller than a third of it (a one-letter text)
    size = max(4, int(min(100 * page.width() * 0.7 / width, page.height() / 3)))
    band = size * 1.4               # the text's own height
    note_font, note_width, note_height = QFont(font), page.width() * NOTE_WIDTH, 0.0
    if note and page.height() >= NOTE_MIN_HEIGHT:
        note_font.setBold(False)
        room = note_room(page, note_width, band)
        note_font.setPixelSize(note_font_size(note_font, note, note_width, max(NOTE_MIN_SIZE, size // 4), room))
        lines = min(note_lines(note_font, note, note_width, note_font.pixelSize()), NOTE_LINES)
        note_height = min(lines * _line_height(note_font), max(room, 0.0))
    painter.translate(page.center())
    painter.rotate(ANGLE)
    painter.translate(0, -note_height / 2)
    font.setPixelSize(size)
    painter.setFont(font)
    painter.setPen(QColor(*COLOR))
    line = QRectF(-page.width(), -band / 2, 2 * page.width(), band)
    painter.drawText(line, Qt.AlignmentFlag.AlignCenter, text)
    if note_height:
        painter.setFont(note_font)
        painter.setClipRect(QRectF(-note_width / 2, line.bottom(), note_width, note_height), Qt.ClipOperation.IntersectClip)
        painter.drawText(QRectF(-note_width / 2, line.bottom(), note_width, note_height + 100000),
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, note)
    painter.restore()


def note_room(page: QRectF, note_width: float, band: float) -> float:
    """The height a note `note_width` wide can take under a text `band` high so that both, centered together and
    turned by ANGLE, stay inside `page`: the note's lower left corner is the first to reach the page's bottom."""
    angle = math.radians(abs(ANGLE))
    half = (page.height() * (0.5 - NOTE_MARGIN) - note_width / 2 * math.sin(angle)) / math.cos(angle)
    return 2 * half - band


def note_font_size(font: QFont, note: str, width: float, size: int, room: float | None = None) -> int:
    """The pixel size for `note` in a box `width` wide: `size` while it fits on NOTE_LINES wrapped lines (fewer when
    `room`, the height there is, holds fewer), else the largest smaller size that does. Never under NOTE_MIN_SIZE:
    what is left over then is cut off."""
    def fits(size: int) -> bool:
        probe = QFont(font)
        probe.setPixelSize(size)
        allowed = NOTE_LINES if room is None else min(NOTE_LINES, int(room // _line_height(probe)))
        return note_lines(font, note, width, size) <= allowed

    while size > NOTE_MIN_SIZE and not fits(size):
        size -= 1
    return size


def note_lines(font: QFont, note: str, width: float, size: int) -> int:
    """How many lines `note` takes at `size` px, wrapped at words in a box `width` wide; NOTE_LINES + 1 when a
    word is wider than the box."""
    font = QFont(font)
    font.setPixelSize(size)
    box = QFontMetricsF(font).boundingRect(QRectF(0, 0, width, 100000),
                                           Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap, note)
    if box.width() > width + 0.5:
        return NOTE_LINES + 1
    return max(1, round(box.height() / _line_height(font)))


def _line_height(font: QFont) -> float:
    """One laid-out line's height: measured, since a fallback font's lines differ from the font's own metrics."""
    return QFontMetricsF(font).boundingRect(QRectF(0, 0, 100000, 100000), Qt.AlignmentFlag.AlignLeft, "Xg").height() or 1.0
