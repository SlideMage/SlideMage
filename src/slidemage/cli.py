"""Entry point: settle which Slidemaster project to open, then start the GUI."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import project, splash


def _ask_for_project(parent_hint: Path | None):
    return project.pick_or_create_project(None, parent_hint or Path.home())


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

    os.environ[project.ENV_VAR] = str(root)
    project.save_last_project(root)

    from .qt_gui import main as gui_main

    gui_main()


if __name__ == "__main__":
    main()
