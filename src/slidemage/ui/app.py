# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Application start, called by cli.main() (`slidemage`) once the project is chosen: the
QApplication, the bundled fonts, the theme and the main window (workspace/window.py)."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .. import splash
from ..plugins import installer, loader, session
from ..plugins.host import PluginHost
from ..project import ProjectContext
from .plugin_ui import HOST_UI
from .kit.fonts import load_fonts
from .kit.theme import ThemeManager
from .workspace import greeting, maintenance
from .workspace.window import WorkspaceWindow

ICON_PATH = Path(__file__).resolve().parents[1] / "assets" / "icon.ico"


def load_plugins(project_context: ProjectContext) -> None:
    """Load the plugins before the window exists; a failure of the machinery itself is logged and the app starts
    without plugins (a failing plugin is already contained by the loader)."""
    try:
        installer.cleanup()
        session.set_loaded(loader.load_all(lambda manifest: PluginHost(manifest, project_context, ui=HOST_UI)))
        log = logging.getLogger(__name__)
        for plugin in session.loaded():
            log.debug("plugin %s %s: %s", plugin.id, getattr(plugin.manifest, "version", "?"), plugin.state)
    except Exception:
        logging.getLogger(__name__).exception("loading the plugins failed; starting without them")
        session.set_loaded([])


def main(project_context: ProjectContext) -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    load_fonts()
    app.setWindowIcon(QIcon(str(ICON_PATH)))
    theme = ThemeManager(project=project_context)
    theme.apply()
    load_plugins(project_context)
    window = WorkspaceWindow(theme, project_context)
    window.show()
    splash.close()
    maintenance.schedule_startup_update_check(window)
    maintenance.schedule_plugin_update_check(window)
    maintenance.schedule_theme_update_check(window)
    maintenance.schedule_citation_update_check(window)
    maintenance.schedule_plugin_offer(window)
    maintenance.schedule_course_hint(window)
    maintenance.schedule_compat_check(window)
    maintenance.schedule_bundled_copies_check(window)
    greeting.schedule_greeting(window)
    sys.exit(app.exec())

