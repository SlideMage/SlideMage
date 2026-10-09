"""Application bootstrap, started via cli.main() (`slidemage`): the
QApplication, the bundled fonts, the theme and the main window
(ui/workspace/window.py). PYSIDE6_MIGRATION.md has the history of the Qt
port; docs/UI_REDESIGN_PLAN.md the plan for the window itself.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import splash
from .ui.kit.fonts import load_fonts
from .ui.kit.theme import ThemeManager
from .ui.workspace.window import WorkspaceWindow

ICON_PATH = Path(__file__).resolve().parent / "assets" / "icon.ico"


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


if __name__ == "__main__":
    main()
