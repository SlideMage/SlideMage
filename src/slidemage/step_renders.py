# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The page lists behind the Preview's step bar, rendered one at a time in the background.

A step list is the pages of an all-steps render (slide_preview `all_steps`) as PNG bytes. Jobs run on one
worker thread, never two at once. A foreground job (the selected slide in the view being looked at) starts
at once; a background job (another version's count, a neighbouring slide) waits until the Preview has no
render of its own running (`busy()`), and is cancelled and put back when one starts (`preempt()`), so the
user's own renders are never slowed by it (docs/plans/reveal-step-slider.md, 5.1).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import reveal_steps
from .compiler import CancelToken

FOREGROUND, BACKGROUND = 0, 1
POLL_SECONDS = 0.25


@dataclass
class _Job:
    key: tuple
    priority: int
    pdf: Callable[[CancelToken], Path]      # gives the finished all-steps PDF; may raise RuntimeError
    note: str = ""
    cancel: CancelToken = field(default_factory=CancelToken)
    requeue: bool = False
    on_pages: Optional[Callable[[Path, list[bytes]], None]] = None   # the worker hands over the PDF and its pages


class StepRenderQueue:
    """`finished(key, pages, error)` is called on the worker thread: `pages` the PNG bytes (empty on an error),
    `error` the message or "". `busy()` says whether the Preview is rendering for the user."""

    def __init__(self, busy: Callable[[], bool], finished: Callable[[tuple, list[bytes], str], None],
                 read_pages: Callable[[Path], list[bytes]] = reveal_steps.read_pages) -> None:
        self._busy = busy
        self._finished = finished
        self._read_pages = read_pages
        self._condition = threading.Condition()
        self._jobs: list[_Job] = []
        self._running: Optional[_Job] = None
        self._closed = False
        self._thread: Optional[threading.Thread] = None

    # -- submitting ---------------------------------------------------------------------

    def submit(self, key: tuple, priority: int, pdf: Callable[[CancelToken], Path],
               on_pages: Optional[Callable[[Path, list[bytes]], None]] = None) -> bool:
        """Queue `key` unless it is queued or running already (a foreground request then lifts a queued
        background one to the front). True when a job was added or promoted."""
        with self._condition:
            if self._closed:
                return False
            for job in self._jobs:
                if job.key == key:
                    promoted = priority < job.priority
                    job.priority = min(job.priority, priority)
                    self._condition.notify_all()
                    return promoted
            running = self._running
            if running is not None and running.key == key:
                return False
            if priority == FOREGROUND and running is not None and running.priority == BACKGROUND:
                running.requeue = True          # a neighbour's count must not make the slide on show wait
                running.cancel.request_stop()
            self._jobs.append(_Job(key, priority, pdf, on_pages=on_pages))
            if self._thread is None:
                self._thread = threading.Thread(target=self._work, daemon=True, name="step-renders")
                self._thread.start()
            self._condition.notify_all()
            return True

    def pending(self, key: tuple) -> bool:
        with self._condition:
            return any(job.key == key for job in self._jobs) or (
                self._running is not None and self._running.key == key)

    def preempt(self) -> None:
        """The Preview starts a render of its own: stop the running background job (it is queued again)."""
        with self._condition:
            running = self._running
            if running is not None and running.priority == BACKGROUND:
                running.requeue = True
                running.cancel.request_stop()

    def drop_background(self) -> None:
        """Forget the queued background jobs (the user moved on) and stop a running one."""
        with self._condition:
            self._jobs = [job for job in self._jobs if job.priority == FOREGROUND]
            running = self._running
            if running is not None and running.priority == BACKGROUND:
                running.cancel.request_stop()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._jobs.clear()
            if self._running is not None:
                self._running.cancel.request_stop()
            self._condition.notify_all()

    # -- the worker ---------------------------------------------------------------------

    def _next(self) -> Optional[_Job]:
        with self._condition:
            while True:
                if self._closed:
                    return None
                if self._jobs:
                    self._jobs.sort(key=lambda job: job.priority)       # stable: first come first served
                    job = self._jobs[0]
                    if job.priority == FOREGROUND or not self._busy():
                        self._jobs.pop(0)
                        self._running = job
                        return job
                    self._condition.wait(POLL_SECONDS)
                else:
                    self._condition.wait()

    def _work(self) -> None:
        while (job := self._next()) is not None:
            pages: list[bytes] = []
            error = ""
            try:
                pdf = job.pdf(job.cancel)
                if job.cancel.is_set():
                    raise RuntimeError("Preview cancelled")
                pages = self._read_pages(pdf)
                if not pages:
                    error = "the render has no pages"
                elif job.on_pages is not None:
                    try:
                        job.on_pages(pdf, pages)
                    except Exception:  # noqa: BLE001 -- keeping the pages for later is a help, never a failure
                        pass
            except Exception as exc:  # noqa: BLE001 -- reported through `finished`, the worker must go on
                error = str(exc) or type(exc).__name__
            with self._condition:
                self._running = None
                if job.requeue and not self._closed and (error and job.cancel.is_set()):
                    self._jobs.append(_Job(job.key, job.priority, job.pdf, on_pages=job.on_pages))
                    continue
                closed = self._closed
            if closed or (error and job.cancel.is_set()):
                continue
            try:
                self._finished(job.key, pages, error)
            except Exception:  # noqa: BLE001 -- a receiver that is gone must not end the worker
                pass
            time.sleep(0)
