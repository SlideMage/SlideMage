"""The status line of the assistant card's tasks (workspace v6 handoff, step 3; step 4 turns it into the task card):
what the TaskRunner (terminal/tasks.py) says while a task or batch runs and when it has ended, with Stop while it
runs and "Show result" for a result a conflict did not apply, a batch's report or the summary of a deck.
"""
from __future__ import annotations

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit

from ..kit.widgets import Button, ModalSheet, Surface, caption, set_property
from .terminal.tasks import TaskRunner


class TaskRow(Surface):
    def __init__(self, app, tasks: TaskRunner) -> None:
        super().__init__()
        self.app = app
        self.tasks = tasks
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.status = caption("")
        layout.addWidget(self.status, 1)
        self.result_button = Button("Show result", "ghost", compact=True)
        self.result_button.clicked.connect(self._show_result)
        self.result_button.hide()
        layout.addWidget(self.result_button)
        self.stop_button = Button("Stop", "secondary", compact=True)
        self.stop_button.clicked.connect(tasks.stop)
        self.stop_button.hide()
        layout.addWidget(self.stop_button)
        tasks.status.connect(self.set_status)
        tasks.busy_changed.connect(self._on_busy)
        tasks.summary.connect(lambda text: self._show_text("Summary of the deck", text))
        self.hide()

    def set_status(self, text: str, tone: str) -> None:
        self.status.setText(text)
        set_property(self.status, "tone", tone)
        self.result_button.setVisible(bool(self.tasks.unapplied or self.tasks.report))
        self.setVisible(bool(text))

    def reveal(self) -> None:
        """Bring the running task's line to the user: the focus goes to its Stop button."""
        if self.stop_button.isVisibleTo(self):
            self.stop_button.setFocus()

    def _on_busy(self, busy: bool) -> None:
        self.stop_button.setVisible(busy)
        self.result_button.hide()

    def _show_result(self) -> None:
        tasks = self.tasks
        self._show_text(*(("Claude's result", tasks.unapplied) if tasks.unapplied
                          else ("What became of each slide", tasks.report)))

    def _show_text(self, title: str, content: str) -> None:
        sheet = ModalSheet(title, self.app, width=640)
        text = QPlainTextEdit(content)
        text.setReadOnly(True)
        sheet.add_tab(title, text)
        sheet.add_button("Copy").clicked.connect(lambda: QGuiApplication.clipboard().setText(text.toPlainText()))
        sheet.add_button("Close", kind="primary", role="accept")
        sheet.exec()
