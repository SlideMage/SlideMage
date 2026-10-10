"""Threads that outlive the sheet which started them (slidemage.ui.background)."""
from __future__ import annotations

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
    assert QApplication.instance().property("_slidemage_background_quit_hook")


def test_a_stopped_worker_that_is_slow_is_kept_and_then_reported_on_the_gui_thread():
    import threading

    app = QApplication.instance() or QApplication([])
    gate = threading.Event()
    thread = Slow(gate)
    thread.start()
    done = []
    assert not background.stop_worker(thread, None, wait_ms=10,
                                      on_done=lambda: done.append(threading.current_thread() is threading.main_thread()))
    assert thread in background._running and done == []          # still running: kept, slot not given back
    gate.set()
    thread.wait()
    app.processEvents()
    assert done == [True] and thread not in background._running


def test_a_stopped_worker_that_ends_in_time_is_reported_at_once():
    import threading

    QApplication.instance() or QApplication([])
    gate = threading.Event()
    thread = Slow(gate)
    thread.start()
    done = []
    assert background.stop_worker(thread, gate.set, on_done=lambda: done.append(1)) and done == [1]
    assert thread not in background._running
