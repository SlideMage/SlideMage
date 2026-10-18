"""The one queue behind every render that is not the user waiting for it (docs/plans/idle-background-rendering.md, 5.1).

Three priority classes, strictly in this order:

* P_FOREGROUND: the user asked (the Preview's own render);
* P_NEIGHBOURS: the reveal slider's renders of the selected slide and its neighbours;
* P_IDLE: the sweep over the decks, only while the machine is idle.

A job of a better class never waits for a worse one, not even for one with the same key: the running job is
cancelled (its process tree is killed) and put back in the queue, then the better job runs. Cancelling is
never a failure. User input while an idle job runs lets a job that has run for less than `grace` seconds
finish and cancels a longer one. One worker thread per allowed process; after each idle job the worker
rests for `duty` times the job's duration (a cap of REST_CAP seconds), so a laptop does not run hot.

Free of Qt: the idle gate is a callable the caller supplies.
"""
from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .compiler import CancelToken

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

    def order(self) -> tuple:
        return (self.priority, self.rank, self.seq)


class RenderScheduler:
    def __init__(self, work: Callable[[Job, CancelToken], None], *,
                 can_start: Callable[[Job], bool] = lambda job: True,
                 on_change: Callable[[], None] = lambda: None,
                 on_error: Callable[[Job, BaseException], None] = lambda job, exc: None,
                 workers: int = 1, duty: float = 0.0, grace: float = 20.0,
                 clock: Callable[[], float] = time.monotonic, sleep: Optional[Callable[[float], None]] = None) -> None:
        self._work, self._can_start, self._on_change, self._on_error = work, can_start, on_change, on_error
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

    def user_active(self) -> None:
        """The user did something. An idle job that has run for longer than the grace period is cancelled (and
        requeued); a shorter one is left to finish. Nothing new starts until the gate allows it again."""
        now = self._clock()
        with self._cond:
            for job in self._running.values():
                if job.priority == P_IDLE and now - job.started > self.grace and not job.cancelled_for_requeue:
                    job.cancelled_for_requeue = True
                    job.cancel.request_stop()

    # -- state -------------------------------------------------------------------------

    def pending(self, priority: Optional[int] = None) -> int:
        with self._cond:
            jobs = list(self._queue.values()) + list(self._running.values())
        return sum(1 for j in jobs if priority is None or j.priority == priority)

    def queued_keys(self) -> list[str]:
        with self._cond:
            return [j.key for j in sorted(self._queue.values(), key=Job.order)]

    def running_keys(self) -> list[str]:
        with self._cond:
            return list(self._running)

    # -- running -----------------------------------------------------------------------

    def _next(self) -> Optional[Job]:
        for job in sorted(self._queue.values(), key=Job.order):
            if job.priority != P_IDLE or self._can_start(job):
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
        with self._cond:
            self._stopping = False
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
