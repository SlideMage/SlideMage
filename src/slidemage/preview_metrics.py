# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Optional wall-clock tracing of one preview, isolated per worker/context.

latexmk rule durations run from its pass-start line to its next log-reading
line (or next rule). They include pipe/logging overhead, not just CPU time.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import re
import time

_current = ContextVar("preview_metrics", default=None)
_RUN = re.compile(r"^Run number (\d+) of rule '([^']+)'")


class PreviewMetrics:
    def __init__(self):
        self.started = time.perf_counter()
        self.stages = {}
        self.counters = {}
        self.rules = []
        self._rule = None

    def __enter__(self):
        self.started = time.perf_counter()
        self._token = _current.set(self)
        return self

    def __exit__(self, *exc):
        self.finish_rule()
        self.seconds = time.perf_counter() - self.started
        _current.reset(self._token)

    def line(self, line):
        match = _RUN.match(line)
        if match:
            self.finish_rule()
            self._rule = (match[2], int(match[1]), time.perf_counter())
        elif line.startswith("Latexmk: Getting log file"):
            self.finish_rule()

    def finish_rule(self):
        if self._rule:
            name, number, start = self._rule
            self.rules.append(
                dict(rule=name, number=number, seconds=time.perf_counter() - start)
            )
            self._rule = None

    def to_dict(self):
        stages = dict(self.stages)
        if "render" in stages and "build" in stages:
            stages["prepare"] = max(0, stages["render"] - stages["build"])
        return dict(
            seconds=getattr(self, "seconds", time.perf_counter() - self.started),
            stages=stages,
            counters=dict(self.counters),
            rules=list(self.rules),
        )


@contextmanager
def stage(name):
    trace = _current.get()
    if trace is None:
        yield
        return
    start = time.perf_counter()
    try:
        yield
    finally:
        trace.stages[name] = trace.stages.get(name, 0) + time.perf_counter() - start


def count(name, amount):
    trace = _current.get()
    if trace is not None:
        trace.counters[name] = trace.counters.get(name, 0) + amount


def measure(name):
    def decorate(function):
        @wraps(function)
        def measured(*args, **kwargs):
            with stage(name):
                return function(*args, **kwargs)

        return measured

    return decorate


def record_line(line):
    trace = _current.get()
    if trace:
        trace.line(line)


def finish_rules():
    trace = _current.get()
    if trace:
        trace.finish_rule()
