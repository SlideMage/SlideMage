""""Housekeeping -> Archive unused slides and media files" confirmation
(2026-09-27, direct instruction, after a batch run archived far more than
expected -- see unused_content.py's own module docstring for the two real
bugs that caused that and are now fixed): lists every file the scan found
before anything is actually moved, so a mistaken/over-broad result can be
caught and cancelled instead of only being discovered afterward in the log.

Non-modal-in-spirit but implemented as an ordinary exec() dialog -- unlike
SyntaxCheckDialog/RenderCheckDialog, there is nothing here to keep working
against while it's open (the scan is already finished by the time this
shows), so a plain modal confirmation is simplest.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from .qt_theme import MUTED_LABEL


class ArchiveUnusedDialog(QDialog):
    def __init__(self, parent, media_files: list[Path], slide_files: list[Path]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Archive unused content")
        self.resize(620, 480)

        layout = QVBoxLayout(self)
        total = len(media_files) + len(slide_files)
        layout.addWidget(QLabel(
            f"<b>{total} file(s)</b> would be moved into media/archive/ or "
            "slides/archive/. Review the list below before continuing --"
            " files can still be moved back by hand afterwards if needed."
        ))
        note = QLabel(
            "A file is listed here because nothing currently \\includegraphics{}s "
            "it (media/) or \\slide{}s/\\slidestep{}s/... it from any deck, "
            "including decks/archive/ (slides/)."
        )
        note.setObjectName(MUTED_LABEL)
        note.setWordWrap(True)
        layout.addWidget(note)

        self.list_widget = QListWidget()
        for path in media_files:
            self.list_widget.addItem(QListWidgetItem(f"media file:  {path.name}"))
        for path in slide_files:
            self.list_widget.addItem(QListWidgetItem(f"slide:  {path.name}"))
        layout.addWidget(self.list_widget, stretch=1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("Cancel")
        cancel_button.setDefault(True)
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)
        archive_button = QPushButton(f"Archive {total} file(s)")
        archive_button.setAutoDefault(False)
        archive_button.clicked.connect(self.accept)
        button_row.addWidget(archive_button)
        layout.addLayout(button_row)
