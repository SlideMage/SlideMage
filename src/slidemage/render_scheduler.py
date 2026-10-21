# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The one queue behind every render that is not the user waiting for it (docs/plans/idle-background-rendering.md, 5.1).

Three priority classes, strictly in this order:

* P_FOREGROUND: the user asked (the Preview's own render);
* P_NEIGHBOURS: the reveal slider's renders of the selected slide and its neighbours;
* P_IDLE: the sweep over the decks, only while the machine is idle.

A job of a better class never waits for a worse one, not even for one with the same key: the running job is
cancelled (its process tree is killed) and put back in the queue, then the better job runs. Cancelling is
never a failure. User input never stops an idle job; it only keeps the next one from starting (the gate). One worker thread per allowed process; after each idle job the worker
rests for `duty` times the job's duration (a cap of REST_CAP seconds), so a laptop does not run hot.

At most `workers` jobs run at once. A job that would run beside others (not the user's own, P_FOREGROUND) starts
only when `may_add()` allows it: the caller's CPU rule (below CPU_LIMIT), so the renders, which count towards the
load themselves, settle at what the machine can spare. With a `budget` (parallel_runs.BUDGET in the app) the count and
the CPU rule cover every render in the process, the user's batches included; an idle job then also stands back while
a batch wants a place, and the user's own job takes a place without waiting.

Free of Qt: the idle gate is a callable the caller supplies.
"""
from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .compiler import CancelToken
from .parallel_runs import RenderBudget

P_FOREGROUND, P_NEIGHBOURS, P_IDLE = 0, 1, 2
PRIORITY_NAMES = {P_FOREGROUND: "foreground", P_NEIGHBOURS: "neighbours", P_IDLE: "idle"}
REST_CAP = 5.0
GATE_POLL = 0.5


@dataclass
class Job:
    key: str
    payload: Any
    priority: int
    rank: tuple = ()
    group: Optional[str] = None
    seq: int = 0
    cancel: CancelToken = field(default_factory=CancelToken)
    started: float = 0.0
    cancelled_for_requeue: bool = False
    budgeted: bool = False

    def order(self) -> tuple:
        return (self.priority, self.rank, self.seq)


class RenderScheduler:
    def __init__(self, work: Callable[[Job, CancelToken], None], *,
                 can_start: Callable[[Job], bool] = lambda job: True,
                 on_change: Callable[[], None] = lambda: None,
                 on_error: Callable[[Job, BaseException], None] = lambda job, exc: None,
                 workers: int = 1, duty: float = 0.0, grace: float = 20.0,
                 may_add: Callable[[], bool] = lambda: True, budget: Optional[RenderBudget] = None,
                 clock: Callable[[], float] = time.monotonic, sleep: Optional[Callable[[float], None]] = None) -> None:
        self._work, self._can_start, self._on_change, self._on_error = work, can_start, on_change, on_error
        self._may_add, self._budget = may_add, budget
        self.workers, self.duty, self.grace = workers, duty, grace
        self._clock = clock
        self._cond = threading.Condition()
        self._queue: dict[str, Job] = {}
        self._running: dict[str, Job] = {}
        self._seq = itertools.count()
        self._threads: list[threading.Thread] = []
        self._stopping = False
        self._sleep = sleep
        self.completed = 0
        self.failed = 0

    # -- submitting ------------------------------------------------------------------

    def submit(self, key: str, payload: Any, priority: int, rank: tuple = (), group: Optional[str] = None) -> Job:
        """Queue a job for `key`, or improve the one already there. A job of a better class than the running one
        of the same or any other key cancels it (it is requeued)."""
        with self._cond:
            running = self._running.get(key)
            if running is not None:
                if priority >= running.priority:
                    return running                      # already on its way, at least as urgent
                # Never wait for a worse job, not even for the same key: stop it, run this one.
                running.cancelled_for_requeue = True
                running.cancel.request_stop()
                job = Job(key, payload, priority, rank, group, next(self._seq))
                self._queue[key] = job
                self._cond.notify_all()
                return job
            queued = self._queue.get(key)
            if queued is not None:
                if (priority, rank) < (queued.priority, queued.rank):
                    queued.priority, queued.rank, queued.group = priority, rank, group
                    queued.payload = payload
                    queued.seq = next(self._seq)
                job = queued
            else:
                job = self._queue[key] = Job(key, payload, priority, rank, group, next(self._seq))
            for other in list(self._running.values()):
                if priority < other.priority and not other.cancelled_for_requeue:
                    other.cancelled_for_requeue = True
                    other.cancel.request_stop()
            self._cond.notify_all()
        self._on_change()
        return job

    def cancel_group(self, group: str) -> int:
        """Drop the queued jobs of `group` and stop running ones; returns how many queued ones were dropped."""
        dropped = 0
        with self._cond:
            for key in [k for k, j in self._queue.items() if j.group == group]:
                del self._queue[key]
                dropped += 1
            for job in self._running.values():
                if job.group == group:
                    job.cancel.request_stop()
            self._cond.notify_all()
        self._on_change()
        return dropped

    def cancel_priority(self, priority: int) -> int:
        dropped = 0
        with self._cond:
            for key in [k for k, j in self._queue.items() if j.priority == priority]:
                del self._queue[key]
                dropped += 1
            for job in self._running.values():
                if job.priority == priority:
                    job.cancel.request_stop()
            self._cond.notify_all()
        self._on_change()
        return dropped

    def interrupt(self, priority: int) -> int:
        """Stop the running jobs of class `priority` and put them back in the queue (not a failure); how many."""
        stopped = 0
        with self._cond:
            for job in self._running.values():
                if job.priority == priority and not job.cancelled_for_requeue:
                    job.cancelled_for_requeue = True
                    job.cancel.request_stop()
                    stopped += 1
            self._cond.notify_all()
        if stopped:
            self._on_change()
        return stopped

    def user_active(self) -> None:
        """The user did something. Nothing running is stopped (only a job of a better class does that, in submit());
        the gate (`can_start`) decides whether the next idle job starts."""

    # -- state -------------------------------------------------------------------------

    def pending(self, priority: Optional[int] = None) -> int:
        with self._cond:
            jobs = list(self._queue.values()) + list(self._running.values())
        return sum(1 for j in jobs if priority is None or j.priority == priority)

    def jobs(self, priority: int) -> list[Job]:
        """The jobs of class `priority` that are queued or running (one that is stopping to be requeued counts once)."""
        with self._cond:
            return [j for j in {**self._running, **self._queue}.values() if j.priority == priority]

    def queued_keys(self) -> list[str]:
        with self._cond:
            return [j.key for j in sorted(self._queue.values(), key=Job.order)]

    def running_keys(self) -> list[str]:
        with self._cond:
            return list(self._running)

    def running_jobs(self) -> list[Job]:
        """The jobs running now, the longest-running first (cancelled ones that are still stopping left out)."""
        with self._cond:
            jobs = [j for j in self._running.values() if not j.cancelled_for_requeue]
        return sorted(jobs, key=lambda j: j.started)

    # -- running -----------------------------------------------------------------------

    def _next(self) -> Optional[Job]:
        running = [j for j in self._running.values() if not j.cancelled_for_requeue]
        if len(running) >= max(1, self.workers):
            return None                          # the cap: as many at once as the profile allows
        adding_checked = None                    # the CPU rule, asked once per pick
        for job in sorted(self._queue.values(), key=Job.order):
            if job.priority == P_IDLE and not self._can_start(job):
                continue
            if self._budget is not None:
                if job.priority == P_FOREGROUND:
                    self._budget.take()          # the user's own: never waits
                elif not self._budget.try_take(self._may_add, background=job.priority == P_IDLE):
                    return None                  # no place in the process-wide budget (or no CPU room) now
                job.budgeted = True
                return job
            if running and job.priority != P_FOREGROUND:
                if adding_checked is None:
                    adding_checked = self._may_add()
                if not adding_checked:
                    continue                     # one more beside the others only while the CPU has room
            return job
        return None

    def run_next(self) -> bool:
        """Run the best startable job on the calling thread; False when there is none. (The worker threads
        call this in a loop; tests call it directly.)"""
        with self._cond:
            job = self._next()
            if job is None:
                return False
            del self._queue[job.key]
            job.started = self._clock()
            job.cancel = CancelToken()
            job.cancel.low_priority = job.priority == P_IDLE
            job.cancelled_for_requeue = False
            self._running[job.key] = job
        self._on_change()
        error: Optional[BaseException] = None
        try:
            self._work(job, job.cancel)
        except BaseException as exc:    # noqa: BLE001 -- reported through on_error, never lost
            error = exc
        finally:
            if job.budgeted:
                job.budgeted = False
                self._budget.release()
        finished = self._clock()
        with self._cond:
            self._running.pop(job.key, None)
            was_cancelled = job.cancel.is_set()
            if was_cancelled and error is not None:
                # cancelled before it was done: put back when it was displaced, dropped when it was cancelled
                if job.cancelled_for_requeue and job.key not in self._queue:
                    self._queue[job.key] = Job(job.key, job.payload, job.priority, job.rank, job.group, next(self._seq))
                error = None                    # a cancelled job is not a failure
            elif error is None:
                self.completed += 1
            else:
                self.failed += 1
            self._cond.notify_all()
        if error is not None:
            self._on_error(job, error)
        if job.priority == P_IDLE and self.duty and not was_cancelled:
            self._rest(min(REST_CAP, (finished - job.started) * self.duty))
        self._on_change()
        return True

    def _rest(self, seconds: float) -> None:
        if seconds <= 0:
            return
        if self._sleep is not None:
            self._sleep(seconds)
            return
        deadline = time.monotonic() + seconds
        with self._cond:
            # ends early when something better than idle work is queued
            while not self._stopping and time.monotonic() < deadline and not any(
                    j.priority < P_IDLE for j in self._queue.values()):
                self._cond.wait(min(0.2, deadline - time.monotonic()))

    def start(self) -> None:
        """Start worker threads up to `workers` (again after `workers` grew); fewer allowed jobs need no stop: the cap
        in _next keeps the surplus threads waiting."""
        with self._cond:
            self._stopping = False
            self._threads = [t for t in self._threads if t.is_alive()]
        while len(self._threads) < self.workers:
            thread = threading.Thread(target=self._loop, daemon=True, name="render-scheduler")
            self._threads.append(thread)
            thread.start()

    def _loop(self) -> None:
        while True:
            with self._cond:
                if self._stopping:
                    return
            if not self.run_next():
                with self._cond:
                    if self._stopping:
                        return
                    self._cond.wait(GATE_POLL)

    def stop(self, wait: float = 5.0) -> None:
        """Cancel everything and end the workers."""
        with self._cond:
            self._stopping = True
            self._queue.clear()
            for job in self._running.values():
                job.cancel.request_stop()
            self._cond.notify_all()
        for thread in self._threads:
            thread.join(wait)
        self._threads.clear()
