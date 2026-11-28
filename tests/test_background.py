# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Threads that outlive the sheet which started them (slidemage.ui.background)."""
from __future__ import annotations

import gc
import threading
import weakref

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QThread
from PySide6.QtWidgets import QWidget

from conftest import wait_until
from slidemage.ui import background


class Slow(QThread):
    def __init__(self, gate):
        super().__init__()
        self.gate = gate

    def run(self):
        self.gate.wait(5)


@pytest.mark.parametrize(("detached", "slow"), [(False, True), (True, True), (True, False), (False, False)])
def test_stopping_workers_keeps_them_alive_and_delivers_callbacks_on_the_gui_thread(qapp, detached, slow):
    gate = threading.Event()
    thread = Slow(gate)
    events = []

    def record(event):
        events.append((event, threading.get_ident()))

    expected = [("stopped", threading.get_ident())]
    if detached:
        background.start_detached(thread, lambda: record("detached"))
        assert thread in background._running and thread.isRunning()
        expected.insert(0, ("detached", threading.get_ident()))
    else:
        thread.start()
    try:
        stopped = background.stop_worker(
            thread, None if slow else gate.set, wait_ms=10 if slow else 2000,
            on_done=lambda: record("stopped"))
        assert stopped is not slow and (thread in background._running) is slow
        assert events == ([] if slow else expected)
    finally:
        gate.set()
        thread.wait()
        qapp.processEvents()
    assert events == expected and thread not in background._running


@pytest.mark.parametrize("failure", [False, True])
def test_background_job_survives_a_dropped_handle_and_reports_on_the_gui_thread(qapp, failure):
    calls, signals, workers = [], [], []
    error = ValueError("failed")

    def work(cancel):
        workers.append(threading.get_ident())
        cancelled = cancel.wait(5)
        if failure:
            raise error
        return cancelled

    main = threading.get_ident()
    handle = background.run_in_background(work, lambda r, e: calls.append((r, e, threading.get_ident())))
    handle.done.connect(lambda r, e: signals.append((r, e, threading.get_ident())))
    ref = weakref.ref(handle)
    del handle
    gc.collect()
    assert (handle := ref()) is not None
    handle.cancel()
    wait_until(lambda: signals)
    assert calls == signals == [(None, error, main) if failure else (True, None, main)]
    assert workers[0] != main
    assert handle.isFinished() and not handle.isRunning() and handle.wait()


def test_destroyed_owner_drops_callbacks_but_retains_cleanup(qapp):
    owner = QWidget()
    gate = threading.Event()
    calls, cleaned = [], []

    def work(report):
        gate.wait(5)
        report("late")
        return 42

    handle = background.run_in_background_with_progress(
        work, calls.append, lambda r, e: calls.append((r, e)), parent=owner)
    handle.finished.connect(lambda: cleaned.append(threading.get_ident()))
    owner.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert handle.cancel_event.is_set()
    gate.set()
    wait_until(lambda: cleaned)
    assert calls == [] and cleaned == [threading.get_ident()]


@pytest.mark.parametrize("slow", [False, True])
def test_stopping_a_handle_keeps_progress_and_releases_once_without_delivering_done(qapp, slow):
    gate = threading.Event()
    events = []

    def work(report):
        gate.wait(5)
        report("moved")

    handle = background.run_in_background_with_progress(
        work, events.append, lambda result, error: events.append("done"))
    handle.finished.connect(lambda: events.append("finished"))
    stopped = handle.stop(None if slow else gate.set, wait_ms=10 if slow else 2000,
                          on_done=lambda: events.append("stopped"))
    expected = ["moved", "finished", "stopped"]
    assert stopped is not slow and handle.cancel_event.is_set()
    assert events == ([] if slow else expected)
    gate.set()
    wait_until(lambda: len(events) >= 3)
    assert events == expected


def test_callback_errors_do_not_skip_cleanup_or_later_progress(qapp, caplog):
    events, cleaned = [], []
    main = threading.get_ident()

    def work(report):
        report("one")
        report("two")
        return 42

    def progress(value):
        events.append((value, threading.get_ident()))
        raise ValueError("progress failed")

    def done(result, error):
        events.append((result, error, threading.get_ident()))
        raise ValueError("done failed")

    handle = background.run_in_background_with_progress(work, progress, done)
    handle.finished.connect(lambda: cleaned.append(True))
    wait_until(lambda: cleaned)
    assert events == [("one", main), ("two", main), (42, None, main)] and cleaned == [True]
    assert caplog.text.count("progress callback raised") == 2 and "done callback raised" in caplog.text
