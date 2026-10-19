# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The scheduler behind background renders: classes, preemption, the idle gate, the rest between jobs."""
from __future__ import annotations

import threading
import time

from slidemage.render_scheduler import P_FOREGROUND, P_IDLE, P_NEIGHBOURS, RenderScheduler


class Cancelled(RuntimeError):
    pass


def make(**kwargs):
    ran = []
    errors = []
    box = {}

    def work(job, cancel):
        ran.append((job.key, job.priority))
        step = box.get("during", {}).get(job.key)
        if step:
            step(job)
        if cancel.is_set():
            raise Cancelled("Preview cancelled")
        if job.key in box.get("fail", ()):
            raise RuntimeError("boom")

    scheduler = RenderScheduler(work, on_error=lambda job, exc: errors.append((job.key, str(exc))), **kwargs)
    scheduler.box, scheduler.ran, scheduler.errors = box, ran, errors
    return scheduler


def drain(scheduler):
    while scheduler.run_next():
        pass


def test_classes_run_in_order_and_ranks_inside_a_class():
    s = make()
    s.submit("idle-b", None, P_IDLE, (2,))
    s.submit("idle-a", None, P_IDLE, (1,))
    s.submit("slider", None, P_NEIGHBOURS, (0,))
    s.submit("user", None, P_FOREGROUND, (0,))
    drain(s)
    assert [k for k, _ in s.ran] == ["user", "slider", "idle-a", "idle-b"]


def test_idle_jobs_wait_for_the_gate_but_the_others_do_not():
    gate = {"open": False}
    s = make(can_start=lambda job: gate["open"])
    s.submit("idle", None, P_IDLE)
    s.submit("slider", None, P_NEIGHBOURS)
    drain(s)
    assert [k for k, _ in s.ran] == ["slider"] and s.pending(P_IDLE) == 1
    gate["open"] = True
    drain(s)
    assert [k for k, _ in s.ran] == ["slider", "idle"]


def test_a_better_class_cancels_the_running_idle_job_which_is_put_back():
    s = make()
    s.box["during"] = {"idle-1": lambda job: s.box["during"].pop("idle-1") and None or s.submit("slider-1", None, P_NEIGHBOURS)}
    s.submit("idle-1", None, P_IDLE)
    s.submit("idle-2", None, P_IDLE, (5,))
    assert s.run_next()                         # idle-1 starts, the slider asks for a slot, idle-1 is cancelled
    assert s.failed == 0 and not s.errors       # not a failure
    drain(s)
    assert [k for k, _ in s.ran] == ["idle-1", "slider-1", "idle-1", "idle-2"]


def test_the_slider_does_not_wait_for_an_idle_job_of_the_same_key():
    s = make()
    s.box["during"] = {"unit": lambda job: s.submit("unit", None, P_NEIGHBOURS) if job.priority == P_IDLE else None}
    s.submit("unit", None, P_IDLE)
    drain(s)
    assert s.ran == [("unit", P_IDLE), ("unit", P_NEIGHBOURS)]
    assert s.pending() == 0


def test_a_request_as_urgent_as_the_running_job_joins_it():
    s = make()
    s.box["during"] = {"unit": lambda job: s.submit("unit", None, P_IDLE)}
    s.submit("unit", None, P_IDLE)
    drain(s)
    assert s.ran == [("unit", P_IDLE)]


def test_user_input_never_stops_a_running_idle_job():
    now = {"t": 100.0}
    s = make(grace=20, clock=lambda: now["t"])
    s.box["during"] = {"young": lambda job: (now.__setitem__("t", 110.0), s.user_active()),
                       "old": lambda job: (now.__setitem__("t", 250.0), s.user_active())}
    s.submit("young", None, P_IDLE, (1,))
    s.submit("old", None, P_IDLE, (2,))
    s.run_next()
    s.run_next()
    assert s.completed == 2 and s.pending() == 0     # however long they ran, both finished


def test_cancel_group_drops_queued_and_stops_running_jobs():
    s = make()
    for n in range(3):
        s.submit(f"u{n}", None, P_IDLE, (n,), group="deck-a")
    s.submit("other", None, P_IDLE, (9,), group="deck-b")
    assert s.cancel_group("deck-a") == 3
    drain(s)
    assert [k for k, _ in s.ran] == ["other"]


def test_a_failing_job_is_reported_once_and_not_repeated():
    s = make()
    s.box["fail"] = {"bad"}
    s.submit("bad", None, P_IDLE)
    s.submit("good", None, P_IDLE, (1,))
    drain(s)
    assert s.errors == [("bad", "boom")] and s.failed == 1 and s.completed == 1
    assert [k for k, _ in s.ran] == ["bad", "good"]


def test_resubmitting_a_queued_job_improves_it_instead_of_duplicating():
    s = make()
    s.submit("x", None, P_IDLE, (5,))
    s.submit("x", None, P_NEIGHBOURS, (0,))
    s.submit("y", None, P_IDLE, (1,))
    assert s.queued_keys() == ["x", "y"] and s.pending() == 2
    drain(s)
    assert s.ran[0] == ("x", P_NEIGHBOURS)


def test_the_worker_rests_after_idle_jobs_only():
    rests = []
    s = make(duty=0.25, sleep=rests.append, clock=iter([0, 4, 4, 4, 0, 0, 0, 0, 0, 0, 0, 0]).__next__)
    s.submit("idle", None, P_IDLE)
    s.run_next()
    assert rests == [1.0]
    s.submit("slider", None, P_NEIGHBOURS)
    s.run_next()
    assert rests == [1.0]


def test_worker_threads_run_jobs_and_stop():
    done = threading.Event()
    s = RenderScheduler(lambda job, cancel: done.set())
    s.start()
    s.submit("a", None, P_IDLE)
    assert done.wait(5)
    deadline = time.time() + 5
    while s.pending() and time.time() < deadline:
        time.sleep(0.01)
    s.stop()
    assert s.pending() == 0


# -- several at once: the cap and the CPU rule ---------------------------------------------------------------------

def run_in_threads(scheduler, count):
    """`count` workers at once, each running jobs until none can start; returns the largest number seen running."""
    peak = {"n": 0}
    lock = threading.Lock()
    release = threading.Event()

    def hold(_job):
        with lock:
            peak["n"] = max(peak["n"], len(scheduler.running_keys()))
        release.wait(2)

    scheduler.box["during"] = {key: hold for key in scheduler.queued_keys()}
    threads = [threading.Thread(target=lambda: drain(scheduler)) for _ in range(count)]
    for thread in threads:
        thread.start()
    time.sleep(0.3)                       # every worker that may start has started
    release.set()
    for thread in threads:
        thread.join(5)
    return peak["n"]


def test_no_more_jobs_run_at_once_than_the_profile_allows():
    s = make(workers=3)
    for i in range(8):
        s.submit(f"idle-{i}", None, P_IDLE, (i,))
    assert run_in_threads(s, 6) == 3
    assert len(s.ran) == 8


def test_a_job_beside_others_starts_only_while_the_cpu_has_room():
    room = {"ok": False}
    s = make(workers=4, may_add=lambda: room["ok"])
    for i in range(4):
        s.submit(f"idle-{i}", None, P_IDLE, (i,))
    assert run_in_threads(s, 4) == 1          # a busy CPU: the first starts, no second beside it
    assert len(s.ran) == 4                    # one after another, nothing is lost
    room["ok"] = True
    for i in range(4):
        s.submit(f"more-{i}", None, P_IDLE, (i,))
    assert run_in_threads(s, 4) == 4          # room: all four at once


def test_the_users_own_render_starts_beside_others_whatever_the_cpu():
    s = make(workers=2, may_add=lambda: False)
    started = threading.Event()
    s.box["during"] = {"idle": lambda job: started.wait(2)}
    s.submit("idle", None, P_IDLE)
    worker = threading.Thread(target=s.run_next)
    worker.start()
    time.sleep(0.1)
    s.submit("mine", None, P_FOREGROUND)      # the user waits for this one
    assert s.run_next() and ("mine", P_FOREGROUND) in s.ran
    started.set()
    worker.join(5)
