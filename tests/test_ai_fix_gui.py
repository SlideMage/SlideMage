# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The lint status line and "Ask AI to fix" of the Source view (the model is faked)."""
from __future__ import annotations

import threading

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from slidemage.ai.providers import OllamaProvider
from slidemage.syntax_check import SyntaxCheckResult, SyntaxIssue
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.workspace import ai_fix
from slidemage.ui.workspace.source_file import SourceFile
from conftest import EXAMPLE_PROJECT

BROKEN = "\\begin{standardframe}{Demo}\nText {unclosed\n\\end{standardframe}\n"


class FakeApp:
    def __init__(self, project=EXAMPLE_PROJECT):
        self.project = project
        self.theme = ThemeManager()
        self.busy = False
        self.started, self.ended = [], []

    def log(self, _line):
        pass

    def open_slide_editor(self, path, **_kwargs):
        pass

    def try_start_ollama_task(self, label, provider=None):
        self.started.append(label)
        return not self.busy

    def end_ollama_task(self, provider=None):
        self.ended.append(True)


class FakeProvider:
    label = "qwen3"


@pytest.fixture
def make_file(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(OllamaProvider, "list_models", lambda self, vision_only=False: ["qwen3"])
    monkeypatch.setattr(ai_fix, "provider_from_combo", lambda *a: FakeProvider())

    def make(text=BROKEN, name="abc-EN-Demo-current.tex"):
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return SourceFile(FakeApp(), path)

    return make


def fake_checker(monkeypatch, result, hold=None):
    """A SyntaxChecker that returns `result`, after `hold` (an Event abort() sets) if given."""
    aborted = threading.Event()

    class Checker:
        def __init__(self, provider):
            self.provider = provider

        def check(self, text):
            if hold is not None:
                hold.wait(5)
                if aborted.is_set():
                    return SyntaxCheckResult(model="qwen3", error="Aborted.", cancelled=True)
            return result

        def abort(self):
            aborted.set()
            if hold is not None:
                hold.set()

    monkeypatch.setattr(ai_fix.syntax_check, "SyntaxChecker", Checker)
    return aborted


def finish(panel):
    if panel._worker is not None:
        panel._worker.wait()
    QApplication.processEvents()
    assert not panel.running


# -- the lint status line ------------------------------------------------------------

def test_the_status_line_counts_errors_and_warnings_and_lists_them(make_file, monkeypatch):
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


def test_the_buffer_is_checked_a_moment_after_the_last_keystroke(make_file):
    file = make_file("\\begin{standardframe}{Demo}\nText\n\\end{standardframe}\n")
    assert file.lint_chip.text() == "No problems found" and file.lint.errors == []
    changes = []
    file.lint_changed.connect(lambda: changes.append(len(file.lint.errors)))
    file.editor.insertPlainText("{")
    file.editor.insertPlainText("{")
    assert changes == [] and file._lint_timer.isActive()
    file._lint_timer.timeout.emit()                  # the pause is over
    assert len(changes) == 1 and changes[0] >= 1 and file.lint_chip.property("tone") == "error"


def test_a_bib_is_not_checked(make_file, tmp_path, monkeypatch, ctx):

    bib = tmp_path / "Slidemaster.bib"
    bib.write_text("@book{a, title={{A}}\n", encoding="utf-8")
    file = SourceFile(FakeApp(ctx), bib)
    assert file.lint is None and file.lint_chip.parent().isHidden()


def test_the_pane_and_the_top_bar_show_the_error_count(qapp, tmp_path):
    from conftest import command_context
    from slidemage.ui.workspace.state import WorkspaceState
    from slidemage.ui.workspace.topbar import TopBar
    from slidemage.ui.workspace.source_view import SourcePane

    path = tmp_path / "abc-EN-Demo-current.tex"
    path.write_text(BROKEN, encoding="utf-8")
    pane, state = SourcePane(FakeApp()), WorkspaceState(EXAMPLE_PROJECT)
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
    pane.current.run_lint()
    assert counts == [1, 0] and badge.isHidden()
    pane.show_path(None)
    assert counts == [1, 0]


# -- Ask AI to fix ------------------------------------------------------------------------

def result_for(*issues):
    return SyntaxCheckResult(issues=list(issues), model="qwen3", elapsed_s=2)


def test_the_proposed_fixes_show_as_a_diff_and_apply_one_by_one_in_one_undo_step_each(make_file, monkeypatch):
    file = make_file()
    fake_checker(monkeypatch, result_for(
        SyntaxIssue(2, "unclosed brace", "Text {unclosed", "Text {unclosed}"),
        SyntaxIssue(3, "no fix known", "\\end{standardframe}", "")))
    panel = file.fix_panel
    file.ask_ai_button.click()
    assert panel.running and file.keep_open and not panel.isHidden()
    assert "Checking with qwen3" in panel.status.text()
    finish(panel)
    assert "2 possible issue(s) found by qwen3" in panel.status.text() and len(panel._rows) == 2
    first, second = panel._rows
    assert first.apply_button.isEnabled() and first.apply_button.isVisibleTo(panel)
    assert second.apply_button.isHidden() and second.note.text() == "No fix suggested."
    first.apply_button.click()
    assert file.editor.text().splitlines()[1] == "Text {unclosed}"
    assert first.apply_button.text() == "Applied"
    file.editor.undo()
    assert file.editor.text() == BROKEN
    assert file.app.started == ["checking syntax"] and file.app.ended == [True]


def test_a_fix_is_only_offered_while_the_line_still_reads_as_the_model_quoted_it(make_file, monkeypatch):
    file = make_file()
    fake_checker(monkeypatch, result_for(SyntaxIssue(2, "unclosed brace", "Text {unclosed", "Text {unclosed}")))
    file.ask_ai_button.click()
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
    fake_checker(monkeypatch, result_for(
        SyntaxIssue(1, "p", "a", "a1\na2"),             # adds a line: later fixes must not shift under it
        SyntaxIssue(3, "p", "c", "C"),
        SyntaxIssue(4, "p", "stale", "D")))             # the model misquoted line 4
    file.ask_ai_button.click()
    finish(file.fix_panel)
    assert file.fix_panel.apply_all_button.isVisibleTo(file.fix_panel)
    assert file.fix_panel.apply_all() == 2
    assert file.editor.text() == "a1\na2\nb\nC\nd\n"
    assert not file.fix_panel.apply_all_button.isVisibleTo(file.fix_panel)


def test_discarding_a_row_removes_it_and_closing_the_panel_clears_everything(make_file, monkeypatch):
    file = make_file()
    fake_checker(monkeypatch, result_for(SyntaxIssue(2, "p", "Text {unclosed", "x"), SyntaxIssue(3, "q", "", "")))
    file.ask_ai_button.click()
    finish(file.fix_panel)
    file.fix_panel._rows[0].discarded.emit(file.fix_panel._rows[0].issue)
    assert len(file.fix_panel._rows) == 1
    file.fix_panel.close_button.click()
    assert file.fix_panel.isHidden() and file.fix_panel._rows == [] and not file.keep_open


def test_no_issues_a_failure_and_checking_again(make_file, monkeypatch):
    file = make_file()
    panel = file.fix_panel
    fake_checker(monkeypatch, result_for())
    file.ask_ai_button.click()
    finish(panel)
    assert panel.status.text().startswith("No issues found by qwen3")
    fake_checker(monkeypatch, SyntaxCheckResult(model="qwen3", error="connection refused"))
    panel.check_button.click()
    finish(panel)
    assert panel.status.text() == "Check failed: connection refused" and panel._rows == []


def test_escape_in_the_editor_or_stop_aborts_a_running_check(make_file, monkeypatch):
    file = make_file()
    hold = threading.Event()
    fake_checker(monkeypatch, result_for(), hold)
    panel = file.fix_panel
    file.show()
    file.ask_ai_button.click()
    assert panel.running and panel.stop_button.isVisibleTo(panel) and not panel.check_button.isEnabled()
    file.editor.setFocus()
    QTest.keyClick(file.editor, Qt.Key.Key_Escape)
    assert panel.status.text() == "Aborting…"
    finish(panel)
    assert panel.status.text() == "Check aborted." and file.app.ended == [True]
    hold.clear()
    fake_checker(monkeypatch, result_for(), hold)
    panel.check_button.click()
    panel.stop_button.click()
    finish(panel)
    assert panel.status.text() == "Check aborted."


def test_closing_the_panel_mid_check_aborts_the_worker(make_file, monkeypatch):
    file = make_file()
    hold = threading.Event()
    aborted = fake_checker(monkeypatch, result_for(), hold)
    file.ask_ai_button.click()
    file.fix_panel.close_panel()
    assert aborted.is_set() and file.fix_panel.isHidden()
    finish(file.fix_panel)


def test_another_model_task_running_or_a_declined_model_starts_no_check(make_file, monkeypatch):
    file = make_file()
    fake_checker(monkeypatch, result_for())
    file.app.busy = True
    file.ask_ai_button.click()
    assert not file.fix_panel.running and not file.keep_open
    file.app.busy = False
    monkeypatch.setattr(ai_fix, "provider_from_combo", lambda *a: None)     # no model, or consent declined
    file.fix_panel.run_check()
    assert not file.fix_panel.running and file.app.started == ["checking syntax"]


def test_a_frozen_version_cannot_be_fixed_and_a_bib_has_no_check(make_file, monkeypatch, tmp_path):
    file = make_file(name="abc-EN-Demo-v1-0-0.tex")
    assert not file.ask_ai_button.isEnabled()
    fake_checker(monkeypatch, result_for(SyntaxIssue(2, "p", "Text {unclosed", "x")))
    file.fix_panel.run_check()
    finish(file.fix_panel)
    assert not file.fix_panel._rows[0].apply_button.isEnabled()
    file.unlock()
    assert file.ask_ai_button.isEnabled()


def test_the_panels_model_picker_follows_the_settings_defaults(make_file, monkeypatch):
    file = make_file()
    fake_checker(monkeypatch, result_for())
    file.refresh_model_preference(["ignored"])            # before the first check there is nothing to refresh
    assert file.fix_panel.model_combo.count() == 0
    file.ask_ai_button.click()
    finish(file.fix_panel)
    assert file.fix_panel.model_combo.currentText() == "qwen3"
    file.refresh_model_preference(["qwen3", "other"])
    assert [file.fix_panel.model_combo.itemText(i) for i in range(file.fix_panel.model_combo.count())] == [
        "qwen3", "other"]


def test_on_claude_code_the_check_is_refused_with_the_routes_name_and_sends_nothing(make_file, monkeypatch):
    from slidemage.ai import ai_profile
    from slidemage.ui import ai_models

    file = make_file()
    monkeypatch.setattr(ai_fix, "provider_from_combo", ai_models.provider_from_combo)
    ai_profile.set_mode(file.app.project, ai_profile.CLOUD)
    ai_profile.mark_cloud_seen(file.app.project)
    told = []
    monkeypatch.setattr(QMessageBox, "critical", lambda _p, _t, text: told.append(text))
    file.ask_ai_button.click()
    panel = file.fix_panel
    assert not panel.running and file.app.started == []
    assert len(told) == 1 and "not available on Cloud · Claude Code" in told[0] and "no other route or model" in told[0]
    assert [panel.model_combo.itemData(i) for i in range(panel.model_combo.count())] == ai_profile.model_choices(file.app.project, ai_profile.CLAUDE_CODE, ai_profile.FIXES)
