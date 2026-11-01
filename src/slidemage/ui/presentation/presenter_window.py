# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The start window of SlideMage Presenter (docs/plans/presenter-app.md, step 2): open a PDF, pick one of the last
ones, drop one on the window, or change the presentation settings. Imports only the kit and the presentation
modules, like standalone.py, so the small Presenter program can be built from it."""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QFileDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...presentation import open_with, presenter_update, recent
from ...version import VERSION_NUMBER
from ..kit import kit_qss as q
from ..kit.widgets import Button, ModalSheet, RowButton, Surface, caption, clear_layout
from . import standalone
from .settings_page import PresentationTab

TITLE = "SlideMage Presenter"
FOLDER_WIDTH = 400         # px of a recent PDF's folder line before it is shortened


def run_in_background(work: Callable[[], None]) -> None:
    """Run `work` on a thread of its own (the update check and download; tests run it on the spot instead)."""
    threading.Thread(target=work, daemon=True).start()


class PresenterStartWindow(QWidget):
    # From the worker threads to the window: the release found (None: up to date), progress (done, total) in bytes,
    # the download is installed, an error message.
    update_found = Signal(object)
    update_progress = Signal(int, int)
    update_installed = Signal()
    update_failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(TITLE)
        self.setAcceptDrops(True)
        self.resize(520, 420)
        self.rows: list[RowButton] = []
        self.presenting = False
        self.waiting: list[Path] = []      # PDFs opened during a talk
        self.update_release = None         # a newer release that carries the Presenter's zip, if one was found
        self.updating = False              # its download is running
        self.update_ready = False          # it is installed: quit when the talk that was running has ended
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
        # The update notice: a quiet line above the footer, shown only when a newer release changes the Presenter.
        self.update_bar = QWidget()
        bar = QHBoxLayout(self.update_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        self.update_label = caption("")
        bar.addWidget(self.update_label, 1)
        self.update_button = Button("Update and restart", "secondary")
        self.update_button.clicked.connect(self.on_update_clicked)
        bar.addWidget(self.update_button)
        self.update_bar.hide()
        root.addWidget(self.update_bar)
        # "Open with": offered only by a frozen Windows or Linux build (open_with.supported()).
        self.open_with_bar = QWidget()
        with_bar = QHBoxLayout(self.open_with_bar)
        with_bar.setContentsMargins(0, 0, 0, 0)
        self.open_with_label = caption("")
        with_bar.addWidget(self.open_with_label, 1)
        self.open_with_button = Button("Add", "secondary")
        self.open_with_button.setToolTip("Only adds SlideMage Presenter to the “Open with” list of PDF files. "
                                         "It never changes the program that opens a PDF on a double-click.")
        self.open_with_button.clicked.connect(self.on_open_with_clicked)
        with_bar.addWidget(self.open_with_button)
        root.addWidget(self.open_with_bar)
        self.open_with_state = open_with.OFF
        self.refresh_open_with()
        footer = QHBoxLayout()
        footer.addWidget(caption(VERSION_NUMBER.lstrip("v")))
        footer.addStretch(1)
        self.settings_button = Button("Presentation settings…", "secondary")
        self.settings_button.clicked.connect(self.open_settings)
        footer.addWidget(self.settings_button)
        root.addLayout(footer)
        self.update_found.connect(self.show_update)
        self.update_progress.connect(self.show_progress)
        self.update_installed.connect(self.finish_update)
        self.update_failed.connect(self.show_update_failure)
        self.refresh()

    # -- the update notice ---------------------------------------------------------------------

    def start_update_check(self) -> None:
        """Look for a newer release in the background, when the shared update mode allows it and the last look is a
        day old. Never blocks the window; a failed check says nothing."""
        if presenter_update.check_due():
            run_in_background(self.check_for_update)

    def check_for_update(self) -> None:
        """The check itself (a worker thread's job): emits update_found with the release, or None."""
        from ... import updater

        try:
            release = presenter_update.find_update()
        except (updater.UpdateError, OSError, ValueError):
            return
        self.update_found.emit(release)

    def show_update(self, release) -> None:
        self.update_release = release
        if release is None:
            self.update_bar.hide()
            return
        self.update_label.setText(f"SlideMage Presenter {release.tag} is available.")
        self.update_label.setProperty("tone", "")
        self.update_button.setText("Update and restart" if presenter_update.can_install() else "Download…")
        self.update_button.setEnabled(True)
        self.update_bar.show()

    def on_update_clicked(self) -> None:
        release = self.update_release
        if release is None or self.presenting or self.updating:      # never during a talk
            return
        if not presenter_update.can_install():
            QDesktopServices.openUrl(QUrl(release.page_url))
            return
        self.updating = True
        self.update_button.setEnabled(False)
        self.update_label.setProperty("tone", "")
        self.update_label.setText(f"Downloading SlideMage Presenter {release.tag}…")
        run_in_background(lambda: self.download_update(release))

    def download_update(self, release) -> None:
        """Download and stage the update, start the swap helper (a worker thread's job)."""
        from ... import updater

        def progress(done: int, total: int) -> bool:
            self.update_progress.emit(done, total)
            return True

        try:
            presenter_update.install(release, progress=progress)
        except (updater.UpdateError, OSError) as exc:
            self.update_failed.emit(str(exc))
            return
        self.update_installed.emit()

    def show_progress(self, done: int, total: int) -> None:
        if total and self.updating:
            self.update_label.setText(f"Downloading SlideMage Presenter {self.update_release.tag}… "
                                      f"{min(100, done * 100 // total)} %")

    def finish_update(self) -> None:
        """The helper is waiting for this process to end, then swaps the folders and starts the new Presenter."""
        self.update_label.setText("Restarting…")
        if self.presenting:
            self.update_ready = True      # present() quits when the talk has ended
        else:
            QApplication.quit()

    def show_update_failure(self, message: str) -> None:
        self.updating = False
        self.update_label.setProperty("tone", "error")
        self.update_label.setText(f"The update failed: {message}")
        self.update_label.style().unpolish(self.update_label)
        self.update_label.style().polish(self.update_label)
        self.update_button.setText("Try again")
        self.update_button.setEnabled(True)

    # -- "Open with" ---------------------------------------------------------------------------

    def refresh_open_with(self, error: str = "") -> None:
        """Show the row when this build can register itself; the button follows the status (Add, Remove, Update)."""
        if not open_with.supported():
            self.open_with_bar.hide()
            return
        try:
            self.open_with_state = open_with.status(sys.executable)
        except OSError as exc:
            self.open_with_state, error = open_with.OFF, error or str(exc)
        state = self.open_with_state
        text = "Offer SlideMage Presenter under “Open with” for PDF files."
        if state == open_with.MOVED:
            text = "“Open with” for PDF files points to another copy of SlideMage Presenter."
        self.open_with_label.setText(error or text)
        self.open_with_label.setProperty("tone", "error" if error else "")
        self.open_with_label.style().unpolish(self.open_with_label)
        self.open_with_label.style().polish(self.open_with_label)
        self.open_with_button.setText({open_with.ON: "Remove", open_with.MOVED: "Update"}.get(state, "Add"))
        self.open_with_bar.show()

    def on_open_with_clicked(self) -> None:
        try:
            if self.open_with_state == open_with.ON:
                open_with.unregister()
            else:
                open_with.register(sys.executable)
        except OSError as exc:
            self.refresh_open_with(f"Could not change it: {exc}")
            return
        self.refresh_open_with()

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
            if self.update_ready:           # an update was installed during the talk
                QApplication.quit()
                return
            self.show()
            self.raise_()
            self.activateWindow()
        if self.waiting:
            QTimer.singleShot(0, lambda: self.present(self.waiting.pop(0)))

    def open_settings(self) -> None:
        sheet = ModalSheet("Presentation settings", self, width=760)      # as wide as SlideMage's Settings
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
