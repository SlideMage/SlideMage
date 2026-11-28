# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The queue behind the step bar: one job at a time, the user's own renders first, background jobs patient."""
from __future__ import annotations

import threading
import time
from pathlib import Path

from slidemage.step_renders import BACKGROUND, FOREGROUND, StepRenderQueue


class Recorder:
    def __init__(self, busy=lambda: False):
        self.done = []
        self.queue = StepRenderQueue(busy, self.finished, read_pages=lambda pdf: [pdf.name.encode()])

    def finished(self, key, pages, error):
        self.done.append((key, pages, error))

    def wait(self, count, seconds=5):
        deadline = time.monotonic() + seconds
        while len(self.done) < count and time.monotonic() < deadline:
            time.sleep(0.01)
        return list(self.done)


def test_a_failing_job_reports_and_the_next_still_runs():
    recorder = Recorder()

    def broken(cancel):
        raise RuntimeError("no TeX")

    recorder.queue.submit(("bad",), FOREGROUND, broken)
    recorder.queue.submit(("good",), FOREGROUND, lambda cancel: Path("ok.pdf"))
    done = recorder.wait(2)
    assert done == [(("bad",), [], "no TeX"), (("good",), [b"ok.pdf"], "")]
    recorder.queue.close()


def test_background_waits_for_idle_unless_promoted_and_duplicate_keys_are_ignored():
    busy = threading.Event()
    busy.set()
    recorder = Recorder(busy=busy.is_set)
    queue = recorder.queue
    assert queue.submit(("a",), BACKGROUND, lambda cancel: Path("a.pdf"))
    assert not queue.submit(("a",), BACKGROUND, lambda cancel: Path("a.pdf"))
    assert queue.pending(("a",))
    time.sleep(0.4)
    assert recorder.done == []                       # the Preview is busy: the background job waits
    assert queue.submit(("a",), FOREGROUND, lambda cancel: Path("a.pdf"))       # promoted: no longer waits
    assert recorder.wait(1) == [(("a",), [b"a.pdf"], "")]
    queue.submit(("slow",), BACKGROUND, lambda cancel: Path("b.pdf"))
    busy.clear()
    assert recorder.wait(2)[-1] == (("slow",), [b"b.pdf"], "")
    queue.close()


def test_foreground_jobs_go_before_waiting_background_ones_and_in_order():
    gate = threading.Event()
    order = []
    recorder = Recorder()

    def hold(cancel):
        gate.wait(5)
        return Path("hold.pdf")

    recorder.queue.submit(("hold",), FOREGROUND, hold)
    recorder.queue.submit(("bg",), BACKGROUND, lambda cancel: order.append("bg") or Path("bg.pdf"))
    recorder.queue.submit(("fg1",), FOREGROUND, lambda cancel: order.append("fg1") or Path("1.pdf"))
    recorder.queue.submit(("fg2",), FOREGROUND, lambda cancel: order.append("fg2") or Path("2.pdf"))
    gate.set()
    recorder.wait(4)
    assert order == ["fg1", "fg2", "bg"]
    recorder.queue.close()


def test_preempting_stops_a_running_background_job_and_runs_it_again_later():
    busy = threading.Event()
    started = threading.Event()
    runs = []
    recorder = Recorder(busy=busy.is_set)

    def work(cancel):
        runs.append(1)
        started.set()
        if len(runs) == 1:
            deadline = time.monotonic() + 5
            while not cancel.is_set() and time.monotonic() < deadline:
                time.sleep(0.01)
            raise RuntimeError("Preview canceled")
        return Path("again.pdf")

    recorder.queue.submit(("bg",), BACKGROUND, work)
    assert started.wait(5)
    busy.set()
    recorder.queue.preempt()
    time.sleep(0.4)
    assert recorder.done == []                      # cancelled, not reported, waiting for the Preview to be idle
    busy.clear()
    done = recorder.wait(1)
    assert done == [(("bg",), [b"again.pdf"], "")] and len(runs) == 2
    recorder.queue.close()


def test_dropping_the_background_forgets_its_queued_jobs():
    busy = threading.Event()
    busy.set()
    recorder = Recorder(busy=busy.is_set)
    recorder.queue.submit(("bg",), BACKGROUND, lambda cancel: Path("bg.pdf"))
    recorder.queue.drop_background()
    assert not recorder.queue.pending(("bg",))
    busy.clear()
    time.sleep(0.4)
    assert recorder.done == []
    recorder.queue.close()


def test_a_closed_queue_takes_nothing():
    recorder = Recorder()
    recorder.queue.close()
    assert not recorder.queue.submit(("a",), FOREGROUND, lambda cancel: Path("a.pdf"))
