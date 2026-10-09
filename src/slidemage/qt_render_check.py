"""GUI half of the pre-render syntax check (latex_lint.py): every path that
starts a PDF render calls `confirm_render()` first.

* nothing found            -> renders straight away (one log line)
* warnings only            -> logged, renders straight away
* at least one error       -> a dialog lists everything found; "Render anyway"
                              continues, "Cancel" (the default button, so Enter
                              is safe) or "Show in editor" does not render.

The check runs on the GUI thread on purpose: it takes milliseconds (see
latex_lint.py's docstring), so it needs no worker thread and the dialog can
be shown before anything is started.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from . import latex_lint
from .latex_lint import CheckResult, LintIssue
from .ui.kit.theme import MUTED_LABEL


class RenderCheckDialog(QDialog):
    def __init__(self, parent, result: CheckResult, what: str,
                 show_in_editor: Optional[Callable[[LintIssue], None]] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Syntax check before rendering")
        self.resize(820, 420)
        self._show_in_editor = show_in_editor
        self.render_anyway = False
        self._issues = sorted(result.issues, key=lambda i: (i.severity != latex_lint.ERROR, i.source, i.line))

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"<b>{len(result.errors)} error(s)</b> and {len(result.warnings)} warning(s) found in "
            f"{what}. Rendering will most likely fail or look wrong."))
        summary = QLabel(result.summary() + " -- a quick static check, not a real compile.")
        summary.setObjectName(MUTED_LABEL)
        layout.addWidget(summary)

        self.table = QTableWidget(len(self._issues), 4)
        self.table.setHorizontalHeaderLabels(["", "Where", "Check", "Problem"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        for row, issue in enumerate(self._issues):
            is_error = issue.severity == latex_lint.ERROR
            cells = ["✖" if is_error else "⚠", f"{issue.source}:{issue.line}", issue.code, issue.message]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(issue.message)
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setWordWrap(True)
        self.table.cellDoubleClicked.connect(lambda row, _c: self._on_show(row))
        layout.addWidget(self.table, stretch=1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.show_button = QPushButton("Show in editor")
        self.show_button.setToolTip("Open the selected problem in its editor tab and do not render (double-click a row does the same).")
        self.show_button.setEnabled(show_in_editor is not None)
        self.show_button.clicked.connect(lambda: self._on_show(self.table.currentRow()))
        buttons.addWidget(self.show_button)
        anyway = QPushButton("Render anyway")
        anyway.setAutoDefault(False)
        anyway.clicked.connect(self._on_anyway)
        buttons.addWidget(anyway)
        cancel = QPushButton("Cancel")
        cancel.setDefault(True)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        if self._issues:
            self.table.selectRow(0)

    def _on_show(self, row: int) -> None:
        if self._show_in_editor is None:
            return
        if row < 0 and self._issues:
            row = 0
        if 0 <= row < len(self._issues):
            self._show_in_editor(self._issues[row])
            self.reject()

    def _on_anyway(self) -> None:
        self.render_anyway = True
        self.accept()


def confirm_render(parent, app, result: CheckResult, what: str,
                   show_in_editor: Optional[Callable[[LintIssue], None]] = None) -> bool:
    """True when the render may go ahead (see the module docstring)."""
    app.log(f"Pre-render syntax check ({what}): {result.summary()}")
    for issue in result.warnings:
        app.log("    " + latex_lint.format_issue(issue))
    if not result.errors:
        return True
    for issue in result.errors:
        app.log("    " + latex_lint.format_issue(issue))
    # Parent: whichever modal window is on top (e.g. a Preview popup), else
    # the caller's widget -- a dialog parented behind a modal one is unusable.
    modal = QApplication.activeModalWidget()
    dialog = RenderCheckDialog(modal or parent, result, what, show_in_editor)
    dialog.exec()
    return dialog.render_anyway


def open_issue_in_editor(app, issue: LintIssue, return_to=None) -> None:
    """Open the file an issue was found in (slide, deck or fragment) and put
    the cursor on its line."""
    if issue.path is None:
        return
    app.open_slide_editor(issue.path, return_to=return_to)
    tab = app._slide_source_tabs.get(issue.path)
    if tab is not None:
        tab.jump_to_line(issue.line)
