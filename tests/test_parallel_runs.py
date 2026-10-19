# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Several preview renders at once: the cap, the CPU rule (one more only while the CPU has room), cancelling, and
a batch that renders its views in parallel but keeps their order."""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from slidemage import parallel_runs, preview_batch


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


def test_up_to_the_cap_run_at_once_and_all_run():
    work, state = tasks(8)
    started = time.perf_counter()
    parallel_runs.run_all(work, workers=4, may_add=lambda: True)
    assert state["ran"] == 8 and state["peak"] == 4
    assert time.perf_counter() - started < 8 * 0.2 * 0.75        # clearly faster than one after another


def test_with_a_busy_cpu_only_one_runs_at_a_time_and_none_is_lost():
    work, state = tasks(4, 0.05)
    parallel_runs.run_all(work, workers=4, may_add=lambda: False)
    assert state["ran"] == 4 and state["peak"] == 1


def test_the_cpu_rule_is_asked_for_every_extra_one():
    asked = []
    work, state = tasks(6, 0.1)
    parallel_runs.run_all(work, workers=3, may_add=lambda: asked.append(1) or len(asked) <= 1)
    assert state["ran"] == 6 and state["peak"] == 2            # room once: a second one; then no more beside it


def test_after_cancel_no_task_starts_and_a_failing_task_does_not_stop_the_others():
    cancel = threading.Event()
    ran = []

    def failing():
        raise RuntimeError("no TeX")

    def ok():
        ran.append(1)

    def cancelling():
        cancel.set()
    parallel_runs.run_all([failing, ok, cancelling, ok, ok], workers=1, may_add=lambda: True, cancel=cancel)
    assert ran == [1]


def test_the_default_is_half_the_cores_within_bounds(monkeypatch):
    monkeypatch.setattr(parallel_runs.os, "cpu_count", lambda: 24)
    assert parallel_runs.default_workers() == 12
    monkeypatch.setattr(parallel_runs.os, "cpu_count", lambda: 64)
    assert parallel_runs.default_workers() == 16
    monkeypatch.setattr(parallel_runs.os, "cpu_count", lambda: 2)
    assert parallel_runs.default_workers() == 2


def test_a_batch_renders_its_views_at_once_and_keeps_their_order(monkeypatch):
    monkeypatch.setattr(preview_batch, "image_group", lambda spec, identity=None: None)   # every view its own image
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
                               options=SimpleNamespace(render_stamp=None, force=False, saved=True, presenter=False,
                                                       mode="slide", overlay=None),
                               revision=SimpleNamespace(text="T"), language="EN")
    monkeypatch.setattr(preview_batch, "replace", lambda obj, **changes: (
        obj.__dict__.update(changes) or obj) if isinstance(obj, SimpleNamespace) else _replace(obj, **changes))
    events = []
    views = ("instructor", "during-course", "after-course")
    results = preview_batch.render_batch(Service(), [spec(v) for v in views], progress=events.append, workers=3,
                                         may_add=lambda: True)
    assert state["peak"] == 3
    assert [r.request.view for r in results] == list(views)
    assert [e.done for e in events if e.status != "rendering"] == [1, 2, 3]


def _replace(obj, **changes):
    from dataclasses import replace
    return replace(obj, **changes)
