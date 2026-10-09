"""Qt-side theme manager for SlideMage's PySide6 rewrite -- see
PYSIDE6_MIGRATION.md. Reuses palette.py's PALETTES data verbatim (the exact
same color values theme.py's Tk ThemeManager uses), but replaces its entire
ttk.Style()/weakref-registry apparatus with a single QSS stylesheet string
applied to the whole QApplication.

theme.py's own module docstring explains *why* it needs per-widget
registration at all: plain tk widgets have no shared style layer, so each
one has to be found and recolored individually, by weak reference, on every
toggle. None of that applies here -- every Qt widget (built-in or custom)
picks up `QApplication.setStyleSheet()` changes automatically, cascading
through the whole widget tree with no registration step. Toggling dark/light
is just "rebuild the QSS string, reapply it."

Three widget-role names (matching theme.py's "Link.TLabel"/"Muted.TLabel"/
"Warning.TLabel" named ttk styles) are exposed as Qt object-name constants --
set them via `label.setObjectName(LINK_LABEL)` and the QSS rules below apply
automatically. Unlike a DOM id, a Qt objectName is not required to be
unique, so many labels can share one.

Moved here from slidemage/qt_theme.py on 2026-10-09 (UI redesign, step 1).
The palette above still styles the old widgets; the redesign's design tokens
(tokens.py) are exposed as `ThemeManager.tokens` and turned into QSS for the
kit widgets by kit_qss.py, appended to the same application stylesheet.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication

from ... import app_settings
from ...palette import PALETTES, Mode
from .kit_qss import build_kit_qss
from .tokens import Tokens, tokens_for

LINK_LABEL = "linkLabel"
MUTED_LABEL = "mutedLabel"
WARNING_LABEL = "warningLabel"
FORMAT_TOOLBAR = "formatToolbar"
CLOSE_BUTTON = "closeButton"


def _checkmark_icon_path() -> str:
    """A checked QCheckBox::indicator needs an actual tick glyph, not just
    a solid fill, to read unambiguously as "on" rather than merely
    colored -- but QSS's `image: url(...)` does NOT support data: URIs
    (confirmed directly: it silently no-ops, leaving just the
    background-color), only real file/qrc paths. So this draws one once
    with QPainter and caches it to a stable temp-dir path outside the
    project tree, generated fresh only if missing. White reads fine on
    both palettes' checked fill color (select_bg), since select_fg -- the
    color Qt would normally pick for "on top of a selection" -- is white
    in both."""
    path = Path(tempfile.gettempdir()) / "slidemage_checkmark.png"
    if not path.exists():
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("white"))
        pen.setWidthF(2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline([QPointF(3.5, 8.5), QPointF(6.5, 11.5), QPointF(12.5, 4.5)])
        painter.end()
        pixmap.save(str(path))
    return path.as_posix()


class ThemeManager:
    def __init__(self) -> None:
        # Persisted UI preference (2026-08-25, moved into the Settings
        # dialog) -- stored via app_settings.py, a plain JSON file inside
        # SlideMage/ itself, not the Windows registry (tried first via
        # QSettings, replaced the same day, direct instruction: this
        # project's whole folder already lives in a synced location, and
        # SlideMage's own settings should travel with it to another
        # machine rather than being tied to one PC's own registry). True
        # (matching this app's own long-standing default) the first time
        # it's ever run anywhere this settings file doesn't exist yet.
        self.dark = bool(app_settings.get("dark_mode", True))

    @property
    def colors(self) -> dict[str, str]:
        return PALETTES["dark" if self.dark else "light"]

    @property
    def tokens(self) -> Tokens:
        return tokens_for(self.dark)

    def status_color(self, status: str) -> str:
        return self.colors[f"status_{status}"]

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
        app_settings.set("dark_mode", dark)
        self.apply()

    def apply(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(self._build_qss())

    def _build_qss(self) -> str:
        c = self.colors
        checkmark = _checkmark_icon_path()
        # First pass covering every widget type this migration's plan
        # calls for (QMainWindow/QWidget/QLabel/QPushButton/QCheckBox/
        # QLineEdit/QComboBox/QPlainTextEdit/QListWidget/QTabWidget/
        # QScrollBar/QDialog) -- individual selectors will likely need
        # tuning once each widget is actually built out in later phases
        # and rendered for real, same as any first-pass stylesheet would.
        qss = f"""
            QMainWindow, QWidget {{
                background-color: {c['bg']};
                color: {c['fg']};
            }}
            QLabel {{
                background-color: transparent;
                color: {c['fg']};
            }}
            QLabel#{LINK_LABEL} {{
                color: {c['link_fg']};
            }}
            QLabel#{MUTED_LABEL} {{
                color: {c['muted_fg']};
            }}
            QLabel#{WARNING_LABEL} {{
                color: {c['warning_fg']};
            }}
            QPushButton {{
                background-color: {c['panel_bg']};
                color: {c['fg']};
                border: 1px solid {c['border']};
                padding: 4px 10px;
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background-color: {c['select_bg']};
                color: {c['select_fg']};
            }}
            QPushButton:disabled {{
                color: {c['disabled_fg']};
            }}
            QCheckBox {{
                background-color: transparent;
                color: {c['fg']};
                spacing: 6px;
            }}
            QCheckBox:disabled {{
                color: {c['disabled_fg']};
            }}
            QCheckBox::indicator {{
                width: 15px;
                height: 15px;
                border: 1px solid {c['fg']};
                border-radius: 3px;
                background-color: {c['entry_bg']};
            }}
            QCheckBox::indicator:hover {{
                border: 1px solid {c['link_fg']};
            }}
            QCheckBox::indicator:checked {{
                background-color: {c['select_bg']};
                border: 1px solid {c['select_bg']};
                image: url({checkmark});
            }}
            QCheckBox::indicator:checked:disabled {{
                background-color: {c['disabled_fg']};
                border: 1px solid {c['disabled_fg']};
                image: url({checkmark});
            }}
            QRadioButton {{
                background-color: transparent;
                color: {c['fg']};
                spacing: 6px;
            }}
            QRadioButton:disabled {{
                color: {c['disabled_fg']};
            }}
            QRadioButton::indicator {{
                width: 14px;
                height: 14px;
                border: 1px solid {c['fg']};
                border-radius: 7px;
                background-color: {c['entry_bg']};
            }}
            QRadioButton::indicator:hover {{
                border: 1px solid {c['link_fg']};
            }}
            QRadioButton::indicator:checked {{
                background-color: {c['select_bg']};
                border: 1px solid {c['select_bg']};
            }}
            QRadioButton::indicator:checked:disabled {{
                background-color: {c['disabled_fg']};
                border: 1px solid {c['disabled_fg']};
            }}
            QWidget#{FORMAT_TOOLBAR} QPushButton, QWidget#{FORMAT_TOOLBAR} QComboBox {{
                background-color: {c['format_toolbar_button_bg']};
            }}
            QPushButton#{CLOSE_BUTTON} {{
                border: 1px solid {c['status_fail']};
                color: {c['status_fail']};
            }}
            QPushButton#{CLOSE_BUTTON}:hover {{
                background-color: {c['status_fail']};
                color: #ffffff;
            }}
            QPushButton#{CLOSE_BUTTON}:disabled {{
                border: 1px solid {c['border']};
                color: {c['disabled_fg']};
            }}
            QLineEdit, QPlainTextEdit, QTextEdit {{
                background-color: {c['entry_bg']};
                color: {c['entry_fg']};
                border: 1px solid {c['border']};
                selection-background-color: {c['select_bg']};
                selection-color: {c['select_fg']};
            }}
            QComboBox {{
                background-color: {c['entry_bg']};
                color: {c['entry_fg']};
                border: 1px solid {c['border']};
                padding: 2px 6px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {c['entry_bg']};
                color: {c['entry_fg']};
                selection-background-color: {c['select_bg']};
                selection-color: {c['select_fg']};
            }}
            QListWidget {{
                background-color: {c['entry_bg']};
                color: {c['entry_fg']};
                border: 1px solid {c['border']};
            }}
            QListWidget::item:selected {{
                background-color: {c['select_bg']};
                color: {c['select_fg']};
            }}
            QTabWidget::pane {{
                border: 1px solid {c['border']};
                background-color: {c['bg']};
            }}
            QTabBar::tab {{
                background-color: {c['bg']};
                padding: 6px 12px;
                border: 1px solid {c['border']};
                border-bottom: none;
                max-width: 220px;
            }}
            QTabBar::tab:selected {{
                background-color: {c['panel_bg']};
            }}
            QScrollBar:vertical, QScrollBar:horizontal {{
                background-color: {c['trough']};
            }}
            /* select_bg (the same blue as a checked checkbox/radio) rather
               than panel_bg: the handle used to be barely darker than its
               own trough in dark mode, so it was unclear which part of the
               scrollbar was draggable. */
            QScrollBar::handle {{
                background-color: {c['select_bg']};
                border: 1px solid {c['select_bg']};
            }}
            QScrollBar::handle:hover {{
                background-color: {c['link_fg']};
                border: 1px solid {c['link_fg']};
            }}
            QDialog {{
                background-color: {c['bg']};
                color: {c['fg']};
            }}
            /* QMenu (2026-08-26, direct report: the "System" menu's second
               item, "Exit SlideMage", sat with almost no right margin
               against the dropdown's own border). Any QSS applying to
               QWidget at all -- the very first rule in this stylesheet --
               already switches Qt from native menu chrome to its own
               QSS-driven rendering for every QMenu too, since QMenu is a
               QWidget; that rendering path's own *default* item padding is
               tighter than a native Windows menu's, particularly on the
               right, which is what actually needed fixing here, not the
               menu's overall width (QMenu already sizes itself to its
               widest item automatically). */
            QMenu {{
                background-color: {c['panel_bg']};
                color: {c['fg']};
                border: 1px solid {c['border']};
            }}
            QMenu::item {{
                padding: 5px 24px 5px 12px;
            }}
            QMenu::item:selected {{
                background-color: {c['select_bg']};
                color: {c['select_fg']};
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {c['border']};
                margin: 4px 6px;
            }}
        """
        return qss + build_kit_qss(self.tokens)
