# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run independent tasks (preview renders) several at once, as many as the machine can spare.

At most `workers` run at once. The first always starts; each one beyond it starts only while `may_add()` allows it
(the CPU rule: below idle_gate.CPU_LIMIT, the same threshold background rendering uses), so the renders, which count
towards the load themselves, settle at what the machine can spare. Free of Qt.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Callable, Optional, Sequence

POLL = 0.25


def default_workers() -> int:
    """Up to half the cores (at most 16: a LaTeX run takes one core and about 300 MB)."""
    return max(2, min(16, (os.cpu_count() or 2) // 2))


def cpu_has_room() -> bool:
    from .idle_gate import CPU_LIMIT
    from .power_status import shared_cpu_meter

    load = shared_cpu_meter().load()
    return load is None or load < CPU_LIMIT


def run_all(tasks: Sequence[Callable[[], None]], *, workers: Optional[int] = None,
            may_add: Callable[[], bool] = cpu_has_room, cancel=None) -> None:
    """Run every task; return when all have run. A task that raises does not stop the others (tasks report their
    own errors). After `cancel` is set no task starts; running ones finish (they watch `cancel` themselves)."""
    workers = max(1, workers if workers is not None else default_workers())
    pending = list(tasks)
    if workers == 1 or len(pending) <= 1:
        for task in pending:
            if cancel is not None and cancel.is_set():
                break
            _run(task)
        return
    lock = threading.Condition()
    running = {"n": 0}

    def worker() -> None:
        while True:
            with lock:
                while True:
                    if not pending or (cancel is not None and cancel.is_set()):
                        return
                    if running["n"] == 0 or (running["n"] < workers and may_add()):
                        task = pending.pop(0)
                        running["n"] += 1
                        break
                    lock.wait(POLL)          # wait for room on the CPU, or for a running task to end
            try:
                _run(task)
            finally:
                with lock:
                    running["n"] -= 1
                    lock.notify_all()

    threads = [threading.Thread(target=worker, daemon=True, name="parallel-run") for _ in range(min(workers, len(pending)))]
    for thread in threads:
        thread.start()
        time.sleep(0)                        # let the first one start before the others ask about the CPU
    for thread in threads:
        thread.join()


def _run(task: Callable[[], None]) -> None:
    try:
        task()
    except Exception:  # noqa: BLE001 -- a task reports its own errors; one must not end the others
        pass
