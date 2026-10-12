"""Render the workspace offscreen in light and dark on an isolated example copy.

Usage: .venv/bin/python tools/ui_screenshots.py [OUTPUT] [--sizes WxH ...] [--mode preview|split|source|details]
Defaults: 1024x640 1280x800 1600x900 1920x1080; OUTPUT is a printed temp folder.
The temporary project and settings are removed afterwards; PNGs remain in OUTPUT.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path


def window_size(value: str) -> tuple[int, int]:
    try:
        width, height = map(int, value.lower().split("x"))
        if width > 0 and height > 0:
            return width, height
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("size must be WIDTHxHEIGHT with positive integers")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("output", nargs="?", type=Path, help="PNG folder (default: a new temp folder)")
    parser.add_argument("--sizes", nargs="+", type=window_size,
                        default=[(1024, 640), (1280, 800), (1600, 900), (1920, 1080)])
    parser.add_argument("--mode", choices=("preview", "split", "source", "details"),
                        help="centre view to show (default: the remembered one)")
    args = parser.parse_args(argv)
    output = args.output or Path(tempfile.mkdtemp(prefix="slidemage-ui-screenshots-"))
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    print(f"Screenshots: {output}", flush=True)

    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo / "src"))
    from slidemage.project import ProjectContext, _ignore_template_build_output

    with tempfile.TemporaryDirectory(prefix="slidemage-ui-project-") as folder:
        root = Path(folder)
        project = root / "example"
        shutil.copytree(repo / "example", project, ignore=_ignore_template_build_output)
        os.environ["SLIDEMASTER_PROJECT"] = str(project)
        os.environ["SLIDEMASTER_LATEX"] = str(repo / "latex")
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ["QT_SCALE_FACTOR"] = "1"

        from PySide6.QtCore import QCoreApplication, QEvent, QSize, Qt
        from PySide6.QtWidgets import QApplication

        from slidemage.ui import layout_settings

        layout_settings.STORE_PATH = root / "layout.json"
        QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
        app = QApplication([])

        from slidemage.ui.kit.fonts import load_fonts
        from slidemage.ui.kit.theme import ThemeManager
        from slidemage.ui.workspace.window import WorkspaceWindow

        load_fonts()
        for name, dark in (("light", False), ("dark", True)):
            theme = ThemeManager(dark=dark)
            theme.apply()
            window = WorkspaceWindow(theme, ProjectContext.at(project))
            if args.mode:
                window.state.set_mode(args.mode)
            try:
                for width, height in args.sizes:
                    window.resize(width, height)
                    window.show()
                    app.processEvents()
                    if window.size() != QSize(width, height):
                        raise ValueError(f"window cannot fit {width}x{height}: {window.size()}")
                    path = output / f"workspace-{name}-{width}x{height}.png"
                    if not window.grab().save(str(path), "PNG"):
                        raise OSError(f"could not save {path}")
                    print(path, flush=True)
            finally:
                window.hide()
                window.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
    return 0


if __name__ == "__main__":
    sys.exit(main())
