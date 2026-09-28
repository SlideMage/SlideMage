"""Entry point: settle which Slidemaster project to open, then start the GUI."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import project, splash


def _ask_for_project(parent_hint: Path | None):
    return project.pick_or_create_project(None, parent_hint or Path.home())


def _confirm_newer_project(root: Path, info: dict) -> bool:
    """Open anyway (True) or Quit, for a project whose format is newer
    than this app's."""
    from PySide6.QtWidgets import QMessageBox

    last = info["last_app_version"] or "a newer SlideMage"
    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("Project from a newer SlideMage")
    box.setText(
        f"This project was last used with SlideMage {last}, which changed its "
        "format; this version may not handle it correctly.")
    box.setInformativeText(f"{root}\n\nUpdate SlideMage (Info → Check for updates…) to be safe.")
    open_button = box.addButton("Open anyway", QMessageBox.ButtonRole.AcceptRole)
    quit_button = box.addButton("Quit", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(quit_button)
    box.exec()
    return box.clickedButton() is open_button


def check_project_format(root: Path, app_version: str) -> bool:
    """False if the user chose not to open a project from a newer
    SlideMage; otherwise records this open in project.json."""
    info = project.read_project_info(root)
    if info["format"] > project.PROJECT_FORMAT:
        splash.close()
        if not _confirm_newer_project(root, info):
            return False
    try:
        project.record_project_open(root, app_version)
    except OSError:
        pass  # e.g. a read-only project folder -- nothing to record then
    return True


def main(argv: list[str] | None = None) -> None:
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
    args, qt_args = parser.parse_known_args(argv)

    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance() or QApplication([sys.argv[0], *qt_args])

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
            root = _ask_for_project(Path.cwd())
        if root is None:
            sys.exit(1)

    from .version import VERSION_NUMBER

    if not check_project_format(root, VERSION_NUMBER):
        sys.exit(1)

    os.environ[project.ENV_VAR] = str(root)
    project.save_last_project(root)

    from .qt_gui import main as gui_main

    gui_main()


if __name__ == "__main__":
    main()
