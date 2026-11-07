# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Threads for network calls that outlive the sheet which asked for them.

A sheet closed while its request is still out must neither wait for the answer nor destroy a
running QThread (that crashes the interpreter). `start_detached` keeps a reference until the
thread has ended, and the application waits for it at quit; the sheet just drops its connections.
`stop_worker` does the same for a worker that is asked to stop but may take a while to do so.
"""
from __future__ import annotations

import inspect
import logging
import threading
from queue import Empty, SimpleQueue
from typing import Callable, Optional

from PySide6.QtCore import QObject, QThread, Signal, Slot
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


class _Worker(QThread):
    reported = Signal()

    def __init__(self, work: Callable[[], object]) -> None:
        super().__init__()
        self.work = work
        self.reports = SimpleQueue()
        self.result = self.error = None

    def report(self, value) -> None:
        self.reports.put(value)
        self.reported.emit()

    def run(self) -> None:
        try:
            self.result = self.work()
        except BaseException as exc:      # handed to done(), never lost on the thread
            self.error = exc


class Handle(QObject):
    """A GUI-thread receiver, retained by start_detached even when its widget disappears.

    cancel() is cooperative: a caller can still show the result of an aborted operation. stop() also drops
    the result callback, for a closing sheet; finished still runs so route leases can be released independently
    of widgets.
    """

    done = Signal(object, object)         # result, exception; also a hook for GUI tests
    finished = Signal()                  # cleanup, even after stop() or destruction of the owner

    def __init__(self, work, done, progress, parent, cancel, logger) -> None:
        super().__init__()               # never parent the thread or receiver to a short-lived widget
        self.cancel_event = cancel if cancel is not None else threading.Event()
        self._done, self._progress = done, progress
        self._logger = logger or logging.getLogger(__name__)
        self._ended = False
        self._with_progress = progress is not None
        self._thread = _Worker(lambda: work(self._thread.report) if self._with_progress else work())
        self._thread.reported.connect(self._report)
        if parent is not None:
            parent.destroyed.connect(self._discard)

    @Slot()
    def _discard(self) -> None:
        self.cancel()
        self._done = self._progress = None

    def cancel(self) -> None:
        self.cancel_event.set()

    def stop(self, abort=None, *, wait_ms=100, on_done=None) -> bool:
        self.cancel()
        self._done = None
        if self._ended:
            if abort is not None:
                abort()
            if on_done is not None:
                on_done()
            return True
        return stop_worker(self._thread, abort, wait_ms=wait_ms, on_done=on_done)

    def wait(self, time: int | None = None) -> bool:
        """Wait for the thread, for tests and callers already using a bounded shutdown wait."""
        return self._ended or (self._thread.wait() if time is None else self._thread.wait(time))

    def isRunning(self) -> bool:
        return not self._ended and self._thread.isRunning()

    def isFinished(self) -> bool:
        return self._ended or self._thread.isFinished()

    @Slot()
    def _report(self) -> None:
        while True:
            try:
                value = self._thread.reports.get_nowait()
            except Empty:
                return
            if self._progress is not None:
                try:
                    self._progress(value)
                except Exception:
                    self._logger.exception("progress callback raised")

    def _finish(self) -> None:
        self._ended = True
        # stop_worker can finish synchronously while queued progress signals still await the event loop.
        self._report()
        try:
            if self._done is not None:
                try:
                    self._done(self._thread.result, self._thread.error)
                except Exception:
                    self._logger.exception("done callback raised" if self._with_progress
                                           else "done() of run_in_background raised")
                self.done.emit(self._thread.result, self._thread.error)
        finally:
            self._done = self._progress = None
            self.finished.emit()
            self._thread.deleteLater()


def run_in_background(work, done, *, parent: QObject | None = None, cancel: threading.Event | None = None,
                      logger: logging.Logger | None = None) -> Handle:
    """Run work() off the GUI thread, then done(result, error) there through start_detached.

    A work function requiring one argument receives the handle's cancellation Event. A supplied cancel event
    lets existing operations share their cancellation checks. Destroying parent drops callbacks and cancels;
    a sheet that merely closes should call handle.stop(). Call this helper on the GUI thread.
    """
    handle = Handle(work, done, None, parent, cancel, logger)
    try:
        inspect.signature(work).bind()
    except TypeError:
        handle._thread.work = lambda: work(handle.cancel_event)
    except ValueError:                    # some extension callables do not expose a signature
        pass
    start_detached(handle._thread, handle._finish)
    return handle


def run_in_background_with_progress(work, progress, done, *, parent: QObject | None = None,
                                    cancel: threading.Event | None = None,
                                    logger: logging.Logger | None = None) -> Handle:
    """Run work(report), queueing progress(value) on the GUI thread before done(result, error)."""
    handle = Handle(work, done, progress, parent, cancel, logger)
    start_detached(handle._thread, handle._finish)
    return handle
