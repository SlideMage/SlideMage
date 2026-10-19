# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI half of the pre-render syntax check (latex_lint.py): every path that
starts a PDF render calls `confirm_render()` first.

* nothing found            -> renders straight away (one log line)
* warnings only            -> logged, renders straight away
* at least one error       -> a dialog lists everything found; "<Verb> anyway"
                              continues, "Cancel" (the default button, so Enter
                              is safe) or a row's "Show in editor" does not.

The check runs on the GUI thread on purpose: it takes milliseconds (see
latex_lint.py's docstring), so it needs no worker thread and the dialog can
be shown before anything is started.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from ... import latex_lint
from ...latex_lint import CheckResult, LintIssue
from ..kit import kit_qss as q
from ..kit.widgets import Button, IconLabel, ModalSheet
from ..text import plural


class RenderCheckSheet(ModalSheet):
    def __init__(self, parent, result: CheckResult, what: str, verb: str = "Render",
                 show_in_editor: Optional[Callable[[LintIssue], None]] = None) -> None:
        errors = len(result.errors)
        super().__init__(f"{plural(errors, 'error')} found", parent, width=720)
        self._show_in_editor = show_in_editor
        self.proceed = False
        issues = sorted(result.issues, key=lambda i: (i.severity != latex_lint.ERROR, i.source, i.line))

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._text(
            f"In {what}. {verb}ing will most likely fail or look wrong.", ""))
        box = QFrame()
        box.setObjectName(q.LIST_BOX)
        rows = QVBoxLayout(box)
        rows.setContentsMargins(4, 4, 4, 4)
        rows.setSpacing(0)
        for issue in issues:
            rows.addWidget(self._row(issue))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMaximumHeight(300)
        scroll.setWidget(box)
        layout.addWidget(scroll)
        layout.addWidget(self._text(result.summary() + " -- a quick static check, not a real compile.", q.PANEL_CAPTION))
        self.add_tab("", body)
        cancel = self.add_button("Cancel", role="reject")
        cancel.setDefault(True)
        anyway = self.add_button(f"{verb} anyway", kind="primary")
        anyway.setAutoDefault(False)
        anyway.clicked.connect(self._on_anyway)

    @staticmethod
    def _text(text: str, name: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName(name)
        label.setWordWrap(True)
        return label

    def _row(self, issue: LintIssue) -> QWidget:
        is_error = issue.severity == latex_lint.ERROR
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 6, 8, 6)
        icon = IconLabel("error" if is_error else "warning", 18)
        icon.set_tone("error" if is_error else "muted")
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        where = QLabel(f"{issue.source}:{issue.line}")
        where.setObjectName(q.PANEL_MONO)
        layout.addWidget(where, 0, Qt.AlignmentFlag.AlignTop)
        text = self._text(f"{issue.message}  ({issue.code})", "")
        text.setToolTip(issue.message)
        layout.addWidget(text, 1)
        button = Button("Show in editor", "secondary", compact=True)
        button.setAutoDefault(False)
        button.setEnabled(self._show_in_editor is not None and issue.path is not None)
        button.clicked.connect(lambda _c=False, i=issue: self._on_show(i))
        layout.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
        return row

    def _on_show(self, issue: LintIssue) -> None:
        self._show_in_editor(issue)
        self.reject()

    def _on_anyway(self) -> None:
        self.proceed = True
        self.accept()


def confirm_render(parent, app, result: CheckResult, what: str,
                   show_in_editor: Optional[Callable[[LintIssue], None]] = None, verb: str = "Render") -> bool:
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
    sheet = RenderCheckSheet(modal or parent, result, what, verb, show_in_editor)
    sheet.exec()
    return sheet.proceed


def open_issue_in_editor(app, issue: LintIssue) -> None:
    """Open the file an issue was found in (slide, deck or fragment) and put
    the cursor on its line."""
    if issue.path is not None:
        app.open_slide_editor(issue.path, line=issue.line)
