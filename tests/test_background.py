# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Threads that outlive the sheet which started them (slidemage.ui.background)."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from slidemage.ui import background


class Slow(QThread):
    def __init__(self, gate):
        super().__init__()
        self.gate, self.ran = gate, False

    def run(self):
        self.gate.wait(5)
        self.ran = True


def test_a_detached_thread_is_kept_until_it_ends():
    import threading

    app = QApplication.instance() or QApplication([])
    gate = threading.Event()
    thread = Slow(gate)
    background.start_detached(thread)
    assert thread in background._running and thread.isRunning()
    gate.set()
    thread.wait()
    app.processEvents()                  # the thread's `finished` is handled by the event loop
    assert thread.ran and thread not in background._running


@pytest.mark.parametrize("slow", [False, True], ids=["stopped", "still-running"])
def test_stopped_workers_are_retained_and_reported_on_the_gui_thread(slow):
    """Regression: retain a worker which outlives the stop timeout until it actually finishes."""
    import threading

    app = QApplication.instance() or QApplication([])
    gate = threading.Event()
    thread = Slow(gate)
    thread.start()
    done = []
    assert background.stop_worker(
        thread, None if slow else gate.set, wait_ms=10 if slow else 2000,
        on_done=lambda: done.append(threading.current_thread() is threading.main_thread()),
    ) is not slow
    assert (thread in background._running) is slow
    assert done == ([] if slow else [True])
    gate.set()
    thread.wait()
    app.processEvents()
    assert done == [True] and thread not in background._running


@pytest.mark.parametrize("slow", [False, True], ids=["stopped", "still-running"])
def test_stopping_a_detached_worker_preserves_both_callbacks(slow):
    import threading

    app = QApplication.instance() or QApplication([])
    gate = threading.Event()
    thread = Slow(gate)
    done = []
    background.start_detached(thread, lambda: done.append("detached"))
    assert background.stop_worker(
        thread, None if slow else gate.set, wait_ms=10 if slow else 2000,
        on_done=lambda: done.append("stopped"),
    ) is not slow
    if slow:
        assert done == []
        gate.set()
        thread.wait()
        app.processEvents()
    assert done == ["detached", "stopped"] and thread not in background._running


@pytest.mark.parametrize("failure", [False, True])
def test_background_result_and_signal_are_delivered_on_gui_thread(qapp, failure):
    import threading
    from conftest import wait_until

    gate = threading.Event()
    calls, signals, workers = [], [], []
    error = ValueError("failed")
    def work():
        workers.append(threading.get_ident())
        gate.wait(5)
        if failure:
            raise error
        return 42

    main = threading.get_ident()
    handle = background.run_in_background(work, lambda r, e: calls.append((r, e, threading.get_ident())))
    handle.done.connect(lambda r, e: signals.append((r, e, threading.get_ident())))
    gate.set()
    wait_until(lambda: signals)
    expected = (None, error, main) if failure else (42, None, main)
    assert calls == signals == [expected]
    assert workers[0] != main
    assert handle.isFinished() and not handle.isRunning() and handle.wait()


def test_dropping_the_handle_keeps_a_running_job_and_receiver(qapp):
    import gc
    import threading
    import weakref
    from conftest import wait_until

    gate = threading.Event()
    got = []
    handle = background.run_in_background(lambda: gate.wait(5), lambda r, e: got.append((r, e)))
    ref = weakref.ref(handle)
    del handle
    gc.collect()
    assert ref() is not None
    gate.set()
    wait_until(lambda: got)
    assert got == [(True, None)]


def test_cancel_event_is_cooperative_and_still_delivers_done(qapp):
    from conftest import wait_until

    got = []
    handle = background.run_in_background(lambda cancel: cancel.wait(5), lambda r, e: got.append((r, e)))
    handle.cancel()
    wait_until(lambda: got)
    assert got == [(True, None)]


@pytest.mark.parametrize("progress", [False, True])
def test_destroyed_owner_drops_callbacks_but_retains_cleanup(qapp, progress):
    import threading
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QWidget
    from conftest import wait_until

    owner = QWidget()
    gate = threading.Event()
    calls, cleaned = [], []
    def work(report=None):
        gate.wait(5)
        if report:
            report("late")
        return 42

    if progress:
        handle = background.run_in_background_with_progress(
            work, calls.append, lambda r, e: calls.append((r, e)), parent=owner)
    else:
        handle = background.run_in_background(work, lambda r, e: calls.append((r, e)), parent=owner)
    handle.finished.connect(lambda: cleaned.append(threading.current_thread() is threading.main_thread()))
    owner.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert handle.cancel_event.is_set()
    gate.set()
    wait_until(lambda: cleaned)
    assert calls == [] and cleaned == [True]


def test_progress_is_queued_before_done_on_gui_thread(qapp):
    import threading
    from conftest import wait_until

    events = []
    main = threading.get_ident()
    def work(report):
        report("one")
        report("two")
        return 42

    background.run_in_background_with_progress(
        work, lambda value: events.append((value, threading.get_ident())),
        lambda result, error: events.append((result, error, threading.get_ident())))
    wait_until(lambda: len(events) == 3)
    assert events == [("one", main), ("two", main), (42, None, main)]


@pytest.mark.parametrize("slow", [False, True])
def test_stopping_a_handle_drops_done_and_releases_once_after_work(qapp, slow):
    import threading
    from conftest import wait_until

    gate = threading.Event()
    done, cleaned = [], []
    handle = background.run_in_background(lambda: gate.wait(5), lambda r, e: done.append((r, e)))
    handle.finished.connect(lambda: cleaned.append("finished"))
    stopped = handle.stop(None if slow else gate.set, wait_ms=10 if slow else 2000,
                          on_done=lambda: cleaned.append("stopped"))
    assert stopped is not slow
    assert handle.cancel_event.is_set()
    assert cleaned == ([] if slow else ["finished", "stopped"])
    gate.set()
    wait_until(lambda: len(cleaned) == 2)
    assert done == [] and cleaned == ["finished", "stopped"]



def test_callback_errors_do_not_skip_cleanup_or_later_progress(qapp, caplog):
    from conftest import wait_until

    events, cleaned = [], []
    def work(report):
        report("one")
        report("two")
        return 42

    def progress(value):
        events.append(value)
        raise ValueError("progress failed")

    def done(result, error):
        events.append((result, error))
        raise ValueError("done failed")

    handle = background.run_in_background_with_progress(work, progress, done)
    handle.finished.connect(lambda: cleaned.append(True))
    wait_until(lambda: cleaned)
    assert events == ["one", "two", (42, None)] and cleaned == [True]
    assert caplog.text.count("progress callback raised") == 2 and "done callback raised" in caplog.text


@pytest.mark.parametrize("slow", [False, True])
def test_closed_sheet_keeps_logging_until_its_operation_has_ended(qapp, slow):
    """Archiving may finish after the sheet's bounded wait: its log messages still belong to the workspace."""
    import threading
    from conftest import wait_until

    gate = threading.Event()
    events, cleaned = [], []
    def work(report):
        gate.wait(5)
        report("moved")

    handle = background.run_in_background_with_progress(
        work, events.append, lambda result, error: events.append("done"))
    handle.finished.connect(lambda: cleaned.append(True))
    assert handle.stop(None if slow else gate.set, wait_ms=0 if slow else 2000) is not slow
    gate.set()
    wait_until(lambda: cleaned)
    assert events == ["moved"]
