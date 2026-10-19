# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the window shows of the compile slot (compile_controller.py): the run's job panel
(job_panel.py), the Log drawer (log_drawer.py) and a toast that answers a single job's end.

Nothing here decides anything about a build; the controller says what changed and the clicks on
the panel and the drawer are handed back to it (or to the flows of compile_actions.py).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QWidget

from ... import open_path
from ...compile_status import DONE, FAILED, JobRow, RunStatus
from ..kit.widgets import Toast
from . import compile_actions
from .job_panel import JobPanel
from .log_drawer import LogDrawer


class CompileDisplay(QObject):
    """Built on the window's central widget; the Log drawer covers the bottom of `window.stack`."""

    def __init__(self, window, central: QWidget) -> None:
        super().__init__(window)
        self.window = window
        controller = self.controller = window.compile
        self.panel = JobPanel(central)
        self.drawer = LogDrawer(central, window.stack)
        self.toast = Toast(central)

        controller.log.connect(self.drawer.append)
        controller.started.connect(self._on_started)
        controller.ended.connect(window.topbar.refresh_compile_menu)
        controller.changed.connect(self._refresh)
        controller.settled.connect(self._report_end)
        controller.pdf_ready.connect(self._auto_open)
        self.panel.stop_all.connect(lambda: compile_actions.ask_to_stop(window))
        self.panel.stop_job.connect(controller.stop_job)
        self.panel.retry_failed.connect(lambda: compile_actions.compile_jobs(window, controller.failed_jobs()))
        self.panel.open_pdfs.connect(lambda: [self.open_pdf(pdf) for pdf in controller.pdfs()])
        self.panel.show_source.connect(lambda name: self.show_error(controller.row(name)))
        self.panel.open_log.connect(self.drawer.open)
        self.drawer.error_clicked.connect(lambda: self.show_error(controller.run.failed[0]))
        self.toast.action_triggered.connect(self._on_toast_action)

    def _on_started(self, run: RunStatus) -> None:
        self.toast.hide()
        self.drawer.set_status("running")
        self.panel.start(run, per_job_stop=bool(self.controller.jobs), can_retry=bool(self.controller.jobs))
        self.window.topbar.refresh_compile_menu()
        self._refresh()

    def _refresh(self) -> None:
        progress = self.controller.progress
        self.panel.refresh(progress.fraction, progress.text, over=self.controller.over)

    def _report_end(self, run: RunStatus) -> None:
        """A single job is answered by a toast, a longer run stays on show in the panel. A
        failure opens the Log drawer."""
        failed = run.failed
        if failed:
            first = failed[0]
            self.drawer.set_status(f"{first.label} failed", f"Show {first.error.where}" if first.error else "")
            self.drawer.open()
            self.panel.raise_()   # the card stays on top of the drawer
        else:
            self.drawer.set_status("last run ok")
        if len(run.rows) > 1:
            return
        self.panel.hide()
        row = next(iter(run.rows.values()))
        if row.state == FAILED:
            text = f"Compile failed in {row.error.slide_id or row.error.path.name}" if row.error \
                else f"{row.label} failed"
            actions = [("source", "Open in Source")] if row.error else []
            self.toast.show_message(text, actions + [("log", "Log")], error=True)
        elif row.state == DONE:
            actions = [("pdf", "Open PDF")] if row.pdf is not None else []
            self.toast.show_message(f"{row.label} ready", actions + [("log", "Log")])

    def _on_toast_action(self, key: str) -> None:
        run = self.controller.run
        row = next(iter(run.rows.values()), None) if run is not None else None
        if key == "log":
            self.drawer.open()
        elif key == "source" and row is not None:
            self.show_error(row)
        elif key == "pdf" and row is not None and row.pdf is not None:
            self.open_pdf(row.pdf)

    def _auto_open(self, pdf: Path) -> None:
        if self.window.build_options.auto_open_checkbox.isChecked():
            self.open_pdf(pdf)

    def show_error(self, row: JobRow) -> None:
        """Open the file a failed job stopped in, on the line of the error."""
        error = row.error
        if error is None:
            return
        if not error.path.is_file():
            self.window.log(f"*** couldn't open {error.path}: the file is gone ***")
            return
        self.window.open_slide_editor(error.path, line=error.line)

    def open_pdf(self, pdf: Path) -> None:
        if not pdf.exists():
            return
        try:
            open_path.open_in_default_app(pdf)
        except OSError as exc:
            self.window.log(f"*** couldn't auto-open {pdf.name}: {exc} ***")
