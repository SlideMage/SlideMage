# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compile worker ownership, cancellation and progress."""
from __future__ import annotations

import threading

import pytest
from conftest import EXAMPLE_PROJECT, wait_until

from slidemage import compile_progress
from slidemage.compile_status import DONE, STOPPED
from slidemage.ui.workspace.compile_controller import CompileController

PASS = ["==== Compiling d -> a ====", "==== MOVING: a -> pdf/a.pdf ====", "==== PASS: a -> pdf/a.pdf ===="]


@pytest.fixture
def controller(qapp):
    return CompileController(EXAMPLE_PROJECT)


def start(controller, work, **kwargs):
    controller.start({"a": "A"}, {"a": compile_progress.JobSpec(3, 1)}, work, **kwargs)


def test_the_compile_slot_is_released_after_success_and_an_unexpected_error(controller):
    events = []
    controller.started.connect(lambda run: events.append("started"))
    controller.ended.connect(lambda: events.append("ended"))
    controller.settled.connect(lambda run: events.append("settled"))
    controller.pdf_ready.connect(lambda pdf: events.append(pdf.name))
    done = []

    def work(log, cancel):
        for line in PASS:
            log(line)
        return "result"

    start(controller, work, pdfs={"a": EXAMPLE_PROJECT.root / "pdf" / "a.pdf"}, on_done=done.append)
    assert controller.running
    wait_until(lambda: controller.is_settled)
    assert not controller.running and controller.cancel is None
    assert controller.run.rows["a"].state == DONE
    assert events[0] == "started" and events[-1] == "settled" and "ended" in events and "a.pdf" in events
    assert done == ["result"]

    def fail(log, cancel):
        raise ZeroDivisionError("boom")

    controller.log.connect(events.append)
    start(controller, fail, failure="Compile run")
    wait_until(lambda: controller.is_settled)
    assert controller.over and "*** Compile run failed: boom ***" in events


def test_stop_cancels_the_token_and_marks_what_never_ran_as_stopped(controller):
    seen = {}

    def work(log, cancel):
        seen["cancel"] = cancel
        log("==== Compiling d -> a ====")
        cancel._event.wait(5)

    start(controller, work)
    wait_until(lambda: "cancel" in seen and controller.run.rows["a"].state != "queued")
    controller.stop()
    wait_until(lambda: controller.is_settled)
    assert seen["cancel"].is_set() and controller.run.rows["a"].state == STOPPED


def test_shutdown_stops_the_run_and_waits_for_the_thread(controller):
    started = threading.Event()

    def work(log, cancel):
        started.set()
        cancel._event.wait(10)

    start(controller, work)
    wait_until(started.is_set)
    worker = controller.worker
    controller.shutdown()
    assert worker.isFinished()


def test_preview_progress_counts_cache_hits_and_preserves_failure(controller):
    from types import SimpleNamespace
    from slidemage.compile_status import FAILED
    observed = []
    controller.changed.connect(lambda: observed.append(
        (controller.progress.fraction, controller.progress.text)))

    def work(log, cancel):
        for index, status in enumerate(('cached', 'failed', 'hidden'), 1):
            controller.preview_progress.emit(SimpleNamespace(index=index, total=3,
                                                            view='instructor', status=status))
            log("Run number 4 of rule 'lualatex'")

    start(controller, work)
    wait_until(lambda: not controller.running)
    assert controller.row('a').state == FAILED
    assert controller.progress.fraction == 1
    assert any(fraction == 1 / 3 and 'cached' in text for fraction, text in observed)
    assert controller.progress.text == '3/3 previews · instructor · hidden'
    start(controller, lambda log, cancel: [log(line) for line in PASS])
    wait_until(lambda: not controller.running)
    assert isinstance(controller.progress, compile_progress.BatchProgress)
    assert controller.row('a').state == DONE
