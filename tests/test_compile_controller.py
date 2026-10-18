"""The compile slot: one run at a time, its worker thread, stopping and what a run reports.
No window here; compile_controller.CompileController only emits signals."""
from __future__ import annotations

import threading

import pytest
from conftest import EXAMPLE_PROJECT, wait_until

from test_workspace_window import COURSE

from slidemage import compile_progress, compiler
from slidemage.compile_status import DONE, STOPPED
from slidemage.ui.workspace.compile_controller import CompileController

PASS = ["==== Compiling d -> a ====", "==== MOVING: a -> pdf/a.pdf ====", "==== PASS: a -> pdf/a.pdf ===="]


@pytest.fixture
def controller(qapp):
    return CompileController(EXAMPLE_PROJECT)


def start(controller, work, **kwargs):
    controller.start({"a": "A"}, {"a": compile_progress.JobSpec(3, 1)}, work, **kwargs)


def test_a_run_takes_the_slot_and_frees_it_when_the_worker_ends(controller):
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
    assert done == ["result"]                         # on_done runs once the slot is free


def test_a_work_that_raises_is_logged_and_still_frees_the_slot(controller):
    lines = []
    controller.log.connect(lines.append)

    def work(log, cancel):
        raise ZeroDivisionError("boom")

    start(controller, work, failure="Compile run")
    wait_until(lambda: not controller.running)
    assert "*** Compile run failed: boom ***" in lines
    assert controller.over


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


def test_retry_hands_back_only_the_failed_jobs(controller, monkeypatch):
    jobs = compiler.build_jobs(COURSE, "all")
    failed = jobs[1].jobname

    def work(log, cancel):
        for job in jobs:
            log(f"==== Compiling course -> {job.jobname} ====")
            log(f"*** FAIL: {job.jobname} -- see .build/{job.jobname}.log ***" if job.jobname == failed
                else f"==== PASS: {job.jobname} -> pdf/{job.jobname}.pdf ====")

    monkeypatch.setattr(compile_progress, "spec_for_job", lambda job: compile_progress.JobSpec(3, 1))
    controller.start({j.jobname: j.jobname for j in jobs}, {j.jobname: compile_progress.JobSpec(3, 1) for j in jobs},
                     work, jobs=jobs)
    wait_until(lambda: controller.is_settled)
    assert [job.jobname for job in controller.failed_jobs()] == [failed]


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
