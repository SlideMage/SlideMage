"""Compile orchestration of the main window: the compile slot (one run at a
time), the worker threads, the run's job panel (job_panel.py) and Log drawer
(log_drawer.py), the pre-check before a build (render_check.py), what happens
when a run ends (toasts, jumping to the failing line) and the other flows that
use the slot (deck snapshots, Update previews, Export PPTX).

`CompileJobsMixin` is mixed into WorkspaceWindow (window.py) and uses its
attributes: `state`, `decks`, `topbar`, `build_options`, `stack` (the column
the Log drawer covers) and the central widget it is built on.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QInputDialog,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from ... import app_settings, compile_progress, compiler, deck_snapshot, latex_lint, open_path, partial_compile
from ... import pptx_export
from ... import slide_ids, slide_snapshot, update_all_previews
from ...compile_status import DONE, FAILED, MOVING, QUEUED, RUNNING, JobRow, RunStatus, job_title
from ...compiler import (
    PDF_DIR,
    PDF_MOVE_RETRY_TOTAL_SECONDS,
    CancelToken,
    CompileJob,
    order_jobs,
    resolve_output_location,
    run_job,
    run_jobs,
)
from ...deck_scan import PROJECT_ROOT, Deck
from ...partial_compile import PartialError, parse_page_spec
from ..dialogs import snapshot as snapshot_sheets
from ..kit.widgets import Toast
from . import render_check
from .job_panel import JobPanel
from .log_drawer import LogDrawer
from .multi_compile import MultiCompileSheet
from .state import WorkspaceState


class CompileSignals(QObject):
    """Cross-thread bridge: run_jobs() (on plain
    threading.Thread workers, same as the Tk version) call
    log.emit(line) from the worker thread. Qt automatically queues a
    cross-thread signal emission onto the receiving QObject's own thread
    (the GUI thread, since this object is created there) -- this replaces
    gui.py's manual queue.Queue + root.after(100, poll) with real
    event-driven delivery, no polling loop needed."""

    log = Signal(str)
    batch_done = Signal()
    # The startup update check's result (updater.UpdatePlan, or the
    # updater.UpdateError it failed with), from its background thread.
    update_check_done = Signal(object)
    # deck_snapshot.snapshot_decks()'s list of SnapshotResult, once a
    # snapshot run is over.
    snapshots_done = Signal(object)
    # A run is over: no job waits, runs or has its PDF moved (the RunStatus).
    run_settled = Signal(object)


class BuildOptionsDialog(QDialog):
    """The four checkboxes that sat in the old window's bottom row, now behind
    Compile -> "Build options…". The checkboxes keep their state while the
    dialog is closed, which is what the compile code (and the editor tabs, for
    the footer timestamp) read."""

    def __init__(self, parent: QWidget, state: WorkspaceState) -> None:
        super().__init__(parent)
        self.setWindowTitle("Build options")
        layout = QVBoxLayout(self)

        self.footer_timestamp_checkbox = QCheckBox("Include footer timestamp")
        # Default off (2026-08-20, direct instruction) -- was on by default.
        self.footer_timestamp_checkbox.setChecked(state.footer_timestamp)
        self.footer_timestamp_checkbox.toggled.connect(state.set_footer_timestamp)
        layout.addWidget(self.footer_timestamp_checkbox)

        self.appendix_toc_checkbox = QCheckBox("Generate appendix TOC")
        self.appendix_toc_checkbox.setToolTip(
            "Adds a clickable appendix (agenda + one thumbnail grid per "
            "chapter) at the end of every whole-deck compile -- Presenter, "
            "Instructor, During-course and After-course, each listing the "
            "slides its version shows -- but not to the per-chapter jobs."
        )
        # Persisted (app_settings.py, same local per-machine store dark
        # mode/tab-width/model-picker settings already use) -- unlike
        # footer_timestamp/auto_open just below, which stay hardcoded
        # per-launch defaults; direct instruction, 2026-09-16.
        self.appendix_toc_checkbox.setChecked(bool(app_settings.get("appendix_toc", False)))
        self.appendix_toc_checkbox.toggled.connect(
            lambda checked: app_settings.set("appendix_toc", checked))
        layout.addWidget(self.appendix_toc_checkbox)

        # Page compiles (Compile -> Selected pages…, partial_compile.py,
        # v5.35.0): swap the new pages into the version's whole-deck PDF, or
        # write them to a separate "<pdf>-pages-....pdf". Remembered.
        self.replace_pages_checkbox = QCheckBox("Pages replace theirs in the full PDF")
        self.replace_pages_checkbox.setToolTip(
            "With selected pages: put the newly compiled pages into that "
            "version's whole-deck PDF in place of the old ones. Off: write them to a "
            "separate PDF next to it.")
        self.replace_pages_checkbox.setChecked(bool(app_settings.get("replace_pages", True)))
        self.replace_pages_checkbox.toggled.connect(
            lambda checked: app_settings.set("replace_pages", checked))
        layout.addWidget(self.replace_pages_checkbox)

        self.auto_open_checkbox = QCheckBox("Auto-open generated PDFs")
        self.auto_open_checkbox.setChecked(True)
        layout.addWidget(self.auto_open_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)


class CompileJobsMixin:
    compiling = False   # a run holds the compile slot (the top bar's menu reads it before _init_compile)

    def _init_compile(self, central: QWidget) -> None:
        """Build the compile UI on the window's central widget and connect the
        log. The Log drawer covers the bottom of `self.stack`."""
        self.cancel_token: Optional[CancelToken] = None
        self._worker: Optional[threading.Thread] = None
        self._progress = compile_progress.BatchProgress()
        # The run on show in the job panel and what it was made from.
        self._run: Optional[RunStatus] = None
        self._run_jobs: dict[str, CompileJob] = {}
        self._run_opens_pdfs = True
        self._run_over = False       # the worker thread has ended
        self._run_settled = False    # ... and no PDF is left to move: the end has been reported
        self._stop_requested = False
        self._after_snapshots: Optional[Callable[[list], None]] = None

        self.signals = CompileSignals()
        self.signals.log.connect(self._log)
        self.signals.batch_done.connect(self._on_batch_done)
        self.signals.snapshots_done.connect(self._on_snapshots_done)

        self.job_panel = JobPanel(central)
        self.job_panel.stop_all.connect(self._stop_compilation)
        self.job_panel.stop_job.connect(self._stop_job)
        self.job_panel.retry_failed.connect(self._retry_failed)
        self.job_panel.open_pdfs.connect(self._open_run_pdfs)
        self.job_panel.show_source.connect(lambda name: self._show_error(self._run.rows[name]))
        self.log_drawer = LogDrawer(central, self.stack)
        self.job_panel.open_log.connect(self.log_drawer.open)
        self.log_drawer.error_clicked.connect(lambda: self._show_error(self._run.failed[0]))
        self.compile_toast = Toast(central)
        self.compile_toast.action_triggered.connect(self._on_compile_toast_action)

    # -- the run on show -------------------------------------------------------------

    def _begin_run(
        self, labels: dict[str, str], specs: dict[str, compile_progress.JobSpec], *, verb: str = "",
        jobs: Optional[list[CompileJob]] = None, pdfs: Optional[dict[str, Path]] = None,
        opens_pdfs: bool = True,
    ) -> None:
        """Take the compile slot for a run of `labels` (jobname -> what to call it) and show its
        job panel. `jobs`: the compile jobs behind it, which can be stopped one by one and
        retried; `pdfs`: where each job's PDF will be."""
        self._progress.reset(specs)
        decks = {job.jobname: job.deck.path for job in jobs or []}
        self._run = RunStatus(labels, root=PROJECT_ROOT, verb=verb, pdfs=pdfs, decks=decks)
        self._run_jobs = {job.jobname: job for job in jobs or []}
        self._run_opens_pdfs = opens_pdfs
        self._run_over = self._run_settled = self._stop_requested = False
        self.compile_toast.hide()
        self.log_drawer.set_status("running")
        self.job_panel.start(self._run, per_job_stop=bool(jobs), can_retry=bool(jobs))
        self.compiling = True
        self.cancel_token = CancelToken()
        self.topbar.refresh_compile_menu()
        self._refresh_job_panel()

    def _start_worker(self, target: Callable, *args) -> None:
        self._worker = threading.Thread(target=target, args=args, daemon=True)
        self._worker.start()

    def _refresh_job_panel(self) -> None:
        if self._run is None or self._run_settled:   # an ad-hoc render is not a run
            return
        self.job_panel.refresh(self._progress.fraction, self._progress.text, over=self._run_over)
        if self._run_over and self._run.settled:
            self._run_settled = True
            self._report_run_end(self._run)
            self.signals.run_settled.emit(self._run)

    def _on_batch_done(self) -> None:
        """The worker thread has ended (the threads only emit): the compile slot is free, what never
        ran is stopped, and the run is over once the last PDF has been moved into place (that goes on
        in the background)."""
        self.compiling = False
        self.cancel_token = None
        self.topbar.refresh_compile_menu()
        if self._run is not None:
            self._run.finish(self._stop_requested)
            self._run_over = True
            self._refresh_job_panel()

    def _report_run_end(self, run: RunStatus) -> None:
        """A single job is answered by a toast, a longer run stays on show in the panel. A
        failure opens the Log drawer."""
        failed = run.failed
        if failed:
            first = failed[0]
            self.log_drawer.set_status(f"{first.label} failed", f"Show {first.error.where}" if first.error else "")
            self.log_drawer.open()
            self.job_panel.raise_()   # the card stays on top of the drawer
        else:
            self.log_drawer.set_status("last run ok")
        if len(run.rows) > 1:
            return
        self.job_panel.hide()
        row = next(iter(run.rows.values()))
        if row.state == FAILED:
            text = f"Compile failed in {row.error.slide_id or row.error.path.name}" if row.error \
                else f"{row.label} failed"
            actions = [("source", "Open in Source")] if row.error else []
            self.compile_toast.show_message(text, actions + [("log", "Log")], error=True)
        elif row.state == DONE:
            actions = [("pdf", "Open PDF")] if row.pdf is not None else []
            self.compile_toast.show_message(f"{row.label} ready", actions + [("log", "Log")])

    def _on_compile_toast_action(self, key: str) -> None:
        row = next(iter(self._run.rows.values()), None) if self._run is not None else None
        if key == "log":
            self.log_drawer.open()
        elif key == "source" and row is not None:
            self._show_error(row)
        elif key == "pdf" and row is not None and row.pdf is not None:
            self._open_pdf(row.pdf)

    def _show_error(self, row: JobRow) -> None:
        """Open the file a failed job stopped in, on the line of the error."""
        error = row.error
        if error is None:
            return
        if not error.path.is_file():
            self._log(f"*** couldn't open {error.path}: the file is gone ***")
            return
        self.open_slide_editor(error.path, line=error.line)

    def _stop_job(self, jobname: str) -> None:
        """Stop one job of the run: a queued one is taken out of the queue, the running
        one is killed and the run goes on with the next."""
        row = self._run.rows.get(jobname) if self._run is not None else None
        if row is None or self.cancel_token is None:
            return
        if row.state == RUNNING:
            self.cancel_token.stop_current()
        elif row.state == QUEUED:
            self.cancel_token.skip(jobname)
            self._run.stop_row(jobname)
            self._refresh_job_panel()

    def _retry_failed(self) -> None:
        jobs = [self._run_jobs[row.jobname] for row in self._run.failed if row.jobname in self._run_jobs]
        if jobs:
            self._compile_jobs(jobs)

    def _open_run_pdfs(self) -> None:
        for row in self._run.rows.values():
            if row.state in (DONE, MOVING) and row.pdf is not None:
                self._open_pdf(row.pdf)

    def _stop_worker(self) -> None:
        """The window is closing: stop the run and wait for its thread."""
        if self.cancel_token is not None:
            self._stop_requested = True
            self.cancel_token.request_stop()
        if self._worker is not None:
            self._worker.join(timeout=10)

    def _start_snapshots(
        self, decks: list[Deck], options: deck_snapshot.SnapshotOptions,
        after: Optional[Callable[[list], None]] = None,
    ) -> bool:
        """Ask about older snapshots, then run deck_snapshot.snapshot_decks()
        on a worker thread. `after(results)` replaces the summary dialog (the
        archive flow). False when nothing was started."""
        if self.compiling:
            QMessageBox.information(self, "Busy", "A compile run is already in progress.")
            return False
        existing = deck_snapshot.find_snapshots([d.name for d in decks])
        delete_old: list = []
        if existing:
            answer = snapshot_sheets.ask_about_old_snapshots(self, existing)
            if answer == snapshot_sheets.CANCEL_RUN:
                return False
            if answer == snapshot_sheets.DELETE_OLD:
                delete_old = existing
        # Same footer/appendix choices as a compile from the toolbar.
        options.footer_timestamp = self.build_options.footer_timestamp_checkbox.isChecked()
        options.appendix_toc = True if self.build_options.appendix_toc_checkbox.isChecked() else None

        specs: dict[str, compile_progress.JobSpec] = {}
        texts: dict[str, str] = {}
        for i, deck in enumerate(decks, 1):
            for job in deck_snapshot.snapshot_jobs(deck, options):
                spec = compile_progress.spec_for_job(job)
                prefix = f"Snapshot {i}/{len(decks)}, {deck.name}"
                key = deck_snapshot.progress_key(job.jobname)
                specs[key], texts[key] = spec, f"{prefix}: compiling {job.jobname}"
                if options.verify:
                    key = deck_snapshot.progress_key(job.jobname, verify=True)
                    specs[key], texts[key] = spec, f"{prefix}: checking {job.jobname}"
        self._after_snapshots = after
        self._begin_run(texts, specs)
        self._start_worker(self._run_snapshots_thread, decks, options, delete_old)
        return True

    def _run_snapshots_thread(self, decks: list[Deck], options: deck_snapshot.SnapshotOptions,
                              delete_old: list) -> None:
        cancel = self.cancel_token
        try:
            results = deck_snapshot.snapshot_decks(
                decks, options, self.signals.log.emit, cancel=cancel, delete_old=delete_old)
        except Exception as exc:  # noqa: BLE001 -- reported, the slot must still be freed
            self.signals.log.emit(f"*** Deck snapshots failed: {exc} ***")
            results = [deck_snapshot.SnapshotResult(d.name, ok=False, error=str(exc))
                       for d in decks]
        created = sum(1 for r in results if r.ok)
        self.signals.log.emit(f"==== Done: {created} of {len(results)} snapshot(s) created ====")
        self.signals.batch_done.emit()
        self.signals.snapshots_done.emit(results)

    def _on_snapshots_done(self, results: list) -> None:
        after, self._after_snapshots = self._after_snapshots, None
        if after is not None:
            after(results)
        else:
            snapshot_sheets.show_summary(self, results)

    def _compile_current(self, kind: str, pages: Optional[list[int]] = None) -> None:
        """A Compile menu entry for the current deck: `kind` is a view,
        "chapters" or "presenter" (compiler.build_jobs)."""
        deck = self.state.deck
        if deck is not None:
            jobs = compiler.build_jobs(deck, kind, pages)
            for job in jobs:
                job.language = self.state.language
            self._compile_jobs(jobs)

    def _compile_several(self) -> None:
        """Compile -> "Several decks…": the PDFs and transcripts ticked in
        MultiCompileSheet, on one compile run."""
        sheet = MultiCompileSheet(self, [deck for deck in self.decks if not deck.archived])
        if not sheet.exec():
            return
        chosen = sheet.chosen()
        jobs = [job for deck, kind in chosen if not kind.startswith("transcript:")
                for job in compiler.build_jobs(deck, kind)]
        transcripts = [(deck, kind.removeprefix("transcript:")) for deck, kind in chosen
                       if kind.startswith("transcript:")]
        if jobs:
            self._compile_jobs(jobs)
        if transcripts:
            failures = sum(not self.generate_deck_transcript(deck, version, quiet=True)
                           for deck, version in transcripts)
            self._log(f"==== Create Transcript: {len(transcripts) - failures} of "
                      f"{len(transcripts)} transcript(s) generated ====")

    def _compile_everything(self) -> None:
        """Compile -> "All decks except archive": every view of every active deck."""
        decks = [deck for deck in self.decks if not deck.archived]
        jobs = [job for deck in decks for job in compiler.build_jobs(deck, "all")]
        if jobs and QMessageBox.question(
                self, "Compile all decks",
                f"Compile {len(jobs)} PDF(s) of {len(decks)} deck(s), every view of each? "
                "The archive is left out.") == QMessageBox.StandardButton.Yes:
            self._compile_jobs(jobs)

    def _compile_pages(self) -> None:
        """Compile menu -> "Selected pages…": the Pages field of the old deck
        table. Takes the pages of the current view."""
        text, ok = QInputDialog.getText(
            self, "Selected pages",
            "Slides of the current view to compile, numbered as in the footers\n"
            "(e.g. 4, 5, 7-10, 15):")
        if not ok or not text.strip():
            return
        try:
            pages = parse_page_spec(text)
        except PartialError as exc:
            QMessageBox.warning(self, "Pages", str(exc))
            return
        self._compile_current(self.state.view, pages)

    def _compile_slides(self, slide_ids: list[str]) -> None:
        """The slide list's "Compile these pages": the frames the slides have in
        the current view's last whole-deck PDF, then the same path as Selected pages."""
        deck = self.state.deck
        if deck is None:
            return
        job = compiler.build_jobs(deck, self.state.view)[0]
        job.language = self.state.language
        try:
            pages = partial_compile.frames_for_slides(job, slide_ids)
        except PartialError as exc:
            QMessageBox.warning(self, "Compile pages", str(exc))
            return
        if not pages:
            QMessageBox.information(
                self, "Compile pages",
                "None of these slides is in the last whole-deck PDF of this view "
                "(not typeset there, or added since). Compile the whole deck first.")
            return
        self._compile_current(self.state.view, pages)

    def _compile_jobs(self, jobs: list[CompileJob]) -> bool:
        """Compile `jobs` through the whole flow (prompts, job panel, Log drawer). False when the run
        did not start: busy, nothing to typeset, or the user cancelled a question."""
        if self.compiling:
            QMessageBox.information(self, "Busy", "A compile run is already in progress.")
            return False
        footer_timestamp = self.build_options.footer_timestamp_checkbox.isChecked()
        appendix_toc = self.build_options.appendix_toc_checkbox.isChecked()
        replace_pages = self.build_options.replace_pages_checkbox.isChecked()
        # One id for everything this click compiles (PDF info /SlideMageRun).
        run_id = datetime.now().isoformat(timespec="seconds")
        outputs: dict[str, Path] = {}   # jobname -> where its PDF lands (the deck's own \deckoutputfolder, or pdf/)
        for job in jobs:
            job.footer_timestamp = footer_timestamp
            # \deckappendixtoc in the deck: always, checkbox or not
            job.appendix_toc = appendix_toc or job.deck.appendix_toc
            job.replace_pages = replace_pages
            job.run_id = run_id
            output_dir, output_stem = resolve_output_location(job)
            outputs[job.jobname] = output_dir / f"{output_stem}.pdf"
        jobs = order_jobs(jobs)   # version by version, then deck by deck
        jobs, empty_descriptions = self._drop_empty_jobs(jobs)
        if not jobs:
            QMessageBox.critical(
                self, "Nothing to compile",
                "No slides to typeset -- every checked job is empty:\n\n"
                + "\n".join(f"  • {d}" for d in empty_descriptions),
            )
            return False
        if empty_descriptions:
            QMessageBox.warning(
                self, "Some jobs skipped",
                "Skipped (no slides to typeset):\n\n"
                + "\n".join(f"  • {d}" for d in empty_descriptions)
                + "\n\nCompiling the rest.",
            )
        jobs = self._confirm_unchanged_jobs(jobs, outputs)
        if not jobs:
            return False
        # Pre-render syntax check (2026-09-26), scoped to exactly what these
        # jobs read: the deck files plus the slides their versions/chapters
        # actually include.
        if not self._confirm_build(latex_lint.check_jobs(jobs), ", ".join(sorted({job.deck.name for job in jobs}))):
            return False
        self._begin_run(
            {job.jobname: job_title(job) for job in jobs},
            {job.jobname: compile_progress.spec_for_job(job) for job in jobs},
            verb="Compiling", jobs=jobs, pdfs={job.jobname: outputs[job.jobname] for job in jobs})
        self._start_worker(self._run_jobs_thread, jobs)
        return True

    def _confirm_build(self, result: latex_lint.CheckResult, what: str) -> bool:
        """The pre-render syntax check of a build: False when it found errors and the user cancelled."""
        return render_check.confirm_render(
            self, self, result, what, verb="Build",
            show_in_editor=lambda issue: render_check.open_issue_in_editor(self, issue))

    def _confirm_unchanged_jobs(self, jobs: list[CompileJob], outputs: dict[str, Path]) -> list[CompileJob]:
        """Versions that haven't changed since their last compile
        (compiler.unchanged_jobs) are only compiled again after asking
        (2026-10-08, direct instruction): Compile anyway / Skip unchanged /
        Cancel. Returns the jobs to compile ([] = nothing)."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            unchanged = compiler.unchanged_jobs(jobs, outputs)
        finally:
            QApplication.restoreOverrideCursor()
        if not unchanged:
            return jobs
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Nothing changed")
        lines = [f"  • {job.jobname} (compiled {created[:16].replace('T', ' ')})"
                 for job, created in unchanged]
        box.setText("Nothing these PDFs are made from has changed since they were last "
                    "compiled:\n\n" + "\n".join(lines) + "\n\nCompile them anyway?")
        box.setInformativeText("SlideMage compares every file the last compile read "
                               "(slides, media, template, framework, packages) and the PDF itself.")
        anyway = box.addButton("Compile anyway", QMessageBox.ButtonRole.AcceptRole)
        skip = box.addButton("Skip unchanged", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(skip)
        box.exec()
        clicked = box.clickedButton()
        if clicked is anyway:
            return jobs
        if clicked is not skip:
            return []
        skipped = {job.jobname for job, _created in unchanged}
        remaining = [job for job in jobs if job.jobname not in skipped]
        if not remaining:
            self._log(f"Nothing compiled: {', '.join(sorted(skipped))} unchanged.")
        return remaining

    def _drop_empty_jobs(
        self, jobs: list[CompileJob]
    ) -> tuple[list[CompileJob], list[str]]:
        """Filters out any job that would typeset zero slides (2026-09-28,
        direct instruction: "SlideMage should give an error message instead
        of trying to compile it" for an empty deck) -- clicking "Create
        PDF" on a deck with no \\slide{}-family calls of its own (e.g.
        #workdeck-mini right after being cleared out, or a brand-new empty
        deck) used to run a real latexmk compile for a PDF with nothing on
        it, the same pointless-but-not-obviously-wrong result whether the
        compile "succeeded" or not.

        compile_progress.count_job_slides() (built for the progress bar's
        own sizing) is reused here rather than a fresh check, since it
        already resolves a job's real slide count correctly for every case
        that matters: version/chapter filtering (\\conditionalslide/
        \\slidestep), and \\input{}-ed fragments like test-slides.tex --
        so a wrapper deck that only \\input{}s a shared slide list is
        correctly NOT flagged as empty, only a deck (or, for a per-chapter
        job, a chapter) that genuinely has nothing to typeset is.

        Returns (surviving jobs, one human-readable description per
        dropped job)."""
        surviving: list[CompileJob] = []
        descriptions: list[str] = []
        for job in jobs:
            if compile_progress.count_job_slides(job.deck, job.version, job.chapter, job.language) > 0:
                surviving.append(job)
                continue
            where = job.deck.name
            if job.chapter is not None:
                where += f", chapter {job.chapter.order} ({job.chapter.title})"
            if job.version:
                where += f" ({job.version})"
            descriptions.append(where)
        return surviving, descriptions

    def _on_export_pptx(self, deck: Deck) -> None:
        """Compiles `deck` (instructor version, direct instruction -- the
        fullest-content version, matching what update_all_previews.py's
        own snapshot refresh already treats as this project's "real"
        default) and exports the result as a .pptx with one full-page
        image per PDF page -- see pptx_export.py's own docstring for why
        one PDF page per pptx slide (every beamer overlay/reveal as its
        own slide) rather than one pptx slide per \\slide{} call, and why
        python-pptx rather than a hand-rolled OOXML package.

        Reuses self.compiling as the same single-flight guard a real
        "Create PDF" batch already checks (same message pattern as
        _on_archive_unused_content's own busy check) -- this runs a real
        latexmk invocation of its own, which can't safely run alongside
        another one."""
        if self.compiling:
            QMessageBox.information(
                self, "Busy",
                "Can't export to PowerPoint while a compile run is in "
                "progress -- wait for it to finish first.",
            )
            return
        if compile_progress.count_job_slides(deck, "instructor", None) == 0:
            QMessageBox.critical(
                self, "Nothing to export", f"{deck.name} has no slides to typeset."
            )
            return
        pptx_job = CompileJob(deck, version="instructor", chapter=None)
        if not self._confirm_build(latex_lint.check_jobs([pptx_job]), deck.name):
            return
        self._begin_run({pptx_job.jobname: f"Export {deck.name} to PowerPoint"},
                        {pptx_job.jobname: compile_progress.spec_for_job(pptx_job)})
        self._start_worker(self._export_pptx_bg, deck)

    def _export_pptx_bg(self, deck: Deck) -> None:
        log = self.signals.log.emit
        job = CompileJob(deck, version="instructor", chapter=None)
        log(f"==== Exporting {deck.name} to PowerPoint (instructor version) ====")
        cancel = self.cancel_token
        try:
            # run_job() itself already logs its own "==== PASS/FAIL:
            # ... ====" lines (picked up by the same log handler every
            # other compile goes through, auto-opening the compiled PDF too
            # if that checkbox is on) -- nothing extra needed here for the
            # compile step itself, only for what happens after it.
            #
            # run_job() doesn't wait for the PDF's move into pdf/ (it
            # backgrounds that so one job's stuck sync client can't block
            # the rest of a batch's queue -- see its own docstring), so
            # reading .build/<jobname>.pdf right after it returns races
            # that same background thread, which copies the PDF out and
            # then deletes every .build/<jobname>.* file, this PDF
            # included -- there's nothing else queued behind a one-off
            # export, so waiting here for on_relocated costs nothing and
            # avoids reading a file that thread may have already removed.
            relocated = threading.Event()
            outcome: dict[str, object] = {"ok": False, "dest_pdf": None}

            def _on_relocated(ok: bool, dest_pdf: Path) -> None:
                outcome["ok"] = ok
                outcome["dest_pdf"] = dest_pdf
                relocated.set()

            if not run_job(job, log, cancel=cancel, on_relocated=_on_relocated):
                log(f"*** FAIL: PowerPoint export of {deck.name} -- "
                   f"compile failed, see above ***")
                return
            # Generous margin over the retry loop's own total budget --
            # this thread has nothing else to do but wait for it anyway.
            relocated.wait(PDF_MOVE_RETRY_TOTAL_SECONDS + 30)
            if not outcome["ok"]:
                log(f"*** FAIL: PowerPoint export of {deck.name} -- "
                   f"couldn't move the compiled PDF into place, see above ***")
                return
            pdf_path = outcome["dest_pdf"]
            out_path = PDF_DIR / f"{job.jobname}.pptx"
            try:
                pptx_export.export_deck_to_pptx(pdf_path, out_path, log=log)
            except Exception as exc:  # noqa: BLE001 -- surfaced, not swallowed
                log(f"*** FAIL: PowerPoint export of {deck.name} -- {exc!r} ***")
                return
            log(f"==== PASS: {out_path.relative_to(PROJECT_ROOT)} ====")
            # Always opened, unlike the auto-open-PDF checkbox above --
            # this is a single, deliberate export the user just asked
            # for, not a batch that could pop open many windows
            # unattended, so there's no "maybe don't" case worth a
            # preference for.
            try:
                open_path.open_in_default_app(out_path)
            except OSError as exc:
                log(f"*** couldn't auto-open {out_path.name}: {exc} ***")
        finally:
            self.signals.batch_done.emit()

    def _stop_compilation(self) -> None:
        cancel = self.cancel_token
        if cancel is None or not self.compiling:
            return
        reply = QMessageBox.question(
            self,
            "Stop creation",
            "Stop the compile run? The job currently compiling will be "
            "killed immediately (including latexmk's own lualatex/biber "
            "children); anything still queued after it will be skipped.",
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.stop_compilation_now()

    def stop_compilation_now(self) -> None:
        """Stop the run without asking (the chat's Stop does; the job panel's asks first)."""
        cancel = self.cancel_token
        if cancel is None or not self.compiling:
            return
        self._log("==== Stop requested -- killing current job and skipping the rest ====")
        self._stop_requested = True
        cancel.request_stop()

    def _run_jobs_thread(self, jobs: list[CompileJob]) -> None:
        cancel = self.cancel_token
        try:
            results = run_jobs(jobs, self.signals.log.emit, cancel=cancel)
            passed = sum(1 for ok in results.values() if ok)
            failed = len(results) - passed
            self.signals.log.emit(f"==== Done: {passed} passed, {failed} failed ====")
        except Exception as exc:  # noqa: BLE001 -- reported, the slot must still be freed
            self.signals.log.emit(f"*** Compile run failed: {exc} ***")
        finally:
            # refresh_compile_menu() touches widgets: this signal is queued onto the GUI thread
            self.signals.batch_done.emit()

    def _on_update_previews(self) -> None:
        """No template picker any more (2026-08-16, direct instruction:
        "I forgot that each deck has a specific template linked to it" --
        there's nothing to pick, every deck already carries its own).
        Scans every deck for which (template, slide) combinations it
        actually needs (update_all_previews.needed_slides_by_template())
        and shows that in the confirmation dialog, so the count reflects
        exactly what's about to be compiled -- not "every slide file in
        the project" the way the old single-template design counted.
        """
        if self.compiling:
            QMessageBox.information(self, "Busy", "A compile run is already in progress.")
            return

        needed = update_all_previews.needed_slides_by_template()
        if not needed:
            QMessageBox.information(
                self, "Nothing to do", "No deck references any slides right now."
            )
            return
        total_slides = sum(len(ids) for ids in needed.values())
        template_names = [
            slide_snapshot.TEMPLATES.get(t, t) for t in sorted(needed)
        ]
        reply = QMessageBox.question(
            self, "Update previews",
            f"Scan every deck (active and archived) and refresh preview "
            f"snapshots for {total_slides} slide-template combination(s) "
            f"across {', '.join(template_names)}? Cached previews no "
            f"longer used by any deck are deleted afterward.\n\nThis is "
            f"one very long compile (well over an hour is plausible for "
            f"this many slides) -- it runs in the background, but "
            f"occupies the compile slot, so no other compile can start "
            f"until it's done.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Pre-render syntax check (2026-09-26) of every slide about to be
        # compiled -- "everything" scope, still only a few tens of ms.
        all_slides = sorted({slug for slugs in needed.values() for slug in slugs})
        if not self._confirm_build(
                latex_lint.check_slide_files(
                    slide_ids.SLIDES_DIR / f"{slug}-current.tex" for slug in all_slides),
                f"{len(all_slides)} slides"):
            return

        # This operation builds its own temp deck/CompileJob entirely inside
        # update_all_previews.run(), with no channel back to this class
        # except the log stream, so the run's rows are registered here first:
        # one jobname per template (there can be several, run one after
        # another), generated here rather than left to run() so both sides
        # agree on the exact strings ahead of time. "-instructor" matches
        # CompileJob.jobname's own "-{version}" suffix (compiler.py) --
        # update_all_previews.run() always compiles the instructor version.
        base_jobnames = {
            template: f"{update_all_previews.JOBNAME_PREFIX}{uuid.uuid4().hex[:8]}"
            for template in needed
        }
        labels = {f"{base_jobname}-instructor":
                  f"Update previews ({slide_snapshot.TEMPLATES.get(template, template)})"
                  for template, base_jobname in base_jobnames.items()}
        # One throw-away megadeck per template (with a bibliography, so 4
        # passes), each typesetting that template's own slides. Nobody wants
        # a 639-slide throwaway PDF popping open, whatever the auto-open checkbox says.
        self._begin_run(
            labels,
            {f"{base_jobname}-instructor": compile_progress.JobSpec(
                compile_progress.PASSES_WITH_BIBLIOGRAPHY, len(needed[template]), estimated=True)
             for template, base_jobname in base_jobnames.items()},
            opens_pdfs=False)
        self._start_worker(self._run_update_previews_thread, needed, base_jobnames)

    def _run_update_previews_thread(
        self, needed: dict[str, set[str]], base_jobnames: dict[str, str]
    ) -> None:
        cancel = self.cancel_token
        try:
            ok = update_all_previews.run(
                self.signals.log.emit, cancel=cancel,
                base_jobnames=base_jobnames, needed=needed,
            )
        except Exception as exc:  # noqa: BLE001 -- reported, batch must still clean up state
            self.signals.log.emit(f"*** Update previews failed: {exc} ***")
            ok = False
        self.signals.log.emit(
            "==== Update previews: compile finished ====" if ok
            else "==== Update previews: FAILED ===="
        )
        self.signals.batch_done.emit()

    def _open_pdf(self, pdf_path: Path) -> None:
        if not pdf_path.exists():
            return
        try:
            open_path.open_in_default_app(pdf_path)
        except OSError as exc:
            self._log(f"*** couldn't auto-open {pdf_path.name}: {exc} ***")

    def _log(self, line: str) -> None:
        """Every log line: into the Log drawer, the progress and the run's rows (and a job whose
        PDF has just landed may open it)."""
        self.log_drawer.append(line)
        progress_update = self._progress.feed(line)
        changed = self._run.feed(line) if self._run is not None else None
        if (changed is not None and changed.state == DONE and changed.pdf is not None
                and self._run_opens_pdfs and self.build_options.auto_open_checkbox.isChecked()):
            self._open_pdf(changed.pdf)
        if progress_update is not None or changed is not None:
            self._refresh_job_panel()

    def log(self, line: str) -> None:
        """Public entry point for the centre column's views and the dialogs
        to append to the log pane -- always called from the main thread (a
        button/dialog action)."""
        self._log(line)
