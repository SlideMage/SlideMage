""""Ask AI to fix": a syntax check by a language model, shown inline above the
editor of the file it checks (docs/UI_REDESIGN_PLAN.md, step 5; it replaces the
old "Check syntax" dialog).

The model reads the file's *current buffer*, unsaved edits included, and
reports possible LaTeX syntax problems, each with the line's text as it saw
it and, where it is confident, a corrected line. A fix is only ever offered
when `SyntaxIssue.fix_is_safe()` confirms that the line still reads exactly
as the model quoted it, so a misremembered or shifted line is never
overwritten (see syntax_check.py). Applying edits the editor (one undo step
per fix); everything stays reviewable against the editor, which is never
locked. The check runs on a worker thread; Esc or Stop ends it. The model
comes from Settings -> "AI models" (local or cloud; the first cloud request in
a project asks for consent, qt_ai_models.provider_from_combo), and the
answering model is named in the panel.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
)

from ... import syntax_check
from ...ai.providers import OllamaProvider
from ...qt_ai_models import fill_model_combo, provider_from_combo
from .. import background
from ..kit import kit_qss as q
from ..kit.widgets import Button, Surface
from .source_editor import SourceEditor

MAX_ROWS_HEIGHT = 230
DISCLAIMER = ("Heuristic check via a language model, not a real LaTeX compile: it can miss real "
              "problems and flag things that are fine. Review every item yourself.")


class _CheckWorker(QThread):
    """One SyntaxChecker.check() off the GUI thread, so that Esc can abort it."""

    finished_with_result = Signal(object)

    def __init__(self, checker: syntax_check.SyntaxChecker, text: str) -> None:
        super().__init__()
        self.checker = checker
        self.text = text

    def run(self) -> None:
        self.finished_with_result.emit(self.checker.check(self.text))


class _IssueRow(Surface):
    """One possible issue: its line (click to go there), the model's problem
    statement, and the line as it is and as the model would write it."""

    applied = Signal(object)    # the SyntaxIssue
    discarded = Signal(object)

    def __init__(self, issue: syntax_check.SyntaxIssue, editor: SourceEditor) -> None:
        super().__init__()
        self.issue = issue
        self._editor = editor
        self._done = False
        self.setObjectName(q.AI_ROW)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)
        header = QLabel(f"<b>Line {issue.line}:</b> {issue.problem}")
        header.setTextFormat(Qt.TextFormat.RichText)
        header.setWordWrap(True)
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        header.setToolTip("Click to jump the editor to this line.")
        header.mousePressEvent = lambda _event: editor.go_to_line(issue.line)  # noqa: E731
        layout.addWidget(header)
        if issue.original:
            self._add_diff(layout, "− ", issue.original, q.DIFF_OLD)
        if issue.suggested_fix:
            self._add_diff(layout, "+ ", issue.suggested_fix, q.DIFF_NEW)
        buttons = QHBoxLayout()
        self.note = QLabel("")
        self.note.setObjectName(q.SOURCE_NOTE)
        buttons.addWidget(self.note, 1)
        self.apply_button = Button("Apply", "primary", compact=True)
        self.apply_button.clicked.connect(self.apply)
        self.apply_button.setVisible(bool(issue.suggested_fix))
        discard = Button("Discard", "ghost", compact=True)
        discard.clicked.connect(lambda: self.discarded.emit(issue))
        buttons.addWidget(discard)
        buttons.addWidget(self.apply_button)
        layout.addLayout(buttons)
        self.update_state()

    @staticmethod
    def _add_diff(layout: QVBoxLayout, sign: str, line: str, name: str) -> None:
        label = QLabel(sign + line)
        label.setObjectName(name)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(label)

    @property
    def is_safe(self) -> bool:
        """The fix may be applied now: there is one, it is not applied yet, and the
        line still reads as the model quoted it."""
        return (not self._done and not self._editor.is_read_only()
                and self.issue.fix_is_safe(self._editor.text().split("\n")))

    def update_state(self) -> None:
        """Re-judge the fix against the buffer as it is now (the user may have edited, or
        another fix moved the lines)."""
        if self._done:
            return
        safe = self.is_safe
        self.apply_button.setEnabled(safe)
        if self.issue.suggested_fix and not safe:
            self.note.setText("The line has changed since the check ran: check again to apply.")
        else:
            self.note.setText("" if self.issue.suggested_fix else "No fix suggested.")

    def apply(self) -> bool:
        if not self.is_safe:
            QMessageBox.warning(
                self, "Apply fix",
                "This line has changed since the check ran: refusing to apply a fix against "
                "content that is no longer there. Check again instead.")
            self.update_state()
            return False
        self._editor.replace_line(self.issue.line, self.issue.suggested_fix)
        self._done = True
        self.apply_button.setEnabled(False)
        self.apply_button.setText("Applied")
        self.note.setText("")
        self.applied.emit(self.issue)
        return True


class AiFixPanel(Surface):
    running_changed = Signal(bool)

    def __init__(self, app, editor: SourceEditor, filename: str) -> None:
        super().__init__()
        self.app = app
        self.editor = editor
        self.filename = filename
        self._worker: Optional[_CheckWorker] = None
        self._provider = None   # the running check's, whose Ollama slot it holds
        self._rows: list[_IssueRow] = []
        self._models_loaded = False
        self.setObjectName(q.AI_PANEL)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(6)
        head = QHBoxLayout()
        self.status = QLabel("")
        self.status.setObjectName(q.SOURCE_NOTE)
        self.status.setWordWrap(True)
        head.addWidget(self.status, 1)
        self.model_combo = QComboBox()
        self.model_combo.setToolTip("The model for this check (the default is set in Settings, AI models).")
        head.addWidget(self.model_combo)
        self.check_button = Button("Check again", "secondary", compact=True)
        self.check_button.setToolTip("Check the editor's current buffer again, edits made since included.")
        self.check_button.clicked.connect(self.run_check)
        head.addWidget(self.check_button)
        self.apply_all_button = Button("Apply all", "primary", compact=True)
        self.apply_all_button.clicked.connect(self.apply_all)
        head.addWidget(self.apply_all_button)
        self.stop_button = Button("Stop", "secondary", compact=True)
        self.stop_button.setToolTip("Abort the check (Esc).")
        self.stop_button.clicked.connect(self.abort)
        head.addWidget(self.stop_button)
        self.close_button = Button("Close", "ghost", compact=True)
        self.close_button.clicked.connect(self.close_panel)
        head.addWidget(self.close_button)
        layout.addLayout(head)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        layout.addWidget(self.progress)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setMaximumHeight(MAX_ROWS_HEIGHT)
        self.scroll.setObjectName(q.SURFACE)
        self.scroll.viewport().setObjectName(q.SURFACE)
        self._rows_holder = Surface()
        self._rows_layout = QVBoxLayout(self._rows_holder)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(6)
        self._rows_layout.addStretch(1)
        self.scroll.setWidget(self._rows_holder)
        layout.addWidget(self.scroll)
        self._show_state()
        self.hide()

    @property
    def running(self) -> bool:
        return self._worker is not None

    def refresh_model_preference(self, models: Optional[list[str]] = None) -> None:
        """(Re)fill the model picker and preselect the default from Settings -> "AI
        models": on the first check, and again from the main window when the Settings
        dialog closes, so a default changed there reaches an open panel (before the first
        check there is nothing to refresh)."""
        if models is None:
            models = OllamaProvider().list_models()
        elif not self._models_loaded:
            return
        fill_model_combo(self.model_combo, "syntax_check", models, "(no AI models available)")
        self._models_loaded = True

    # -- running -------------------------------------------------------------------

    def run_check(self) -> None:
        """Show the panel and check the editor's current buffer."""
        self.show()
        if self._worker is not None:
            return
        if not self._models_loaded:
            self.refresh_model_preference()
        provider = provider_from_combo(self, self.model_combo, "this file's full LaTeX source")
        if provider is None or not self.app.try_start_ollama_task("checking syntax", provider):
            self._show_state()
            return
        self._provider = provider   # whose Ollama slot stop() and _on_finished() give back
        self._clear_rows()
        self.status.setText(f"Checking with {provider.label}… (Esc to abort)")
        worker = _CheckWorker(syntax_check.SyntaxChecker(provider), self.editor.text())
        worker.finished_with_result.connect(lambda result, w=worker: self._on_finished(w, result))
        self._worker = worker
        self.running_changed.emit(True)
        self._show_state()
        worker.start()

    def abort(self) -> bool:
        """Stop a running check; whether one was running (so Esc knows if it was used)."""
        if self._worker is None:
            return False
        self.status.setText("Aborting…")
        self._worker.checker.abort()
        return True

    def stop(self) -> None:
        """Abort a running check (closing the panel, the window or the project); its worker thread
        is kept until it has ended."""
        worker, self._worker = self._worker, None
        if worker is None:
            return
        provider = self._provider      # its Ollama slot is given back once the worker is really over
        background.stop_worker(worker, worker.checker.abort, on_done=lambda: self.app.end_ollama_task(provider))
        self.running_changed.emit(False)
        self._show_state()

    def close_panel(self) -> None:
        self.stop()
        self._clear_rows()
        self.hide()

    def _on_finished(self, worker: _CheckWorker, result: syntax_check.SyntaxCheckResult) -> None:
        if worker is not self._worker:      # stopped meanwhile: nobody waits for this result
            return
        self._worker = None
        worker.wait()
        worker.deleteLater()
        self.app.end_ollama_task(self._provider)
        self.running_changed.emit(False)
        if result.cancelled:
            self.status.setText("Check aborted.")
        elif not result.ok:
            self.status.setText(f"Check failed: {result.error}")
        elif not result.issues:
            self.status.setText(f"No issues found by {result.model} ({result.elapsed_s:.0f}s). {DISCLAIMER}")
        else:
            self.status.setText(f"{len(result.issues)} possible issue(s) found by {result.model} "
                                f"({result.elapsed_s:.0f}s). {DISCLAIMER}")
            for issue in result.issues:
                row = _IssueRow(issue, self.editor)
                row.applied.connect(self._on_applied)
                row.discarded.connect(self._on_discarded)
                self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)
                self._rows.append(row)
        self._show_state()

    # -- the issue rows --------------------------------------------------------------

    def _clear_rows(self) -> None:
        for row in self._rows:
            row.deleteLater()
        self._rows.clear()

    def _on_applied(self, _issue) -> None:
        self.app.log(f"Applied syntax fix on line {_issue.line} of {self.filename}")
        for row in self._rows:
            row.update_state()
        self._show_state()

    def _on_discarded(self, issue) -> None:
        row = next(r for r in self._rows if r.issue is issue)
        self._rows.remove(row)
        row.deleteLater()
        self._show_state()

    def apply_all(self) -> int:
        """Apply every fix that is safe, last line first so that a fix that adds or removes
        lines cannot move one still to come; returns how many."""
        count = 0
        for row in sorted(self._rows, key=lambda r: r.issue.line, reverse=True):
            if row.is_safe and row.apply():
                count += 1
        return count

    def _show_state(self) -> None:
        running = self._worker is not None
        self.progress.setVisible(running)
        self.stop_button.setVisible(running)
        self.check_button.setEnabled(not running)
        self.model_combo.setEnabled(not running and bool(self.model_combo.currentData()))
        self.apply_all_button.setVisible(any(r.is_safe for r in self._rows))
        self.scroll.setVisible(bool(self._rows))
