r"""Speaker notes: the \note{...} calls of the focused slide, as plain editable text.

Beamer's notes are the instructor's and never reach a student transcript. The parsing and the
edits of the source text are slide_source's (note_calls, replace_note, remove_note, add_note).
An edit does not write the file itself: it goes into the Source view's buffer of the slide
(CentreColumn.edit_slide_text), and "Save notes" then saves that buffer the way Save in the
Source view does -- with its version prompt, backup and deck questions -- so a note is never
saved by a route that skips them. Pending text is moved to the buffer (unsaved) when the slide,
the deck or the panel changes. A frozen version is read-only here, as in the Source view."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit

from .... import slide_language, slide_source
from ...kit import kit_qss as q
from ...kit.widgets import Button
from .base import Row, SidePanel, box, text


class SpeakerNotes(SidePanel):
    key = "notes"
    title = "Speaker notes"

    def __init__(self, app, state) -> None:
        super().__init__(app, state)
        self._path: Optional[Path] = None
        self._shown: list[str] = []                 # the notes' contents as they were shown
        self._edits: list[QPlainTextEdit] = []      # one per shown note
        self._new: Optional[QPlainTextEdit] = None  # a note to add

    def suffix(self) -> str:
        return "instructor only"

    def meta(self) -> str:
        count = len(slide_source.note_calls(self.slide_text()))
        return str(count) if count else ""

    def refresh(self) -> None:
        self._edits, self._new = [], None
        super().refresh()

    def build(self, id_slug: str) -> None:
        self._path = self.slide_path()
        calls = slide_source.note_calls(self.slide_text())
        self._shown = [c.content for c in calls]
        editable = self._path is not None and slide_language.is_current_file(self._path)
        frame, layout = box()
        for number, call in enumerate(calls, start=1):
            row = Row(layout)
            row.body.addWidget(text(f"Note {number}" + (f" · {call.overlay}" if call.overlay else ""), q.PANEL_MONO))
            self._edits.append(self._editor(row, call.content, "", editable))
        row = Row(layout)
        if editable:
            row.body.addWidget(text("New note" if calls else "No notes on this slide.", q.DETAILS_LABEL))
            self._new = self._editor(row, "", "What the instructor says here…", True)
        else:
            row.body.addWidget(text("This is a frozen version: its notes are read-only.", q.DETAILS_LABEL)
                               if calls else text("No notes on this slide.", q.DETAILS_LABEL))
        self.body.addWidget(frame)
        if editable:
            line = QHBoxLayout()
            line.addStretch(1)
            self._save = Button("Save notes", "primary", compact=True)
            self._save.setToolTip("Put the notes into the slide and save it, with the usual question how "
                                  "significant the change is.")
            self._save.clicked.connect(self._save_notes)
            line.addWidget(self._save)
            self.body.addLayout(line)
        self.body.addStretch(1)
        self.set_dirty(False)

    def _editor(self, row: Row, content: str, placeholder: str, editable: bool) -> QPlainTextEdit:
        edit = QPlainTextEdit(content)
        edit.setPlaceholderText(placeholder)
        edit.setReadOnly(not editable)
        edit.setFixedHeight(76)
        edit.textChanged.connect(lambda: self.set_dirty(True))   # connected after the text: showing is no edit
        row.body.addWidget(edit)
        return edit

    # -- editing ---------------------------------------------------------------------------

    def _apply(self) -> bool:
        """Put the typed notes into the Source view's buffer of the slide. False when the slide's
        notes are no longer the ones shown (they were edited in the Source view meanwhile)."""
        shown, typed = self._shown, [e.toPlainText().strip() for e in self._edits]
        added = self._new.toPlainText().strip() if self._new is not None else ""
        applied = []

        def change(source: str) -> str:
            if [c.content for c in slide_source.note_calls(source)] != shown:
                return source
            for index in reversed(range(len(shown))):
                if not typed[index]:
                    source = slide_source.remove_note(source, index)
                elif typed[index] != shown[index].strip():
                    source = slide_source.replace_note(source, index, typed[index])
            if added:
                source = slide_source.add_note(source, added)
            applied.append(True)
            return source

        done = self.app.centre.edit_slide_text(self._path, change)
        if done and not applied:
            self.app.log(f"The notes of {self._path.name} changed in the Source view; the panel shows them again.")
        return done and bool(applied)

    def flush(self) -> None:
        if self.dirty and self._path is not None:
            if self._apply():
                self.set_dirty(False)
            else:
                self.app.log(f"The typed notes of {self._path.name} could not be applied.")

    def _save_notes(self) -> None:
        if self._apply():
            self.app.centre.source.save()
        self.set_dirty(False)
        self.refresh()
