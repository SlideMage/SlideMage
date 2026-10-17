"""The compile job panel (prototype v3): a card at the bottom of the window with
the run's progress, one row per job (state, what it is doing, Stop) and, once
the run is over, what became of it with Log, Retry failed and Open PDF.

It only shows what compile_status.RunStatus and compile_progress.BatchProgress
tell it and reports the user's clicks as signals; compile_jobs.py acts on them.
A run of a single job shows no rows; the window answers its end with a toast.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEvent, QObject, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from ...compile_status import DONE, FAILED, MOVING, QUEUED, RUNNING, STOPPED, JobRow, RunStatus
from ..kit import kit_qss as q
from ..kit.widgets import Button, IconButton, IconLabel, apply_shadow, set_property

WIDTH = 460
# state -> (icon, icon tone)
STATE_ICONS = {
    QUEUED: ("schedule", "muted"), RUNNING: ("autorenew", ""), MOVING: ("drive_file_move", ""),
    DONE: ("check_circle", "ok"), FAILED: ("error", "error"), STOPPED: ("block", "muted"),
}


def row_detail(row: JobRow, progress: str) -> str:
    """What a row says about its job; `progress` is the running job's "pass 2/4, slide 7/40"."""
    if row.state == QUEUED:
        return "waiting"
    if row.state == RUNNING:
        return progress or "starting"
    if row.state == MOVING:
        return "moving the PDF into place"
    if row.state == FAILED:
        return f"failed · {row.error.where}" if row.error else "failed · see the log"
    if row.state == STOPPED:
        return "stopped" if row.started else "skipped"
    return "done"


class _RowWidget(QWidget):
    stop_clicked = Signal(str)
    source_clicked = Signal(str)

    def __init__(self, row: JobRow) -> None:
        super().__init__()
        self._jobname = row.jobname
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 4, 4)
        layout.setSpacing(10)
        self.icon = IconLabel("schedule", 18)
        layout.addWidget(self.icon)
        self.name = QLabel(row.label)
        self.name.setToolTip(row.label)
        layout.addWidget(self.name, 1)
        self.detail = QLabel("")
        self.detail.setObjectName(q.PANEL_CAPTION)
        layout.addWidget(self.detail)
        self.stop = IconButton("close", "Stop this job", size=14)
        self.stop.clicked.connect(lambda: self.stop_clicked.emit(self._jobname))
        layout.addWidget(self.stop)
        self.source = IconButton("code", "Open in Source", size=14)
        self.source.clicked.connect(lambda: self.source_clicked.emit(self._jobname))
        layout.addWidget(self.source)

    def update_row(self, row: JobRow, progress: str, can_stop: bool) -> None:
        icon, tone = STATE_ICONS[row.state]
        self.icon.set_icon(icon)
        self.icon.set_tone(tone)
        self.detail.setText(row_detail(row, progress))
        set_property(self.detail, "tone", "error" if row.state == FAILED else "")
        self.stop.setVisible(can_stop and row.state in (QUEUED, RUNNING))
        self.source.setVisible(row.state == FAILED and row.error is not None)


class JobPanel(QFrame):
    stop_all = Signal()
    stop_job = Signal(str)
    show_source = Signal(str)
    retry_failed = Signal()
    open_pdfs = Signal()
    open_log = Signal()

    def __init__(self, parent: QWidget) -> None:
        """`parent` is the window's central widget; the card sits at its bottom centre."""
        super().__init__(parent)
        self.setObjectName(q.JOB_CARD)
        self.setFixedWidth(WIDTH)
        self._rows: dict[str, _RowWidget] = {}
        self._run: Optional[RunStatus] = None
        self._per_job_stop = self._can_retry = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(12)
        self._icon = IconLabel("check_circle", 24)
        head.addWidget(self._icon)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self._title = QLabel("")
        self._title.setObjectName(q.JOB_TITLE)
        self._sub = QLabel("")
        self._sub.setObjectName(q.JOB_SUB)
        self._sub.setWordWrap(True)
        titles.addWidget(self._title)
        titles.addWidget(self._sub)
        head.addLayout(titles, 1)
        self._percent = QLabel("")
        self._percent.setObjectName(q.JOB_PCT)
        head.addWidget(self._percent)
        self._close = IconButton("close", "Close", size=18)
        self._close.clicked.connect(self.hide)
        head.addWidget(self._close)
        layout.addLayout(head)

        self._bar = QProgressBar()
        self._bar.setObjectName(q.JOB_BAR)
        self._bar.setTextVisible(False)
        self._bar.setRange(0, 1000)
        layout.addWidget(self._bar)

        self._box = QFrame()
        self._box.setObjectName(q.LIST_BOX)
        self._rows_layout = QVBoxLayout(self._box)
        self._rows_layout.setContentsMargins(4, 4, 4, 4)
        self._rows_layout.setSpacing(0)
        layout.addWidget(self._box)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        self.log_button = Button("Log", "secondary", compact=True)
        self.retry_button = Button("Retry failed", "secondary", compact=True)
        self.open_button = Button("Open PDF", "primary", compact=True)
        self.stop_button = Button("Stop", "primary", compact=True)
        self.log_button.clicked.connect(self.open_log)
        self.retry_button.clicked.connect(self.retry_failed)
        self.open_button.clicked.connect(self.open_pdfs)
        self.stop_button.clicked.connect(self.stop_all)
        for button in (self.log_button, self.retry_button, self.open_button, self.stop_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        apply_shadow(self, "raised")
        parent.installEventFilter(self)
        self.hide()

    # -- content -----------------------------------------------------------------

    def start(self, run: RunStatus, *, per_job_stop: bool, can_retry: bool) -> None:
        """A new run: one row per job. `per_job_stop`: a row can be stopped on its own;
        `can_retry`: the failed jobs can be run again."""
        self._run = run
        self._per_job_stop, self._can_retry = per_job_stop, can_retry
        for widget in self._rows.values():
            widget.setParent(None)
        self._rows = {}
        for name, row in run.rows.items():
            widget = _RowWidget(row)
            widget.stop_clicked.connect(self.stop_job)
            widget.source_clicked.connect(self.show_source)
            self._rows[name] = widget
            self._rows_layout.addWidget(widget)
        self._box.setVisible(len(run.rows) > 1)

    def refresh(self, fraction: Optional[float], progress: str, *, over: bool) -> None:
        """Bring the card up to date. `fraction`/`progress`: compile_progress's overall
        value (None while unknown) and the running job's "pass 2/4, slide 7/40". `over`: the
        run's worker has ended; the card then tells the outcome once no PDF is left to move."""
        run = self._run
        failed = run.failed
        done = over and run.settled
        busy = next((r for r in run.rows.values() if r.state in (RUNNING, MOVING)), None)
        for name, widget in self._rows.items():
            widget.update_row(run.rows[name], progress, can_stop=self._per_job_stop and not over)
        if done:
            self._title.setText(f"Done: {run.summary()}")
            error = failed[0].error if failed else None
            self._sub.setText(f"{failed[0].label} failed in {error.where}: {error.message}" if error else "")
            self._icon.set_icon("error_outline" if failed else "check_circle")
            self._icon.set_tone("error" if failed else "ok")
            self._percent.setText("")
        else:
            position = list(run.rows).index(busy.jobname) + 1 if busy else 0
            self._title.setText(f"{run.verb} {busy.label}".strip() if busy else "Working…")
            self._sub.setText(" · ".join(part for part in (
                f"{position} of {len(run.rows)}" if len(run.rows) > 1 and position else "",
                progress if busy and busy.state == RUNNING else row_detail(busy, "") if busy else "") if part))
            self._bar.setRange(0, 1000 if fraction is not None else 0)
            self._bar.setValue(round((fraction or 0) * 1000))
            self._percent.setText(f"{round(fraction * 100)}%" if fraction is not None else "")
        self._icon.setVisible(done)
        self._close.setVisible(done)
        self._bar.setVisible(not done)
        self._sub.setVisible(bool(self._sub.text()))
        self.stop_button.setVisible(not over)
        self.retry_button.setVisible(done and bool(failed) and self._can_retry)
        pdfs = [r for r in run.rows.values() if r.state in (DONE, MOVING) and r.pdf is not None]
        self.open_button.setVisible(done and bool(pdfs))
        self.open_button.setText("Open PDFs" if len(pdfs) > 1 else "Open PDF")
        self.adjustSize()
        self._reposition()
        self.show()
        self.raise_()

    # -- placement ---------------------------------------------------------------

    def _reposition(self) -> None:
        parent = self.parentWidget()
        self.move((parent.width() - self.width()) // 2, parent.height() - self.height() - 24)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize and self.isVisible():
            self._reposition()
        return super().eventFilter(obj, event)

