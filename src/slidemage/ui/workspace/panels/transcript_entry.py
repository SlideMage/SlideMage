"""Transcript entry: what the focused slide contributes to a student transcript (During or After
course; transcript.generate_single_slide() renders it from the slide's text as the Source view
holds it), and its summary.

The summary is a note that lives in media/alt-text.json, not in the .tex file, shown at the top of
the slide's entry. It is edited here (it moved from the Details view); a pending edit is saved when
the slide, the deck or the panel changes, so that it is never lost. Nothing is rendered for the
Instructor view: transcripts are made for the two student versions. The images' descriptions
belong to the Image descriptions panel, the text of the slide to its source."""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit

from .... import alt_images, transcript
from ....slide_language import bare_id
from ...kit import kit_qss as q
from ...kit.widgets import Button
from ..menus import VIEW_LABELS
from .base import Row, SidePanel, box, text


class TranscriptEntry(SidePanel):
    key = "transcript"
    title = "Transcript entry"

    def __init__(self, app, state) -> None:
        super().__init__(app, state)
        self._summary: Optional[QPlainTextEdit] = None
        self._save: Optional[Button] = None
        self._slide = ""   # the bare id the summary editor belongs to

    def suffix(self) -> str:
        return f"in {VIEW_LABELS[self.state.view]}"

    def meta(self) -> str:
        return "per version"

    def refresh(self) -> None:
        self._summary = self._save = None
        super().refresh()

    def build(self, id_slug: str) -> None:
        slide_id, view = bare_id(id_slug), self.state.view
        self._slide = slide_id
        entry = None
        if view in transcript.STUDENT_VERSIONS:
            try:
                entry = transcript.generate_single_slide(
                    self.slide_text(), slide_id, view, self.state.language.lower()).slides[0]
            except RuntimeError as exc:
                self.body.addWidget(text(str(exc), q.PANEL_MISSING))
        frame, layout = box()
        if view not in transcript.STUDENT_VERSIONS:
            row = Row(layout)
            row.body.addWidget(text("Transcripts are made for During course and After course only. Switch "
                                    "View as to see this slide's entry, or build them from the Compile menu.",
                                    q.DETAILS_LABEL))
        elif entry is not None:
            row = Row(layout)
            row.body.addWidget(text(f"Slide {slide_id} · {VIEW_LABELS[view]} · {self.state.language}", q.PANEL_MONO))
            row.body.addWidget(text(entry.title, q.PREVIEW_TITLE))
        self._add_summary(layout, entry.summary if entry is not None else self._stored_summary(slide_id))
        if entry is not None:
            row = Row(layout)
            row.body.addWidget(text(entry.body or "(no text)", q.DETAILS_VALUE))
            for image in entry.images:
                state = ("decorative" if image.role == alt_images.ROLE_DECORATIVE
                         else "described" if image.described else "no description yet")
                row.body.addWidget(text(f"Image {image.reference}: {state}", q.PANEL_CAPTION))
            if entry.source:
                row.body.addWidget(text(entry.source, q.PANEL_CAPTION))
        self.body.addWidget(frame)
        if entry is not None and entry.missing_description:
            self.body.addWidget(text("Some images have no description yet: write them in Image descriptions.",
                                     q.PANEL_CAPTION))
        self.body.addStretch(1)
        self.set_dirty(False)

    @staticmethod
    def _stored_summary(slide_id: str) -> str:
        return alt_images.load_slide_notes().get(slide_id, alt_images.SlideNotes()).summary

    def _add_summary(self, layout, summary: str) -> None:
        row = Row(layout)
        row.body.addWidget(text("Summary", q.DETAILS_LABEL))
        self._summary = QPlainTextEdit(summary)
        self._summary.setFixedHeight(64)
        self._summary.setPlaceholderText("Optional: shown at the top of this slide's transcript entry, "
                                         "before its body text.")
        self._save = Button("Save summary", "secondary", compact=True)
        self._save.setEnabled(False)
        # Connected after the initial text: showing the slide must not mark it changed.
        self._summary.textChanged.connect(self._edited)
        self._save.clicked.connect(self.flush)
        row.body.addWidget(self._summary)
        line = QHBoxLayout()
        line.addStretch(1)
        line.addWidget(self._save)
        row.body.addLayout(line)

    def _edited(self) -> None:
        self.set_dirty(True)
        self._save.setEnabled(True)

    def flush(self) -> None:
        """Save a pending summary (it has no Discard: leaving the slide or the deck saves it)."""
        if self._summary is None or not self.dirty:
            return
        slide_id, summary = self._slide, self._summary.toPlainText().strip()

        def mutate(notes: dict[str, alt_images.SlideNotes]) -> bool:
            notes.setdefault(slide_id, alt_images.SlideNotes()).summary = summary
            return True

        alt_images.update_slide_notes(mutate)
        self.set_dirty(False)
        self._save.setEnabled(False)
        self.app.log(f"Saved transcript summary for {slide_id}" if summary
                     else f"Cleared transcript summary for {slide_id}")
