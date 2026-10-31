# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""SlideMage Presenter: a small program that presents a PDF without a project (docs/plans/presenter-app.md).

`SlideMagePresenter talk.pdf` presents it at once and then shows the start window; without an argument the start
window comes first. It imports only the presentation modules and the kit, never the project, compiler or
workspace (tests/test_presenter_imports.py), so the frozen build stays small and starts fast."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# First argument: import everything the Presenter needs, then exit 0, with no window (as cli.SELF_TEST_FLAG).
SELF_TEST_FLAG = "--self-test"
ICON_PATH = Path(__file__).resolve().parent / "assets" / "presenter-icon.svg"
# Opt-in start-time measurement (docs/plans/presenter-app.md, step 3): with SLIDEMAGE_PRESENTER_TIMING=1 the start
# window is shown, the time since the process was created goes to SLIDEMAGE_PRESENTER_TIMING_FILE (or stdout), and
# the program quits; nothing is written to the settings. packaging/launch_presenter.py sets PROCESS_START.
TIMING_ENV = "SLIDEMAGE_PRESENTER_TIMING"
TIMING_FILE_ENV = "SLIDEMAGE_PRESENTER_TIMING_FILE"
_IMPORTED_AT = time.perf_counter()
PROCESS_START: float | None = None      # time.perf_counter() at the first line of the launcher, if it set it


def _seconds_since_process_start() -> float:
    """Seconds since this process was created: from the operating system on Windows (so the bootloader's time counts),
    else since the launcher's first line, else since this module was imported."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            created, _exit, _kernel, _user = (wintypes.FILETIME() for _ in range(4))
            if kernel32.GetProcessTimes(kernel32.GetCurrentProcess(), ctypes.byref(created), ctypes.byref(_exit),
                                        ctypes.byref(_kernel), ctypes.byref(_user)):
                ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime      # 100 ns since 1601
                now = wintypes.FILETIME()
                kernel32.GetSystemTimeAsFileTime(ctypes.byref(now))
                return (((now.dwHighDateTime << 32) | now.dwLowDateTime) - ticks) / 1e7
        except Exception:
            pass
    return time.perf_counter() - (PROCESS_START if PROCESS_START is not None else _IMPORTED_AT)


def _self_test() -> int:
    try:
        import pymupdf  # noqa: F401
        from PySide6 import QtCore, QtGui, QtSvg, QtWidgets  # noqa: F401

        from .presentation import recent  # noqa: F401
        from .ui.kit import fonts, theme, widgets  # noqa: F401
        from .ui.presentation import presenter_window, resume_ui, settings_page, standalone  # noqa: F401
    except BaseException:
        # Exit 1 here: an exception left to a windowed build opens a message box, which no one clicks in CI.
        import traceback

        traceback.print_exc()
        return 1
    print("SlideMage Presenter self-test: ok")
    return 0


def pdf_arguments(argv: list[str]) -> list[Path]:
    """The .pdf files among the command-line arguments."""
    return [Path(arg) for arg in argv if arg.lower().endswith(".pdf")]


def make_filter(app):
    """An event filter on `app` for macOS's "open this file": a file opened from Finder arrives as a QFileOpenEvent,
    not in argv. Windows and Linux never send it, so it does nothing there. A file that arrives before the start
    window exists waits in `pending`; afterwards it is presented from the event loop, not from inside the event."""
    from PySide6.QtCore import QEvent, QObject, QTimer

    class Filter(QObject):
        def __init__(self) -> None:
            super().__init__(app)
            self.window = None                  # the start window, once it exists
            self.pending: list[Path] = []       # files opened before it did

        def eventFilter(self, obj, event) -> bool:
            if event.type() == QEvent.Type.FileOpen:
                self.open_file(event.file())
                return True
            return False

        def open_file(self, name: str) -> None:
            if not name.lower().endswith(".pdf"):
                return
            if self.window is None:
                self.pending.append(Path(name))
            else:
                QTimer.singleShot(0, lambda: self.window.present(Path(name)))

    flt = Filter()
    app.installEventFilter(flt)
    return flt


def _report_timing(app) -> None:
    """Write the start time (the window has been shown) and quit; see TIMING_ENV."""
    text = f"{_seconds_since_process_start():.3f}\n"
    target = os.environ.get(TIMING_FILE_ENV)
    if target:
        Path(target).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    app.quit()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if args[:1] == [SELF_TEST_FLAG]:
        return _self_test()

    from PySide6 import QtSvg  # noqa: F401 -- Qt's SVG support: without it QIcon draws the .svg icon empty
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from .ui.kit.fonts import load_fonts
    from .ui.kit.theme import ThemeManager
    from .ui.presentation.presenter_window import TITLE, PresenterStartWindow

    app = QApplication.instance() or QApplication([sys.argv[0], *args])
    app.setApplicationName(TITLE)
    app.setWindowIcon(QIcon(str(ICON_PATH)))
    app.setQuitOnLastWindowClosed(False)      # the start window is hidden during a talk; closing it quits (its closeEvent)
    opened = make_filter(app)
    load_fonts()
    ThemeManager(project=None).apply()

    window = PresenterStartWindow()
    opened.window = window
    queue = [*pdf_arguments(args), *opened.pending]
    opened.pending.clear()
    if queue:
        window.present(queue[0])      # shows the start window when the talk is over
    elif os.environ.get(TIMING_ENV):
        window.show()
        QTimer.singleShot(0, lambda: _report_timing(app))
    else:
        window.show()
    for later in queue[1:]:           # a second file is presented after the first
        window.present(later)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
