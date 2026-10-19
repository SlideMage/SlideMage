# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run independent tasks (preview renders) several at once, as many as the machine can spare.

At most `workers` run at once. The first always starts; each one beyond it starts only while `may_add()` allows it
(the CPU rule: below idle_gate.CPU_LIMIT, the same threshold background rendering uses), so the renders, which count
towards the load themselves, settle at what the machine can spare.

One budget for the whole process (BUDGET): the background renders (render_scheduler), the reveal-step renders and the
user's batches all draw from it, so together they never run more than `default_workers()` at once, and the CPU rule
looks at the total. The first render in the process always starts, and so does the user's own (`take()`). Free of Qt.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Callable, Optional, Sequence

POLL = 0.25
CEILING = 32                  # a LaTeX run takes about 300 MB: 32 at once is about 10 GB


def default_workers() -> int:
    """As many as there are (logical) cores, at most CEILING. A preview render mostly waits (process starts, file
    access, latexmk's bookkeeping) and computes only in short bursts, so one per core leaves the CPU rule in charge."""
    return max(2, min(CEILING, os.cpu_count() or 2))


class RenderBudget:
    """How many renders run at once in this process, across every source. Thread-safe."""

    def __init__(self, limit: Optional[int] = None) -> None:
        self._limit = limit
        self._lock = threading.Lock()
        self._in_use = 0
        self._wanted = 0

    @property
    def limit(self) -> int:
        return self._limit if self._limit is not None else default_workers()

    def in_use(self) -> int:
        with self._lock:
            return self._in_use

    def take(self) -> None:
        """The user's own render: it never waits, whatever else runs (it may go above the limit)."""
        with self._lock:
            self._in_use += 1

    def try_take(self, may_add: Callable[[], bool], *, background: bool = False) -> bool:
        """One more render: the first always, any further one only below the limit and while `may_add()` (the CPU
        rule) allows it. A `background` one also stands back while the user's batch wants a place."""
        with self._lock:
            if background and self._wanted:
                return False
            if self._in_use == 0 or (self._in_use < self.limit and may_add()):
                self._in_use += 1
                return True
            return False

    def release(self) -> None:
        with self._lock:
            self._in_use = max(0, self._in_use - 1)

    def want(self, delta: int) -> None:
        """A user's batch is waiting for (+1) or no longer waiting for (-1) a place."""
        with self._lock:
            self._wanted = max(0, self._wanted + delta)


BUDGET = RenderBudget()


def cpu_has_room() -> bool:
    from .idle_gate import CPU_LIMIT
    from .power_status import shared_cpu_meter

    load = shared_cpu_meter().load()
    return load is None or load < CPU_LIMIT


def run_all(tasks: Sequence[Callable[[], None]], *, workers: Optional[int] = None,
            may_add: Callable[[], bool] = cpu_has_room, cancel=None, budget: Optional[RenderBudget] = None) -> None:
    """Run every task; return when all have run. A task that raises does not stop the others (tasks report their
    own errors). After `cancel` is set no task starts; running ones finish (they watch `cancel` themselves).
    The batch's first task always starts (the user asked for it); the others draw on `budget` (default: BUDGET)."""
    budget = budget if budget is not None else BUDGET
    workers = max(1, workers if workers is not None else budget.limit)
    pending = list(tasks)
    if workers == 1 or len(pending) <= 1:
        for task in pending:
            if cancel is not None and cancel.is_set():
                break
            budget.take()
            try:
                _run(task)
            finally:
                budget.release()
        return
    lock = threading.Condition()
    running = {"n": 0}
    budget.want(1)                           # background renders stand back while this batch has work

    def worker() -> None:
        while True:
            with lock:
                while True:
                    if not pending or (cancel is not None and cancel.is_set()):
                        return
                    if running["n"] == 0:
                        budget.take()        # the batch's own first: never waits
                    elif not (running["n"] < workers and budget.try_take(may_add)):
                        lock.wait(POLL)      # wait for room on the CPU or in the budget, or for a task to end
                        continue
                    task = pending.pop(0)
                    running["n"] += 1
                    break
            try:
                _run(task)
            finally:
                budget.release()
                with lock:
                    running["n"] -= 1
                    lock.notify_all()

    threads = [threading.Thread(target=worker, daemon=True, name="parallel-run") for _ in range(min(workers, len(pending)))]
    for thread in threads:
        thread.start()
        time.sleep(0)                        # let the first one start before the others ask about the CPU
    try:
        for thread in threads:
            thread.join()
    finally:
        budget.want(-1)


def _run(task: Callable[[], None]) -> None:
    try:
        task()
    except Exception:  # noqa: BLE001 -- a task reports its own errors; one must not end the others
        pass
