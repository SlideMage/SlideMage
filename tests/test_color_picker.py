# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tools → Pick color from screen."""

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPixmap

from slidemage.ui.workspace import color_picker
from slidemage.ui.workspace.color_picker import ColorPickerOverlay, color_at, hex_of


def test_a_color_is_written_as_upper_case_hex():
    assert hex_of(QColor(0, 112, 192)) == "#0070C0"
    assert hex_of(QColor(255, 255, 255)) == "#FFFFFF"


def test_color_at_reads_a_pixel_and_nothing_outside_the_image():
    image = QImage(4, 3, QImage.Format.Format_RGB32)
    image.fill(QColor("#102030"))
    image.setPixelColor(2, 1, QColor("#ABCDEF"))
    assert hex_of(color_at(image, 2, 1)) == "#ABCDEF" and hex_of(color_at(image, 0, 0)) == "#102030"
    assert color_at(image, 4, 0) is None and color_at(image, -1, 0) is None and color_at(image, 0, 3) is None


def test_the_overlay_picks_the_pixel_under_the_pointer_and_scales_with_the_screen(qapp):
    screen = QGuiApplication.primaryScreen()
    pixmap = QPixmap(40, 20)
    pixmap.fill(QColor("#336699"))
    pixmap.setDevicePixelRatio(2.0)                 # 40 x 20 device pixels on a 20 x 10 screen area
    overlay = ColorPickerOverlay(screen, pixmap)
    got = []
    overlay.picked.connect(got.append)
    image = pixmap.toImage()
    image.setPixelColor(6, 4, QColor("#FF8800"))     # device pixel (6, 4) is the logical point (3, 2)
    overlay._image = image
    assert hex_of(overlay.color_under(QPoint(3, 2))) == "#FF8800"
    overlay._finish(overlay.color_under(QPoint(3, 2)))
    assert got == ["#FF8800"]
