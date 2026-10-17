"""The compile slot: one run at a time, owned here and only displayed by the window.

`CompileController` holds everything a run is made of -- the cancel token, the worker thread, the
progress estimate (compile_progress.py), the job rows (compile_status.py) and the jobs behind them
(for retry) -- and tells the window what changed through signals. It knows no widget. A flow
(compile_actions.py) asks what to do, then hands `start()` the run's rows and the work to do on the
worker thread; every log line, from that thread or any other, goes through `log`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QThread, Signal

from ... import compile_progress, project
from ...compile_status import DONE, MOVING, QUEUED, RUNNING, JobRow, RunStatus
from ...compiler import CancelToken, CompileJob
from .. import background

Work = Callable[[Callable[[str], None], CancelToken], Any]   # (log, cancel) -> whatever `on_done` is given


class _Worker(QThread):
    def __init__(self, work: Callable[[], None]) -> None:
        super().__init__()
        self._work = work

    def run(self) -> None:
        self._work()


class CompileController(QObject):
    log = Signal(str)            # any thread: a line for the Log drawer, the progress and the rows
    started = Signal(object)     # the RunStatus of a new run
    changed = Signal()           # progress or a row moved, or the worker ended
    ended = Signal()             # the worker has ended: the slot is free
    pdf_ready = Signal(object)   # a job's PDF has landed (Path) in a run that opens its PDFs
    settled = Signal(object)     # the run is over, its last PDF in place (the RunStatus)

    def __init__(self, context: project.ProjectContext, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.context = context
        self.cancel: Optional[CancelToken] = None
        self.progress = compile_progress.BatchProgress()
        self.run: Optional[RunStatus] = None       # the run on show, finished or not
        self.jobs: dict[str, CompileJob] = {}      # what its rows were made from (retry, stop one)
        self.worker: Optional[_Worker] = None
        self.over = False                          # the worker has ended
        self.is_settled = False                    # ... and no PDF is left to move: the end is reported
        self._opens_pdfs = True
        self._stop_requested = False
        self._on_done: Optional[Callable[[Any], None]] = None
        self._result: Any = None
        self.log.connect(self._feed)

    @property
    def running(self) -> bool:
        return self.worker is not None

    def start(
        self, labels: dict[str, str], specs: dict[str, compile_progress.JobSpec], work: Work, *,
        verb: str = "", jobs: Optional[list[CompileJob]] = None, pdfs: Optional[dict[str, Path]] = None,
        opens_pdfs: bool = True, failure: str = "Compile run", on_done: Optional[Callable[[Any], None]] = None,
    ) -> None:
        """Take the slot for a run of `labels` (jobname -> what to call it) and do `work(log, cancel)`
        on a worker thread. `jobs`: the compile jobs behind the rows, which can be stopped one by one
        and retried; `pdfs`: where each job's PDF will be. A work that raises is logged as
        "<failure> failed". `on_done(result)` runs once the slot is free again."""
        self.progress.reset(specs)
        self.jobs = {job.jobname: job for job in jobs or []}
        self.run = RunStatus(labels, root=self.context.root, verb=verb, pdfs=pdfs,
                             decks={name: job.deck.path for name, job in self.jobs.items()})
        self._opens_pdfs, self._on_done, self._result = opens_pdfs, on_done, None
        self.over = self.is_settled = self._stop_requested = False
        self.cancel = cancel = CancelToken()

        def target() -> None:
            try:
                self._result = work(self.log.emit, cancel)
            except Exception as exc:  # noqa: BLE001 -- reported, the slot must still be freed
                self.log.emit(f"*** {failure} failed: {exc} ***")

        self.worker = _Worker(target)
        self.started.emit(self.run)
        background.start_detached(self.worker, self._worker_ended)

    def _worker_ended(self) -> None:
        """The worker is over (this runs on the GUI thread): the slot is free, what never ran is
        stopped, and the run is settled once the last PDF has been moved into place (that goes on in
        the background)."""
        self.worker = self.cancel = None
        self.run.finish(self._stop_requested)
        self.over = True
        self.ended.emit()
        self._update()
        if self._on_done is not None:
            self._on_done(self._result)

    def _update(self) -> None:
        if self.is_settled:                 # an ad-hoc render is not a run
            return
        self.changed.emit()
        if self.over and self.run.settled:
            self.is_settled = True
            self.settled.emit(self.run)

    def _feed(self, line: str) -> None:
        progress_update = self.progress.feed(line)
        row = self.run.feed(line) if self.run is not None else None
        if row is not None and row.state == DONE and row.pdf is not None and self._opens_pdfs:
            self.pdf_ready.emit(row.pdf)
        if progress_update is not None or row is not None:
            self._update()

    def stop(self) -> None:
        """Stop the run: the job being compiled is killed, the rest skipped."""
        if self.cancel is not None:
            self._stop_requested = True
            self.cancel.request_stop()

    def stop_job(self, jobname: str) -> None:
        """Stop one job: a queued one is taken out of the queue, the running one is killed and the
        run goes on with the next."""
        row = self.run.rows.get(jobname) if self.run is not None else None
        if row is None or self.cancel is None:
            return
        if row.state == RUNNING:
            self.cancel.stop_current()
        elif row.state == QUEUED:
            self.cancel.skip(jobname)
            self.run.stop_row(jobname)
            self._update()

    def failed_jobs(self) -> list[CompileJob]:
        return [self.jobs[row.jobname] for row in self.run.failed if row.jobname in self.jobs]

    def pdfs(self) -> list[Path]:
        return [row.pdf for row in self.run.rows.values() if row.state in (DONE, MOVING) and row.pdf is not None]

    def row(self, jobname: str) -> JobRow:
        return self.run.rows[jobname]

    def shutdown(self, wait_ms: int = 10000) -> None:
        """The window is closing: stop the run and wait for its thread."""
        self.stop()
        if self.worker is not None:
            self.worker.wait(wait_ms)
