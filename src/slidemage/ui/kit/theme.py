# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Qt-side theme manager: the light/dark choice, and the one application
stylesheet (kit_qss.py) built from the design tokens (tokens.py) for it.

Every Qt widget picks up `QApplication.setStyleSheet()` changes automatically,
cascading through the whole widget tree with no registration step: toggling
dark/light is "rebuild the QSS string, reapply it".

palette.py's PALETTES (the pre-redesign colors) still feed what QSS cannot
express: the source editor's syntax colors and the status colors.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

from ... import app_settings
from ...project import ProjectContext
from .palette import PALETTES
from .fonts import load_fonts
from .kit_qss import KIT_ICONS, build_kit_qss
from .tokens import FONT_ICONS, Tokens, tokens_for


def _draw_icon(path: Path, glyph: str, color: str, glyph_px: int, size: int, scale: int) -> None:
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
    image.save(str(path))


def _icon_files(t: Tokens) -> dict[str, str]:
    """The images of KIT_ICONS in the theme's colors, drawn once from the Material Icons font into the
    temp folder (QSS `image: url(...)` takes files only, not glyphs or data: URIs), with the `@2x`
    file Qt picks on a high-resolution screen."""
    folder = Path(tempfile.gettempdir()) / "slidemage-kit-icons"
    folder.mkdir(exist_ok=True)
    files = {}
    for name, (glyph, token, glyph_px, size) in KIT_ICONS.items():
        color = getattr(t, token)
        path = folder / f"{name}-{color.lstrip('#')}-{glyph_px}-{size}.png"
        if not path.exists():
            load_fonts()
            _draw_icon(path.with_name(f"{path.stem}@2x.png"), glyph, color, glyph_px, size, 2)
            _draw_icon(path, glyph, color, glyph_px, size, 1)
        files[name] = path.as_posix()
    return files


class ThemeManager:
    def __init__(self, dark: bool | None = None, project: ProjectContext | None = None) -> None:
        """`dark` is for the project picker, which runs before there is a project. With a
        `project` the choice is read from its settings (the JSON file inside the project folder, so
        it travels with it; dark the first time) and written back by set_dark()."""
        self.project = project
        if dark is None:
            dark = project is None or bool(app_settings.get(project, "dark_mode", True))
        self.dark = dark

    @property
    def colors(self) -> dict[str, str]:
        return PALETTES["dark" if self.dark else "light"]

    @property
    def tokens(self) -> Tokens:
        return tokens_for(self.dark)

    def syntax_colors(self) -> dict[str, str]:
        """For a QSyntaxHighlighter's QTextCharFormat colors -- not
        QSS-expressible, since they're per-character-range formats inside a
        text document, not widget chrome."""
        c = self.colors
        return {
            "comment": c["syntax_comment"],
            "command": c["syntax_command"],
            "brace": c["syntax_brace"],
            "env": c["syntax_env"],
            "math": c["syntax_math"],
            "todo": c["syntax_todo"],
            "brace_match_bg": c["select_bg"],
        }

    def toggle(self) -> None:
        self.set_dark(not self.dark)

    def set_dark(self, dark: bool) -> None:
        self.dark = dark
        if self.project is not None:
            app_settings.set(self.project, "dark_mode", dark)
        self.apply()

    def apply(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(self._build_qss())

    def _build_qss(self) -> str:
        return build_kit_qss(self.tokens, _icon_files(self.tokens))
