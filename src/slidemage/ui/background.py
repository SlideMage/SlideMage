# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Threads for network calls that outlive the sheet which asked for them.

A sheet closed while its request is still out must neither wait for the answer nor destroy a
running QThread (that crashes the interpreter). `start_detached` keeps a reference until the
thread has ended, and the application waits for it at quit; the sheet just drops its connections.
`stop_worker` does the same for a worker that is asked to stop but may take a while to do so.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QObject, QThread, Slot
from PySide6.QtWidgets import QApplication

_running: dict[QThread, "_Watch"] = {}


class _Watch(QObject):
    """Lives on the GUI thread, so that a thread's end is handled there (not on the ending thread)."""

    def __init__(self, thread: QThread, on_done: Optional[Callable[[], None]], delete: bool) -> None:
        super().__init__()
        self.thread, self.on_done, self.delete = thread, on_done, delete
        thread.finished.connect(self.done)

    @Slot()
    def done(self) -> None:
        if _running.pop(self.thread, None) is None:
            return
        self.thread.wait()                  # `finished` comes just before the thread is completely over
        if self.on_done is not None:
            self.on_done()
        if self.delete:
            self.thread.deleteLater()
        self.deleteLater()


def _wait_for_threads() -> None:
    for thread in tuple(_running):
        thread.wait()


def _keep(thread: QThread, on_done: Optional[Callable[[], None]] = None, delete: bool = False) -> _Watch:
    app = QApplication.instance()
    if app is not None and not app.property("_slidemage_background_quit_hook"):
        app.aboutToQuit.connect(_wait_for_threads)
        app.setProperty("_slidemage_background_quit_hook", True)
    watch = _running.get(thread)
    if watch is not None:
        previous = watch.on_done
        if previous is not None and on_done is not None:
            def both() -> None:
                try:
                    previous()
                finally:
                    on_done()
            watch.on_done = both
        elif on_done is not None:
            watch.on_done = on_done
        watch.delete = watch.delete or delete
        return watch
    watch = _running[thread] = _Watch(thread, on_done, delete)
    return watch


def start_detached(thread: QThread, on_done: Optional[Callable[[], None]] = None) -> None:
    """Start `thread`; `on_done()` runs on the GUI thread once it has ended."""
    watch = _keep(thread, on_done)
    try:
        thread.start()
    except BaseException:
        _running.pop(thread, None)
        thread.finished.disconnect(watch.done)
        watch.deleteLater()
        raise


def stop_worker(thread: QThread, abort: Optional[Callable[[], None]] = None, *, wait_ms: int = 100,
                on_done: Optional[Callable[[], None]] = None) -> bool:
    """Ask a worker to end (requestInterruption(), then `abort()` for whatever it blocks on) and give it
    `wait_ms` to do so. One that is still running afterwards stays referenced until it has ended (the
    application waits for it at quit). Either way `on_done()` runs once it is over, and then the thread
    is deleted. Whether it had ended by the time of the call."""
    thread.requestInterruption()
    if abort is not None:
        abort()
    if thread.wait(wait_ms):
        if thread in _running:
            _keep(thread, on_done, delete=True).done()
        else:
            if on_done is not None:
                on_done()
            thread.deleteLater()
        return True
    watch = _keep(thread, on_done, delete=True)
    if thread.isFinished():                 # it ended between the wait and the connection
        watch.done()
    return False
