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
