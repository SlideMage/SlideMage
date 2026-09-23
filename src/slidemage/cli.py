"""Entry point: settle which Slidemaster project to open, then start the GUI."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import project


def _ask_for_project(parent_hint: Path | None):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    start = str(parent_hint or Path.home())
    while True:
        chosen = QFileDialog.getExistingDirectory(
            None, f"Open a Slidemaster project (folder containing {project.MARKER})", start
        )
        if not chosen:
            return None
        path = Path(chosen)
        if project.is_project(path):
            return path.resolve()
        QMessageBox.warning(
            None, "Not a Slidemaster project",
            f"{path} has no {project.MARKER}. Pick the project's root folder.",
        )
        start = chosen


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
            QMessageBox.critical(
                None, "Not a Slidemaster project", f"{root} has no {project.MARKER}."
            )
            sys.exit(2)
    else:
        root = project.discover() or _ask_for_project(Path.cwd())
        if root is None:
            sys.exit(1)

    os.environ[project.ENV_VAR] = str(root)
    project.save_last_project(root)

    from .qt_gui import main as gui_main

    gui_main()


if __name__ == "__main__":
    main()
