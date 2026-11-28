# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Several preview renders at once: the cap, the CPU rule (one more only while the CPU has room), cancelling, and
a batch that renders its views in parallel but keeps their order."""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from slidemage import parallel_runs, batch_render


def tasks(count, seconds=0.2):
    """`count` tasks that each take `seconds`; returns (tasks, the largest number seen running at once)."""
    lock = threading.Lock()
    state = {"now": 0, "peak": 0, "ran": 0}

    def task():
        with lock:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
        time.sleep(seconds)
        with lock:
            state["now"] -= 1
            state["ran"] += 1
    return [task] * count, state


@pytest.mark.parametrize("cpu_has_room, peak", [(False, 1), (True, 4)])
def test_worker_cap_and_cpu_gate_limit_concurrency_without_losing_tasks(cpu_has_room, peak):
    work, state = tasks(8, 0.1)
    parallel_runs.run_all(work, workers=4, may_add=lambda: cpu_has_room,
                          budget=parallel_runs.RenderBudget(8))
    assert state["ran"] == 8 and state["peak"] == peak


def test_the_cpu_rule_is_asked_for_every_extra_one():
    asked = []
    work, state = tasks(6, 0.1)
    parallel_runs.run_all(work, workers=3, may_add=lambda: asked.append(1) or len(asked) <= 1,
                          budget=parallel_runs.RenderBudget(8))
    assert state["ran"] == 6 and state["peak"] == 2            # room once: a second one; then no more beside it


def test_after_cancel_no_task_starts_and_a_failing_task_does_not_stop_the_others():
    cancel = threading.Event()
    ran = []

    def failing():
        raise RuntimeError("no TeX")

    def ok():
        ran.append(1)

    parallel_runs.run_all([failing, ok, cancel.set, ok], workers=1, cancel=cancel)
    assert ran == [1]


def test_two_batches_share_one_budget():
    budget = parallel_runs.RenderBudget(3)
    work, state = tasks(6, 0.1)
    batches = [threading.Thread(target=parallel_runs.run_all, args=(work,),
                                kwargs=dict(workers=3, may_add=lambda: True, budget=budget)) for _ in range(2)]
    for batch in batches:
        batch.start()
    for batch in batches:
        batch.join()
    # each batch's own first never waits, so at most the limit plus one (the other batch's first) at once
    assert state["ran"] == 12 and state["peak"] <= 4 and budget.in_use() == 0


def test_the_budget_first_always_then_the_limit_and_the_cpu_rule_and_the_users_own_never_waits():
    budget = parallel_runs.RenderBudget(2)
    assert budget.try_take(lambda: False)                  # the first in the process: always
    assert not budget.try_take(lambda: False)              # a second: only with CPU room
    assert budget.try_take(lambda: True)
    assert not budget.try_take(lambda: True)               # the limit
    budget.take()                                          # the user's own render: above the limit, no waiting
    assert budget.in_use() == 3
    for _ in range(3):
        budget.release()
    budget.take()
    budget.want(1)                                         # a batch waits: background renders stand back
    assert not budget.try_take(lambda: True, background=True)
    assert budget.try_take(lambda: True)
    budget.want(-1)
    assert not budget.try_take(lambda: True, background=True)    # the limit again (2 in use)


def test_a_batch_renders_its_views_at_once_and_keeps_their_order(monkeypatch):
    lock = threading.Lock()
    state = {"now": 0, "peak": 0}

    class Request:
        def __init__(self, spec):
            self.spec, self.preview_result = spec, None

        def wait(self, _cancel=None):
            with lock:
                state["now"] += 1
                state["peak"] = max(state["peak"], state["now"])
            time.sleep(0.15 if self.spec.view == "instructor" else 0.05)     # the first finishes last
            with lock:
                state["now"] -= 1
            return None, b"png", (), None

    class Service:
        def request(self, *args, spec=None, **kwargs):
            return Request(spec)

    def spec(view):
        return SimpleNamespace(view=view, target=SimpleNamespace(hidden=False), capture_error=None,
                               options=SimpleNamespace(presenter=False),
                               revision=SimpleNamespace(text="T"), language="EN")
    events = []
    views = ("instructor", "during-course", "after-course")
    monkeypatch.setattr(parallel_runs, "BUDGET", parallel_runs.RenderBudget(8))
    monkeypatch.setattr(parallel_runs, "cpu_has_room", lambda: True)
    results = batch_render.render_batch(Service(), [spec(v) for v in views], progress=events.append)
    assert state["peak"] == 3
    assert [r.request.view for r in results] == list(views)
    assert [e.done for e in events if e.status != "rendering"] == [1, 2, 3]
