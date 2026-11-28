# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Housekeeping file selection, archive conflicts and background work."""
from __future__ import annotations

import os
import threading
import time

import pytest
from conftest import wait_until
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QWidget

from slidemage import housekeeping, project, unused_content
from slidemage.render_store import RenderStore
from slidemage.ui.dialogs import housekeeping as sheet_module
from slidemage.ui.dialogs.housekeeping import ARCHIVE_PAGE, HousekeepingJobs, HousekeepingSheet
from slidemage.ui.workspace import maintenance


@pytest.fixture
def folders(tmp_path):
    root = tmp_path
    for name in ("pdf", ".build", "decks", ".temp", "media", "slides"):
        (root / name).mkdir()
    (root / "pdf" / "a.pdf").write_bytes(b"x" * 2048)
    (root / "pdf" / "b.pdf").write_bytes(b"x")
    (root / ".build" / "t-Deck-instructor-abc").mkdir()
    (root / ".build" / "legacy.log").write_text("log", encoding="utf-8")
    (root / "decks" / "_slidemage_t.tex").write_text("wrapper", encoding="utf-8")
    (root / "decks" / "deck.tex").write_text(r"\slide{abc-EN-Kept}", encoding="utf-8")
    (root / ".temp" / "scratch.pptx").write_text("scratch", encoding="utf-8")
    (root / "slides" / "abc-EN-Kept-current.tex").write_text(r"\includegraphics{media/kept.png}", encoding="utf-8")
    (root / "slides" / "abd-EN-Gone-current.tex").write_text("x", encoding="utf-8")
    (root / "media" / "kept.png").write_bytes(b"i")
    (root / "media" / "gone.png").write_bytes(b"i")
    return root


def test_housekeeping_removes_only_generated_files_and_reports_progress(folders, ctx):
    (folders / "pdf" / "sub").mkdir()
    steps = []
    pdfs = housekeeping.pdf_files(ctx)
    assert sorted(p.name for p in pdfs) == ["a.pdf", "b.pdf"]
    housekeeping.delete_files(pdfs, steps.append)
    assert not housekeeping.pdf_files(ctx)
    assert [s.fraction for s in steps] == [0.5, 1.0]
    steps.clear()
    found = housekeeping.find_temp_files(ctx)
    assert [p.name for p in found.build] == ["legacy.log", "t-Deck-instructor-abc"]
    assert [p.name for p in found.wrappers] == ["_slidemage_t.tex"]
    assert [p.name for p in found.scratch] == ["scratch.pptx"]
    housekeeping.remove_temp_files(ctx, found, steps.append)
    assert not housekeeping.find_temp_files(ctx) and (ctx.decks_dir / "deck.tex").is_file()
    assert [s.fraction for s in steps] == [0.25, 0.5, 0.75, 1.0]


def test_archive_files_moves_only_what_it_is_given(folders, ctx):
    media, slides = unused_content.find_unused_media(ctx), unused_content.find_unused_slides(ctx)
    assert [p.name for p in media] == ["gone.png"] and [p.name for p in slides] == ["abd-EN-Gone-current.tex"]
    assert unused_content.archive_files(ctx, [], slides, lambda _line: None) == (0, 1)
    assert (folders / "media" / "gone.png").is_file() and (folders / "slides" / "archive" / slides[0].name).is_file()


def test_forgotten_stores_are_removed_only_after_thirty_days(tmp_path):
    ctx = project.ProjectContext.at(tmp_path)
    store = RenderStore(ctx)
    current = store.root
    store.close()
    stores = current.parent.parent
    assert (current / "project.txt").read_text(encoding="utf-8") == str(ctx.root.resolve())
    (current / "project.txt").unlink()     # even an unmarked old store of the open project stays
    old = time.time() - 31 * 86400
    os.utime(current / "index.sqlite", (old, old))
    for name, age, folder in (("missing-old", old, tmp_path / "missing"),
                              ("missing-recent", time.time(), tmp_path / "missing"),
                              ("unmarked-old", old, None),
                              ("existing-old", old, tmp_path)):
        sibling = stores / name
        (sibling / "render-store").mkdir(parents=True)
        index = sibling / "render-store" / "index.sqlite"
        index.touch()
        os.utime(index, (age, age))
        if folder is not None:
            (sibling / "render-store" / "project.txt").write_text(str(folder), encoding="utf-8")
    housekeeping.prune_render_stores(ctx)
    assert {p.name for p in stores.iterdir()} == {current.parent.name, "missing-recent", "existing-old"}


NO_JOBS = HousekeepingJobs(lambda then: None, lambda then: None, lambda then: None)


class Window(QWidget):
    compiling = False
    def __init__(self, project):
        super().__init__()
        self.project = project

    def log(self, _line):
        pass


def test_empty_pdf_asks_first(folders, monkeypatch, qapp, ctx):
    window = Window(ctx)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    maintenance.empty_pdf_folder(window)
    assert len(housekeeping.pdf_files(ctx)) == 2
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    maintenance.empty_pdf_folder(window)
    wait_until(lambda: housekeeping.pdf_files(ctx) == [])


def test_remove_temp_files_is_refused_while_compiling(folders, monkeypatch, qapp, ctx):
    window = Window(ctx)
    window.compiling = True
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    maintenance.remove_temp_files(window)
    assert housekeeping.find_temp_files(ctx)


def open_sheet(window, jobs=NO_JOBS, page=0):
    sheet = HousekeepingSheet(window, jobs, page)
    wait_until(lambda: sheet._scan is None)
    return sheet


def test_the_sheet_opens_before_the_scan_has_finished(folders, qapp, ctx, monkeypatch):
    release = threading.Event()
    find_temp_files = housekeeping.find_temp_files
    monkeypatch.setattr(housekeeping, "find_temp_files", lambda ctx: release.wait(5) and find_temp_files(ctx))
    sheet = HousekeepingSheet(Window(ctx), NO_JOBS)
    assert sheet.pdf.sub.text() == sheet.temp.sub.text() == "Counting…"
    assert not sheet.pdf.button.isEnabled() and not sheet.archive.button.isEnabled()
    release.set()
    wait_until(lambda: sheet._scan is None)
    assert sheet.pdf.button.isEnabled() and sheet.temp.sub.text().startswith("2 items in .build/")


def rows(sheet):
    return {"pdf": sheet.pdf, "temp": sheet.temp, "archive": sheet.archive, "previews": sheet.previews,
            "links": sheet.links}


def test_maintenance_buttons_run_actions_and_respect_an_active_compile(folders, qapp, ctx):
    window = Window(ctx)
    jobs = HousekeepingJobs(lambda then: (housekeeping.delete_files(housekeeping.pdf_files(ctx)), then()),
                            lambda then: None, lambda then: then(3))
    sheet = open_sheet(window, jobs)
    assert all(row.button.isEnabled() for row in rows(sheet).values())
    sheet.pdf.button.click()
    wait_until(lambda: sheet._scan is None)
    assert not housekeeping.pdf_files(ctx) and not sheet.pdf.button.isEnabled()
    window.compiling = True
    blocked = open_sheet(window)
    assert {name for name, row in rows(blocked).items() if row.button.isEnabled()} == {"links"}
    blocked.close()
    window.compiling = False
    sheet.links.button.click()
    assert sheet.links.sub.text() == "3 files updated"
    sheet.previews.button.click()                    # a long compile: the caller starts it
    assert sheet.update_previews and sheet.result() == 1


def wait_for_archive(sheet):
    sheet._worker.wait()
    QApplication.processEvents()
    QApplication.sendPostedEvents()


def test_archive_review_lists_the_files_and_moves_the_ticked_ones(folders, qapp, ctx):
    window = Window(ctx)
    sheet = open_sheet(window, page=ARCHIVE_PAGE)
    assert sheet.files.count() == 2
    next(b for b in sheet.findChildren(QPushButton) if b.text() == "Select none").click()
    assert not sheet.archive_button.isEnabled()
    sheet.back_button.click()
    assert sheet.pages.currentIndex() == sheet_module.LIST_PAGE
    sheet.archive.button.click()
    slide_item = next(sheet.files.item(i) for i in range(2) if sheet.files.item(i).text().startswith("slide"))
    slide_item.setCheckState(Qt.CheckState.Unchecked)
    sheet.archive_button.click()
    wait_for_archive(sheet)
    wait_until(lambda: sheet._scan is None)
    assert (folders / "media" / "archive" / "gone.png").is_file()
    assert (folders / "slides" / "abd-EN-Gone-current.tex").is_file()      # unticked: stays
    assert sheet.pages.currentIndex() == sheet_module.LIST_PAGE
    assert sheet.archive.sub.text() == "Moved 1 media file to media/archive/ and 0 slides to slides/archive/"


def test_closing_the_sheet_lets_a_running_move_finish(folders, qapp, ctx):
    sheet = open_sheet(Window(ctx), page=ARCHIVE_PAGE)
    sheet.archive_button.click()
    sheet.reject()                                   # the move is short: the sheet gives it a moment, then lets go
    assert sheet._worker is None
    QApplication.processEvents()
    assert (folders / "media" / "archive" / "gone.png").is_file()


def test_a_file_whose_archived_copy_differs_can_be_compared(folders, qapp, ctx):
    archive = folders / "slides" / "archive"
    archive.mkdir()
    (folders / "slides" / "abd-EN-Gone-current.tex").write_text("one\ntwo\nthree\n", encoding="utf-8")
    (archive / "abd-EN-Gone-current.tex").write_text("one\nTWO\nthree\n", encoding="utf-8")
    (folders / "media" / "archive").mkdir()
    (folders / "media" / "archive" / "gone.png").write_bytes(b"\xff\xfe\x00 other picture")
    sheet = open_sheet(Window(ctx), page=ARCHIVE_PAGE)
    rows = {sheet.files.item(i).text().split()[0]: sheet.files.item(i) for i in range(sheet.files.count())}
    slide, media = rows["slide"], rows["media"]
    assert slide.checkState() == media.checkState() == Qt.CheckState.Unchecked
    assert not sheet.compare_button.isEnabled()              # no row is current yet
    slide.setCheckState(Qt.CheckState.Checked)
    sheet.files.setCurrentItem(slide)
    assert sheet.compare_button.isEnabled()
    sheet.compare_button.click()
    assert sheet.pages.currentIndex() == sheet_module.DIFF_PAGE
    assert not sheet.archive_button.isVisible() and "abd-EN-Gone-current.tex" in sheet.diff_title.text()
    lines = [label.text() for label in sheet.diff_lines.findChildren(sheet_module.QLabel)]
    assert lines == ["  one", "− TWO", "+ two", "  three"]
    sheet.back_button.click()
    assert sheet.pages.currentIndex() == ARCHIVE_PAGE
    assert slide.checkState() == Qt.CheckState.Checked        # the review was not refilled
    sheet.files.itemDoubleClicked.emit(media)                 # a double click compares the row clicked
    assert sheet.pages.currentIndex() == sheet_module.DIFF_PAGE
    assert sheet.diff_note.text().startswith("Not a text file") and sheet.diff_lines.isHidden()


def test_the_comparison_keeps_one_copy_and_the_review_keeps_its_ticks(folders, qapp, ctx, monkeypatch):
    trashed = []
    monkeypatch.setattr(sheet_module.deck_snapshot, "move_to_trash", lambda path: trashed.append(path.read_text(
        encoding="utf-8")) or path.unlink() or True)
    archive = folders / "slides" / "archive"
    archive.mkdir()
    slide = folders / "slides" / "abd-EN-Gone-current.tex"
    slide.write_text("new\n", encoding="utf-8")
    (archive / slide.name).write_text("old\n", encoding="utf-8")
    sheet = open_sheet(Window(ctx), page=ARCHIVE_PAGE)
    rows = {sheet.files.item(i).text().split()[0]: sheet.files.item(i) for i in range(sheet.files.count())}
    rows["media"].setCheckState(Qt.CheckState.Unchecked)
    sheet.files.itemDoubleClicked.emit(rows["slide"])
    assert sheet.keep_archived_button.isVisibleTo(sheet) and sheet.keep_file_button.isVisibleTo(sheet)
    sheet.keep_archived_button.click()
    assert trashed == ["new\n"] and not slide.exists() and (archive / slide.name).read_text(encoding="utf-8") == "old\n"
    assert sheet.pages.currentIndex() == ARCHIVE_PAGE and sheet.files.count() == 1
    assert sheet.files.item(0).checkState() == Qt.CheckState.Unchecked          # the media row kept its tick
    assert not sheet.keep_archived_button.isVisibleTo(sheet)
    sheet.back_button.click()
    wait_until(lambda: sheet._scan is None)
    assert sheet.archive.sub.text().startswith("0 slides and 1 media file")


def test_keeping_the_file_replaces_the_archived_copy(folders, qapp, ctx, monkeypatch):
    monkeypatch.setattr(sheet_module.deck_snapshot, "move_to_trash", lambda path: path.unlink() or True)
    archive = folders / "slides" / "archive"
    archive.mkdir()
    slide = folders / "slides" / "abd-EN-Gone-current.tex"
    slide.write_text("new\n", encoding="utf-8")
    (archive / slide.name).write_text("old\n", encoding="utf-8")
    sheet = open_sheet(Window(ctx), page=ARCHIVE_PAGE)
    row = next(sheet.files.item(i) for i in range(sheet.files.count()) if sheet.files.item(i).text().startswith("slide"))
    sheet.files.itemDoubleClicked.emit(row)
    sheet.keep_file_button.click()
    assert not slide.exists() and (archive / slide.name).read_text(encoding="utf-8") == "new\n"


def test_ticked_decks_are_archived_forgotten_and_closed(folders, qapp, ctx):
    from slidemage import deck_scan
    text = r"""\documentclass{beamer}
\def\input@path{{../}}
\graphicspath{{../}}
\begin{document}
\slide{abc-EN-Kept}
\end{document}
"""
    for name in ("deck", "other"):
        (ctx.decks_dir / f"{name}.tex").write_text(text, encoding="utf-8")

    class DeckWindow(Window):
        def __init__(self, project):
            super().__init__(project)
            self.decks = deck_scan.scan_decks(project)
            self.state = type("State", (), {"deck": None})()
            self.forgotten, self.reloaded = [], []
            self.background = type("Background", (), {"deck_archived": lambda _s, deck: self.forgotten.append(deck.name)})()

        def reload_decks(self, closing=frozenset()):
            self.reloaded.append(set(closing))
            self.decks = deck_scan.scan_decks(self.project)

    window = DeckWindow(ctx)
    names = sorted(d.name for d in window.decks if not d.archived)
    sheet = open_sheet(window)
    assert sheet.decks_row.button.isEnabled()
    sheet.decks_row.button.click()
    assert sheet.pages.currentIndex() == sheet_module.DECKS_PAGE
    assert sheet.deck_list.count() == len(names)
    assert not sheet.archive_decks_button.isEnabled()
    item = next(sheet.deck_list.item(i) for i in range(sheet.deck_list.count())
                if sheet.deck_list.item(i).text() == "other")
    item.setCheckState(Qt.CheckState.Checked)
    sheet.archive_decks_button.click()
    sheet._deck_worker.wait()
    QApplication.processEvents()
    QApplication.sendPostedEvents()
    wait_until(lambda: sheet._scan is None)
    assert (folders / "decks" / "archive" / "other.tex").is_file() and not (folders / "decks" / "other.tex").exists()
    assert (folders / "decks" / "deck.tex").is_file()
    assert window.forgotten == ["other"] and window.reloaded == [{"other"}]
    assert sheet.pages.currentIndex() == sheet_module.LIST_PAGE and sheet.decks_row.sub.text() == "Archived 1 deck"
