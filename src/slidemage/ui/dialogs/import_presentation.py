# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Deck -> "Import PPTX/ODP…": each slide of a PowerPoint (.pptx) or OpenDocument Presentation
(.odp) file becomes a new slide at the end of a deck (slide_import.import_presentation). The import runs on
a worker; the sheet is the modal, so it shows the indicator and cannot be closed until the import ends."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QLineEdit, QMessageBox, QVBoxLayout

from ... import deck_editor, languages, slide_import
from ...deck_scan import Deck, scan_decks
from ...progress import Progress
from .. import background
from ..kit.tokens import SPACE
from ..kit.widgets import BusyIndicator, Button, Field, ModalSheet, SegmentedControl, Surface, caption

_log = logging.getLogger(__name__)

DESCRIPTION = (
    "Imports each slide of a PowerPoint (.pptx) or OpenDocument Presentation (.odp) file as a new "
    "slide, with real, editable text, not a picture of the original. A slide with no extractable "
    "text but at least one image becomes an image-only slide; a blank slide is skipped. The visual "
    "design of the source (tables, columns, diagrams) cannot be recovered: expect to clean up the result.")


class ImportPresentationSheet(ModalSheet):
    def __init__(self, app, current: Optional[Deck] = None) -> None:
        """`app` is the window; the slides go to the end of a deck, `current` by default."""
        super().__init__("Import PPTX/ODP", app, width=560)
        self.app = app
        self._worker: background.Handle | None = None
        self._decks = [deck for deck in scan_decks(app.project) if not deck.archived]
        body = Surface()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE.xl)
        note = caption(DESCRIPTION)
        layout.addWidget(note)

        file_row = Surface()
        row = QHBoxLayout(file_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.file_edit = QLineEdit()
        self.file_edit.setReadOnly(True)
        self.browse = Button("Browse…", "secondary")
        self.browse.clicked.connect(self._on_browse)
        row.addWidget(self.file_edit, 1)
        row.addWidget(self.browse)
        layout.addWidget(Field("File", file_row))

        self.deck_combo = QComboBox()
        for deck in self._decks:
            self.deck_combo.addItem(deck.name, deck)
        index = next((i for i, deck in enumerate(self._decks) if current and deck.path == current.path), -1)
        self.deck_combo.setCurrentIndex(max(index, 0))
        layout.addWidget(Field("Add to deck", self.deck_combo))
        codes = languages.project_languages(self.app.project).codes
        self.language = SegmentedControl([(code, code) for code in codes], current=codes[0])
        layout.addWidget(Field("Language of the slides", self.language))
        self.busy = BusyIndicator()
        layout.addWidget(self.busy)
        self.add_tab("", body)
        self.cancel_button = self.add_button("Cancel", role="reject")
        self.import_button = self.add_button("Import", kind="primary")
        self.import_button.clicked.connect(self._on_import)

    def _on_browse(self) -> None:
        chosen, _filter = QFileDialog.getOpenFileName(
            self, "Choose a presentation to import", "", "Presentations (*.pptx *.odp)")
        if chosen:
            self.file_edit.setText(chosen)

    def _on_import(self) -> None:
        if not self.file_edit.text():
            QMessageBox.critical(self, "Import", "Choose a file to import first.")
            return
        deck: Optional[Deck] = self.deck_combo.currentData()
        if deck is None:
            QMessageBox.critical(self, "Import", "This project has no active decks to import into.")
            return
        source = Path(self.file_edit.text())
        ctx = self.app.project
        if self.app.centre.is_dirty(deck.path):
            QMessageBox.critical(self, "Import", f"{deck.path.name} has unsaved edits. Save them before importing.")
            return
        workspace = self.app.assistant.workspace

        def is_dirty(path: Path) -> bool:
            return workspace.on_gui(lambda: self.app.centre.is_dirty(path), True)
        language = self.language.current() or languages.project_languages(ctx).codes[0]
        self._set_running(True)
        self.busy.start(f"Reading {source.name}…")
        self._worker = background.run_in_background_with_progress(
            lambda report: slide_import.import_presentation(
                ctx, source, deck, language, log=report, on_progress=report, is_dirty=is_dirty),
            self._on_progress, lambda summary, error: self._on_imported(summary, error, source, deck),
            parent=self, busy_reason="importing slides")

    def _set_running(self, running: bool) -> None:
        for widget in (self.browse, self.deck_combo, self.language, self.cancel_button, self.import_button):
            widget.setEnabled(not running)

    def _on_progress(self, value: str | Progress) -> None:
        """The worker reports log lines (str) and the bar (Progress) on one channel, so the log is written here."""
        if isinstance(value, Progress):
            self.busy.show_progress(value)
        else:
            self.app.log(value)

    def _on_imported(self, summary, error, source: Path, deck: Deck) -> None:
        self._worker = None
        self.busy.finish()
        self._set_running(False)
        if error is not None:
            QMessageBox.critical(self, "Import failed", f"Could not import {source.name}:\n\n{error}")
            return
        parts = [f"Imported {len(summary.imported)} slide(s) from {source.name} into {deck.name}"]
        if summary.skipped_blank:
            parts.append(f"({summary.skipped_blank} blank source slide(s) skipped)")
        self.accept()
        message = " ".join(parts)
        if summary.after is None:
            self.app.log(message)
            return
        message += ". Undo keeps the library slides and their IDs."
        entry = deck_editor.DeckUndo("Undo", {deck.path: (deck.text, summary.after)})
        warning = summary.warning
        try:
            self.app.after_deck_edit(deck.path, message, previous_text=entry)
        except Exception as exc:
            _log.exception("Could not refresh the deck after import")
            warning = " ".join(filter(None, (warning, f"Refresh failed: {exc}")))
        if warning:
            QMessageBox.warning(self.app, "Import saved", f"{message}\nWarning: {warning}")

    def reject(self) -> None:
        """No Cancel: a half-imported deck is worse than waiting (Escape and the close button end here too)."""
        if self._worker is None:
            super().reject()
