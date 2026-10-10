"""Application start, called by cli.main() (`slidemage`) once the project is chosen: the
QApplication, the bundled fonts, the theme and the main window (workspace/window.py)."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .. import splash
from .kit.fonts import load_fonts
from .kit.theme import ThemeManager
from .workspace.window import WorkspaceWindow

ICON_PATH = Path(__file__).resolve().parents[1] / "assets" / "icon.ico"


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    load_fonts()
    app.setWindowIcon(QIcon(str(ICON_PATH)))
    theme = ThemeManager()
    theme.apply()
    window = WorkspaceWindow(theme)
    window.show()
    splash.close()
    window.schedule_startup_update_check()
    window.schedule_compat_check()
    window.schedule_bundled_copies_check()
    sys.exit(app.exec())

