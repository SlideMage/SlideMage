"""What the Images page runs on a model: drafting a slide or the whole project, translating, tuning
the prompt.

A mixin of ImagesPage (images.py), which holds the state these methods work on: the slide and forms
on show, the model pickers and the job card. One job runs at a time (image_jobs.Job, a QThread that
`background.stop_worker` can always end) and holds the app-wide Ollama slot for its whole life; a
cloud provider needs none, which the window's try_start_ollama_task decides.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Optional

from PySide6.QtWidgets import QCheckBox, QMessageBox

from ... import alt_draft, alt_images
from ...qt_ai_models import provider_from_combo
from .. import background
from .image_dialogs import PromptTuningSheet
from .image_form import ImageForm
from .image_jobs import Job, draft_work, translate_work


class ImageRunsMixin:
    def _translation_in_flight(self) -> bool:
        """Whether a form on show is waiting for its translation."""
        return self._translating is not None and self._translating in self._forms

    def _start(self, job: Job, detail: str, steps: int, on_outcome) -> None:
        """Run `job` (its Ollama slot is taken); `on_outcome(summary or exception)` follows on this thread."""
        self._job, self._on_outcome = job, on_outcome
        job.progress.connect(lambda index, total, image: self._on_progress(job, index, total, image))
        job.image_done.connect(lambda image, written: self._on_image_done(job, image, written))
        job.result.connect(self._on_job_result)
        self.job_card.start(job.title, detail, steps)
        self.app.log(f"{job.title}: {detail}")
        self._update_buttons()
        job.start()

    def _on_progress(self, job: Job, index: int, total: int, image: str) -> None:
        if job is not self._job:      # stopped meanwhile (its thread may still report)
            return
        self.job_card.set_progress(index, total, image)
        self.app.log(f"  [{index}/{total}] {image}")

    def _on_job_result(self, job: Job, outcome: object) -> None:
        if job is not self._job:      # stopped meanwhile: nobody waits for this
            return
        self._job, on_outcome = None, self._on_outcome
        job.wait()
        job.deleteLater()
        self.app.end_ollama_task(job.provider)
        self.job_card.hide()
        self._update_buttons()
        on_outcome(outcome)

    def _stop_clicked(self) -> None:
        job = self._job
        if job is None:
            return
        if self.job_card.single:    # one request, no queue to stop after: abort it
            self._abort_job()
            return
        job.stop_requested = not job.stop_requested   # a second click takes it back
        self.job_card.set_stopping(job.stop_requested)
        self.app.log("Stopping after the current image…" if job.stop_requested else "Stop rescinded: going on.")

    def _abort_job(self) -> None:
        """End the running job now (Stop on a single request, closing the window): its thread is kept
        until it has ended and gives the Ollama slot back then."""
        job, self._job = self._job, None
        if job is None:
            return
        provider = job.provider
        background.stop_worker(job, provider.abort, on_done=lambda: self.app.end_ollama_task(provider))
        self.job_card.hide()
        if self._translation_in_flight():
            self._translating.end_translation(alt_draft.TranslationResult(error="stopped"))
        self._translating = None
        self.app.log("Stopped.")
        self._update_buttons()

    def shutdown(self) -> None:
        """The window closes: no worker thread outlives it."""
        self._abort_job()

    def _on_image_done(self, job: Job, image: str, written: bool) -> None:
        """One image of a drafting run was written."""
        if written and job is self._job:
            self._refresh_states()

    def _finished_batch(self, verb: str, outcome: object, summary_line: str) -> None:
        if isinstance(outcome, Exception):
            self.app.log(f"*** {verb} failed: {outcome} ***")
        else:
            for line in outcome.errors:
                self.app.log(f"    {line}")
            self.app.log(summary_line)
        if self.dirty:
            self.app.log("The page is not refreshed while the form has unsaved edits; save them, then rescan.")
            self._refresh_states()
        else:
            self.reload(self._current_path())

    def _confirm_batch(self, title: str, text: str, details: str, also: str = "") -> tuple[bool, bool]:
        """Ask before a run that takes long: (whether to start, whether the extra checkbox `also`, if there is
        one, is ticked)."""
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.setInformativeText(details)
        checkbox = QCheckBox(also) if also else None
        if checkbox is not None:
            box.setCheckBox(checkbox)
        box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        box.button(QMessageBox.StandardButton.Ok).setText("Start")
        return box.exec() == QMessageBox.StandardButton.Ok, checkbox is not None and checkbox.isChecked()

    # drafting

    def _draft_backend(self) -> Optional[alt_draft.ModelBackend]:
        """The backend for the picked model; None (the user is told) when there is none or a cloud request
        was declined. Asked on the GUI thread, before an Ollama slot is reserved."""
        provider = provider_from_combo(self, self.draft_model, "the slide's text and the images to describe")
        return None if provider is None else alt_draft.ModelBackend(provider)

    def _draft_slide(self) -> None:
        view = self._current
        if view is None or self._job is not None:
            return
        jobs = alt_draft.slide_jobs(view.row, self._entries)
        if not jobs:
            QMessageBox.information(self, "Nothing to draft", "This slide's images are decorative, or are vector "
                                    "files the model cannot read.")
            return
        backend = self._draft_backend()
        if backend is None or not self.app.try_start_ollama_task("drafting descriptions", backend.provider):
            return
        job = Job("Drafting descriptions", backend.provider, draft_work(jobs, backend))
        self._start(job, f"{view.row.path.name} via {backend.label}", len(jobs), self._drafted)

    def _draft_all(self) -> None:
        backend = self._draft_backend()
        if backend is None or not self.app.try_start_ollama_task("drafting descriptions", backend.provider):
            return
        queue = alt_draft.images_needing_drafts()
        redraftable = alt_draft.images_needing_drafts(redraft_unless_model=backend.label)
        other_model = max(len(redraftable) - len(queue), 0)
        if not queue and not other_model:
            QMessageBox.information(self, "Nothing to draft",
                                    "Every describable image already has a draft or a reviewed description.")
            self.app.end_ollama_task(backend.provider)
            return
        go, again = self._confirm_batch(
            "Draft all descriptions", f"Draft {len(queue)} image(s) using {backend.label}?",
            "Each image is written to disk as it finishes, so you can stop any time and resume later: the queue is "
            "recomputed from the files.\n\nReviewed descriptions are never overwritten. Expect this to take hours; "
            "it runs in the background.",
            f"Also redraft {other_model} image(s) drafted by a different model" if other_model else "")
        if not go:
            self.app.end_ollama_task(backend.provider)
            return
        if again:
            queue = redraftable
        job = Job("Drafting image descriptions", backend.provider, draft_work(queue, backend))
        self._start(job, f"{len(queue)} image(s) via {backend.label}", len(queue), self._drafted)

    def _drafted(self, outcome: object) -> None:
        summary = outcome
        line = ""
        if not isinstance(outcome, Exception):
            line = (f"{'Stopped' if summary.stopped_early else 'Finished'}: {summary.written} image(s) drafted, "
                    f"{summary.skipped} skipped, {summary.failed} failed, in {summary.seconds / 60:.1f} min. "
                    + (f"{summary.fabrications} value table(s) removed as unreliable. " if summary.fabrications else "")
                    + (f"{summary.skipped_changed} skipped because you reviewed them mid-run. "
                       if summary.skipped_changed else "")
                    + "All drafts are unreviewed: check every number against the image.")
        self._finished_batch("Drafting", outcome, line)

    # tuning the prompt

    def _tune(self, form: ImageForm) -> None:
        view = self._current
        if view is None or self._job is not None:
            return
        provider = provider_from_combo(self, self.draft_model, "the slide's text and the image to describe")
        if provider is None:
            return
        found = alt_draft.draftable_images(replace(view.row, images=[form.reference]), self._entries)
        if not found:
            QMessageBox.information(self, "Nothing to draft", "The model cannot read this image: it is decorative, "
                                    "a vector file it cannot render, or the file is missing.")
            return
        if not self.app.try_start_ollama_task("tuning a description prompt", provider):
            return
        reference, resolved = found[0]
        sheet = PromptTuningSheet(self.app, reference, resolved, alt_draft.build_context(view.row.path, reference),
                                  provider, form.entry.hint, lambda: self.app.end_ollama_task(provider))
        if not sheet.exec() or sheet.result_draft is None:
            return
        result = sheet.result_draft
        # Written like any draft, so that the review state, the drafted-by marker and the guarantee that
        # a reviewed description is never overwritten are the same; only the prompt differed.
        if not alt_draft.apply_one_draft(reference, result, result.model, hint=sheet.hint):
            QMessageBox.warning(self, "Not written", "This image is reviewed (or was reviewed while the sheet was "
                                "open), so the draft was not written over it. Clear the review first to replace it.")
            return
        self.app.log(f"Tuned draft written for {view.row.path.name} [{reference}]")
        self._refresh_states()

    # translating

    def _translate_all(self) -> None:
        provider = provider_from_combo(self, self.translate_model, "the descriptions of all untranslated images")
        if provider is None or not self.app.try_start_ollama_task("translating images", provider):
            return
        backend = alt_draft.ModelTranslationBackend(provider)
        queue = alt_draft.images_needing_translation()
        if not queue:
            QMessageBox.information(self, "Nothing to translate", "Every image with English text already has a "
                                    "current (non-stale) German translation.")
            self.app.end_ollama_task(provider)
            return
        go, _again = self._confirm_batch(
            "Translate all images", f"Translate {len(queue)} image(s) into German using {backend.label}?",
            "Each image is written to disk as it finishes, so you can stop any time and resume later: the queue is "
            "recomputed from the files.\n\nThese are unreviewed translations, like a drafted description: check "
            "them before relying on them.")
        if not go:
            self.app.end_ollama_task(provider)
            return
        job = Job("Translating descriptions to German", provider, translate_work(queue, backend))
        self._start(job, f"{len(queue)} image(s) via {backend.label}", len(queue), self._translated)

    def _translated(self, outcome: object) -> None:
        line = ""
        if not isinstance(outcome, Exception):
            line = (f"{'Stopped' if outcome.stopped_early else 'Finished'} translating: {outcome.written} image(s) "
                    f"translated, {outcome.skipped} skipped, {outcome.failed} failed, in {outcome.seconds / 60:.1f} "
                    "min. All translations are unreviewed: check them before relying on them.")
        self._finished_batch("Translating", outcome, line)

    def _ask_which_english(self) -> Optional[str]:
        """The English text has unsaved changes: translate "unsaved", "disk" (what is saved) or "save" it first."""
        box = QMessageBox(self)
        box.setWindowTitle("Translate")
        box.setText("The English text has unsaved changes. Translate the current (unsaved) draft, the version "
                    "saved on disk, or save the draft first and then translate it?")
        unsaved = box.addButton("Unsaved draft", QMessageBox.ButtonRole.AcceptRole)
        disk = box.addButton("Version on disk", QMessageBox.ButtonRole.AcceptRole)
        save = box.addButton("Save, then translate", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(unsaved)
        box.exec()
        return {unsaved: "unsaved", disk: "disk", save: "save"}.get(box.clickedButton())

    def _translate_image(self, form: ImageForm, save_first: bool) -> None:
        """Translate one image's English text into the German fields of its form (nothing is saved)."""
        if self._job is not None:
            return
        english = form.english()
        if not save_first and english != form.saved_english():
            choice = self._ask_which_english()
            if choice is None:
                return
            if choice == "disk":
                english = form.saved_english()
            save_first = choice == "save"
        if save_first:
            if not self._save(reviewed=False):
                return
            english = form.english()
        provider = provider_from_combo(self, self.translate_model, "this image's description text")
        if provider is None or not self.app.try_start_ollama_task("translating this image", provider):
            return
        short, long, takeaway = english
        entry = alt_images.ImageEntry(image=form.reference, short=short, long=long, takeaway_default=takeaway)
        form.begin_translation(english)
        self._translating = form
        backend = alt_draft.ModelTranslationBackend(provider)
        job = Job("Translating to German", provider, lambda _job: backend.translate(entry))
        self._start(job, f"{form.reference} via {provider.label}", 1, lambda outcome: self._translated_one(form, outcome))

    def _translated_one(self, form: ImageForm, outcome: object) -> None:
        self._translating = None
        result = alt_draft.TranslationResult(error=str(outcome)) if isinstance(outcome, Exception) else outcome
        if form not in self._forms:
            self.app.log(f"Translation of {form.reference} finished after you left its slide: discarded.")
            return
        form.end_translation(result)
        if result.ok:
            self.app.log(f"Translated {form.reference} into German.")
        else:
            self.app.log(f"*** Translation of {form.reference} failed: {result.error} ***")
            QMessageBox.warning(self, "Translation failed", result.error or "Unknown error")
