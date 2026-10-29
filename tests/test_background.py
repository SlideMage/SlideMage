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
