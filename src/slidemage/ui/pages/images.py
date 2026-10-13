"""The Images page (UI_REDESIGN_PLAN.md, step 9): review the descriptions of every image.

Slide-centric, as the review always was: the left column lists the slides that show images with
their review state (image_nav.py), the right one shows the selected slide's images large enough to
check a number against the chart, each with the fields that describe it (image_form.py). A drafting
pass puts numbers read off charts into those descriptions, which is exactly where a model goes
wrong, so every draft is unreviewed until a person saves it as reviewed.

Everything about an image lives once in media/alt-text.json (alt_images.py), shared by the slides
that show it; only the takeaway can differ per slide and only the reviewed stamp is per (image,
slide). This page and the side panel are the only writers. What a form means for the store is
image_review's; drafting and translating are alt_draft's, run here as one job at a time on a thread
(image_jobs.py) that holds the Ollama slot (cloud models need none) and can be stopped.

An edit that is not saved yet is the page's `dirty`: it is saved as a draft when the slide, the
deck or the page changes, and counts for the close prompt like the side panels' pending edits.
"""
from __future__ import annotations

from pathlib import Path
from typing import Collection, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
)

from ... import alt_draft, alt_images, image_review, slide_language
from ..ai_models import fill_model_combo
from ..dialogs.transcript_preview import show_transcript_preview
from ..kit import kit_qss as q
from ..kit.widgets import Button, Card, Field, IconButton, SegmentedControl, Surface, caption
from .image_dialogs import ReplaceImageSheet
from .image_form import ImageForm, review_refused
from .image_jobs import Job, JobCard
from .image_nav import SlideNav
from .image_runs import ImageRunsMixin

LANGUAGES = (("en", "EN"), ("de", "DE"))
DRAFT_TIP = ("Draft every image that still needs one, unattended. Each image is written as it finishes, so it can "
             "be stopped and resumed later.")
TRANSLATE_TIP = ("Translate the short, long and takeaway text of every image that has English text and no current "
                 "German translation. Each image is written as it finishes.")


def review_label(image_count: int) -> str:
    """The review button says "all images" once there is more than one to check, so that it stands out."""
    return "Save and mark all images reviewed" if image_count > 1 else "Save and mark reviewed"


class ImagesPage(ImageRunsMixin, Surface):
    title = "Image descriptions"   # what the close prompt calls its unsaved edits
    closed = Signal()             # the back arrow

    def __init__(self, app, state, source) -> None:
        """`app` is the window: it logs, opens a slide in the Source view and holds the Ollama slot; `state` says
        which deck is open; `source` (the centre column) gives the Source view's buffers: slide_text, is_dirty, sync_source."""
        super().__init__()
        self.app, self.state, self.source = app, state, source
        self.dirty = False
        self._loaded = self._models_loaded = False
        self._entries: dict[str, alt_images.ImageEntry] = {}
        self._views: list[image_review.SlideView] = []
        self._current: Optional[image_review.SlideView] = None
        self._forms: list[ImageForm] = []
        self._language = LANGUAGES[0][0]
        self._job: Optional[Job] = None
        self._on_outcome = None          # what the running job's result is handed to
        self._translating: Optional[ImageForm] = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)
        self.nav = SlideNav(app.theme)
        self._build_batch_controls(self.nav.layout())
        outer.addWidget(self.nav)
        outer.addWidget(self._build_slide_column(), 1)

        self.nav.selected.connect(self._on_selected)
        self.nav.find_entered.connect(self.show_slide)
        self.nav.view_changed.connect(self._on_view_changed)
        self.nav.rescan_clicked.connect(self._on_rescan)
        self.nav.back_clicked.connect(self.closed)
        state.deck_changed.connect(self._on_deck_changed)
        self._show_slide(None)

    # -- building -----------------------------------------------------------------------------------

    def _build_batch_controls(self, layout: QVBoxLayout) -> None:
        self.draft_model, self.translate_model = QComboBox(), QComboBox()
        layout.addWidget(Field("Describe images with", self.draft_model))
        layout.addWidget(Field("Translate with", self.translate_model))
        buttons = QHBoxLayout()
        self.draft_all_button = Button("Draft all…", "primary")
        self.draft_all_button.setToolTip(DRAFT_TIP)
        self.draft_all_button.clicked.connect(self._draft_all)
        self.translate_all_button = Button("Translate all…", "secondary")
        self.translate_all_button.setToolTip(TRANSLATE_TIP)
        self.translate_all_button.clicked.connect(self._translate_all)
        buttons.addWidget(self.draft_all_button, 1)
        buttons.addWidget(self.translate_all_button, 1)
        layout.addLayout(buttons)

    def _build_slide_column(self) -> Card:
        card = Card()
        layout = card.layout()
        layout.setSpacing(10)
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.slide_title = QLabel("")
        self.slide_title.setObjectName(q.DETAILS_TITLE)
        self.slide_title.setWordWrap(True)
        self.slide_title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.slide_note = caption("")
        titles.addWidget(self.slide_title)
        titles.addWidget(self.slide_note)
        head.addLayout(titles, 1)
        self.languages = SegmentedControl(LANGUAGES, current=self._language, mono=True)
        self.languages.changed.connect(self._set_language)
        head.addWidget(self.languages, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(head)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.draft_button = Button("Draft this slide", "secondary", compact=True)
        self.draft_button.setToolTip("Draft this slide's images with the model above. Each draft is written to the "
                                     "store as unreviewed; reviewed descriptions are never overwritten.")
        self.draft_button.clicked.connect(self._draft_slide)
        self.clear_button = Button("Clear draft", "ghost", compact=True)
        self.clear_button.setToolTip("Discard this slide's unreviewed drafts. Never touches a reviewed description. "
                                     "An image used on other slides too is cleared for all of them.")
        self.clear_button.clicked.connect(self._clear_draft)
        self.open_button = IconButton("open_in_new", "Open this slide in the Source view")
        self.open_button.clicked.connect(self._open_source)
        self.transcript_button = IconButton("article", "Preview this slide's transcript entry")
        self.transcript_button.clicked.connect(self._preview_transcript)
        self.save_button = Button("Save draft", "secondary", compact=True)
        self.save_button.clicked.connect(lambda: self._save(reviewed=False))
        self.review_button = Button(review_label(1), "primary", compact=True)
        self.review_button.clicked.connect(lambda: self._save(reviewed=True))
        for widget in (self.draft_button, self.clear_button, self.open_button, self.transcript_button):
            actions.addWidget(widget)
        actions.addStretch(1)
        layout.addLayout(actions)
        saves = QHBoxLayout()
        saves.setSpacing(6)
        saves.addStretch(1)
        saves.addWidget(self.save_button)
        saves.addWidget(self.review_button)
        layout.addLayout(saves)

        self.job_card = JobCard(self._stop_clicked)
        layout.addWidget(self.job_card)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setObjectName(q.SURFACE)
        scroll.viewport().setObjectName(q.SURFACE)
        self.scroll = scroll
        self.forms_host = Surface()
        self.forms_layout = QVBoxLayout(self.forms_host)
        self.forms_layout.setContentsMargins(0, 0, 8, 0)
        self.forms_layout.addStretch(1)
        scroll.setWidget(self.forms_host)
        layout.addWidget(scroll, 1)
        return card

    # -- loading ------------------------------------------------------------------------------------

    def ensure_loaded(self) -> None:
        """The first scan, run when the page is first shown rather than at launch: it walks every slide,
        hashes the images they reference and syncs the store."""
        if not self._models_loaded:
            self.refresh_model_preferences()
        if not self._loaded:
            self._loaded = True
            self.reload()

    def refresh_model_preferences(self, models: Optional[list[str]] = None,
                                  vision_models: Optional[list[str]] = None) -> None:
        """(Re)fill both model pickers and preselect the defaults of Settings -> AI models: on the first
        show, and after the Settings sheet closed, so that a changed default reaches the open page."""
        self._models_loaded = True
        fill_model_combo(self.app.project, self.draft_model, "image_description", "(no vision models available)",
                         local_models=vision_models, vision_only=True)
        fill_model_combo(self.app.project, self.translate_model, "translation", "(no AI models available)",
                         local_models=models, fallback_local=alt_draft.DEFAULT_TRANSLATION_MODEL)
        self._update_buttons()

    def reload(self, preserve: Optional[Path] = None) -> None:
        """Scan the slides again (pending edits are saved as a draft first)."""
        self.flush()
        report = alt_images.sync_store(self.app.project)
        if report.added:
            self.app.log(f"alt-text store: added {len(report.added)} new image row(s).")
        if report.new_uses:
            self.app.log(f"alt-text store: {len(report.new_uses)} new slide/image reference(s) found.")
        self._entries = alt_images.load_store(self.app.project)
        self._views = image_review.scan_views(self.app.project, self._entries)
        self._populate(preserve or self._current_path())

    def _current_path(self) -> Optional[Path]:
        return self._current.row.path if self._current is not None else None

    def _order(self) -> dict[str, int]:
        deck = self.state.deck
        if self.nav.order != "deck" or deck is None or deck.is_test_deck:
            return {}
        return image_review.sort_order(deck)

    def _populate(self, preserve: Optional[Path] = None, *, row: int = 0) -> None:
        """List the slides again and show the one at `preserve`, else the one now at `row`. The slide
        already on show stays as it is (a translation may be under way in its forms)."""
        self.flush()
        view = self.nav.populate(self._views, self._entries, self._order(), preserve=preserve, row=row)
        if view is None or view is not self._current:
            self._show_slide(view)

    def _refresh_states(self, *, discard: Collection[str] = ()) -> None:
        """Read the store again and re-state every slide: a form was saved, or a worker wrote images.
        Forms without edits show what is stored now; a form with edits keeps them, except those of the
        images in `discard`, whose edits are given up for what is stored (even while a translation is
        on its way: the result is merged into whatever the form holds when it arrives)."""
        self._entries = alt_images.load_store(self.app.project)
        for view in self._views:
            view.state = image_review.slide_state(view.row, self._entries, view.slide_hash)
        self.nav.refresh_items(self._views, self._entries)
        if self._current is not None:
            self._set_slide_note(self._current)
            for form in self._forms:
                entry = alt_images.lookup(self._entries, form.reference) or alt_images.ImageEntry(image=form.reference)
                if form.reference in discard or (not form.changed and not form.translating):
                    form.rebase(entry, self._current.slide_hash)
                else:
                    form.refresh_entry(entry)
        self._edited()

    # -- the slide on show -----------------------------------------------------------------------------

    def _set_slide_note(self, view: image_review.SlideView) -> None:
        self.slide_note.setText(f"{view.row.path.name} · {alt_images.STATE_LABELS[view.state]}")

    def _show_slide(self, view: Optional[image_review.SlideView]) -> None:
        self._current = view
        for form in self._forms:
            form.setParent(None)
            form.deleteLater()
        self._forms = []
        if view is not None:
            row = view.row
            self.slide_title.setText(f"{row.slide_id} — {row.title}")
            self._set_slide_note(view)
            for reference in row.images:
                entry = alt_images.lookup(self._entries, reference) or alt_images.ImageEntry(image=reference)
                form = ImageForm(self.app, reference, entry, row.slide_id, view.slide_hash)
                form.set_language(self._language)
                form.set_availability(self._job is not None, self.translate_model.isEnabled())
                form.edited.connect(self._edited)
                form.replace_clicked.connect(self._replace_image)
                form.tune_clicked.connect(self._tune)
                form.translate_clicked.connect(self._translate_image)
                self.forms_layout.insertWidget(self.forms_layout.count() - 1, form)
                self._forms.append(form)
        else:
            self.slide_title.setText("No slide selected")
            self.slide_note.setText("Nothing is listed under this filter." if self._loaded else "")
        self.review_button.setText(review_label(len(self._forms)))
        self.scroll.verticalScrollBar().setValue(0)
        self._edited()
        self._update_buttons()

    def _on_selected(self, view: Optional[image_review.SlideView]) -> None:
        """The user chose a slide in the list: leave the one on show."""
        if view is self._current:
            return
        if not self._may_leave_translation():
            self.nav.select(self._current)
            return
        self.flush()
        self._show_slide(view)

    def _on_view_changed(self) -> None:
        """Another filter or order. A filter that no longer lists the slide on show means leaving it: the
        same question as for a click on another slide, and "No" puts the filter back."""
        if (not self.nav.lists(self._current, self._views, self._entries, self._order())
                and not self._may_leave_translation()):
            self.nav.restore_filter()
            return
        self._populate(self._current_path(), row=self.nav.current_row())

    def _may_leave_translation(self) -> bool:
        """False when a translation is on its way for a form on show and the user does not want to lose it
        by leaving the slide."""
        return not self._translation_in_flight() or QMessageBox.question(
            self, "Translation in progress",
            "A German translation is still being generated for an image on this slide. Switching to another "
            "slide now discards the result when it finishes. Switch anyway?") == QMessageBox.StandardButton.Yes

    def _on_rescan(self) -> None:
        if self._may_leave_translation():
            self.reload(self._current_path())

    def show_slide(self, text: str) -> None:
        """Jump to the slide `text` (an id or id-slug) whatever the filter shows."""
        match = image_review.find_slide(self._views, text)
        if match is None:
            QMessageBox.information(
                self, "Find slide",
                f"No slide matching \"{text}\" with any images was found. This page only lists slides that show "
                "at least one image.")
            return
        if match is not self._current and not self._may_leave_translation():
            return
        self.nav.set_filter(image_review.FILTER_ALL)
        self._populate(match.row.path)

    def _set_language(self, language: str) -> None:
        self._language = language
        for form in self._forms:
            form.set_language(language)

    def _on_deck_changed(self, _deck) -> None:
        """The order may follow the deck; what was typed belongs to the slide it was typed on."""
        if self._loaded:
            self._populate(self._current_path())
        else:
            self.flush()

    # -- unsaved edits ------------------------------------------------------------------------------------

    def _edited(self) -> None:
        dirty = any(form.changed for form in self._forms)
        if dirty != self.dirty:
            self.dirty = dirty
            self.state.set_dirty(dirty, "images")

    def flush(self) -> None:
        """Save what was typed as a draft (this slide's use of its images becomes unreviewed): before the
        slide, the deck or the page changes, and when the window closes."""
        if self.dirty and self._current is not None:
            self._save(reviewed=False)

    def _save(self, *, reviewed: bool) -> bool:
        """Store the forms of the slide on show; "reviewed" is refused while an informative image has no
        long description. Returns whether it was saved."""
        view = self._current
        if view is None:
            return False
        if reviewed and review_refused(self, [(form.reference, form.role, form.values()["long"])
                                              for form in self._forms]):
            return False
        row = view.row
        image_review.save_slide_forms(self.app.project, row.slide_id, row.path, [form.form_edit() for form in self._forms],
                                      reviewed=reviewed)
        self.app.log(f"{'Reviewed' if reviewed else 'Saved draft for'} {row.path.name}")
        view.slide_hash = alt_images.slide_context_hash(row.path)   # the slide may have changed since the scan
        self._refresh_states(discard=[form.reference for form in self._forms])
        if reviewed:   # on to the next slide that the filter lists
            self._populate(row.path, row=self.nav.current_row())
        return True

    # -- the slide's own actions ---------------------------------------------------------------------------

    def _open_source(self) -> None:
        if self._current is not None:
            self.app.open_slide_editor(self._current.row.path)

    def _preview_transcript(self) -> None:
        view = self._current
        if view is None:
            return
        row, id_slug = view.row, view.row.path.name.removesuffix(slide_language.CURRENT_SUFFIX)
        language = "de" if slide_language.own_language(id_slug) == "DE" else "en"
        show_transcript_preview(self.app, self.source.slide_text(row.path), row.slide_id, id_slug,
                                self.state.view, language)

    def _clear_draft(self) -> None:
        view = self._current
        if view is None:
            return
        entries = alt_images.load_store(self.app.project)
        clearable = [reference for reference in view.row.images
                     if (entry := alt_images.lookup(entries, reference)) is not None
                     and alt_images.image_state(entry) == alt_images.STATE_DRAFT]
        if not clearable:
            QMessageBox.information(
                self, "Nothing to clear",
                "Clear draft only removes an unreviewed description. None of this slide's images are in that state.")
            return
        shared = [reference for reference in clearable if len(alt_images.lookup(entries, reference).used_on) > 1]
        warning = ""
        if shared:
            warning = (f"\n\nNote: {', '.join(shared)} {'is' if len(shared) == 1 else 'are'} also used on other "
                       "slides: there is one shared description, so clearing it clears it everywhere.")
        if QMessageBox.question(self, "Clear draft", f"Discard the unreviewed draft for {', '.join(clearable)}?"
                                + warning) != QMessageBox.StandardButton.Yes:
            return

        def mutate(store: dict[str, alt_images.ImageEntry]) -> bool:
            changed = False
            for reference in clearable:
                entry = store.get(reference)
                if entry is not None and alt_images.image_state(entry) == alt_images.STATE_DRAFT:
                    entry.short = entry.long = entry.drafted_by = ""
                    changed = True
            return changed

        alt_images.update_store(self.app.project, mutate)
        self.app.log(f"Cleared draft(s) on {view.row.path.name}: {', '.join(clearable)}")
        self._refresh_states(discard=clearable)     # typed text would be saved again as a draft otherwise

    # -- replacing an image ----------------------------------------------------------------------------------

    def _replace_image(self, form: ImageForm) -> None:
        """Copy another file into media/ under a new name and point this slide (and, if asked, the other
        slides using the image) at it. The old file stays; so does its description unless nothing uses
        the image any more and the user agrees to delete it."""
        view = self._current
        if view is None or view.row.slide_id != form.slide_id:
            return
        others = sorted(slide_id for slide_id in form.entry.used_on if slide_id != form.slide_id)
        sheet = ReplaceImageSheet(self, self.app.project, form.reference, others)
        if not sheet.exec() or sheet.source is None:
            return
        self.flush()    # the forms are shown again once the slides are re-read
        try:
            image_review.copy_into_media(self.app.project, sheet.source, sheet.new_name)
        except OSError as exc:
            QMessageBox.critical(self, "Replace image", f"Could not copy the file: {exc}")
            return
        self.app.log(f"Copied {sheet.source} to media/{sheet.new_name}")
        rows = {v.row.slide_id: v.row for v in self._views}
        targets = {form.slide_id: view.row.path}
        if sheet.on_others.isChecked():
            targets.update({slide_id: rows[slide_id].path for slide_id in others if slide_id in rows})
        changed, failures = image_review.repoint_slides(
            self.app.project, form.entry, self._entries, targets, rows, form.reference, f"media/{sheet.new_name}",
            unsaved=self.source.is_dirty)
        for slide_id in changed:
            self.source.sync_source(targets[slide_id])   # a clean buffer of the slide shows the new reference
        if changed:
            self.app.log(f"Replaced {form.reference} with media/{sheet.new_name} on: " + ", ".join(changed))
        if failures:
            QMessageBox.warning(self, "Replace image", "Some slides could not be updated:\n\n" + "\n".join(failures))
        # Only if no slide shows the old image any more does its description describe nothing.
        if image_review.is_unused_after(form.entry, changed):
            if not image_review.has_text(form.entry):
                alt_images.delete_entry(self.app.project, form.entry.image)
            elif QMessageBox.question(
                    self, "Replace image",
                    f"\"{form.reference}\" is no longer used on any slide. Delete its now-unused description "
                    "(short, long, takeaway and source text)?") == QMessageBox.StandardButton.Yes:
                alt_images.delete_entry(self.app.project, form.entry.image)
                self.app.log(f"Deleted now-unused description for {form.entry.image}")
        self.reload(view.row.path)

    # -- jobs -------------------------------------------------------------------------------------------------

    def _update_buttons(self) -> None:
        busy, shown = self._job is not None, self._current is not None
        self.draft_button.setEnabled(shown and not busy and self.draft_model.isEnabled())
        self.draft_all_button.setEnabled(not busy and self.draft_model.isEnabled())
        self.translate_all_button.setEnabled(not busy and self.translate_model.isEnabled())
        self.clear_button.setEnabled(shown)
        for button in (self.open_button, self.transcript_button, self.save_button, self.review_button):
            button.setEnabled(shown)
        for form in self._forms:
            form.set_availability(busy, self.translate_model.isEnabled())
