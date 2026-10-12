"""The flows around a build: what the Compile menu, Export PPTX, Update previews and deck snapshots
ask and check before a run, and the work each hands to the compile controller (compile_controller.py).

Plain functions of the window (window.py), which provides `project`, `state`, `decks`, `compile` (the
controller), `build_options` and `log()`.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from ... import compile_log, compile_progress, compiler, deck_snapshot, latex_lint, open_path, partial_compile
from ... import pptx_export, slide_language, slide_snapshot, update_all_previews
from ...compile_status import job_title
from ...compiler import PDF_MOVE_RETRY_TOTAL_SECONDS, CompileJob, order_jobs, resolve_output_location, run_job, run_jobs
from ...deck_scan import Deck
from ...partial_compile import PartialError, parse_page_spec
from ..dialogs import snapshot as snapshot_sheets
from . import deck_actions, render_check
from .multi_compile import MultiCompileSheet


def _busy(window, message: str = "A compile run is already in progress.") -> bool:
    """Whether a run holds the compile slot (then the user is told)."""
    if window.compile.running:
        QMessageBox.information(window, "Busy", message)
    return window.compile.running


# -- stopping --------------------------------------------------------------------------

def ask_to_stop(window) -> None:
    if not window.compile.running:
        return
    reply = QMessageBox.question(
        window,
        "Stop creation",
        "Stop the compile run? The job currently compiling will be "
        "killed immediately (including latexmk's own lualatex/biber "
        "children); anything still queued after it will be skipped.",
    )
    if reply == QMessageBox.StandardButton.Yes:
        stop_now(window)


def stop_now(window) -> None:
    """Stop the run without asking (the chat's Stop does; the job panel's asks first)."""
    if window.compile.running:
        window.log(compile_log.stop_requested())
        window.compile.stop()


# -- the Compile menu --------------------------------------------------------------------

def compile_current(window, kind: str, pages: Optional[list[int]] = None) -> None:
    """A Compile menu entry for the current deck: `kind` is a view,
    "chapters" or "presenter" (compiler.build_jobs)."""
    deck = window.state.deck
    if deck is not None:
        jobs = compiler.build_jobs(deck, kind, pages)
        for job in jobs:
            job.language = window.state.language
        compile_jobs(window, jobs)


def compile_several(window) -> None:
    """Compile -> "Several decks…": the PDFs and transcripts ticked in
    MultiCompileSheet, on one compile run."""
    sheet = MultiCompileSheet(window, [deck for deck in window.decks if not deck.archived])
    if not sheet.exec():
        return
    chosen = sheet.chosen()
    jobs = [job for deck, kind in chosen if not kind.startswith("transcript:")
            for job in compiler.build_jobs(deck, kind)]
    transcripts = [(deck, kind.removeprefix("transcript:")) for deck, kind in chosen
                   if kind.startswith("transcript:")]
    if jobs:
        compile_jobs(window, jobs)
    if transcripts:
        failures = sum(not deck_actions.generate_deck_transcript(window, deck, version, quiet=True)
                       for deck, version in transcripts)
        window.log(f"==== Create Transcript: {len(transcripts) - failures} of "
                   f"{len(transcripts)} transcript(s) generated ====")


def compile_everything(window) -> None:
    """Compile -> "All decks except archive": every view of every active deck."""
    decks = [deck for deck in window.decks if not deck.archived]
    jobs = [job for deck in decks for job in compiler.build_jobs(deck, "all")]
    if jobs and QMessageBox.question(
            window, "Compile all decks",
            f"Compile {len(jobs)} PDF(s) of {len(decks)} deck(s), every view of each? "
            "The archive is left out.") == QMessageBox.StandardButton.Yes:
        compile_jobs(window, jobs)


def compile_pages(window) -> None:
    """Compile menu -> "Selected pages…": the Pages field of the old deck
    table. Takes the pages of the current view."""
    text, ok = QInputDialog.getText(
        window, "Selected pages",
        "Slides of the current view to compile, numbered as in the footers\n"
        "(e.g. 4, 5, 7-10, 15):")
    if not ok or not text.strip():
        return
    try:
        pages = parse_page_spec(text)
    except PartialError as exc:
        QMessageBox.warning(window, "Pages", str(exc))
        return
    compile_current(window, window.state.view, pages)


def compile_slides(window, slide_ids: list[str]) -> None:
    """The slide list's "Compile these pages": the frames the slides have in
    the current view's last whole-deck PDF, then the same path as Selected pages."""
    deck = window.state.deck
    if deck is None:
        return
    job = compiler.build_jobs(deck, window.state.view)[0]
    job.language = window.state.language
    try:
        pages = partial_compile.frames_for_slides(window.project, job, slide_ids)
    except PartialError as exc:
        QMessageBox.warning(window, "Compile pages", str(exc))
        return
    if not pages:
        QMessageBox.information(
            window, "Compile pages",
            "None of these slides is in the last whole-deck PDF of this view "
            "(not typeset there, or added since). Compile the whole deck first.")
        return
    compile_current(window, window.state.view, pages)


# -- compiling jobs ----------------------------------------------------------------------

def compile_jobs(window, jobs: list[CompileJob]) -> bool:
    """Compile `jobs` through the whole flow (prompts, job panel, Log drawer). False when the run
    did not start: busy, nothing to typeset, or the user cancelled a question."""
    if _busy(window):
        return False
    options = window.build_options
    run_id = datetime.now().isoformat(timespec="seconds")   # one id for everything this click compiles (PDF info /SlideMageRun)
    outputs: dict[str, Path] = {}   # jobname -> where its PDF lands (the deck's own \deckoutputfolder, or pdf/)
    for job in jobs:
        job.footer_timestamp = options.footer_timestamp_checkbox.isChecked()
        # \deckappendixtoc in the deck: always, checkbox or not
        job.appendix_toc = options.appendix_toc_checkbox.isChecked() or job.deck.appendix_toc
        job.replace_pages = options.replace_pages_checkbox.isChecked()
        job.run_id = run_id
        output_dir, output_stem = resolve_output_location(window.project, job)
        outputs[job.jobname] = output_dir / f"{output_stem}.pdf"
    jobs = order_jobs(jobs)   # version by version, then deck by deck
    jobs, empty_descriptions = _drop_empty_jobs(window.project, jobs)
    if not jobs:
        QMessageBox.critical(
            window, "Nothing to compile",
            "No slides to typeset -- every checked job is empty:\n\n"
            + "\n".join(f"  • {d}" for d in empty_descriptions),
        )
        return False
    if empty_descriptions:
        QMessageBox.warning(
            window, "Some jobs skipped",
            "Skipped (no slides to typeset):\n\n"
            + "\n".join(f"  • {d}" for d in empty_descriptions)
            + "\n\nCompiling the rest.",
        )
    jobs = _confirm_unchanged_jobs(window, jobs, outputs)
    if not jobs:
        return False
    # Pre-render syntax check (2026-09-26), scoped to exactly what these
    # jobs read: the deck files plus the slides their versions/chapters
    # actually include.
    if not _confirm_build(window, latex_lint.check_jobs(jobs), ", ".join(sorted({job.deck.name for job in jobs}))):
        return False

    def work(log: Callable[[str], None], cancel: compiler.CancelToken) -> None:
        results = run_jobs(window.project, jobs, log, cancel=cancel)
        passed = sum(1 for ok in results.values() if ok)
        log(f"==== Done: {passed} passed, {len(results) - passed} failed ====")

    window.compile.start(
        {job.jobname: job_title(job) for job in jobs},
        {job.jobname: compile_progress.spec_for_job(window.project, job) for job in jobs}, work,
        verb="Compiling", jobs=jobs, pdfs={job.jobname: outputs[job.jobname] for job in jobs})
    return True


def _confirm_build(window, result: latex_lint.CheckResult, what: str) -> bool:
    """The pre-render syntax check of a build: False when it found errors and the user cancelled."""
    return render_check.confirm_render(
        window, window, result, what, verb="Build",
        show_in_editor=lambda issue: render_check.open_issue_in_editor(window, issue))


def _confirm_unchanged_jobs(window, jobs: list[CompileJob], outputs: dict[str, Path]) -> list[CompileJob]:
    """Versions that haven't changed since their last compile
    (compiler.unchanged_jobs) are only compiled again after asking
    (2026-10-08, direct instruction): Compile anyway / Skip unchanged /
    Cancel. Returns the jobs to compile ([] = nothing)."""
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        unchanged = compiler.unchanged_jobs(window.project, jobs, outputs)
    finally:
        QApplication.restoreOverrideCursor()
    if not unchanged:
        return jobs
    box = QMessageBox(window)
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
        window.log(f"Nothing compiled: {', '.join(sorted(skipped))} unchanged.")
    return remaining


def _drop_empty_jobs(ctx, jobs: list[CompileJob]) -> tuple[list[CompileJob], list[str]]:
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
        if compile_progress.count_job_slides(ctx, job.deck, job.version, job.chapter, job.language) > 0:
            surviving.append(job)
            continue
        where = job.deck.name
        if job.chapter is not None:
            where += f", chapter {job.chapter.order} ({job.chapter.title})"
        if job.version:
            where += f" ({job.version})"
        descriptions.append(where)
    return surviving, descriptions


# -- deck snapshots ----------------------------------------------------------------------

def start_snapshots(
    window, decks: list[Deck], options: deck_snapshot.SnapshotOptions,
    after: Optional[Callable[[list], None]] = None,
) -> bool:
    """Ask about older snapshots, then run deck_snapshot.snapshot_decks()
    on the compile slot. `after(results)` replaces the summary dialog (the
    archive flow). False when nothing was started."""
    if _busy(window):
        return False
    existing = deck_snapshot.find_snapshots([d.name for d in decks], root=window.project.root)
    delete_old: list = []
    if existing:
        answer = snapshot_sheets.ask_about_old_snapshots(window, existing)
        if answer == snapshot_sheets.CANCEL_RUN:
            return False
        if answer == snapshot_sheets.DELETE_OLD:
            delete_old = existing
    # Same footer/appendix choices as a compile from the toolbar.
    options.footer_timestamp = window.build_options.footer_timestamp_checkbox.isChecked()
    options.appendix_toc = True if window.build_options.appendix_toc_checkbox.isChecked() else None

    specs: dict[str, compile_progress.JobSpec] = {}
    texts: dict[str, str] = {}
    for i, deck in enumerate(decks, 1):
        for job in deck_snapshot.snapshot_jobs(deck, options):
            spec = compile_progress.spec_for_job(window.project, job)
            prefix = f"Snapshot {i}/{len(decks)}, {deck.name}"
            key = deck_snapshot.progress_key(job.jobname)
            specs[key], texts[key] = spec, f"{prefix}: compiling {job.jobname}"
            if options.verify:
                key = deck_snapshot.progress_key(job.jobname, verify=True)
                specs[key], texts[key] = spec, f"{prefix}: checking {job.jobname}"

    def work(log: Callable[[str], None], cancel: compiler.CancelToken) -> list:
        try:
            results = deck_snapshot.snapshot_decks(
                decks, options, log, cancel=cancel, delete_old=delete_old, ctx=window.project)
        except Exception as exc:  # noqa: BLE001 -- reported, the slot must still be freed
            log(f"*** Deck snapshots failed: {exc} ***")
            results = [deck_snapshot.SnapshotResult(d.name, ok=False, error=str(exc)) for d in decks]
        log(f"==== Done: {sum(1 for r in results if r.ok)} of {len(results)} snapshot(s) created ====")
        return results

    window.compile.start(texts, specs, work, on_done=after or (
        lambda results: snapshot_sheets.show_summary(window, window.project, results)))
    return True


# -- Export PPTX -------------------------------------------------------------------------

def export_pptx(window, deck: Deck) -> None:
    """Compiles `deck` (instructor version, direct instruction -- the
    fullest-content version, matching what update_all_previews.py's
    own snapshot refresh already treats as this project's "real"
    default) and exports the result as a .pptx with one full-page
    image per PDF page -- see pptx_export.py's own docstring for why
    one PDF page per pptx slide (every beamer overlay/reveal as its
    own slide) rather than one pptx slide per \\slide{} call, and why
    python-pptx rather than a hand-rolled OOXML package.

    The compile slot is the same single-flight guard a real "Create PDF"
    batch checks -- this runs a real latexmk invocation of its own, which
    can't safely run alongside another one."""
    if _busy(window, "Can't export to PowerPoint while a compile run is in progress -- wait for it to finish first."):
        return
    if compile_progress.count_job_slides(window.project, deck, "instructor", None) == 0:
        QMessageBox.critical(window, "Nothing to export", f"{deck.name} has no slides to typeset.")
        return
    job = CompileJob(deck, version="instructor", chapter=None)
    if not _confirm_build(window, latex_lint.check_jobs([job]), deck.name):
        return
    window.compile.start(
        {job.jobname: f"Export {deck.name} to PowerPoint"}, {job.jobname: compile_progress.spec_for_job(window.project, job)},
        lambda log, cancel: _export_pptx(window.project, job, log, cancel), failure="PowerPoint export")


def _export_pptx(context, job: CompileJob, log: Callable[[str], None], cancel: compiler.CancelToken) -> None:
    deck = job.deck
    log(f"==== Exporting {deck.name} to PowerPoint (instructor version) ====")
    # run_job() itself already logs its own "==== PASS/FAIL: ... ====" lines (picked up by the same
    # log handler every other compile goes through, auto-opening the compiled PDF too if that
    # checkbox is on) -- nothing extra needed here for the compile step itself, only for what happens
    # after it.
    #
    # run_job() doesn't wait for the PDF's move into pdf/ (it backgrounds that so one job's stuck
    # sync client can't block the rest of a batch's queue -- see its own docstring), so reading
    # .build/<jobname>.pdf right after it returns races that same background thread, which copies
    # the PDF out and then deletes every .build/<jobname>.* file, this PDF included -- there's
    # nothing else queued behind a one-off export, so waiting here for on_relocated costs nothing
    # and avoids reading a file that thread may have already removed.
    relocated = threading.Event()
    outcome: dict[str, object] = {"ok": False, "dest_pdf": None}

    def on_relocated(ok: bool, dest_pdf: Path) -> None:
        outcome["ok"] = ok
        outcome["dest_pdf"] = dest_pdf
        relocated.set()

    if not run_job(context, job, log, cancel=cancel, on_relocated=on_relocated):
        log(f"*** FAIL: PowerPoint export of {deck.name} -- compile failed, see above ***")
        return
    # Generous margin over the retry loop's own total budget -- this thread has nothing else to do
    # but wait for it anyway.
    relocated.wait(PDF_MOVE_RETRY_TOTAL_SECONDS + 30)
    if not outcome["ok"]:
        log(f"*** FAIL: PowerPoint export of {deck.name} -- couldn't move the compiled PDF into place, see above ***")
        return
    out_path = context.pdf_dir / f"{job.jobname}.pptx"
    try:
        pptx_export.export_deck_to_pptx(outcome["dest_pdf"], out_path, log=log)
    except Exception as exc:  # noqa: BLE001 -- surfaced, not swallowed
        log(f"*** FAIL: PowerPoint export of {deck.name} -- {exc!r} ***")
        return
    log(f"==== PASS: {out_path.relative_to(context.root)} ====")
    # Always opened, unlike the auto-open-PDF checkbox -- this is a single, deliberate export the
    # user just asked for, not a batch that could pop open many windows unattended.
    try:
        open_path.open_in_default_app(out_path)
    except OSError as exc:
        log(f"*** couldn't auto-open {out_path.name}: {exc} ***")


# -- Update previews ---------------------------------------------------------------------

def update_previews(window) -> None:
    """No template picker any more (2026-08-16, direct instruction:
    "I forgot that each deck has a specific template linked to it" --
    there's nothing to pick, every deck already carries its own).
    Scans every deck for which (template, slide) combinations it
    actually needs (update_all_previews.needed_slides_by_template())
    and shows that in the confirmation dialog, so the count reflects
    exactly what's about to be compiled -- not "every slide file in
    the project" the way the old single-template design counted.
    """
    if _busy(window):
        return
    needed = update_all_previews.needed_slides_by_template(window.project)
    if not needed:
        QMessageBox.information(window, "Nothing to do", "No deck references any slides right now.")
        return
    total_slides = sum(len(ids) for ids in needed.values())
    template_names = [slide_snapshot.TEMPLATES.get(t, t) for t in sorted(needed)]
    reply = QMessageBox.question(
        window, "Update previews",
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
    if not _confirm_build(
            window,
            latex_lint.check_slide_files(
                window.project.slides_dir / slide_language.current_name(slug) for slug in all_slides),
            f"{len(all_slides)} slides"):
        return

    # This operation builds its own temp deck/CompileJob entirely inside update_all_previews.run(),
    # with no channel back to this module except the log stream, so the run's rows are registered
    # here first: one jobname per template (there can be several, run one after another), generated
    # here rather than left to run() so both sides agree on the exact strings ahead of time.
    # "-instructor" matches CompileJob.jobname's own "-{version}" suffix (compiler.py) --
    # update_all_previews.run() always compiles the instructor version.
    base_jobnames = {template: f"{update_all_previews.JOBNAME_PREFIX}{uuid.uuid4().hex[:8]}" for template in needed}
    labels = {f"{base}-instructor": f"Update previews ({slide_snapshot.TEMPLATES.get(template, template)})"
              for template, base in base_jobnames.items()}

    def work(log: Callable[[str], None], cancel: compiler.CancelToken) -> None:
        try:
            ok = update_all_previews.run(window.project, log, cancel=cancel, base_jobnames=base_jobnames, needed=needed)
        except Exception as exc:  # noqa: BLE001 -- reported, batch must still clean up state
            log(f"*** Update previews failed: {exc} ***")
            ok = False
        log("==== Update previews: compile finished ====" if ok else "==== Update previews: FAILED ====")

    # One throw-away megadeck per template (with a bibliography, so 4 passes), each typesetting that
    # template's own slides. Nobody wants a 639-slide throwaway PDF popping open, whatever the
    # auto-open checkbox says.
    window.compile.start(
        labels,
        {f"{base}-instructor": compile_progress.JobSpec(
            compile_progress.PASSES_WITH_BIBLIOGRAPHY, len(needed[template]), estimated=True)
         for template, base in base_jobnames.items()},
        work, opens_pdfs=False)
