# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The start window of SlideMage Presenter (docs/plans/presenter-app.md, step 2): open a PDF, pick one of the last
ones, drop one on the window, or change the presentation settings. Imports only the kit and the presentation
modules, like standalone.py, so the small Presenter program can be built from it."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QFileDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...presentation import recent
from ...version import VERSION_NUMBER
from ..kit import kit_qss as q
from ..kit.widgets import Button, ModalSheet, RowButton, Surface, caption, clear_layout
from . import standalone
from .settings_page import PresentationTab

TITLE = "SlideMage Presenter"
FOLDER_WIDTH = 400         # px of a recent PDF's folder line before it is shortened


class PresenterStartWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(TITLE)
        self.setAcceptDrops(True)
        self.resize(520, 420)
        self.rows: list[RowButton] = []
        self.presenting = False
        self.waiting: list[Path] = []      # PDFs opened during a talk
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 16)
        root.setSpacing(12)
        title = QLabel(TITLE)
        title.setObjectName(q.SHEET_TITLE)
        root.addWidget(title)
        root.addWidget(caption("Present a presenter PDF (slides and notes) or any plain PDF. Drop one here, or open it."))
        self.open_button = Button("Open PDF…", "primary")
        self.open_button.clicked.connect(self.choose_file)
        buttons = QHBoxLayout()
        buttons.addWidget(self.open_button)
        buttons.addStretch(1)
        root.addLayout(buttons)
        root.addWidget(caption("Recent"))
        self._list = Surface()
        self._list_layout = QVBoxLayout(self._list)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(0)
        root.addWidget(self._list)
        root.addStretch(1)
        footer = QHBoxLayout()
        footer.addWidget(caption(VERSION_NUMBER.lstrip("v")))
        footer.addStretch(1)
        self.settings_button = Button("Presentation settings…", "secondary")
        self.settings_button.clicked.connect(self.open_settings)
        footer.addWidget(self.settings_button)
        root.addLayout(footer)
        self.refresh()

    # -- the list ------------------------------------------------------------------------------

    def refresh(self) -> None:
        clear_layout(self._list_layout)
        self.rows = []
        for path in recent.load():
            row = RowButton("slideshow", path.name, str(path.parent))
            # one line, shortened in the middle: a long folder would otherwise wrap and widen the window
            row.sub.setWordWrap(False)
            row.sub.setToolTip(str(path.parent))
            row.sub.setText(row.sub.fontMetrics().elidedText(str(path.parent), Qt.TextElideMode.ElideMiddle,
                                                              FOLDER_WIDTH))
            row.path = path
            row.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            row.clicked.connect(lambda path=path: self.present(path))
            self.rows.append(row)
            self._list_layout.addWidget(row)
        self.empty_note = None
        if not self.rows:
            self.empty_note = caption("PDFs you present appear here.")
            self._list_layout.addWidget(self.empty_note)

    def keyPressEvent(self, event) -> None:
        focused = self.focusWidget()
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and focused in self.rows:
            focused.clicked.emit()
            return
        super().keyPressEvent(event)

    # -- actions -------------------------------------------------------------------------------

    def choose_file(self) -> None:
        recents = recent.load()
        start = str(recents[0].parent) if recents else str(Path.home())
        chosen, _filter = QFileDialog.getOpenFileName(self, "Present a PDF", start, "PDF files (*.pdf)")
        if chosen:
            self.present(Path(chosen))

    def present(self, path: Path) -> None:
        """Hide this window while the talk runs, then bring it back with the list updated. A PDF opened while a
        talk runs (macOS's "open this file" can come at any time) waits until that talk has ended."""
        if self.presenting:
            self.waiting.append(path)
            return
        self.presenting = True
        self.hide()
        try:
            if standalone.present_pdf_file(path):
                recent.add(path)
        finally:
            self.presenting = False
            self.refresh()
            self.show()
            self.raise_()
            self.activateWindow()
        if self.waiting:
            QTimer.singleShot(0, lambda: self.present(self.waiting.pop(0)))

    def open_settings(self) -> None:
        sheet = ModalSheet("Presentation settings", self, width=560)
        sheet.add_tab("", PresentationTab(), scroll=True)
        sheet.add_button("Close", kind="primary", role="accept")
        sheet.exec()

    def closeEvent(self, event) -> None:
        super().closeEvent(event)
        QApplication.quit()

    # -- drag and drop -------------------------------------------------------------------------

    @staticmethod
    def _pdfs(mime) -> list[Path]:
        return [Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile()
                and url.toLocalFile().lower().endswith(".pdf")]

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._pdfs(event.mimeData()):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        pdfs = self._pdfs(event.mimeData())
        if pdfs:
            event.acceptProposedAction()
            QTimer.singleShot(0, lambda: self.present(pdfs[0]))    # return from the drop before the talk starts
