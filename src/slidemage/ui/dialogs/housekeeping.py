"""The Housekeeping sheet (UI_REDESIGN_PLAN.md, step 9): the clean-up and update jobs of a project in one place.

Cleanup: empty pdf/, remove temp files (.build/, leftover wrappers, .temp/), archive unused
slides and media. Updating: update the slide previews, reestablish translation links. Each row
says what there is to do and has one button; the buttons run the window's own actions
(ui/workspace/maintenance.py), which ask before they delete. "Archive unused content" has a page
of its own, where the files the scan found can be ticked before anything moves; the move runs on a
thread that the sheet waits for when it closes. Update previews is a long compile: the sheet closes
and the caller starts it (`update_previews`).
"""
from __future__ import annotations

from typing import Callable, NamedTuple

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ... import deck_snapshot, housekeeping, unused_content
from ...project import ProjectContext
from .. import background
from ..kit import kit_qss as q
from ..kit.widgets import Button, ModalSheet, Surface, caption
from ..text import plural

LIST_PAGE, ARCHIVE_PAGE = 0, 1
WORKER_WAIT_MS = 10000
BUSY_NOTE = "A compile run is in progress."


class _ArchiveWorker(QThread):
    """unused_content.archive_files() off the GUI thread: a move inside a synced folder can be slow."""

    logged = Signal(str)
    finished_with = Signal(int, int)       # media moved, slides moved

    def __init__(self, project: ProjectContext, media: list, slides: list) -> None:
        super().__init__()
        self._project, self._media, self._slides = project, media, slides

    def run(self) -> None:
        moved = unused_content.archive_files(self._project, self._media, self._slides, self.logged.emit)
        self.finished_with.emit(*moved)


class _Row(QFrame):
    """A job: its name, what there is to do, and the button that does it."""

    def __init__(self, title: str, button: str, on_click: Callable[[], None]) -> None:
        super().__init__()
        self.setObjectName(q.PANEL_ROW)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        self.title = QLabel(title)
        self.sub = caption()
        texts.addWidget(self.title)
        texts.addWidget(self.sub)
        layout.addLayout(texts, 1)
        self.button = Button(button, "secondary", compact=True)
        self.button.clicked.connect(on_click)
        layout.addWidget(self.button, 0, Qt.AlignmentFlag.AlignVCenter)

    def show_state(self, sub: str, *, enabled: bool) -> None:
        self.sub.setText(sub)
        self.button.setEnabled(enabled)


class HousekeepingJobs(NamedTuple):
    """What the list page runs: the window's own housekeeping actions (workspace/maintenance.py)."""
    empty_pdf: Callable[[], None]
    remove_temp: Callable[[], None]
    sync_links: Callable[[], int]


class HousekeepingSheet(ModalSheet):
    def __init__(self, app, jobs: HousekeepingJobs, page: int = LIST_PAGE) -> None:
        """`app` is the window; `jobs` are the actions it runs for the list. `page` is the one to open on
        (ARCHIVE_PAGE for the archive review)."""
        super().__init__("Housekeeping", app, width=640)
        self.app = app
        self.jobs = jobs
        self.update_previews = False
        self._worker: _ArchiveWorker | None = None
        self._unused: tuple[list, list] = ([], [])
        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_list())
        self.pages.addWidget(self._build_archive())
        self.add_tab("", self.pages)
        self.close_button = self.add_button("Close", kind="primary", role="accept")
        self.back_button = self.add_button("Cancel")
        self.back_button.clicked.connect(lambda: self._show_page(LIST_PAGE))
        self.archive_button = self.add_button("Archive", kind="primary")
        self.archive_button.clicked.connect(self._on_archive)
        self.refresh()
        self._show_page(page)

    # -- building --------------------------------------------------------------------------

    def _build_list(self) -> QWidget:
        page = Surface()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.pdf = _Row("Empty the pdf folder", "Empty", self._on_empty_pdf)
        self.temp = _Row("Remove temp files", "Remove", self._on_remove_temp)
        self.archive = _Row("Archive unused content", "Review…", lambda: self._show_page(ARCHIVE_PAGE))
        self.previews = _Row("Update slide previews", "Update…", self._on_previews)
        self.links = _Row("Reestablish translation links", "Check", self._on_links)
        for heading, rows in (("Cleanup", (self.pdf, self.temp, self.archive)),
                              ("Updating", (self.previews, self.links))):
            label = QLabel(heading)
            label.setObjectName(q.FIELD_LABEL)
            layout.addWidget(label)
            for row in rows:
                layout.addWidget(row)
        layout.addStretch(1)
        return page

    def _build_archive(self) -> QWidget:
        page = Surface()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.archive_intro = QLabel()
        self.archive_intro.setWordWrap(True)
        layout.addWidget(self.archive_intro)
        note = caption("A file is listed because nothing \\includegraphics{}s it (media/), or no deck "
                       "-- archived decks included -- uses it as a slide (slides/). Archived files can be "
                       "moved back by hand.")
        layout.addWidget(note)
        bulk = Surface()
        bulk_row = QHBoxLayout(bulk)
        bulk_row.setContentsMargins(0, 0, 0, 0)
        select_all = Button("Select all", "ghost", compact=True)
        select_all.clicked.connect(lambda: self._select_all(True))
        select_none = Button("Select none", "ghost", compact=True)
        select_none.clicked.connect(lambda: self._select_all(False))
        bulk_row.addStretch(1)
        bulk_row.addWidget(select_all)
        bulk_row.addWidget(select_none)
        layout.addWidget(bulk)
        self.files = QListWidget()
        self.files.setFixedHeight(220)
        self.files.itemChanged.connect(lambda _item: self._update_archive_button())
        layout.addWidget(self.files)
        self.archive_status = QLabel()
        self.archive_status.setObjectName(q.PANEL_CAPTION)
        layout.addWidget(self.archive_status)
        return page

    # -- what there is to do ----------------------------------------------------------------

    def refresh(self) -> None:
        compiling = self.app.compiling
        pdfs = housekeeping.pdf_files(self.app.project)
        self.pdf.show_state(
            f"{plural(len(pdfs), 'file')} in pdf/ · {deck_snapshot.format_size(sum(p.stat().st_size for p in pdfs))}"
            " · they come back with the next build" if pdfs else "pdf/ is empty", enabled=bool(pdfs))
        temp = housekeeping.find_temp_files(self.app.project)
        self.temp.show_state(
            f"{plural(len(temp.build), 'item')} in .build/, {plural(len(temp.wrappers), 'leftover wrapper file')} "
            f"in decks/, {plural(len(temp.scratch), 'item')} in .temp/ (the workflow scratch folder)"
            if temp else "Nothing to remove", enabled=bool(temp) and not compiling)
        self._unused = (unused_content.find_unused_media(self.app.project), unused_content.find_unused_slides(self.app.project))
        media, slides = self._unused
        self.archive.show_state(
            f"{plural(len(slides), 'slide')} and {plural(len(media), 'media file')} nothing uses"
            if media or slides else "No unused slides or media files",
            enabled=bool(media or slides) and not compiling and self._worker is None)
        self.previews.show_state(
            "Re-renders the previews of the slides the decks use: one very long compile that "
            "occupies the compile slot" if not compiling else BUSY_NOTE, enabled=not compiling)
        self.links.show_state("Re-pairs EN and DE files after renames", enabled=True)

    def _show_page(self, page: int) -> None:
        self.pages.setCurrentIndex(page)
        archive = page == ARCHIVE_PAGE
        self.set_title("Archive unused content" if archive else "Housekeeping")
        self.close_button.setVisible(not archive)
        self.back_button.setVisible(archive)
        self.archive_button.setVisible(archive)
        if archive:
            self._fill_archive()

    # -- the jobs --------------------------------------------------------------------------

    def _on_empty_pdf(self) -> None:
        self.jobs.empty_pdf()
        self.refresh()

    def _on_remove_temp(self) -> None:
        self.jobs.remove_temp()
        self.refresh()

    def _on_previews(self) -> None:
        self.update_previews = True
        self.accept()

    def _on_links(self) -> None:
        changed = self.jobs.sync_links()
        self.links.show_state(f"{plural(changed, 'file')} updated", enabled=True)

    # -- archive unused content --------------------------------------------------------------

    def _fill_archive(self) -> None:
        media, slides = self._unused
        self.files.blockSignals(True)
        self.files.clear()
        for kind, paths in (("slide", slides), ("media", media)):
            for path in paths:
                item = QListWidgetItem(f"{kind}    {path.name}")
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked)
                item.setData(Qt.ItemDataRole.UserRole, (kind, path))
                self.files.addItem(item)
        self.files.blockSignals(False)
        self.archive_status.setText("")
        self._update_archive_button()

    def _checked(self) -> list[tuple[str, object]]:
        return [self.files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.files.count())
                if self.files.item(i).checkState() == Qt.CheckState.Checked]

    def _select_all(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self.files.count()):
            self.files.item(i).setCheckState(state)

    def _update_archive_button(self) -> None:
        count = len(self._checked())
        self.archive_intro.setText(
            f"<b>{plural(self.files.count(), 'file')}</b> would be moved into media/archive/ or "
            "slides/archive/. Untick what should stay." if self.files.count()
            else "No unused slides or media files.")
        self.archive_button.setText(f"Archive {plural(count, 'file')}")
        self.archive_button.setEnabled(count > 0 and self._worker is None and not self.app.compiling)

    def _on_archive(self) -> None:
        chosen = self._checked()
        if not chosen or self._worker is not None:
            return
        self._worker = _ArchiveWorker(self.app.project, [p for kind, p in chosen if kind == "media"],
                                      [p for kind, p in chosen if kind == "slide"])
        self._worker.logged.connect(self.app.log)
        self._worker.finished_with.connect(self._on_archived)
        self.archive_button.setEnabled(False)
        self.back_button.setEnabled(False)
        self.archive_status.setText("Moving…")
        self._worker.start()

    def _on_archived(self, media: int, slides: int) -> None:
        worker, self._worker = self._worker, None
        worker.wait()
        worker.deleteLater()
        self.back_button.setEnabled(True)
        self._show_page(LIST_PAGE)
        self.refresh()
        self.archive.sub.setText(f"Moved {plural(media, 'media file')} to media/archive/ and "
                                 f"{plural(slides, 'slide')} to slides/archive/")

    def done(self, result: int) -> None:
        """Closing the sheet gives a running move a moment; its thread is kept until it has ended."""
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.finished_with.disconnect(self._on_archived)
            background.stop_worker(worker, wait_ms=WORKER_WAIT_MS)
        super().done(result)
