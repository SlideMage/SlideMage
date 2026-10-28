# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The compile flow of the workspace: pre-check, job panel, Log drawer, the failure
toast that jumps to the failing line, stopping, retrying and closing mid-compile.
The compiler is replaced by a script that writes the log lines a real run writes."""
from __future__ import annotations

import threading

import pytest
from conftest import wait_until
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton

from slidemage import compile_progress, compiler, deck_outline, latex_lint
from slidemage.compile_status import DONE, FAILED, QUEUED, STOPPED
from conftest import EXAMPLE_PROJECT
from slidemage.ui.workspace import compile_actions, render_check

from test_workspace_window import COURSE, MANUAL, OLD, WORK, make_deck, qapp, window as window  # noqa: F401 -- fixtures

SLIDE = sorted((EXAMPLE_PROJECT.root / "slides").glob("*-current.tex"))[0]
SLIDE_ID = SLIDE.name.split("-")[0]
ERROR_LINE = f"{SLIDE.relative_to(EXAMPLE_PROJECT.root).as_posix()}:47: Undefined control sequence."


def toast_texts(toast):
    """(message, action labels) of a toast."""
    return ([label.text() for label in toast.findChildren(QLabel)],
            [button.text() for button in toast.findChildren(QPushButton)])


def show_buttons(sheet):
    return [b for b in sheet.findChildren(QPushButton) if b.text() == "Show in editor"]


def press(drawer, text):
    next(b for b in drawer.findChildren(QPushButton) if b.text() == text).click()


def passing(job):
    return [f"==== Compiling {job.deck.name} -> {job.jobname} ====", "Run number 1 of rule 'lualatex'",
            f"==== MOVING: {job.jobname} -> pdf/{job.jobname}.pdf ====",
            f"==== PASS: {job.jobname} -> pdf/{job.jobname}.pdf ===="]


def failing(job):
    return [f"==== Compiling {job.deck.name} -> {job.jobname} ====", ERROR_LINE,
            f"*** FAIL: {job.jobname} -- see .build/{job.jobname}.log ***"]


@pytest.fixture
def env(ctx, window, monkeypatch):  # noqa: F811
    """A window whose compiles run `env.script(job)` instead of latexmk; it records what it ran."""
    class Env:
        pass

    e = Env()
    e.window, e.ran, e.fails, e.opened, e.opened_pdfs = window, [], set(), [], []
    e.script = lambda job: failing(job) if job.jobname in e.fails else passing(job)

    def run_jobs(ctx, jobs, log, cancel=None):
        results = {}
        for job in jobs:
            e.ran.append(job.jobname)
            for line in e.script(job):
                log(line)
            results[job.jobname] = job.jobname not in e.fails
        log(f"==== Done: {sum(results.values())} passed, {len(results) - sum(results.values())} failed ====")
        return results

    monkeypatch.setattr(compile_actions, "run_jobs", run_jobs)
    monkeypatch.setattr(compile_progress, "count_job_slides", lambda *a: 1)
    monkeypatch.setattr(compile_progress, "spec_for_job", lambda ctx, job: compile_progress.JobSpec(3, 1))
    monkeypatch.setattr(compiler, "unchanged_jobs", lambda ctx, jobs, outputs: [])
    monkeypatch.setattr(latex_lint, "check_jobs", lambda _ctx, jobs: latex_lint.CheckResult())
    monkeypatch.setattr(window, "open_slide_editor", lambda path, on_saved=None, line=None: e.opened.append((path, line)))
    monkeypatch.setattr(window.compile_display, "open_pdf", lambda path: e.opened_pdfs.append(path.name))
    window.state.set_deck(COURSE)

    def finished():
        wait_until(lambda: not window.compiling and window.compile.is_settled)

    e.finished = finished
    return e


def build(env, kind="all"):
    jobs = compiler.build_jobs(COURSE, kind)
    compile_actions.compile_jobs(env.window, jobs)
    return jobs


# -- a run ----------------------------------------------------------------------

def test_a_run_shows_its_jobs_and_ends_with_a_summary_card(env):
    env.fails = {"course-during-course"}
    build(env)
    env.finished()
    panel, run = env.window.compile_display.panel, env.window.compile.run
    assert [row.state for row in run.rows.values()] == [DONE, FAILED, DONE]
    assert not panel.isHidden() and "Done: 2 passed, 1 failed" in panel._title.text()
    assert not panel.retry_button.isHidden() and not panel.stop_button.isVisibleTo(panel)
    assert not panel.open_button.isHidden() and panel.open_button.text() == "Open PDFs"
    assert panel._rows["course-during-course"].detail.text() == f"failed · {SLIDE_ID} · line 47"
    assert not panel._rows["course-during-course"].source.isHidden()
    assert not env.window.compile_display.drawer.isHidden()                       # a failure opens the Log
    assert env.window.compile_display.drawer._error.text() == f"Show {SLIDE_ID} · line 47"
    env.window.compile_display.drawer._error.click()
    env.window.compile_display.panel._rows["course-during-course"].source.click()
    assert env.opened == [(SLIDE, 47)] * 2


def test_auto_open_opens_each_pdf_that_lands_and_the_card_opens_them_again(env):
    env.window.build_options.auto_open_checkbox.setChecked(True)
    build(env)
    env.finished()
    assert env.opened_pdfs == ["course-instructor.pdf", "course-during-course.pdf", "course-after-course.pdf"]
    env.opened_pdfs.clear()
    env.window.compile_display.panel.open_button.click()
    assert len(env.opened_pdfs) == 3
    env.opened_pdfs.clear()
    env.window.build_options.auto_open_checkbox.setChecked(False)
    build(env, "instructor")
    env.finished()
    assert env.opened_pdfs == []


@pytest.mark.parametrize("fails", [False, True], ids=["ready-pdf", "failed-source"])
def test_single_job_toast_opens_its_pdf_or_failing_source(env, fails):
    env.window.build_options.auto_open_checkbox.setChecked(False)
    if fails:
        env.fails = {"course-instructor"}
    build(env, "instructor")
    env.finished()
    toast = env.window.compile_display.toast
    assert not toast.isHidden() and env.window.compile_display.panel.isHidden()
    if fails:
        assert toast_texts(toast) == ([f"Compile failed in {SLIDE_ID}"], ["Open in Source", "Log"])
        env.window.compile_display._on_toast_action("source")
        assert env.opened == [(SLIDE, 47)]
        env.window.compile_display._on_toast_action("log")
        assert not env.window.compile_display.drawer.isHidden()
    else:
        assert toast_texts(toast) == (["course · Instructor ready"], ["Open PDF", "Log"])
        assert env.window.compile_display.drawer.isHidden()
        env.window.compile_display._on_toast_action("pdf")
        assert env.opened_pdfs == ["course-instructor.pdf"]


def test_retry_failed_runs_only_the_failed_jobs_again(env):
    env.fails = {"course-during-course"}
    build(env)
    env.finished()
    env.ran.clear()
    env.fails = set()
    env.window.compile_display.panel.retry_button.click()
    env.finished()
    assert env.ran == ["course-during-course"]
    assert not env.window.compile_display.toast.isHidden()


def test_stopping_a_job_skips_a_queued_one_and_kills_the_running_one(ctx, env, monkeypatch):
    window = env.window
    release = threading.Event()

    def blocking(ctx, jobs, log, cancel=None):
        log(f"==== Compiling course -> {jobs[0].jobname} ====")
        release.wait(5)
        log(f"*** FAIL: {jobs[0].jobname} -- stopped by user ***")
        for job in jobs[1:]:
            if cancel.is_skipped(job.jobname):
                log(f"==== Skipped: {job.jobname} ====")
        log("==== Done: 0 passed, 1 failed ====")
        return {}

    monkeypatch.setattr(compile_actions, "run_jobs", blocking)
    build(env)
    wait_until(lambda: window.compile.run.rows["course-instructor"].state != QUEUED)
    killed = []
    window.compile.cancel.stop_current = lambda: killed.append(True)
    window.compile.stop_job("course-instructor")
    window.compile.stop_job("course-after-course")
    assert killed == [True] and window.compile.run.rows["course-after-course"].state == STOPPED
    assert window.compile.cancel.is_skipped("course-after-course")
    assert window.compile_display.panel._rows["course-after-course"].detail.text() == "skipped"
    release.set()
    env.finished()
    assert [row.state for row in window.compile.run.rows.values()] == [STOPPED, STOPPED, STOPPED]


def test_stop_all_asks_and_stops_the_whole_run(ctx, env, monkeypatch):
    window = env.window
    release = threading.Event()

    def blocking(ctx, jobs, log, cancel=None):
        log(f"==== Compiling course -> {jobs[0].jobname} ====")
        cancel._event.wait(5)
        log(f"*** FAIL: {jobs[0].jobname} -- stopped by user ***")
        log(f"==== Stopped: {len(jobs) - 1} job(s) skipped ====")
        release.set()
        return {}

    monkeypatch.setattr(compile_actions, "run_jobs", blocking)
    build(env)
    wait_until(lambda: window.compile.run.rows["course-instructor"].state != QUEUED)
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No)
    window.compile_display.panel.stop_button.click()
    assert not window.compile.cancel.is_set()
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    window.compile_display.panel.stop_button.click()
    env.finished()
    assert window.compile.run.summary() == "0 passed, 3 stopped"
    assert "Done: 0 passed, 3 stopped" in window.compile_display.panel._title.text()


def test_closing_the_window_mid_compile_stops_the_run_and_its_thread(ctx, env, monkeypatch):
    window = env.window
    started = threading.Event()

    def blocking(ctx, jobs, log, cancel=None):
        started.set()
        cancel._event.wait(10)
        return {}

    monkeypatch.setattr(compile_actions, "run_jobs", blocking)
    build(env)
    wait_until(started.is_set)
    token, worker = window.compile.cancel, window.compile.worker
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No)
    window.close()
    assert not token.is_set() and worker.isRunning()                  # asked, and the answer was no
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    assert window.close() is True
    assert token.is_set() and not worker.isRunning()


# -- the pre-check ------------------------------------------------------------------

def broken():
    issue = latex_lint.LintIssue(latex_lint.CHECKS[0][0], "Unbalanced braces", 9, SLIDE.name, SLIDE)
    return latex_lint.CheckResult(issues=[issue], files_checked=1)


def test_a_build_with_errors_waits_for_build_anyway(env, monkeypatch):
    monkeypatch.setattr(latex_lint, "check_jobs", lambda _ctx, jobs: broken())
    answers = iter(["cancel", "anyway", "show"])

    def exec_(sheet):
        answer = next(answers)
        if answer == "anyway":
            sheet._on_anyway()
        elif answer == "show":
            show_buttons(sheet)[0].click()
        else:
            sheet.reject()

    monkeypatch.setattr(render_check.RenderCheckSheet, "exec", exec_)
    build(env, "instructor")
    assert env.ran == [] and not env.window.compiling                     # cancelled
    build(env, "instructor")
    env.finished()
    assert env.ran == ["course-instructor"]                              # "Build anyway"
    build(env, "instructor")                                             # "Show in editor": no build, jumps
    assert env.ran == ["course-instructor"] and env.opened == [(SLIDE, 9)]
    assert "Unbalanced braces" in env.window.compile_display.drawer.text.toPlainText()


# -- the menu and the other entry points ------------------------------------------------

def test_the_caret_compiles_the_selected_slides_and_every_active_deck(env, monkeypatch):
    window = env.window
    seen = []
    monkeypatch.setattr(compile_actions, "compile_slides", lambda window, ids: seen.append(ids))
    window.topbar.command.emit("compile:slides")                          # nothing selected, nothing focused: disabled
    window.state.set_selection(("aaa", "bbb"))
    assert window.topbar._compile_menu._entries and any(
        e[0] == "item" and e[1] == "compile:slides" and e[6] for e in window.topbar._compile_menu._entries)
    window.topbar.command.emit("compile:slides")
    assert seen == [["aaa", "bbb"]]
    window.decks = [WORK, COURSE, MANUAL, OLD]
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    jobs = []
    monkeypatch.setattr(compile_actions, "compile_jobs", lambda window, batch: jobs.extend(batch))
    window.topbar.command.emit("compile:everything")
    assert sorted({job.deck.name for job in jobs}) == ["#workdeck", "course", "slidemage-manual"]   # not the archive
    assert len(jobs) == 1 + 3 + 3


def test_current_deck_compile_and_selected_pages_take_the_workspace_language(ctx, env, monkeypatch):
    window = env.window
    window.state.set_language("DE")
    captured = []
    monkeypatch.setattr(compile_actions, "compile_jobs", lambda window, jobs: captured.extend(jobs))
    compile_actions.compile_current(window, "instructor")
    assert captured[-1].language == "DE" and captured[-1].jobname == "course-instructor-de"
    looked_up = []
    monkeypatch.setattr(compile_actions.partial_compile, "frames_for_slides",
                        lambda ctx, job, ids: looked_up.append((job.language, ids)) or [2])
    compile_actions.compile_slides(window, ["ddd"])
    assert looked_up == [("DE", ["ddd"])]
    assert captured[-1].pages == [2] and captured[-1].language == "DE"


def test_the_log_drawer_is_closed_until_asked_and_takes_every_writer(env):
    window = env.window
    drawer = window.compile_display.drawer
    assert drawer.isHidden()
    window.log("from the window")
    window.log("from a thread")
    wait_until(lambda: "from a thread" in drawer.text.toPlainText())
    assert drawer.text.toPlainText().splitlines() == ["from the window", "from a thread"]
    window.topbar.command.emit("log")
    assert not drawer.isHidden()
    press(drawer, "Copy log")
    assert QApplication.clipboard().text() == "from the window\nfrom a thread"
    press(drawer, "Clear log")
    assert drawer.text.toPlainText() == ""
    window.topbar.command.emit("log")
    assert drawer.isHidden()


# -- carried over ----------------------------------------------------------------------

def test_route_leases_are_independent_and_exclusive(window, monkeypatch):  # noqa: F811
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warned.append(a[2]))
    local = window.acquire_route_task("ollama", "checking")
    cloud = window.acquire_route_task("anthropic_api", "drafting")
    assert local is not None and cloud is not None
    assert window.acquire_route_task("ollama", "checking again") is None and warned
    cloud.release()
    assert window._route_tasks["ollama"][0] == "checking"
    local.release()
    admin = window.acquire_route_task("ollama", "model admin")
    assert admin is not None
    admin.release()
    assert not window._route_tasks


def test_refresh_decks_forgets_the_cached_lint_results(window, monkeypatch):  # noqa: F811
    forgotten = []
    monkeypatch.setattr(deck_outline, "forget_lint", lambda: forgotten.append(True))
    window.topbar.command.emit("refresh_decks")
    assert forgotten == [True]


def test_a_deck_switch_rebuilds_the_slide_list_once_and_so_does_a_rescan_of_the_same_deck(window, monkeypatch):  # noqa: F811
    window.state.set_deck(COURSE)
    count = []
    monkeypatch.setattr(window.slide_list, "rebuild", lambda: count.append(1))
    window.reload_decks()                                            # a rescan of the deck now open
    assert len(count) == 1
    count.clear()
    window.state.deck = make_deck("gone")                            # its file has vanished: a real switch
    window.reload_decks()
    assert window.state.deck.name != "gone" and len(count) == 1
