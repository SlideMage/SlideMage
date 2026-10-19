# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Image descriptions: the images of the focused slide, with role, short and long description and
review state, editable here.

A save goes through alt_images.save_slide_image() (the same store, media/alt-text.json, as the
Images page, which has all the fields and the batch drafting): "Save draft" keeps the text unreviewed for this slide,
"Mark reviewed" confirms the image and this slide's use of it. Redraft asks the vision model
of the active route (Local, Claude Code or the API, with the one-time cloud consent) for a new
description and puts it into the fields; nothing is stored until it is saved. A pending edit is
saved as a draft when the slide, the deck or the panel changes. The Reference / citation is the full editor's
field for the panel's language (source or source_de), saved with the rest and with its own review state
(alt_images.source_state): a change makes it "To review", "Mark reviewed" under it confirms it at once.
The takeaway and the German descriptions are the Images page's."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit

from .... import alt_blocks, alt_draft, alt_images, image_review
from ....ai import ai_profile, resolver
from ....project import ProjectContext
from ....slide_language import bare_id
from ...ai_models import built, cloud_label, task_route
from ...kit import kit_qss as q
from ...kit.widgets import Button, Chip, SegmentedControl
from ...pages.image_form import ROLES, SOURCE_SPECS, STATE_TONES, SourceStatus, labelled_edit, review_refused
from ...text import plural
from .base import Row, SidePanel, box, empty_row, text

THUMBNAIL = 56
PIXMAP_SUFFIXES = (".png", ".jpg", ".jpeg")


class ImageForm(Row):
    """One image: what is typed is `role`, `short`, `long` and the source of `language`; `baseline` and
    `source_baseline` ((source, source_de)) are what the store had."""

    def __init__(self, layout, project: ProjectContext, reference: str, entry: Optional[alt_images.ImageEntry],
                 state: str, language: str) -> None:
        super().__init__(layout)
        self.reference = reference
        entry = entry or alt_images.ImageEntry(image=reference)
        self.baseline = (entry.role, entry.short, entry.long)
        self.source_baseline = (entry.source, entry.source_de)
        self.source_key = "source_de" if language == "DE" else "source"
        self.source_stored = alt_images.source_state(entry)
        head = QHBoxLayout()
        resolved = alt_blocks.resolve_image(project, reference)
        picture = QLabel()
        picture.setFixedSize(THUMBNAIL, THUMBNAIL)
        pixmap = QPixmap(str(resolved)) if resolved is not None and resolved.suffix.lower() in PIXMAP_SUFFIXES else None
        if pixmap is not None and not pixmap.isNull():
            picture.setPixmap(pixmap.scaled(THUMBNAIL, THUMBNAIL, Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation))
        head.addWidget(picture)
        info = text(reference, q.PANEL_MONO)
        info.setToolTip(reference)
        head.addWidget(info, 1)
        self.state_chip = Chip(alt_images.STATE_LABELS[state], STATE_TONES[state])
        head.addWidget(self.state_chip, 0, Qt.AlignmentFlag.AlignTop)
        self.body.addLayout(head)

        self.roles = SegmentedControl(ROLES, current=self.baseline[0])
        self.body.addWidget(self.roles)
        self.short_edit = self._edit("Short description (the figure's caption)", self.baseline[1], 48)
        self.long_edit = self._edit("Long description (what a student who cannot see it needs to know)",
                                    self.baseline[2], 110)
        shown = self.source_baseline[1] if self.source_key == "source_de" else self.source_baseline[0]
        self.source_edit, source_field = labelled_edit(SOURCE_SPECS[self.source_key], shown)
        self.body.addWidget(source_field)
        self.source_status = SourceStatus()
        self.body.addWidget(self.source_status)
        self.source_edit.textChanged.connect(self.show_source)
        self.show_source()
        self.note = text("", q.PANEL_CAPTION)
        self.note.hide()
        self.body.addWidget(self.note)
        buttons = QHBoxLayout()
        self.project = project
        self.redraft_button = Button(cloud_label(project, "Redraft…"), "secondary", compact=True)
        self.redraft_button.setToolTip("Ask the vision model of the active AI route (AI setup) for a "
                                       "new description. It fills the fields; nothing is saved until you save.")
        self.save_button = Button("Save draft", "secondary", compact=True)
        self.review_button = Button("Mark reviewed", "primary", compact=True)
        buttons.addWidget(self.redraft_button)
        buttons.addStretch(1)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.review_button)
        self.body.addLayout(buttons)

    def _edit(self, placeholder: str, value: str, height: int) -> QPlainTextEdit:
        edit = QPlainTextEdit(value)
        edit.setPlaceholderText(placeholder)
        edit.setFixedHeight(height)
        self.body.addWidget(edit)
        return edit

    @property
    def role(self) -> str:
        return self.roles.current() or alt_images.ROLE_INFORMATIVE

    def values(self) -> tuple[str, str, str]:
        return self.role, self.short_edit.toPlainText().strip(), self.long_edit.toPlainText().strip()

    def source_text(self) -> str:
        return self.source_edit.toPlainText().strip()

    def typed_source(self) -> tuple[str, str]:
        """(source, source_de) as the store would have them: the other language's as it was shown."""
        typed = self.source_text()
        return (self.source_baseline[0], typed) if self.source_key == "source_de" else (typed, self.source_baseline[1])

    def show_source(self) -> None:
        self.source_status.show_state(self.source_stored, self.typed_source(), self.source_baseline)

    @property
    def changed(self) -> bool:
        return self.values() != self.baseline or self.typed_source() != self.source_baseline


class ImageDescriptions(SidePanel):
    key = "images"
    title = "Image descriptions"

    drafted = Signal(str, str, object, object)   # slide id, reference, whose Ollama slot to give back, alt_draft.DraftResult

    def __init__(self, app, state, actions) -> None:
        super().__init__(app, state, actions)
        self._forms: list[ImageForm] = []
        self._slide: Optional[tuple[str, Path]] = None   # (bare id, file) the forms belong to
        self.drafted.connect(self._on_drafted)

    def meta(self) -> str:
        count = len(alt_blocks.referenced_images(self.slide_text()))
        return plural(count, "image")

    def refresh(self) -> None:
        self._forms.clear()
        super().refresh()

    def refresh_route(self) -> None:
        for form in self._forms:
            form.redraft_button.setText(cloud_label(form.project, "Redraft…"))

    def build(self, id_slug: str) -> None:
        path = self.slide_path()
        references = alt_blocks.referenced_images(self.slide_text()) if path is not None else []
        slide_id = bare_id(id_slug)
        self._slide = (slide_id, path) if path is not None else None
        frame, layout = box()
        if not references:
            empty_row(layout, "No images on this slide.")
        else:
            entries = alt_images.load_store(self.app.project)
            slide_hash = alt_images.slide_context_hash(path)
            for reference in references:
                entry = alt_images.lookup(entries, reference)
                state = image_review.image_state(entries, reference, slide_id, slide_hash)
                form = ImageForm(layout, self.app.project, reference, entry, state, self.state.language)
                form.roles.changed.connect(lambda _role: self._edited())
                form.short_edit.textChanged.connect(self._edited)
                form.long_edit.textChanged.connect(self._edited)
                form.source_edit.textChanged.connect(self._edited)
                form.source_status.review_clicked.connect(lambda f=form: self._review_source(f))
                form.redraft_button.clicked.connect(lambda _=False, f=form: self._redraft(f))
                form.save_button.clicked.connect(lambda _=False, f=form: self._save(f, reviewed=False))
                form.review_button.clicked.connect(lambda _=False, f=form: self._save(f, reviewed=True))
                self._forms.append(form)
        self.place(frame)
        self.set_dirty(False)

    # -- saving --------------------------------------------------------------------------

    def _edited(self) -> None:
        self.set_dirty(any(form.changed for form in self._forms))

    def _save(self, form: ImageForm, *, reviewed: bool) -> None:
        role, short, long = form.values()
        if reviewed and review_refused(self, [(form.reference, role, long)]):
            return
        self._store(form, reviewed)
        self.refresh()

    def _store(self, form: ImageForm, reviewed: bool) -> None:
        """Save the form: only what changed since it was shown, a source apart (it goes to review)."""
        slide_id, path = self._slide
        role, short, long = form.values()
        alt_images.save_slide_image(self.app.project, form.reference, slide_id, path, role=role, short=short,
                                    long=long, reviewed=reviewed, baseline=form.baseline)
        if form.typed_source() != form.source_baseline:
            alt_images.save_source(self.app.project, form.reference, **{form.source_key: form.source_text()})
        self.app.log(f"{'Reviewed' if reviewed else 'Saved draft of'} {form.reference} on {path.name}")

    def _review_source(self, form: ImageForm) -> None:
        """Confirm the stored citation at once, apart from the description's Save."""
        entry = alt_images.mark_source_reviewed(self.app.project, form.reference)
        if entry is not None:
            form.source_stored = alt_images.source_state(entry)
            form.show_source()

    def flush(self) -> None:
        """Save what was typed as drafts (this slide's use of the image becomes unreviewed)."""
        if not self.dirty or self._slide is None:
            return
        for form in [f for f in self._forms if f.changed]:
            self._store(form, reviewed=False)
            form.baseline, form.source_baseline = form.values(), form.typed_source()
        self.set_dirty(False)

    # -- redrafting ---------------------------------------------------------------------------

    def _redraft(self, form: ImageForm) -> None:
        slide_id, path = self._slide
        row = alt_blocks.SlideRow(path=path, slide_id=slide_id, title="", images=[form.reference])
        found = alt_draft.draftable_images(self.app.project, row, {})
        if not found:
            QMessageBox.information(self, "Redraft", "The model cannot read this image: it is a vector file "
                                    "it cannot render, or the file is missing.")
            return
        route = task_route(self, self.app.project, ai_profile.IMAGE_DESCRIPTION, "the slide's text and this image")
        backend = None if route is None else built(self, resolver.draft_backend, self.app.project, route)
        if backend is None or not self.app.try_start_ollama_task("drafting a description", backend.provider):
            return
        form.redraft_button.setEnabled(False)
        form.note.setText(f"Drafting with {backend.label}…")
        form.note.show()
        context = alt_draft.build_context(self.app.project, path, form.reference)
        threading.Thread(target=self._draft_bg, args=(slide_id, form.reference, backend.provider, backend, found[0][1], context),
                         daemon=True).start()

    def _draft_bg(self, slide_id: str, reference: str, provider, backend, resolved: Path, context) -> None:
        try:
            result = backend.draft(resolved, context)
        except Exception as exc:  # noqa: BLE001 -- shown on the form; the slot must still be given back
            result = alt_draft.DraftResult(error=str(exc) or type(exc).__name__)
        self.drafted.emit(slide_id, reference, provider, result)

    def _on_drafted(self, slide_id: str, reference: str, provider, result) -> None:
        self.app.end_ollama_task(provider)
        if self._slide is None or self._slide[0] != slide_id:
            return
        form = next((f for f in self._forms if f.reference == reference), None)
        if form is None:
            return   # the slide changed meanwhile
        form.redraft_button.setEnabled(True)
        if not result.ok:
            form.note.setText(f"The draft failed: {result.error or 'the model gave no description'}")
            return
        form.short_edit.setPlainText(result.short)
        form.long_edit.setPlainText(result.long)
        suggestion = " The model suggests this image is decorative." if result.role_suggestion == alt_images.ROLE_DECORATIVE else ""
        form.note.setText(f"Drafted by {result.model}: check it, then save.{suggestion}")
        form.note.show()
