"""Deck -> "Import PPTX/ODP…": each slide of a PowerPoint (.pptx) or OpenDocument Presentation
(.odp) file becomes a new slide at the end of a deck (slide_import.import_presentation)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QLineEdit, QMessageBox, QVBoxLayout

from ... import slide_import
from ...deck_scan import Deck, scan_decks
from ..kit.widgets import Button, Field, ModalSheet, SegmentedControl, Surface, caption

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
        self._decks = [deck for deck in scan_decks() if not deck.archived]
        body = Surface()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        note = caption(DESCRIPTION)
        layout.addWidget(note)

        file_row = Surface()
        row = QHBoxLayout(file_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.file_edit = QLineEdit()
        self.file_edit.setReadOnly(True)
        browse = Button("Browse…", "secondary")
        browse.clicked.connect(self._on_browse)
        row.addWidget(self.file_edit, 1)
        row.addWidget(browse)
        layout.addWidget(Field("File", file_row))

        self.deck_combo = QComboBox()
        for deck in self._decks:
            self.deck_combo.addItem(deck.name, deck)
        index = self.deck_combo.findText(current.name) if current is not None else -1
        self.deck_combo.setCurrentIndex(max(index, 0))
        layout.addWidget(Field("Add to deck", self.deck_combo))
        self.language = SegmentedControl([("EN", "EN"), ("DE", "DE")], current="EN")
        layout.addWidget(Field("Language of the slides", self.language))
        self.add_tab("", body)
        self.add_button("Cancel", role="reject")
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
        previous_text = deck.text
        try:
            summary = slide_import.import_presentation(source, deck, self.language.current() or "EN", log=self.app.log)
        except Exception as exc:  # noqa: BLE001 -- surfaced, not swallowed
            QMessageBox.critical(self, "Import failed", f"Could not import {source.name}:\n\n{exc}")
            return
        parts = [f"Imported {len(summary.imported)} slide(s) from {source.name} into {deck.name}"]
        if summary.skipped_blank:
            parts.append(f"({summary.skipped_blank} blank source slide(s) skipped)")
        self.accept()
        self.app.after_deck_edit(deck.path, " ".join(parts), previous_text=previous_text)
