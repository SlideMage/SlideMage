"""System -> "Import PPTX/ODP..." -- a standalone dialog (not opened from
any one deck-editor tab) that runs slide_import.import_presentation()
against a chosen .pptx/.odp file and a chosen target deck. Direct
instruction, 2026-09-23.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from . import deck_scan, slide_import


class ImportPresentationDialog(QDialog):
    def __init__(self, app) -> None:
        super().__init__(app)
        self.app = app
        self.setWindowTitle("Import PPTX/ODP")
        self.resize(480, 200)

        self._decks = [d for d in deck_scan.scan_decks() if not d.archived]

        layout = QVBoxLayout(self)
        description = QLabel(
            "Imports each slide of a PowerPoint (.pptx) or OpenDocument "
            "Presentation (.odp) file as a new Slidemaster slide, with "
            "real, editable text -- not a picture of the original. A "
            "slide with no extractable text but at least one image "
            "becomes an image-only slide instead; a genuinely blank "
            "slide is skipped. Text extraction can't recover an "
            "arbitrary source deck's own visual design (tables, "
            "multi-column layouts, diagrams) -- expect to clean up the "
            "result, same as any other text conversion."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        file_row = QHBoxLayout()
        file_row.addWidget(QLabel("File:"))
        self.file_edit = QLineEdit()
        self.file_edit.setReadOnly(True)
        file_row.addWidget(self.file_edit, stretch=1)
        browse_button = QPushButton("Browse…")
        browse_button.clicked.connect(self._on_browse)
        file_row.addWidget(browse_button)
        layout.addLayout(file_row)

        deck_row = QHBoxLayout()
        deck_row.addWidget(QLabel("Add to deck:"))
        self.deck_combo = QComboBox()
        self.deck_combo.addItems([d.name for d in self._decks])
        deck_row.addWidget(self.deck_combo, stretch=1)
        layout.addLayout(deck_row)

        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("Language:"))
        self.language_combo = QComboBox()
        self.language_combo.addItems(["EN", "DE"])
        lang_row.addWidget(self.language_combo)
        lang_row.addStretch(1)
        layout.addLayout(lang_row)

        layout.addStretch(1)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.button(QDialogButtonBox.StandardButton.Ok).setText("Import")
        button_box.accepted.connect(self._on_import)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _on_browse(self) -> None:
        chosen, _filter = QFileDialog.getOpenFileName(
            self, "Choose a presentation to import",
            "", "Presentations (*.pptx *.odp)",
        )
        if chosen:
            self.file_edit.setText(chosen)

    def _on_import(self) -> None:
        if not self.file_edit.text():
            QMessageBox.critical(self, "Import", "Choose a file to import first.")
            return
        if not self._decks:
            QMessageBox.critical(self, "Import", "This project has no active decks to import into.")
            return
        source_path = Path(self.file_edit.text())
        deck = self._decks[self.deck_combo.currentIndex()]
        language = self.language_combo.currentText()
        previous_text = deck.text

        try:
            summary = slide_import.import_presentation(
                source_path, deck, language, log=self.app.log
            )
        except Exception as exc:  # noqa: BLE001 -- surfaced, not swallowed
            QMessageBox.critical(
                self, "Import failed",
                f"Could not import {source_path.name}:\n\n{exc}",
            )
            return

        parts = [f"Imported {len(summary.imported)} slide(s) from {source_path.name} "
                 f"into {deck.name}"]
        if summary.skipped_blank:
            parts.append(f"({summary.skipped_blank} blank source slide(s) skipped)")
        self.app.after_deck_edit(deck.path, " ".join(parts), previous_text=previous_text)
        self.accept()
