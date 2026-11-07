# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared glyph drawing and opt-in widget styles, using the real kit stylesheet."""
from pathlib import Path

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QColorDialog, QLabel

from slidemage.plugins.host import PluginHost
from slidemage.ui.kit import theme as theme_module
from slidemage.ui.kit.fonts import load_fonts
from slidemage.ui.kit.kit_qss import KIT_ICONS
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.kit.tokens import FONT_ICONS, FONT_MONO, TYPE, tokens_for
from slidemage.ui.kit.widgets import Chip, ColorSwatchButton, IconButton


def _legacy_icon(path, glyph, color, glyph_px, size, scale):
    # Frozen pre-stage-2 QSS renderer: compare encoded PNG bytes, not just pixels.
    image = QImage(size * scale, size * scale, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    font = QFont(FONT_ICONS)
    font.setPixelSize(glyph_px * scale)
    painter.setFont(font)
    painter.setPen(QColor(color))
    painter.drawText(image.rect(), Qt.AlignmentFlag.AlignCenter, glyph)
    painter.end()
    assert image.save(str(path))


@pytest.mark.parametrize("dark", [False, True])
def test_qss_icon_files_stay_byte_identical(qapp, tmp_path, monkeypatch, dark):
    load_fonts()
    monkeypatch.setattr(theme_module.tempfile, "gettempdir", lambda: str(tmp_path))
    tokens = tokens_for(dark)
    files = theme_module._icon_files(tokens)
    for name, (glyph, token, glyph_px, size) in KIT_ICONS.items():
        path = Path(files[name])
        for scale in (1, 2):
            actual = path if scale == 1 else path.with_name(f"{path.stem}@2x.png")
            expected = tmp_path / f"{name}-legacy-{scale}.png"
            _legacy_icon(expected, glyph, getattr(tokens, token), glyph_px, size, scale)
            assert actual.read_bytes() == expected.read_bytes()


@pytest.mark.parametrize("dark", [False, True])
@pytest.mark.parametrize("px", [16, 23])
def test_host_icon_has_native_1x_and_2x_pixmaps(qapp, dark, px):
    # icon() has no window or project dependency.
    icon = PluginHost.icon(None, "check", tokens_for(dark).ok, px)
    assert not icon.isNull()
    for scale in (1, 2):
        pixmap = icon.pixmap(QSize(px, px), scale)
        assert pixmap.size() == QSize(px * scale, px * scale)
        assert pixmap.devicePixelRatio() == scale
        image = pixmap.toImage()
        assert any(image.pixelColor(x, y).alpha() for x in range(image.width()) for y in range(image.height()))


@pytest.mark.parametrize("dark", [False, True])
def test_host_widget_options_and_faint_restyle_both_ways(qapp, dark):
    tokens = tokens_for(dark)
    sheet = ThemeManager(dark=dark)._build_qss()
    button = PluginHost.IconButton(None, "more_vert", "More", faint=True)
    assert isinstance(button, IconButton)
    button.setStyleSheet(sheet)
    button.show()
    qapp.processEvents()
    role = button.foregroundRole()
    faint = button.palette().color(role)
    assert faint.rgb() == QColor(tokens.text_4).rgb() and abs(faint.alphaF() - 0.55) < 0.01   # text_4 at 55 %
    before = button.grab().toImage()
    button.set_faint(False)
    assert button.palette().color(role) == QColor(tokens.text)
    assert button.grab().toImage() != before
    button.set_faint(True)
    assert button.palette().color(role) == faint
    assert button.grab().toImage() == before
    normal = PluginHost.IconButton(None, "more_vert", "More")
    assert normal.property("faint") is False
    normal.setStyleSheet(sheet)
    normal.ensurePolished()
    assert normal.palette().color(role) == QColor(tokens.text)
    button.close()

    for mono in (False, True):
        chip = PluginHost.Chip(None, "1-0-0", icon="check", mono=mono)
        assert isinstance(chip, Chip)
        chip.setStyleSheet(sheet)
        chip.show()
        qapp.processEvents()
        label = next(label for label in chip.findChildren(QLabel) if label.text() == "1-0-0")
        if mono:
            assert label.font().pixelSize() == TYPE.micro
            assert label.font().family() == FONT_MONO
        icon = next(label for label in chip.findChildren(QLabel) if label.text() == "check")
        assert icon.font().family() == FONT_ICONS
        assert icon.fontMetrics().horizontalAdvance("check") < 20
        chip.close()


def test_swatch_keeps_its_label_and_only_emits_clicked(qapp):
    button = ColorSwatchButton("Colour")
    heard = []
    button.clicked.connect(lambda: heard.append(True))
    button.set_color("#8055aaff")
    assert button.text() == "Colour"
    assert "#55aaff" in button.styleSheet()
    button.click()
    assert heard == [True]
    assert not button.findChildren(QColorDialog)
