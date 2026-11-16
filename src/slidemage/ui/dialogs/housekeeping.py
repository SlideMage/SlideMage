# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Housekeeping sheet (UI_REDESIGN_PLAN.md, step 9): the clean-up and update jobs of a project in one place.

Cleanup: empty pdf/, remove temp files (.build/, leftover wrappers, .temp/), archive unused
slides and media. Updating: update the slide previews, reestablish translation links. Each row
says what there is to do and has one button; the buttons run the window's own actions
(ui/workspace/maintenance.py), which ask before they delete. "Archive unused content" has a page
of its own, where the files the scan found can be ticked before anything moves; the move runs on a
thread that the sheet waits for when it closes. Update previews is a long compile: the sheet closes
and the caller starts it (`update_previews`). The sheet opens at once: its rows say "Counting…" while one worker scans.
"""
from __future__ import annotations

from typing import Callable, NamedTuple

from PySide6.QtCore import Qt
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
from ...progress import Progress
from .. import background
from ..kit import kit_qss as q
from ..kit.tokens import SPACE
from ..kit.widgets import BusyIndicator, Button, ModalSheet, Surface, caption
from ..text import plural

LIST_PAGE, ARCHIVE_PAGE = 0, 1
WORKER_WAIT_MS = 10000
BUSY_NOTE = "A compile run is in progress."


class _Row(QFrame):
    """A job: its name, what there is to do, and the button that does it."""

    def __init__(self, title: str, button: str, on_click: Callable[[], None]) -> None:
        super().__init__()
        self.setObjectName(q.PANEL_ROW)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, SPACE.md, 0, SPACE.md)
        texts = QVBoxLayout()
        texts.setSpacing(SPACE.s_2xs)
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
    """What the list page runs: the window's own housekeeping actions (workspace/maintenance.py). They run on a
    worker, so each takes what to do afterwards: `then()`, or `then(files updated)` for the links."""
    empty_pdf: Callable[[Callable[[], None]], None]
    remove_temp: Callable[[Callable[[], None]], None]
    sync_links: Callable[[Callable[[int], None]], None]


class HousekeepingSheet(ModalSheet):
    def __init__(self, app, jobs: HousekeepingJobs, page: int = LIST_PAGE) -> None:
        """`app` is the window; `jobs` are the actions it runs for the list. `page` is the one to open on
        (ARCHIVE_PAGE for the archive review)."""
        super().__init__("Housekeeping", app, width=640)
        self.app = app
        self.jobs = jobs
        self.update_previews = False
        self._worker: background.Handle | None = None
        self._scan: background.Handle | None = None
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
        self.previews = _Row("Render all previews now", "Render…", self._on_previews)
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
        layout.setSpacing(SPACE.lg)
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
        self.busy = BusyIndicator()
        layout.addWidget(self.busy)
        return page

    # -- what there is to do ----------------------------------------------------------------

    def refresh(self, archive_note: str = "") -> None:
        """The rows say "Counting…" until one worker has scanned pdf/, the temp folders and the unused content;
        `archive_note` then replaces the archive row's count."""
        for row in (self.pdf, self.temp, self.archive):
            row.show_state("Counting…", enabled=False)
        ctx = self.app.project

        def scan() -> tuple:
            pdfs = housekeeping.pdf_files(ctx)
            return (pdfs, sum(p.stat().st_size for p in pdfs), housekeeping.find_temp_files(ctx),
                    unused_content.find_unused_media(ctx), unused_content.find_unused_slides(ctx))

        self._scan = background.run_in_background(
            scan, lambda found, error: self._show_counts(found, error, archive_note), parent=self)

    def _show_counts(self, found, error, archive_note: str) -> None:
        self._scan = None
        if error is not None:
            for row in (self.pdf, self.temp, self.archive):
                row.show_state(f"Couldn't count: {error}", enabled=False)
            return
        compiling = self.app.compiling
        pdfs, size, temp, media, slides = found
        self._unused = (media, slides)
        self.pdf.show_state(
            f"{plural(len(pdfs), 'file')} in pdf/ · {deck_snapshot.format_size(size)}"
            " · they come back with the next build" if pdfs else "pdf/ is empty", enabled=bool(pdfs))
        self.temp.show_state(
            f"{plural(len(temp.build), 'item')} in .build/, {plural(len(temp.wrappers), 'leftover wrapper file')} "
            f"in decks/, {plural(len(temp.scratch), 'item')} in .temp/ (the workflow scratch folder)"
            if temp else "Nothing to remove", enabled=bool(temp) and not compiling)
        self.archive.show_state(
            archive_note or (f"{plural(len(slides), 'slide')} and {plural(len(media), 'media file')} nothing uses"
                             if media or slides else "No unused slides or media files"),
            enabled=bool(media or slides) and not compiling and self._worker is None)
        self.previews.show_state(
            "Renders every deck and view prepared by the background sweep; "
            "occupies the compile slot" if not compiling else BUSY_NOTE, enabled=not compiling)
        self.links.show_state("Re-pairs EN and DE files after renames", enabled=True)
        if self.pages.currentIndex() == ARCHIVE_PAGE:
            self._fill_archive()

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
        self.jobs.empty_pdf(self.refresh)

    def _on_remove_temp(self) -> None:
        self.jobs.remove_temp(self.refresh)

    def _on_previews(self) -> None:
        self.update_previews = True
        self.accept()

    def _on_links(self) -> None:
        self.jobs.sync_links(lambda changed: self.links.show_state(f"{plural(changed, 'file')} updated", enabled=True))

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
            else "Counting…" if self._scan is not None else "No unused slides or media files.")
        self.archive_button.setText(f"Archive {plural(count, 'file')}")
        self.archive_button.setEnabled(count > 0 and self._worker is None and not self.app.compiling)

    def _on_archive(self) -> None:
        """A move inside a synced folder can be slow: archive off the GUI thread."""
        chosen = self._checked()
        if not chosen or self._worker is not None:
            return
        ctx = self.app.project
        media, slides = [p for kind, p in chosen if kind == "media"], [p for kind, p in chosen if kind == "slide"]
        self._worker = background.run_in_background_with_progress(
            lambda report: unused_content.archive_files(ctx, media, slides, report, on_progress=report),
            self._on_archive_progress, self._on_archived, parent=self)
        self.archive_button.setEnabled(False)
        self.back_button.setEnabled(False)
        self.busy.start("Moving…")

    def _on_archive_progress(self, value: str | Progress) -> None:
        """The worker reports log lines (str) and the bar (Progress) on one channel."""
        if isinstance(value, Progress):
            self.busy.show_progress(value)
        else:
            self.app.log(value)

    def _on_archived(self, moved: tuple[int, int] | None, error) -> None:
        self._worker = None
        self.busy.finish()
        self.back_button.setEnabled(True)
        if error is not None:
            self.app.log(f"*** archiving failed: {error} ***")
            self._update_archive_button()
            return
        media, slides = moved
        self._show_page(LIST_PAGE)
        self.refresh(f"Moved {plural(media, 'media file')} to media/archive/ and "
                     f"{plural(slides, 'slide')} to slides/archive/")

    def done(self, result: int) -> None:
        """Closing the sheet gives a running move a moment; its thread is kept until it has ended."""
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.stop(wait_ms=WORKER_WAIT_MS)
        if self._scan is not None:
            self._scan.stop()
        super().done(result)
