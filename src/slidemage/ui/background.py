"""Threads for network calls that outlive the sheet which asked for them.

A sheet closed while its request is still out must neither wait for the answer nor destroy a
running QThread (that crashes the interpreter). `start_detached` keeps a reference until the
thread has ended, and the application waits for it at quit; the sheet just drops its connections.
"""
from __future__ import annotations

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

_running: set[QThread] = set()


def _wait_for_threads() -> None:
    for thread in tuple(_running):
        thread.wait()


def start_detached(thread: QThread) -> None:
    app = QApplication.instance()
    if app is not None and not app.property("_slidemage_background_quit_hook"):
        app.aboutToQuit.connect(_wait_for_threads)
        app.setProperty("_slidemage_background_quit_hook", True)
    _running.add(thread)
    thread.finished.connect(lambda: _running.discard(thread))
    thread.start()
