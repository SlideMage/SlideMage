"""The compile flow of the workspace: pre-check, job panel, Log drawer, the failure
toast that jumps to the failing line, stopping, retrying and closing mid-compile.
The compiler is replaced by a script that writes the log lines a real run writes."""
from __future__ import annotations

import threading
import time

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton

from slidemage import compile_progress, compiler, deck_outline, latex_lint
from slidemage.compile_status import DONE, FAILED, QUEUED, STOPPED
from slidemage.deck_scan import PROJECT_ROOT
from slidemage.ui.workspace import compile_jobs, render_check

from test_workspace_window import COURSE, MANUAL, OLD, WORK, make_deck, qapp, window  # noqa: F401 -- fixtures

SLIDE = sorted((PROJECT_ROOT / "slides").glob("*-current.tex"))[0]
SLIDE_ID = SLIDE.name.split("-")[0]
ERROR_LINE = f"{SLIDE.relative_to(PROJECT_ROOT).as_posix()}:47: Undefined control sequence."


def toast_texts(toast):
    """(message, action labels) of a toast."""
    return ([label.text() for label in toast.findChildren(QLabel)],
            [button.text() for button in toast.findChildren(QPushButton)])


def show_buttons(sheet):
    return [b for b in sheet.findChildren(QPushButton) if b.text() == "Show in editor"]


def press(drawer, text):
    next(b for b in drawer.findChildren(QPushButton) if b.text() == text).click()


def wait_until(condition, timeout=5.0):
    end = time.monotonic() + timeout
    while not condition():
        QApplication.processEvents()
        assert time.monotonic() < end, "timed out"
        time.sleep(0.005)
    QApplication.processEvents()


def passing(job):
    return [f"==== Compiling {job.deck.name} -> {job.jobname} ====", "Run number 1 of rule 'lualatex'",
            f"==== MOVING: {job.jobname} -> pdf/{job.jobname}.pdf ====",
            f"==== PASS: {job.jobname} -> pdf/{job.jobname}.pdf ===="]


def failing(job):
    return [f"==== Compiling {job.deck.name} -> {job.jobname} ====", ERROR_LINE,
            f"*** FAIL: {job.jobname} -- see .build/{job.jobname}.log ***"]


@pytest.fixture
def env(window, monkeypatch):  # noqa: F811
    """A window whose compiles run `env.script(job)` instead of latexmk; it records what it ran."""
    class Env:
        pass

    e = Env()
    e.window, e.ran, e.fails, e.opened, e.opened_pdfs = window, [], set(), [], []
    e.script = lambda job: failing(job) if job.jobname in e.fails else passing(job)

    def run_jobs(jobs, log, cancel=None):
        results = {}
        for job in jobs:
            e.ran.append(job.jobname)
            for line in e.script(job):
                log(line)
            results[job.jobname] = job.jobname not in e.fails
        log(f"==== Done: {sum(results.values())} passed, {len(results) - sum(results.values())} failed ====")
        return results

    monkeypatch.setattr(compile_jobs, "run_jobs", run_jobs)
    monkeypatch.setattr(compile_progress, "count_job_slides", lambda *a: 1)
    monkeypatch.setattr(compile_progress, "spec_for_job", lambda job: compile_progress.JobSpec(3, 1))
    monkeypatch.setattr(compiler, "unchanged_jobs", lambda jobs, outputs: [])
    monkeypatch.setattr(latex_lint, "check_jobs", lambda jobs: latex_lint.CheckResult())
    monkeypatch.setattr(window, "open_slide_editor", lambda path, on_saved=None, line=None: e.opened.append((path, line)))
    monkeypatch.setattr(window, "_open_pdf", lambda path: e.opened_pdfs.append(path.name))
    window.state.set_deck(COURSE)

    def finished():
        wait_until(lambda: not window.compiling and window._run_settled)

    e.finished = finished
    return e


def build(env, kind="all"):
    jobs = compiler.build_jobs(COURSE, kind)
    env.window._compile_jobs(jobs)
    return jobs


# -- a run ----------------------------------------------------------------------

def test_a_run_shows_its_jobs_and_ends_with_a_summary_card(env):
    env.fails = {"course-during-course"}
    build(env)
    env.finished()
    panel, run = env.window.job_panel, env.window._run
    assert [row.state for row in run.rows.values()] == [DONE, FAILED, DONE]
    assert not panel.isHidden() and "Done: 2 passed, 1 failed" in panel._title.text()
    assert not panel.retry_button.isHidden() and not panel.stop_button.isVisibleTo(panel)
    assert not panel.open_button.isHidden() and panel.open_button.text() == "Open PDFs"
    assert panel._rows["course-during-course"].detail.text() == f"failed · {SLIDE_ID} · line 47"
    assert not panel._rows["course-during-course"].source.isHidden()
    assert not env.window.log_drawer.isHidden()                       # a failure opens the Log
    assert env.window.log_drawer._error.text() == f"Show {SLIDE_ID} · line 47"
    assert env.window.topbar._compile_menu is not None


def test_auto_open_opens_each_pdf_that_lands_and_the_card_opens_them_again(env):
    env.window.build_options.auto_open_checkbox.setChecked(True)
    build(env)
    env.finished()
    assert env.opened_pdfs == ["course-instructor.pdf", "course-during-course.pdf", "course-after-course.pdf"]
    env.opened_pdfs.clear()
    env.window.job_panel.open_button.click()
    assert len(env.opened_pdfs) == 3
    env.opened_pdfs.clear()
    env.window.build_options.auto_open_checkbox.setChecked(False)
    build(env, "instructor")
    env.finished()
    assert env.opened_pdfs == []


def test_a_job_that_fails_is_reported_by_a_toast_that_opens_the_source_at_its_line(env):
    env.fails = {"course-instructor"}
    build(env, "instructor")
    env.finished()
    toast = env.window.compile_toast
    assert not toast.isHidden() and env.window.job_panel.isHidden()
    assert toast_texts(toast) == ([f"Compile failed in {SLIDE_ID}"], ["Open in Source", "Log"])
    env.window._on_compile_toast_action("source")
    assert env.opened == [(SLIDE, 47)]
    env.window._on_compile_toast_action("log")
    assert not env.window.log_drawer.isHidden()


def test_a_job_that_passes_is_answered_by_a_toast_with_its_pdf(env):
    env.window.build_options.auto_open_checkbox.setChecked(False)
    build(env, "instructor")
    env.finished()
    assert not env.window.compile_toast.isHidden() and env.window.job_panel.isHidden()
    assert toast_texts(env.window.compile_toast) == (["course · Instructor ready"], ["Open PDF", "Log"])
    assert env.window.log_drawer.isHidden()
    env.window._on_compile_toast_action("pdf")
    assert env.opened_pdfs == ["course-instructor.pdf"]


def test_the_failing_file_may_be_gone(env):
    env.script = lambda job: [f"==== Compiling course -> {job.jobname} ====", "slides/zzz-gone.tex:3: Oops",
                              f"*** FAIL: {job.jobname} -- x ***"]
    build(env, "instructor")
    env.finished()
    env.window._on_compile_toast_action("source")
    assert env.opened == [] and "the file is gone" in env.window.log_drawer.text.toPlainText()


def test_the_error_button_of_the_drawer_and_the_row_open_the_source(env):
    env.fails = {"course-after-course"}
    build(env)
    env.finished()
    env.window.log_drawer._error.click()
    env.window.job_panel._rows["course-after-course"].source.click()
    assert env.opened == [(SLIDE, 47)] * 2


def test_retry_failed_runs_only_the_failed_jobs_again(env):
    env.fails = {"course-during-course"}
    build(env)
    env.finished()
    env.ran.clear()
    env.fails = set()
    env.window.job_panel.retry_button.click()
    env.finished()
    assert env.ran == ["course-during-course"]
    assert not env.window.compile_toast.isHidden()


def test_stopping_a_job_skips_a_queued_one_and_kills_the_running_one(env, monkeypatch):
    window = env.window
    release = threading.Event()

    def blocking(jobs, log, cancel=None):
        log(f"==== Compiling course -> {jobs[0].jobname} ====")
        release.wait(5)
        log(f"*** FAIL: {jobs[0].jobname} -- stopped by user ***")
        for job in jobs[1:]:
            if cancel.is_skipped(job.jobname):
                log(f"==== Skipped: {job.jobname} ====")
        log("==== Done: 0 passed, 1 failed ====")
        return {}

    monkeypatch.setattr(compile_jobs, "run_jobs", blocking)
    build(env)
    wait_until(lambda: window._run.rows["course-instructor"].state != QUEUED)
    killed = []
    window.cancel_token.stop_current = lambda: killed.append(True)
    window._stop_job("course-instructor")
    window._stop_job("course-after-course")
    assert killed == [True] and window._run.rows["course-after-course"].state == STOPPED
    assert window.cancel_token.is_skipped("course-after-course")
    assert window.job_panel._rows["course-after-course"].detail.text() == "skipped"
    release.set()
    env.finished()
    assert [row.state for row in window._run.rows.values()] == [STOPPED, STOPPED, STOPPED]


def test_stop_all_asks_and_stops_the_whole_run(env, monkeypatch):
    window = env.window
    release = threading.Event()

    def blocking(jobs, log, cancel=None):
        log(f"==== Compiling course -> {jobs[0].jobname} ====")
        cancel._event.wait(5)
        log(f"*** FAIL: {jobs[0].jobname} -- stopped by user ***")
        log(f"==== Stopped: {len(jobs) - 1} job(s) skipped ====")
        release.set()
        return {}

    monkeypatch.setattr(compile_jobs, "run_jobs", blocking)
    build(env)
    wait_until(lambda: window._run.rows["course-instructor"].state != QUEUED)
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No)
    window.job_panel.stop_button.click()
    assert not window.cancel_token.is_set()
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    window.job_panel.stop_button.click()
    env.finished()
    assert window._run.summary() == "0 passed, 3 stopped"
    assert "Done: 0 passed, 3 stopped" in window.job_panel._title.text()


def test_closing_the_window_mid_compile_stops_the_run_and_its_thread(env, monkeypatch):
    window = env.window
    started = threading.Event()

    def blocking(jobs, log, cancel=None):
        started.set()
        cancel._event.wait(10)
        return {}

    monkeypatch.setattr(compile_jobs, "run_jobs", blocking)
    build(env)
    wait_until(started.is_set)
    token, worker = window.cancel_token, window._worker
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No)
    window.close()
    assert not token.is_set() and worker.is_alive()                  # asked, and the answer was no
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    assert window.close() is True
    assert token.is_set() and not worker.is_alive()


# -- the pre-check ------------------------------------------------------------------

def broken():
    issue = latex_lint.LintIssue(latex_lint.CHECKS[0][0], "Unbalanced braces", 9, SLIDE.name, SLIDE)
    return latex_lint.CheckResult(issues=[issue], files_checked=1)


def test_a_build_with_errors_waits_for_build_anyway(env, monkeypatch):
    monkeypatch.setattr(latex_lint, "check_jobs", lambda jobs: broken())
    answers = iter(["cancel", "anyway", "show"])
    seen = []

    def exec_(sheet):
        seen.append(sheet)
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
    assert [b.text() for b in seen[0].findChildren(QPushButton)][-2:] == ["Cancel", "Build anyway"]
    build(env, "instructor")                                             # "Show in editor": no build, jumps
    assert env.ran == ["course-instructor"] and env.opened == [(SLIDE, 9)]
    assert "Unbalanced braces" in env.window.log_drawer.text.toPlainText()


def test_the_check_sheet_lists_errors_before_warnings_and_confirm_logs_a_clean_check(qapp):  # noqa: F811
    warning = latex_lint.LintIssue("underscore", "x", 1, "a.tex", None)
    error = latex_lint.LintIssue(latex_lint.CHECKS[0][0], "y", 2, "b.tex", None)
    result = latex_lint.CheckResult(issues=[warning, error], files_checked=2)
    sheet = render_check.RenderCheckSheet(None, result, "deck", "Build", None)
    assert sheet.windowTitle() == "1 error found" and len(show_buttons(sheet)) == 2
    assert not any(b.isEnabled() for b in show_buttons(sheet))            # no editor, no file
    logged = []
    app = type("App", (), {"log": staticmethod(logged.append)})
    assert render_check.confirm_render(None, app, latex_lint.CheckResult(files_checked=3), "deck") is True
    assert logged and logged[0].startswith("Pre-render syntax check (deck): 3 file(s)")


# -- the menu and the other entry points ------------------------------------------------

def test_the_caret_compiles_the_selected_slides_and_every_active_deck(env, monkeypatch):
    window = env.window
    seen = []
    monkeypatch.setattr(window, "_compile_slides", lambda ids: seen.append(ids))
    window.topbar.command.emit("compile:slides")                          # nothing selected, nothing focused: disabled
    window.state.set_selection(("aaa", "bbb"))
    assert window.topbar._compile_menu._entries and any(
        e[0] == "item" and e[1] == "compile:slides" and e[6] for e in window.topbar._compile_menu._entries)
    window.topbar.command.emit("compile:slides")
    assert seen == [["aaa", "bbb"]]
    window.decks = [WORK, COURSE, MANUAL, OLD]
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    jobs = []
    monkeypatch.setattr(window, "_compile_jobs", lambda batch: jobs.extend(batch))
    window.topbar.command.emit("compile:everything")
    assert sorted({job.deck.name for job in jobs}) == ["#workdeck", "course", "slidemage-manual"]   # not the archive
    assert len(jobs) == 1 + 3 + 3


def test_current_deck_compile_and_selected_pages_take_the_workspace_language(env, monkeypatch):
    window = env.window
    window.state.set_language("DE")
    captured = []
    monkeypatch.setattr(window, "_compile_jobs", lambda jobs: captured.extend(jobs))
    window._compile_current("instructor")
    assert captured[-1].language == "DE" and captured[-1].jobname == "course-instructor-de"
    looked_up = []
    monkeypatch.setattr(compile_jobs.partial_compile, "frames_for_slides",
                        lambda job, ids: looked_up.append((job.language, ids)) or [2])
    window._compile_slides(["ddd"])
    assert looked_up == [("DE", ["ddd"])]
    assert captured[-1].pages == [2] and captured[-1].language == "DE"


def test_the_log_drawer_is_closed_until_asked_and_takes_every_writer(env):
    window = env.window
    drawer = window.log_drawer
    assert drawer.isHidden()
    window.log("from the window")
    window.signals.log.emit("from a thread")
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

class Provider:
    def __init__(self, local):
        self.is_local = local


def test_only_local_ollama_tasks_take_the_ollama_slot(window, monkeypatch):  # noqa: F811
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warned.append(a[2]))
    local, cloud = Provider(True), Provider(False)
    assert window.try_start_ollama_task("drafting", cloud) and window.try_start_ollama_task("translating", cloud)
    assert window._ollama_task_label is None                         # clouds take no slot
    assert window.try_start_ollama_task("checking", local)
    assert window.try_start_ollama_task("describing", cloud)         # and do not wait for it
    assert not window.try_start_ollama_task("checking again", local) and warned
    window.end_ollama_task(cloud)                                    # a cloud task ending frees nothing
    assert window._ollama_task_label == "checking"
    window.end_ollama_task(local)
    assert window._ollama_task_label is None
    assert window.try_start_ollama_task("model admin") and window._ollama_task_label == "model admin"
    window.end_ollama_task()
    assert window._ollama_task_label is None


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
