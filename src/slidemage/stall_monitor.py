# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Finds the freezes of the window itself, whichever code causes them: a timer on the GUI thread fires every
INTERVAL_MS, and when it fires more than LATE_S late, the debug log (area `timing`) gets `stall late=...` with the
machine's CPU use over that time, the threads that exist and where each of them is (its innermost frames). A
stall that no `timing.span` covers (a worker thread holding the GIL, a disk wait, another program using the CPU)
shows up here, with who else was running. Nothing runs while the debug log is off beyond one clock read per tick."""
from __future__ import annotations

import sys
import threading
import time
from typing import Optional

from PySide6.QtCore import QObject, QTimer

from . import timing

INTERVAL_MS = 50
LATE_S = 0.15
FRAMES_PER_THREAD = 3
MAIN_FRAMES = 8
BUSY_FRAMES = 9       # a worker that is not idle
WATCH_S = 0.1        # how often the watchdog looks
MAX_REPORTS = 3      # thread reports kept per stall


def system_cpu_times() -> Optional[tuple[int, int]]:
    """(busy, total) 100-ns ticks of the whole machine since boot (Windows), else None."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
    if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        return None
    def value(t):
        return (t.dwHighDateTime << 32) | t.dwLowDateTime
    total = value(kernel) + value(user)               # kernel time includes the idle time
    return total - value(idle), total


def thread_report(main_ident: int) -> str:
    """Where every thread is now: `name@file:line function < caller ...`, the GUI thread first and deeper."""
    names = {t.ident: t.name for t in threading.enumerate()}
    parts = []
    for ident, frame in sorted(sys._current_frames().items(), key=lambda item: item[0] != main_ident):
        if ident == threading.get_ident():
            continue                                   # the watchdog itself
        limit = MAIN_FRAMES if ident == main_ident else FRAMES_PER_THREAD
        top = frame.f_code
        if ident != main_ident and top.co_name in ("wait", "_worker", "_select") and                 top.co_filename.replace(chr(92), "/").rsplit("/", 1)[-1] in ("threading.py", "thread.py", "selectors.py"):
            limit = 1                                  # idle: parked in a wait, nothing to learn from its callers
        elif ident != main_ident:
            limit = BUSY_FRAMES                        # at work, or in a lock: the callers say which lock and who holds it
        frames = []
        while frame is not None and len(frames) < limit:
            code = frame.f_code
            frames.append(f"{code.co_filename.replace(chr(92), '/').rsplit('/', 1)[-1]}:{frame.f_lineno} {code.co_name}")
            frame = frame.f_back
        parts.append(f"{'GUI' if ident == main_ident else names.get(ident, ident)}@" + " < ".join(frames))
    return "; ".join(parts)


class StallMonitor(QObject):
    """Create on the GUI thread. The timer beats there; a watchdog thread notices a missing beat while it lasts and
    records where the threads are (what a report afterwards could not show), and the next beat logs it."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._main = threading.get_ident()
        self._beat = self._last = time.perf_counter()
        self._cpu = system_cpu_times()
        self._seen: list[str] = []        # reports taken during the stall under way
        self._timer = QTimer(self)
        self._timer.setInterval(INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._stop = threading.Event()
        threading.Thread(target=self._watch, name="stall-watchdog", daemon=True).start()
        self.destroyed.connect(lambda *_: self._stop.set())

    def _watch(self) -> None:
        while not self._stop.wait(WATCH_S):
            if timing.enabled() and time.perf_counter() - self._beat > LATE_S + INTERVAL_MS / 1000:
                if len(self._seen) < MAX_REPORTS:
                    self._seen.append(thread_report(self._main))

    def _tick(self) -> None:
        now = time.perf_counter()
        late = now - self._last - INTERVAL_MS / 1000
        self._last = self._beat = now
        cpu, before, self._cpu = system_cpu_times(), self._cpu, None
        self._cpu = cpu
        seen, self._seen = self._seen, []
        if late < LATE_S or not timing.enabled():
            return
        load = ""
        if cpu is not None and before is not None and cpu[1] > before[1]:
            load = f" cpu={100 * (cpu[0] - before[0]) / (cpu[1] - before[1]):.0f}%"
        reports = " || ".join(seen) if seen else "(none taken)"
        timing.log.debug("stall late=%.3f%s samples=%d threads=[%s]", late, load, len(seen), reports)
