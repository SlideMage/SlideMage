"""Compile orchestration of the main window, moved out of qt_gui.py (step 3 of
docs/UI_REDESIGN_PLAN.md) with the logic unchanged except for what the old
deck table's rows used to carry: jobs now come from compiler.build_jobs() for
the current deck and there are no per-row status dots, so progress shows in
the status line, the progress bar and the log. Step 7 replaces this with the
job panel and `compile_jobs.py` proper.

`CompileJobsMixin` is mixed into WorkspaceWindow (window.py) and uses its
attributes: `signals`, `_progress`, `progress_bar`, `status_label`, `log_text`,
`topbar`, `build_options` and the `compiling` / `cancel_token` slot.
"""
from __future__ import annotations

import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
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
from ... import qt_render_check, qt_snapshot_dialog, slide_ids, slide_snapshot, update_all_previews
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
from .multi_compile import MultiCompileSheet

RUNNING_LOG_RE = re.compile(r"^==== Compiling \S+ -> (\S+) ====")
MOVING_LOG_RE = re.compile(r"^==== MOVING: (\S+) ->")
PASS_LOG_RE = re.compile(r"^==== PASS: (\S+) ->")
FAIL_LOG_RE = re.compile(r"^\*\*\* FAIL: (\S+) --")
DONE_LOG_RE = re.compile(r"^==== Done: (.+) ====$")
RENDER_START_RE = re.compile(r"^==== Rendering (\S+) -> \S+ ====")
RENDER_PASS_RE = re.compile(r"^==== PASS: render of (\S+) ->")
RENDER_FAIL_RE = re.compile(r"^\*\*\* FAIL: render of (\S+) --")
RUN_NUMBER_RE = re.compile(r"^Run number (\d+) of rule '([^']+)'")


class CompileSignals(QObject):
    """Cross-thread bridge: run_jobs()/archive_unused_content() (on plain
    threading.Thread workers, same as the Tk version) call
    log.emit(line) from the worker thread. Qt automatically queues a
    cross-thread signal emission onto the receiving QObject's own thread
    (the GUI thread, since this object is created there) -- this replaces
    gui.py's manual queue.Queue + root.after(100, poll) with real
    event-driven delivery, no polling loop needed."""

    log = Signal(str)
    batch_done = Signal()
    # For a background thread (e.g. the slide preview's Render now)
    # that needs to re-enable a button once it's done -- setEnabled() is a
    # widget mutation, so it has to run on the GUI thread same as
    # everything else here. Signal(object) rather than Signal(QPushButton)
    # so this can carry any widget type, not just buttons.
    enable_button = Signal(object)
    # The startup update check's result (updater.UpdatePlan, or the
    # updater.UpdateError it failed with), from its background thread.
    update_check_done = Signal(object)
    # deck_snapshot.snapshot_decks()'s list of SnapshotResult, once a
    # snapshot run is over.
    snapshots_done = Signal(object)


class BuildOptionsDialog(QDialog):
    """The four checkboxes that sat in the old window's bottom row, now behind
    Compile -> "Build options…". The checkboxes keep their state while the
    dialog is closed, which is what the compile code (and the editor tabs, for
    the footer timestamp) read. Step 7 turns them into toggles of the Compile
    menu."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Build options")
        layout = QVBoxLayout(self)

        self.footer_timestamp_checkbox = QCheckBox("Include footer timestamp")
        # Default off (2026-08-20, direct instruction) -- was on by default.
        self.footer_timestamp_checkbox.setChecked(False)
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
    def _on_batch_done(self) -> None:
        self.topbar.set_compiling(False)

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
            answer = qt_snapshot_dialog.ask_about_old_snapshots(self, existing)
            if answer == qt_snapshot_dialog.CANCEL_RUN:
                return False
            if answer == qt_snapshot_dialog.DELETE_OLD:
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
        self._job_progress_texts = texts
        self._progress.reset(specs)
        self._after_snapshots = after
        self.compiling = True
        self.cancel_token = CancelToken()
        self.topbar.set_compiling(True)
        threading.Thread(target=self._run_snapshots_thread,
                         args=(decks, options, delete_old), daemon=True).start()
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
        self.compiling = False
        self.cancel_token = None
        self.signals.batch_done.emit()
        self.signals.snapshots_done.emit(results)

    def _on_snapshots_done(self, results: list) -> None:
        self._progress.reset({})
        self._clear_progress_if_idle()
        after, self._after_snapshots = self._after_snapshots, None
        if after is not None:
            after(results)
        else:
            qt_snapshot_dialog.show_summary(self, results)

    def _compile_current(self, kind: str, pages: Optional[list[int]] = None) -> None:
        """A Compile menu entry for the current deck: `kind` is a view,
        "chapters" or "presenter" (compiler.build_jobs)."""
        deck = self.state.deck
        if deck is not None:
            self._compile_jobs(compiler.build_jobs(deck, kind, pages))

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

    def _compile_jobs(self, jobs: list[CompileJob]) -> None:
        if self.compiling:
            QMessageBox.information(self, "Busy", "A compile run is already in progress.")
            return
        footer_timestamp = self.build_options.footer_timestamp_checkbox.isChecked()
        appendix_toc = self.build_options.appendix_toc_checkbox.isChecked()
        replace_pages = self.build_options.replace_pages_checkbox.isChecked()
        # One id for everything this click compiles (PDF info /SlideMageRun).
        run_id = datetime.now().isoformat(timespec="seconds")
        for job in jobs:
            job.footer_timestamp = footer_timestamp
            # \deckappendixtoc in the deck: always, checkbox or not
            job.appendix_toc = appendix_toc or job.deck.appendix_toc
            job.replace_pages = replace_pages
            job.run_id = run_id
            output_dir, output_stem = resolve_output_location(job)
            self._job_output_paths[job.jobname] = output_dir / f"{output_stem}.pdf"
        jobs = order_jobs(jobs)   # version by version, then deck by deck
        jobs, empty_descriptions = self._drop_empty_jobs(jobs)
        if not jobs:
            QMessageBox.critical(
                self, "Nothing to compile",
                "No slides to typeset -- every checked job is empty:\n\n"
                + "\n".join(f"  • {d}" for d in empty_descriptions),
            )
            return
        if empty_descriptions:
            QMessageBox.warning(
                self, "Some jobs skipped",
                "Skipped (no slides to typeset):\n\n"
                + "\n".join(f"  • {d}" for d in empty_descriptions)
                + "\n\nCompiling the rest.",
            )
        jobs = self._confirm_unchanged_jobs(jobs)
        if not jobs:
            return
        # Pre-render syntax check (2026-09-26), scoped to exactly what these
        # jobs read: the deck files plus the slides their versions/chapters
        # actually include.
        if not qt_render_check.confirm_render(
                self, self, latex_lint.check_jobs(jobs),
                ", ".join(sorted({job.deck.name for job in jobs})),
                show_in_editor=lambda issue: qt_render_check.open_issue_in_editor(self, issue)):
            return
        self._start_jobs(jobs)

    def _confirm_unchanged_jobs(self, jobs: list[CompileJob]) -> list[CompileJob]:
        """Versions that haven't changed since their last compile
        (compiler.unchanged_jobs) are only compiled again after asking
        (2026-10-08, direct instruction): Compile anyway / Skip unchanged /
        Cancel. Returns the jobs to compile ([] = nothing)."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            unchanged = compiler.unchanged_jobs(jobs, self._job_output_paths)
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
            if compile_progress.count_job_slides(job.deck, job.version, job.chapter) > 0:
                surviving.append(job)
                continue
            where = job.deck.name
            if job.chapter is not None:
                where += f", chapter {job.chapter.order} ({job.chapter.title})"
            if job.version:
                where += f" ({job.version})"
            descriptions.append(where)
            self._job_output_paths.pop(job.jobname, None)
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
        if not qt_render_check.confirm_render(
                self, self, latex_lint.check_jobs([CompileJob(deck, version="instructor", chapter=None)]),
                deck.name,
                show_in_editor=lambda issue: qt_render_check.open_issue_in_editor(self, issue)):
            return
        pptx_job = CompileJob(deck, version="instructor", chapter=None)
        self._progress.reset({pptx_job.jobname: compile_progress.spec_for_job(pptx_job)})
        self.compiling = True
        threading.Thread(target=self._export_pptx_bg, args=(deck,), daemon=True).start()

    def _export_pptx_bg(self, deck: Deck) -> None:
        log = self.signals.log.emit
        job = CompileJob(deck, version="instructor", chapter=None)
        log(f"==== Exporting {deck.name} to PowerPoint (instructor version) ====")
        try:
            # run_job() itself already logs its own "==== PASS/FAIL:
            # ... ====" lines (picked up by the same PASS_LOG_RE/
            # FAIL_LOG_RE-driven log handler every other compile goes
            # through, auto-opening the compiled PDF too if that
            # checkbox is on) -- nothing extra needed here for the
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

            if not run_job(job, log, on_relocated=_on_relocated):
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
            self.compiling = False

    def _start_jobs(self, jobs: list[CompileJob]) -> None:
        self._job_progress_texts = compile_progress.build_progress_texts(jobs)
        self._progress.reset({job.jobname: compile_progress.spec_for_job(job) for job in jobs})
        self.compiling = True
        self.cancel_token = CancelToken()
        self.topbar.set_compiling(True)
        threading.Thread(target=self._run_jobs_thread, args=(jobs,), daemon=True).start()

    def _stop_compilation(self) -> None:
        if self.cancel_token is None or not self.compiling:
            return
        reply = QMessageBox.question(
            self,
            "Stop creation",
            "Stop the compile run? The job currently compiling will be "
            "killed immediately (including latexmk's own lualatex/biber "
            "children); anything still queued after it will be skipped.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._log("==== Stop requested -- killing current job and skipping the rest ====")
        self.cancel_token.request_stop()

    def _run_jobs_thread(self, jobs: list[CompileJob]) -> None:
        cancel = self.cancel_token
        results = run_jobs(jobs, self.signals.log.emit, cancel=cancel)
        passed = sum(1 for ok in results.values() if ok)
        failed = len(results) - passed
        self.signals.log.emit(f"==== Done: {passed} passed, {failed} failed ====")
        self.compiling = False
        self.cancel_token = None
        # set_compiling() touches widgets -- runs via this signal (queued
        # onto the GUI thread automatically, same as the log signal above)
        # rather than being called directly from this worker thread.
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
        if not qt_render_check.confirm_render(
                self, self,
                latex_lint.check_slide_files(
                    slide_ids.SLIDES_DIR / f"{slug}-current.tex" for slug in all_slides),
                f"{len(all_slides)} slides",
                show_in_editor=lambda issue: qt_render_check.open_issue_in_editor(self, issue)):
            return

        self.compiling = True
        self.cancel_token = CancelToken()
        self.topbar.set_compiling(True)
        # _log()'s RUNNING_LOG_RE handling looks up a human-readable status
        # line in self._job_progress_texts by jobname -- normally populated
        # by _start_jobs() from the real compile queue, but this operation
        # builds its own temp deck/CompileJob entirely inside
        # update_all_previews.run(), with no channel back to this class
        # except the log stream. Without registering an entry here first,
        # each template's own "==== Compiling ... ====" line still matches
        # RUNNING_LOG_RE fine, but the lookup finds nothing and the status
        # line by "Log:" just stays blank for the whole run. One jobname
        # per template (there can be several, run one after another), all
        # generated here rather than left to run() so both sides agree on
        # the exact strings ahead of time. "-instructor" matches
        # CompileJob.jobname's own "-{version}" suffix (compiler.py) --
        # update_all_previews.run() always compiles the instructor version.
        base_jobnames = {
            template: f"{update_all_previews.JOBNAME_PREFIX}{uuid.uuid4().hex[:8]}"
            for template in needed
        }
        self._job_progress_texts = {
            f"{base_jobname}-instructor":
                f"Update previews ({slide_snapshot.TEMPLATES.get(template, template)})"
            for template, base_jobname in base_jobnames.items()
        }
        # One throw-away megadeck per template (with a bibliography, so 4
        # passes), each typesetting that template's own slides.
        self._progress.reset({
            f"{base_jobname}-instructor": compile_progress.JobSpec(
                compile_progress.PASSES_WITH_BIBLIOGRAPHY, len(needed[template]), estimated=True)
            for template, base_jobname in base_jobnames.items()
        })
        threading.Thread(
            target=self._run_update_previews_thread, args=(needed, base_jobnames), daemon=True
        ).start()

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
        self.compiling = False
        self.cancel_token = None
        # set_compiling() touches widgets -- runs via this signal (queued
        # onto the GUI thread automatically), same as _run_jobs_thread's
        # own use of it.
        self.signals.batch_done.emit()

    def _open_pdf(self, jobname: str) -> None:
        pdf_path = self._job_output_paths.get(jobname, PDF_DIR / f"{jobname}.pdf")
        if not pdf_path.exists():
            return
        try:
            open_path.open_in_default_app(pdf_path)
        except OSError as exc:
            self._log(f"*** couldn't auto-open {pdf_path.name}: {exc} ***")

    def _apply_progress(self, update: tuple) -> None:
        """Show a compile_progress.BatchProgress.feed() result: the thin bar
        and, while a job is running, the position in the status label."""
        fraction, text, finished = update
        bar = self.progress_bar
        if finished:
            bar.setRange(0, 1000)
            bar.setValue(1000)
            # Leave the full bar visible for a moment, then clear it -- unless
            # another batch has started meanwhile.
            QTimer.singleShot(1200, self._clear_progress_if_idle)
            return
        if fraction is None:
            if self._progress.active:
                bar.setRange(0, 0)           # size unknown: busy animation
            else:
                bar.setRange(0, 1000)
                bar.setValue(0)
            return
        bar.setRange(0, 1000)
        bar.setValue(round(fraction * 1000))
        if text and self._current_progress_base and self._progress.active:
            self.status_label.setText(f"{self._current_progress_base}: {text}")

    def _clear_progress_if_idle(self) -> None:
        if not self._progress.active and not self.compiling:
            self.progress_bar.setRange(0, 1000)
            self.progress_bar.setValue(0)

    def _copy_log(self) -> None:
        QGuiApplication.clipboard().setText(self.log_text.toPlainText())

    def _clear_log(self) -> None:
        self.log_text.clear()

    def _log(self, line: str) -> None:
        self.log_text.appendPlainText(line)

        progress_update = self._progress.feed(line)
        self._update_status_from_log(line)
        if progress_update is not None:
            self._apply_progress(progress_update)

    def _update_status_from_log(self, line: str) -> None:
        render_start = RENDER_START_RE.match(line)
        if render_start:
            self._current_progress_base = f"Rendering {render_start.group(1)}"
            self.status_label.setText(f"{self._current_progress_base}: starting...")
            return
        render_pass = RENDER_PASS_RE.match(line)
        if render_pass:
            self.status_label.setText(f"Done: rendered {render_pass.group(1)}")
            self._current_progress_base = ""
            return
        render_fail = RENDER_FAIL_RE.match(line)
        if render_fail:
            self.status_label.setText(f"Render failed: {render_fail.group(1)}")
            self._current_progress_base = ""
            return

        for pattern, status in (
            (RUNNING_LOG_RE, "running"),
            (MOVING_LOG_RE, "moving"),
            (PASS_LOG_RE, "pass"),
            (FAIL_LOG_RE, "fail"),
        ):
            match = pattern.match(line)
            if match:
                jobname = match.group(1)
                # "Update previews"' own temp megadeck (update_all_previews.py)
                # shares this same PASS log line with no other channel back to
                # the GUI -- excluded here unconditionally, not gated on the
                # checkbox, since nobody wants a 639-slide throwaway PDF
                # popping open regardless of their normal auto-open preference.
                is_preview_all = jobname.startswith(update_all_previews.JOBNAME_PREFIX)
                if status == "pass" and self.build_options.auto_open_checkbox.isChecked() and not is_preview_all:
                    self._open_pdf(jobname)
                if status in ("running", "moving"):
                    base = self._job_progress_texts.get(jobname, "")
                    if status == "running":
                        self._current_progress_base = base
                        if base:
                            self.status_label.setText(f"{base}: starting...")
                    elif base:
                        self.status_label.setText(f"{base}: compiled, relocating PDF...")
                break
        else:
            done_match = DONE_LOG_RE.match(line)
            if done_match:
                self.status_label.setText(f"Done: {done_match.group(1)}")
                return
            run_match = RUN_NUMBER_RE.match(line)
            if run_match and self._current_progress_base and not self._progress.active:
                # (with compile_progress tracking the job, _apply_progress()
                # writes the richer "pass 2/4, slide 137/395" text instead)
                run_number = run_match.group(1)
                self.status_label.setText(f"{self._current_progress_base}: Compile {run_number}...")

    def log(self, line: str) -> None:
        """Public entry point for the deck editor/slide source tab modules
        to append to the log pane -- always called from the main thread (a
        button/dialog action)."""
        self._log(line)

