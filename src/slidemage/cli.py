# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Entry point: settle which Slidemaster project to open, then start the GUI."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import project, splash

CLAUDE_HOOK_FLAG = "--claude-hook"   # first argument: run Claude Code's hook instead of the app (ai/claude_launch.py)
# First argument: import everything the window needs, then exit 0, with no window. The release workflow runs
# each build with it before uploading, so a build that stops at startup (a library missing from the bundle, as
# PyMuPDF 2.0's layout model in v8.33.0's Windows build) is never published.
SELF_TEST_FLAG = "--self-test"
PLUGINS_FLAG = "--plugins"   # after SELF_TEST_FLAG: the plugin host's self-test instead (plugins/selftest.py)


def _prepare_gui(project_root: Path | None) -> None:
    """The fonts and the kit stylesheet, for the sheets that run before the window (the project
    picker, the newer-project question). With a project, its settings decide light or dark; the
    picker has none."""
    from .ui.kit.fonts import load_fonts
    from .ui.kit.theme import ThemeManager

    load_fonts()
    ThemeManager(project=project.ProjectContext.at(project_root) if project_root is not None else None).apply()


def _ask_for_project() -> Path | None:
    from .ui.dialogs.open_project import OpenProjectSheet

    from .ui.presentation.launch import present_pdf_file

    _prepare_gui(None)
    while True:
        sheet = OpenProjectSheet(first_run=True)
        sheet.exec()
        if sheet.pdf is None:
            return sheet.chosen
        present_pdf_file(sheet.pdf)      # no project needed; afterwards the start screen comes back


def _confirm_newer_project(root: Path, info: dict) -> bool:
    """Open anyway (True) or Quit, for a project whose format is newer
    than this app's."""
    from .ui.dialogs.open_project import NewerProjectSheet
    from .version import VERSION_NUMBER

    _prepare_gui(root)
    sheet = NewerProjectSheet(None, root.name, info["last_app_version"], VERSION_NUMBER, opening=True)
    sheet.exec()
    return sheet.choice == NewerProjectSheet.OPEN


def check_project_format(root: Path, app_version: str) -> bool:
    """False if the user chose not to open a project from a newer
    SlideMage; otherwise records this open in project.json."""
    info = project.read_project_info(root)
    if info["format"] > project.PROJECT_FORMAT:
        splash.close()
        if not _confirm_newer_project(root, info):
            return False
    if project.is_snapshot(root):
        return True  # a deck snapshot stays exactly as it was made
    try:
        project.record_project_open(root, app_version)
    except OSError:
        pass  # e.g. a read-only project folder -- nothing to record then
    return True


def main(argv: list[str] | None = None) -> None:
    if (sys.argv[1:] if argv is None else argv)[:1] == ['--preview-raster']:
        # A frozen executable has no python -m; dispatch before project/GUI setup.
        from .preview_raster import serve
        serve()
        return
    if (sys.argv[1:] if argv is None else argv)[:1] == [CLAUDE_HOOK_FLAG]:
        # Claude Code's PreToolUse hook (ai/claude_hook.py), run as this program in a frozen build, which
        # has no `python -m`: before anything else, no window.
        from .ai import claude_hook

        sys.exit(claude_hook.main())
    if (sys.argv[1:] if argv is None else argv)[:2] == [SELF_TEST_FLAG, PLUGINS_FLAG]:
        # The plugin host's check (plugins/selftest.py): every standard-library module a plugin may import, then a
        # plugin loaded through the loader. No window; before the window's imports, so it is checked on its own.
        splash.close()
        from .plugins import selftest

        sys.exit(selftest.run())
    if (sys.argv[1:] if argv is None else argv)[:1] == [SELF_TEST_FLAG]:
        splash.close()
        try:
            from .ui import app  # noqa: F401 -- the import is the test: the window's modules and their libraries
        except BaseException:
            # Exit 1 here: an exception left to a windowed build opens a message box, which no one clicks in CI.
            import traceback

            traceback.print_exc()
            sys.exit(1)
        print("SlideMage self-test: ok")
        return
    parser = argparse.ArgumentParser(
        prog="slidemage",
        description="Build, compile and manage Slidemaster slide decks.",
    )
    parser.add_argument(
        "--project", type=Path,
        help=f"Slidemaster project folder (the one containing {project.MARKER}). "
             f"Default: ${project.ENV_VAR}, else searched upward from the current "
             "directory, else the last project opened.",
    )
    parser.add_argument(
        "--check-project", action="store_true",
        help="no window: print what a newer SlideMage changed that may affect the project "
             "(and write .slidemage/compat-report.md/.json); exit code 1 if something "
             "may break. With --fix the automatic updates run first (backed up).")
    parser.add_argument("--fix", action="store_true", help="with --check-project: run the automatic updates")
    parser.add_argument("--json", action="store_true", help="with --check-project: print JSON")
    args, qt_args = parser.parse_known_args(argv)

    if args.check_project:
        from . import compat

        root = args.project or project.find_upward(Path.cwd()) or project.load_last_project()
        if root is None:
            print("No project found; give one with --project.", file=sys.stderr)
            sys.exit(2)
        sys.exit(compat.main([str(root)] + (["--fix"] if args.fix else []) + (["--json"] if args.json else [])))

    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtWidgets import QApplication, QMessageBox

    # Qt WebEngine (the Claude Code terminal) needs this before the QApplication exists.
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication.instance() or QApplication([sys.argv[0], *qt_args])  # noqa: F841 -- keep QApplication alive

    if args.project is not None:
        root = args.project.resolve()
        if not project.is_project(root):
            splash.close()
            QMessageBox.critical(
                None, "Not a Slidemaster project", f"{root} has no {project.MARKER}."
            )
            sys.exit(2)
    else:
        root = project.discover()
        if root is None:
            splash.close()  # the folder picker would open underneath it
            root = _ask_for_project()
        if root is None:
            sys.exit(1)

    from .version import VERSION_NUMBER

    os.environ[project.ENV_VAR] = str(root)   # before the first sheet: its theme reads the project's settings
    if not check_project_format(root, VERSION_NUMBER):
        sys.exit(1)

    project.save_last_project(root)

    from .ui.app import main as gui_main

    gui_main(project.ProjectContext.at(root))


if __name__ == "__main__":
    main()
