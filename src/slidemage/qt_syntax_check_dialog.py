""""Check syntax" results dialog (2026-08-31, direct instruction) -- shows
what syntax_check.OllamaSyntaxChecker found for one slide/deck editor
tab's own *current buffer* (unsaved edits included, same as "Render to
PDF"), with a per-issue "Apply fix" button wherever
syntax_check.SyntaxIssue.fix_is_safe() confirms the model's own claimed
"original" line still matches the live buffer exactly.

Applying a fix edits the source tab's own QPlainTextEdit directly (one
Undo step per fix, via the source tab's own document -- Ctrl+Z in the
editor undoes it same as any other edit), then marks that row applied and
disables its own button. Multiple fixes can be reviewed and applied one
at a time without closing this dialog; re-running the check (a fresh
"Check again") re-evaluates every row's own safety against whatever the
buffer looks like at that moment.

Non-modal by design (self.setModal(False), .show() not .exec()) -- unlike
DuplicateSlideDialog/AddSlideDialog, which each produce one atomic result
the caller waits on, a syntax check is meant to be reviewed *against* the
editor while still being able to click around in it (scroll to a
reported line, fix something by hand, then click "Check again").
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from . import alt_draft, app_settings, syntax_check
from .qt_theme import MUTED_LABEL, WARNING_LABEL


class _CheckWorker(QThread):
    """Runs one OllamaSyntaxChecker.check() off the GUI thread (2026-09-26,
    direct instruction: Escape aborts a running check -- impossible while
    the request blocked the GUI thread's own event loop)."""

    finished_with_result = Signal(object)

    def __init__(self, checker: syntax_check.OllamaSyntaxChecker, text: str) -> None:
        super().__init__()
        self.checker = checker
        self.text = text

    def run(self) -> None:
        self.finished_with_result.emit(self.checker.check(self.text))


class SyntaxCheckDialog(QDialog):
    def __init__(self, source_tab, filename: str) -> None:
        super().__init__(source_tab)
        self.app = source_tab.app
        self.source_tab = source_tab
        self.filename = filename
        self._worker: _CheckWorker | None = None
        self.setWindowTitle(f"Check syntax — {filename}")
        self.setModal(False)
        self.resize(720, 520)
        self._build()
        self._run_check()

    # -- widgets ------------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        # Preselects the default from Settings -> "AI models"; a different
        # pick here applies to this dialog only.
        self.refresh_model_preference()
        model_row.addWidget(self.model_combo)
        self.recheck_button = QPushButton("Check again")
        self.recheck_button.setToolTip(
            "Re-run against this editor's *current* buffer -- picks up any "
            "edits (including ones you just made by hand) since the last check."
        )
        self.recheck_button.clicked.connect(self._run_check)
        model_row.addWidget(self.recheck_button)
        model_row.addStretch(1)
        layout.addLayout(model_row)

        self.status_label = QLabel("")
        self.status_label.setObjectName(MUTED_LABEL)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.results_scroll = QScrollArea()
        self.results_scroll.setWidgetResizable(True)
        self.results_inner = QWidget()
        self.results_layout = QVBoxLayout(self.results_inner)
        self.results_layout.addStretch(1)
        self.results_scroll.setWidget(self.results_inner)
        layout.addWidget(self.results_scroll, stretch=1)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        close_row.addWidget(close_button)
        layout.addLayout(close_row)

    def refresh_model_preference(self, models: list[str] | None = None) -> None:
        """(Re)fill the model picker and preselect the default from
        Settings -> "AI models" -- on construction, and again from
        qt_gui.py after the Settings dialog closes, so a default changed
        there (or a model deleted) reaches this dialog while it's open."""
        if models is None:
            models = alt_draft.list_all_models()
        self.model_combo.clear()
        self.model_combo.addItems(models or ["(no Ollama models installed)"])
        self.model_combo.setEnabled(bool(models))
        default = app_settings.default_model("syntax_check")
        if default in models:
            self.model_combo.setCurrentText(default)

    def _clear_results(self) -> None:
        while self.results_layout.count() > 1:  # keep the trailing stretch
            item = self.results_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    # -- run ------------------------------------------------------------------

    def is_running(self) -> bool:
        return self._worker is not None

    def abort_check(self) -> bool:
        """Escape (dialog focused, or the editor -- see the source tab's
        own escape hook): stops a running check. Returns whether one was
        actually running, so the caller knows if the key press was used."""
        if self._worker is None:
            return False
        self.status_label.setText("Aborting…")
        self._worker.checker.abort()
        return True

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self.abort_check():
            event.accept()
            return
        super().keyPressEvent(event)

    def done(self, result: int) -> None:
        # Closing the dialog mid-check aborts it too -- the worker thread
        # must not outlive the dialog it reports to.
        if self._worker is not None:
            self._worker.checker.abort()
            self._worker.wait(5000)
        super().done(result)

    def _run_check(self) -> None:
        if self._worker is not None:
            return
        model = self.model_combo.currentText()
        if not model or model.startswith("("):
            QMessageBox.critical(self, "Check syntax", "No Ollama models are installed.")
            return
        if not self.app.try_start_ollama_task("checking syntax"):
            return

        self._clear_results()
        self.status_label.setText(f"Checking with {model}… (press Esc to abort)")
        self.recheck_button.setEnabled(False)
        checker = syntax_check.OllamaSyntaxChecker(
            model=model, host=app_settings.get_ollama_host())
        worker = _CheckWorker(checker, self.source_tab.widget.toPlainText())
        worker.finished_with_result.connect(self._on_check_finished)
        self._worker = worker
        worker.start()

    def _on_check_finished(self, result: syntax_check.SyntaxCheckResult) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.wait()
        self.recheck_button.setEnabled(True)
        self.app.end_ollama_task()

        if result.cancelled:
            self.status_label.setText("Check aborted.")
            return
        if not result.ok:
            self.status_label.setText(f"Check failed: {result.error}")
            return

        disclaimer = (
            "Heuristic check via a local language model, not a real LaTeX "
            "compile -- it can miss real problems and flag things that are "
            "actually fine. Review every item yourself."
        )
        if not result.issues:
            self.status_label.setText(
                f"No issues found by {result.model} ({result.elapsed_s:.0f}s). {disclaimer}"
            )
            return
        self.status_label.setText(
            f"{len(result.issues)} possible issue(s) found by {result.model} "
            f"({result.elapsed_s:.0f}s). {disclaimer}"
        )
        for issue in result.issues:
            self.results_layout.insertWidget(
                self.results_layout.count() - 1, self._build_issue_row(issue))

    # -- issue rows ------------------------------------------------------------

    def _build_issue_row(self, issue: syntax_check.SyntaxIssue) -> QWidget:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        row_layout = QVBoxLayout(frame)

        header = QLabel(f"<b>Line {issue.line}:</b> {issue.problem}")
        header.setWordWrap(True)
        header.setTextFormat(Qt.TextFormat.RichText)
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        header.setToolTip("Click to jump the editor to this line.")
        header.mousePressEvent = (  # noqa: E731
            lambda event, ln=issue.line: self._jump_to_line(ln)
        )
        row_layout.addWidget(header)

        if issue.original:
            original_label = QLabel(f"Current:  {issue.original}")
            original_label.setObjectName(MUTED_LABEL)
            original_label.setWordWrap(True)
            row_layout.addWidget(original_label)

        if issue.suggested_fix:
            fix_label = QLabel(f"Suggested:  {issue.suggested_fix}")
            fix_label.setWordWrap(True)
            row_layout.addWidget(fix_label)

            buffer_lines = self.source_tab.widget.toPlainText().split("\n")
            safe = issue.fix_is_safe(buffer_lines)

            button_row = QHBoxLayout()
            button_row.addStretch(1)
            apply_button = QPushButton("Apply fix")
            apply_button.setEnabled(safe)
            if not safe:
                unsafe_label = QLabel(
                    "(line has changed since this check ran -- re-check to apply)")
                unsafe_label.setObjectName(WARNING_LABEL)
                button_row.addWidget(unsafe_label)
            apply_button.clicked.connect(
                lambda checked=False, i=issue, b=apply_button: self._apply_fix(i, b)
            )
            button_row.addWidget(apply_button)
            row_layout.addLayout(button_row)

        return frame

    def _jump_to_line(self, line: int) -> None:
        document = self.source_tab.widget.document()
        block = document.findBlockByNumber(line - 1)
        if not block.isValid():
            return
        cursor = QTextCursor(block)
        self.source_tab.widget.setTextCursor(cursor)
        self.source_tab.widget.centerCursor()
        self.source_tab.widget.setFocus()

    def _apply_fix(self, issue: syntax_check.SyntaxIssue, button: QPushButton) -> None:
        buffer_lines = self.source_tab.widget.toPlainText().split("\n")
        if not issue.fix_is_safe(buffer_lines):
            QMessageBox.warning(
                self, "Apply fix",
                "This line has changed since the check ran -- refusing to "
                "apply a fix against content that's no longer there. Click "
                "\"Check again\" instead.",
            )
            button.setEnabled(False)
            return

        document = self.source_tab.widget.document()
        block = document.findBlockByNumber(issue.line - 1)
        cursor = QTextCursor(block)
        # StartOfBlock/EndOfBlock, not the LineUnderCursor selection type --
        # LineUnderCursor selects only the current *visual* line, which a
        # long slide line word-wrapped across several on-screen rows would
        # truncate; a block is always exactly one logical line regardless
        # of how it wraps on screen.
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        cursor.beginEditBlock()
        cursor.insertText(issue.suggested_fix)
        cursor.endEditBlock()

        button.setEnabled(False)
        button.setText("Applied")
        self.app.log(f"Applied syntax fix on line {issue.line} of {self.filename}")
