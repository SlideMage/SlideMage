# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Workspace compile controls driven by scripted compiler status lines."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import threading

import pytest
from conftest import wait_until
from PySide6.QtWidgets import QApplication, QInputDialog, QLabel, QMessageBox, QPushButton

from slidemage import compile_progress, compiler, deck_outline, latex_lint
from slidemage.compile_status import DONE, FAILED, QUEUED, STOPPED
from conftest import EXAMPLE_PROJECT
from slidemage.ui.dialogs.saved_versions import SavedVersionsSheet
from slidemage.ui.workspace import compile_actions, render_check

from test_workspace_window import COURSE, MANUAL, OLD, WORK, make_deck, qapp, window as window  # noqa: F401 -- fixtures

SLIDE = sorted((EXAMPLE_PROJECT.root / "slides").glob("*-current.tex"))[0]
SLIDE_ID = SLIDE.name.split("-")[0]
ERROR_LINE = f"{SLIDE.relative_to(EXAMPLE_PROJECT.root).as_posix()}:47: Undefined control sequence."


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
    e = SimpleNamespace(window=window, ran=[], fails=set(), opened=[], opened_pdfs=[])
    e.script = lambda job: failing(job) if job.jobname in e.fails else passing(job)

    def run_jobs(ctx, jobs, log, cancel=None, *, resolver=None):
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
    monkeypatch.setattr(compiler, "unchanged_jobs", lambda ctx, jobs, outputs, **kwargs: [])
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
        press(toast, "Open in Source")
        assert env.opened == [(SLIDE, 47)]
        press(toast, "Log")
        assert not env.window.compile_display.drawer.isHidden()
    else:
        assert env.window.compile_display.drawer.isHidden()
        press(toast, "Open PDF")
        assert env.opened_pdfs == ["course-instructor.pdf"]


def test_a_failed_build_shows_its_source_and_retries_only_failed_jobs(env):
    env.fails = {"course-during-course"}
    build(env)
    env.finished()
    display = env.window.compile_display
    assert [row.state for row in env.window.compile.run.rows.values()] == [DONE, FAILED, DONE]
    assert not display.panel.isHidden() and not display.drawer.isHidden()
    assert "2 passed, 1 failed" in display.panel._title.text()
    display.panel._rows["course-during-course"].source.click()
    assert env.opened == [(SLIDE, 47)]

    env.ran.clear()
    env.fails.clear()
    display.panel.retry_button.click()
    env.finished()
    assert env.ran == ["course-during-course"]
    assert not env.window.compile_display.toast.isHidden()


def test_stopping_a_job_skips_a_queued_one_and_kills_the_running_one(env, monkeypatch):
    window = env.window
    release = threading.Event()

    def blocking(ctx, jobs, log, cancel=None, *, resolver=None):
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
    release.set()
    env.finished()
    assert [row.state for row in window.compile.run.rows.values()] == [STOPPED, STOPPED, STOPPED]


def test_stop_all_asks_and_stops_the_whole_run(env, monkeypatch):
    window = env.window

    def blocking(ctx, jobs, log, cancel=None, *, resolver=None):
        log(f"==== Compiling course -> {jobs[0].jobname} ====")
        cancel._event.wait(5)
        log(f"*** FAIL: {jobs[0].jobname} -- stopped by user ***")
        log(f"==== Stopped: {len(jobs) - 1} job(s) skipped ====")
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


def test_closing_the_window_mid_compile_stops_the_run_and_its_thread(env, monkeypatch):
    window = env.window
    started = threading.Event()

    def blocking(ctx, jobs, log, cancel=None, *, resolver=None):
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
            press(sheet, "Show in editor")
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


def test_the_caret_compiles_the_selected_slides_and_every_active_deck(env, monkeypatch):
    window = env.window
    seen = []
    monkeypatch.setattr(compile_actions, "compile_slides", lambda window, ids: seen.append(ids))
    window.topbar.command.emit("compile:slides")                          # nothing selected, nothing focused: disabled
    window.state.set_selection(("aaa", "bbb"))                            # not in the caret menu, but still a command
    window.topbar.command.emit("compile:slides")
    assert seen == [["aaa", "bbb"]]
    window.decks = [WORK, COURSE, MANUAL, OLD]
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    jobs = []
    monkeypatch.setattr(compile_actions, "compile_jobs", lambda window, batch: jobs.extend(batch))
    window.topbar.command.emit("compile:everything")
    assert sorted({job.deck.name for job in jobs}) == ["#workdeck", "course", "slidemage-manual"]   # not the archive
    assert len(jobs) == 1 + 3 + 3


def test_current_deck_compile_and_selected_pages_take_the_workspace_language(env, monkeypatch):
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


def test_refresh_decks_invalidates_lint_and_rebuilds_the_list_once(window, monkeypatch):  # noqa: F811
    window.state.set_deck(COURSE)
    count, forgotten = [], []
    monkeypatch.setattr(window.slide_list, "rebuild", lambda: count.append(1))
    monkeypatch.setattr(deck_outline, "forget_lint", lambda: forgotten.append(True))
    window.topbar.command.emit("refresh_decks")
    assert len(count) == 1 and forgotten == [True]
    count.clear()
    window.state.deck = make_deck("gone")                            # its file has vanished: a real switch
    window.reload_decks()
    assert window.state.deck.name != "gone" and len(count) == 1
    window.state.set_deck(COURSE)
    window.reload_decks(closing=frozenset({COURSE.name}))
    assert window.state.deck is None or window.state.deck.name != COURSE.name


def test_the_current_view_compiles_once_in_another_color_mode(env, monkeypatch):
    window = env.window
    deck = replace(COURSE, text="\\documentclass{beamer}\n\\input{SlideMage_template_slidemage}\n\\begin{document}\n")
    window.state.set_deck(deck)
    window.state.set_view("after-course")
    command = window.commands["compile:mode"]
    assert command.enabled(window)
    captured = []
    monkeypatch.setattr(compile_actions, "compile_jobs", lambda window, jobs: captured.extend(jobs))
    window.commands.run("compile:mode", window)
    assert [(job.version, job.mode, job.jobname) for job in captured] == [
        ("after-course", "dark", "course-after-course-dark")]

    (window.project.root / "SlideMage_template_acme.tex").write_text("% SlideMage modes: light, dark=Dark slides, gray\n")
    window.state.set_deck(replace(deck, text=deck.text.replace("slidemage}", "acme}")))
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: ("Gray", True))
    captured.clear()
    assert window.commands.run("compile:mode", window)
    assert [job.mode for job in captured] == ["gray"]
    (window.project.root / "SlideMage_template_acme.tex").write_text("\\input{SlideMage_setup}\n")      # no modes: disabled
    assert not command.enabled(window)


@pytest.fixture
def saved(env, monkeypatch):
    from slidemage import app_settings, slide_versioning
    settings = {}
    env.saved_versions = slide_versioning.saved_versions
    monkeypatch.setattr(app_settings, "get", lambda _ctx, key, default=None: settings.get(key, default))
    monkeypatch.setattr(app_settings, "set", lambda _ctx, key, value: settings.__setitem__(key, value))
    monkeypatch.setattr(slide_versioning, "saved_versions",
                        lambda _ctx, deck, _language, **_kw: {"ijp-EN-A": "x", "mgt-EN-B": "y"} if deck is COURSE else {})
    env.edits, env.asked, env.logged = [], [], []
    script = env.script
    env.script = lambda job: env.edits.append(job.current_edits) or script(job)
    monkeypatch.setattr(env.window, "log", lambda line: env.logged.append(line))

    def choose(text, remember=False):
        def fake_exec(sheet):
            env.asked.append("\n".join(label.text() for label in sheet.findChildren(QLabel)))
            sheet.remember_check.setChecked(remember)
            next(b for b in sheet.findChildren(QPushButton) if b.text() == text).click()
            return sheet.result()
        monkeypatch.setattr(SavedVersionsSheet, "exec", fake_exec)
    env.choose = choose
    env.setting = lambda key, default: settings.get(getattr(slide_versioning, key), default)
    return env


def test_making_last_versions_the_setting_stops_asking_but_still_logs(saved, monkeypatch):
    saved.choose("Compile last versions", remember=True)
    build(saved, "instructor")
    saved.finished()
    assert len(saved.asked) == 1 and "course · 2 slides\nijp, mgt" in saved.asked[0]
    assert not saved.setting("ASK_SAVED_VERSIONS_SETTING_KEY", True)
    monkeypatch.setattr(SavedVersionsSheet, "exec", lambda sheet: pytest.fail("asked again"))
    saved.logged.clear()
    build(saved, "instructor")
    saved.finished()
    assert saved.edits == [False, False]
    assert any("compiled from their last version" in line for line in saved.logged)


@pytest.mark.parametrize("remember", [False, True])
def test_compile_with_edits_skips_the_last_versions_for_this_run_or_as_the_setting(saved, remember):
    saved.choose("Compile with edits (+)", remember)
    build(saved, "instructor")
    saved.finished()
    assert saved.edits == [True]
    assert saved.setting("RENDER_CHANGES_SETTING_KEY", False) is remember
    assert not any("compiled from their last version" in line for line in saved.logged)


@pytest.mark.parametrize("updated", [False, True])
def test_update_versions_first_compiles_only_if_every_update_succeeds(ctx, saved, monkeypatch, updated):
    from slidemage import deck_scan, slide_versioning

    ctx.decks_dir.mkdir()
    ctx.slides_dir.mkdir()
    slugs = ("ijp-EN-A", "mgt-EN-B")
    raw = r"\setSlideVersion{1-0-0+}" + "\nedited\n"
    for slug in slugs:
        (ctx.slides_dir / f"{slug}-current.tex").write_text(raw)
        (ctx.slides_dir / f"{slug}-v1-0-0.tex").write_text("original")
    deck_file = ctx.decks_dir / "course.tex"
    deck_file.write_text(r"\documentclass{beamer}\begin{document}" + "".join(rf"\slide{{{s}}}" for s in slugs))
    deck = deck_scan.read_deck(deck_file)
    window = saved.window
    renderer = window.centre.preview._renders.renderer(window.project)
    monkeypatch.setattr(window.centre.preview._renders, "renderer", lambda _ctx: renderer)
    monkeypatch.setattr(window, "project", ctx)
    monkeypatch.setattr(window.state, "project", ctx)
    monkeypatch.setattr(window, "after_version_updates", lambda paths: None)
    monkeypatch.setattr(slide_versioning, "saved_versions", saved.saved_versions)
    if not updated:
        (ctx.slides_dir / "mgt-EN-B-v1-0-1.tex").write_text("already frozen")
    warnings = []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: next(b for b in box.buttons() if b.text() == "Patch").click())
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, message: warnings.append(message))
    saved.choose("Update versions first")
    started = compile_actions.compile_jobs(window, [compiler.CompileJob(deck, "instructor", None)])
    if started:
        saved.finished()
    assert started is updated
    assert saved.ran == (["course-instructor"] if updated else [])
    assert (ctx.slides_dir / "ijp-EN-A-v1-0-1.tex").exists() is updated
    if not updated:
        assert warnings and "mgt-EN-B" in warnings[0]
        assert all((ctx.slides_dir / f"{slug}-current.tex").read_text() == raw for slug in slugs)


def test_cancel_compiles_nothing(saved):
    saved.choose("Cancel")
    assert not compile_actions.compile_jobs(saved.window, compiler.build_jobs(COURSE, "instructor"))
    assert saved.ran == []
