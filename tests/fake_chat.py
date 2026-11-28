# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Scriptable route-owned conversation and task runner for GUI tests.

These doubles use the route contract and never start a process or contact a service.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QLineEdit, QVBoxLayout, QWidget

from slidemage.ai.task_result import CANCELLED, FAILED, Outcome, judge


class FakeChatSurface(QWidget):
    """A route-owned conversation whose lifecycle can be observed by tests."""

    setup_changed = Signal()
    subtitle = "Scripted conversation"
    needs_setup = False

    def __init__(self, *_args):
        super().__init__()
        self.composer = QLineEdit(self)
        self.composer.setAccessibleName("Message")
        QVBoxLayout(self).addWidget(self.composer)
        self.turns = []
        self.replies = []
        self.answer = QLabel(self)
        self.layout().addWidget(self.answer)
        self.restarts = []
        self.session_live = False
        self.stopped = False
        self.composer.returnPressed.connect(self.send)

    def send(self):
        self.turns.append(self.composer.text())
        self.composer.clear()
        if self.replies:
            self.answer.setText(self.replies.pop(0))
        self.session_live = True

    def restart(self, *args):
        self.restarts.append(args)
        self.turns.clear()
        self.answer.clear()
        self.session_live = False

    def end_session(self):
        self.session_live = False

    def stop(self):
        self.stopped = True
        self.session_live = False


class FakeTaskRunner:
    """Script answers, outcomes, exceptions or callables; record each captured request.

    Dictionary answers pass through the same task validation as a route implementation.
    The last scripted step repeats, making concurrent batches deterministic when using
    callables that select their answer from the request.
    """

    def __init__(self, ctx, *steps):
        self.ctx = ctx
        self.steps = list(steps)
        self.calls = []
        self._lock = threading.Lock()

    def __call__(self, task, captured, request, cancel, span):
        with self._lock:
            index = len(self.calls)
            self.calls.append((task, captured, request, cancel, span))
            step = self.steps[min(index, len(self.steps) - 1)] if self.steps else Outcome(FAILED, message="No scripted answer.")
        if cancel.is_set():
            return Outcome(CANCELLED)
        if callable(step):
            step = step(task, captured, request, cancel, span)
        if isinstance(step, Exception):
            raise step
        if isinstance(step, Outcome):
            return step
        outcome = Outcome(FAILED, attempts=1)
        judge(self.ctx, task, captured, step, outcome, "Fake route", span)
        return outcome
