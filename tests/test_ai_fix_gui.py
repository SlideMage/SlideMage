# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The lint status line and "Ask AI to fix" of the Source view (the model is faked)."""
from __future__ import annotations

import threading

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from slidemage.ai import ai_profile
from slidemage.syntax_check import SyntaxCheckResult, SyntaxIssue
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.workspace import ai_fix
from slidemage.ui.workspace.source_file import SourceFile
from conftest import EXAMPLE_PROJECT

BROKEN = "\\begin{standardframe}{Demo}\nText {unclosed\n\\end{standardframe}\n"


class FakeApp:
    def __init__(self, project):
        self.project = project
        self.theme = ThemeManager()
        self.busy = False
        self.started, self.ended = [], []

    def log(self, _line):
        pass

    def open_slide_editor(self, path, **_kwargs):
        pass

    def acquire_route_task(self, route_id, label):
        from slidemage.plugins.host import _RouteTaskLease
        self.started.append(label)
        return None if self.busy else _RouteTaskLease(lambda: self.ended.append(True))


class FakeProvider:
    label = "qwen3"


@pytest.fixture
def make_file(qapp, ctx, monkeypatch, fake_routes):
    fake_routes.local.choices = ["qwen3"]
    fake_routes.local.choice_label = lambda choice: choice
    monkeypatch.setattr(ai_fix, "picked_route", lambda *a: ai_profile.Route("fake_local", ai_profile.FIXES, "qwen3"))
    monkeypatch.setattr(ai_fix, "built", lambda *a: FakeProvider())

    def make(text=BROKEN, name="abc-EN-Demo-current.tex"):
        path = ctx.root / name
        path.write_text(text, encoding="utf-8")
        return SourceFile(FakeApp(ctx), path)

    return make


def fake_checker(monkeypatch, result, hold=None):
    """A SyntaxChecker that returns `result`, after `hold` (an Event abort() sets) if given."""
    aborted = threading.Event()

    class Checker:
        def __init__(self, _provider):
            pass

        def check(self, text):
            if hold is not None:
                hold.wait(5)
            return SyntaxCheckResult(model="qwen3", error="Aborted.", cancelled=True) if aborted.is_set() else result

        def abort(self):
            aborted.set()
            if hold is not None:
                hold.set()

    monkeypatch.setattr(ai_fix.syntax_check, "SyntaxChecker", Checker)
    return aborted


def start_check(file, monkeypatch, result, hold=None):
    aborted = fake_checker(monkeypatch, result, hold)
    file.ask_ai_button.click()
    return aborted


def finish(panel):
    if panel._worker is not None:
        panel._worker.wait()
    QApplication.processEvents()
    assert not panel.running


def test_the_lint_status_lists_issues_and_skips_bibliographies(make_file, monkeypatch):
    from slidemage.ui.kit.widgets import PopoverMenu

    file = make_file()
    assert file.lint_chip.text() == "1 error" and file.lint_chip.property("tone") == "error"
    shown = []
    monkeypatch.setattr(PopoverMenu, "popup_below", lambda self, anchor, **kw: shown.append(self))
    file._show_issues()
    menu = shown[0]
    items = [e for e in menu._entries if e[0] == "item"]
    assert len(items) == 1 and items[0][3] == "line 2" and items[0][2] == "opening { is never closed"
    jumps = []
    file.editor.go_to_line = jumps.append
    menu.triggered.emit("0")
    assert jumps == [file.lint.issues[0].line]

    bib = make_file("@book{a, title={{A}}", name="SlideMage.bib")
    assert bib.lint is None and bib.lint_chip.parent().isHidden()


def test_debounced_lint_updates_the_top_bar_error_count(qapp, tmp_path):
    from conftest import command_context
    from slidemage.ui.workspace.state import WorkspaceState
    from slidemage.ui.workspace.topbar import TopBar
    from slidemage.ui.workspace.source_view import SourcePane

    path = tmp_path / "abc-EN-Demo-current.tex"
    path.write_text(BROKEN, encoding="utf-8")
    pane, state = SourcePane(FakeApp(EXAMPLE_PROJECT)), WorkspaceState(EXAMPLE_PROJECT)
    context = command_context()
    context.state = state
    bar = TopBar(context)
    counts = []
    pane.lint_errors_changed.connect(counts.append)
    pane.lint_errors_changed.connect(state.set_lint_errors)
    pane.show_path(path)
    badge = bar._modes._badges["source"]
    assert counts == [1] and badge.text() == "1" and not badge.isHidden()
    pane.current.editor.set_text("\\begin{standardframe}{Demo}\nText\n\\end{standardframe}\n")
    pane.current.editor.insertPlainText(" ")
    assert counts == [1] and pane.current._lint_timer.isActive()
    pane.current._lint_timer.timeout.emit()
    assert counts == [1, 0] and badge.isHidden()
    pane.show_path(None)
    assert counts == [1, 0]


def result_for(*issues):
    return SyntaxCheckResult(issues=list(issues), model="qwen3", elapsed_s=2)


def test_single_fix_is_undoable_and_discard_and_close_clear_rows(make_file, monkeypatch):
    file = make_file()
    start_check(file, monkeypatch, result_for(
        SyntaxIssue(2, "unclosed brace", "Text {unclosed", "Text {unclosed}"),
        SyntaxIssue(3, "no fix known", r"\end{standardframe}", "")))
    panel = file.fix_panel
    finish(panel)
    first, second = panel._rows
    assert second.apply_button.isHidden()
    first.apply_button.click()
    assert file.editor.text().splitlines()[1] == "Text {unclosed}"
    file.editor.undo()
    assert file.editor.text() == BROKEN
    assert file.app.started == ["checking syntax"] and file.app.ended == [True]
    second.discarded.emit(second.issue)
    assert panel._rows == [first]
    panel.close_button.click()
    assert panel.isHidden() and not panel._rows and not file.keep_open


def test_a_fix_is_only_offered_while_the_line_still_reads_as_the_model_quoted_it(make_file, monkeypatch):
    file = make_file()
    start_check(file, monkeypatch, result_for(SyntaxIssue(2, "unclosed brace", "Text {unclosed", "Text {unclosed}")))
    finish(file.fix_panel)
    row = file.fix_panel._rows[0]
    file.editor.replace_line(2, "Text edited by hand")
    row.update_state()
    assert not row.apply_button.isEnabled() and "changed since the check ran" in row.note.text()
    told = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: told.append(args[2]))
    assert not row.apply()
    assert told and file.editor.text().splitlines()[1] == "Text edited by hand"


def test_apply_all_works_from_the_last_line_up_and_skips_what_is_no_longer_safe(make_file, monkeypatch):
    file = make_file("a\nb\nc\nd\n")
    start_check(file, monkeypatch, result_for(
        SyntaxIssue(1, "p", "a", "a1\na2"),
        SyntaxIssue(3, "p", "c", "C"),
        SyntaxIssue(4, "p", "stale", "D")))
    finish(file.fix_panel)
    assert file.fix_panel.apply_all_button.isVisibleTo(file.fix_panel)
    assert file.fix_panel.apply_all() == 2
    assert file.editor.text() == "a1\na2\nb\nC\nd\n"
    assert not file.fix_panel.apply_all_button.isVisibleTo(file.fix_panel)


def test_no_issues_a_failure_and_checking_again(make_file, monkeypatch):
    file = make_file()
    panel = file.fix_panel
    start_check(file, monkeypatch, result_for())
    finish(panel)
    assert panel.status.text().startswith("No issues found by qwen3")
    fake_checker(monkeypatch, SyntaxCheckResult(model="qwen3", error="connection refused"))
    panel.check_button.click()
    finish(panel)
    assert panel.status.text() == "Check failed: connection refused" and panel._rows == []


@pytest.mark.parametrize("trigger", ["escape", "stop", "close"])
def test_active_check_can_be_aborted(make_file, monkeypatch, trigger):
    file = make_file()
    file.show()
    panel = file.fix_panel
    aborted = start_check(file, monkeypatch, result_for(), threading.Event())
    assert panel.running and panel.stop_button.isVisibleTo(panel) and not panel.check_button.isEnabled()
    if trigger == "escape":
        file.editor.setFocus()
        QTest.keyClick(file.editor, Qt.Key.Key_Escape)
        assert panel.status.text() == "Aborting…"
    elif trigger == "stop":
        panel.stop_button.click()
    else:
        panel.close_panel()
        assert panel.isHidden()
    finish(panel)
    assert aborted.is_set() and file.app.ended == [True]
    if trigger != "close":
        assert panel.status.text() == "Check aborted."


def test_another_model_task_running_or_a_declined_model_starts_no_check(make_file, monkeypatch):
    file = make_file()
    file.app.busy = True
    file.ask_ai_button.click()
    assert not file.fix_panel.running and not file.keep_open
    file.app.busy = False
    monkeypatch.setattr(ai_fix, "picked_route", lambda *a: None)     # no model, or consent declined
    file.fix_panel.run_check()
    assert not file.fix_panel.running and file.app.started == ["checking syntax"]


def test_a_frozen_version_cannot_be_fixed_until_unlocked(make_file, monkeypatch):
    file = make_file(name="abc-EN-Demo-v1-0-0.tex")
    assert not file.ask_ai_button.isEnabled()
    fake_checker(monkeypatch, result_for(SyntaxIssue(2, "p", "Text {unclosed", "x")))
    file.fix_panel.run_check()
    finish(file.fix_panel)
    assert not file.fix_panel._rows[0].apply_button.isEnabled()
    file.unlock()
    assert file.ask_ai_button.isEnabled()


def test_a_route_without_a_provider_refuses_the_check(make_file, monkeypatch, fake_routes):
    from slidemage.ui import ai_models

    file = make_file()
    fake_routes.cloud.provider = lambda ctx, route: None
    monkeypatch.setattr(ai_fix, "picked_route", ai_models.picked_route)
    monkeypatch.setattr(ai_fix, "built", ai_models.built)
    ai_profile.set_mode(file.app.project, ai_profile.CLOUD)
    ai_profile.mark_cloud_seen(file.app.project)
    told = []
    monkeypatch.setattr(QMessageBox, "critical", lambda _p, _t, text: told.append(text))
    file.ask_ai_button.click()
    panel = file.fix_panel
    assert not panel.running and file.app.started == []
    assert len(told) == 1 and "not available on Cloud · Fake cloud" in told[0] and "no other route or model" in told[0]
    assert panel.model_combo.currentData() in fake_routes.cloud.choices
