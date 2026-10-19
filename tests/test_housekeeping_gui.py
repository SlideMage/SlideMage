# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Housekeeping: what pdf/ and the temp folders hold (housekeeping.py), the actions of the
window, and the sheet that offers them in one place."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QWidget

from slidemage import housekeeping, unused_content
from slidemage.ui.dialogs import housekeeping as sheet_module
from slidemage.ui.dialogs.housekeeping import ARCHIVE_PAGE, HousekeepingJobs, HousekeepingSheet
from slidemage.ui.workspace import maintenance


@pytest.fixture
def folders(tmp_path, monkeypatch):
    """A project of its own: pdf/, .build/, decks/ with a leftover wrapper, .temp/ and unused content."""
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


# -- housekeeping.py -------------------------------------------------------------------------------

def test_the_temp_files_are_the_build_items_the_wrappers_and_the_scratch_folder(folders, ctx):
    found = housekeeping.find_temp_files(ctx)
    assert [p.name for p in found.build] == ["legacy.log", "t-Deck-instructor-abc"]
    assert [p.name for p in found.wrappers] == ["_slidemage_t.tex"]
    assert [p.name for p in found.scratch] == ["scratch.pptx"]
    assert found.count == 4 and found
    housekeeping.remove_temp_files(ctx, found)
    assert not housekeeping.find_temp_files(ctx)
    assert (folders / "decks" / "deck.tex").is_file()           # a real deck stays


def test_pdf_files_lists_only_files_and_delete_removes_them(folders, ctx):
    (folders / "pdf" / "sub").mkdir()
    assert sorted(p.name for p in housekeeping.pdf_files(ctx)) == ["a.pdf", "b.pdf"]
    housekeeping.delete_files(housekeeping.pdf_files(ctx))
    assert housekeeping.pdf_files(ctx) == []


def test_archive_files_moves_only_what_it_is_given(folders, ctx):
    media, slides = unused_content.find_unused_media(ctx), unused_content.find_unused_slides(ctx)
    assert [p.name for p in media] == ["gone.png"] and [p.name for p in slides] == ["abd-EN-Gone-current.tex"]
    assert unused_content.archive_files(ctx, [], slides, lambda _line: None) == (0, 1)
    assert (folders / "media" / "gone.png").is_file() and (folders / "slides" / "archive" / slides[0].name).is_file()


# -- the window's actions --------------------------------------------------------------------------

NO_JOBS = HousekeepingJobs(lambda: None, lambda: None, lambda: 0)


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
    assert housekeeping.pdf_files(ctx) == []


def test_remove_temp_files_is_refused_while_compiling(folders, monkeypatch, qapp, ctx):
    window = Window(ctx)
    window.compiling = True
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    maintenance.remove_temp_files(window)
    assert housekeeping.find_temp_files(ctx)


# -- the sheet ---------------------------------------------------------------------------------------

def rows(sheet):
    return {"pdf": sheet.pdf, "temp": sheet.temp, "archive": sheet.archive, "previews": sheet.previews,
            "links": sheet.links}


def test_rows_with_nothing_to_do_are_disabled_and_a_compile_blocks_the_dangerous_ones(folders, qapp, ctx):
    housekeeping.delete_files(housekeeping.pdf_files(ctx))
    window = Window(ctx)
    window.compiling = True
    sheet = HousekeepingSheet(window, NO_JOBS)
    state = {name: row.button.isEnabled() for name, row in rows(sheet).items()}
    assert state == {"pdf": False, "temp": False, "archive": False, "previews": False, "links": True}
    assert sheet.pdf.sub.text() == "pdf/ is empty"


def test_the_buttons_run_the_windows_actions_and_the_sheet_follows(folders, qapp, ctx):
    window = Window(ctx)
    jobs = HousekeepingJobs(lambda: housekeeping.delete_files(housekeeping.pdf_files(ctx)), lambda: None, lambda: 3)
    sheet = HousekeepingSheet(window, jobs)
    assert all(row.button.isEnabled() for row in rows(sheet).values())
    sheet.pdf.button.click()
    assert sheet.pdf.sub.text() == "pdf/ is empty" and not sheet.pdf.button.isEnabled()
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
    sheet = HousekeepingSheet(window, NO_JOBS, ARCHIVE_PAGE)
    assert sheet.windowTitle() == "Archive unused content" and sheet.files.count() == 2
    assert sheet.archive_button.text() == "Archive 2 files"
    next(b for b in sheet.findChildren(QPushButton) if b.text() == "Select none").click()
    assert not sheet.archive_button.isEnabled() and sheet.archive_button.text() == "Archive 0 files"
    sheet.back_button.click()
    assert sheet.pages.currentIndex() == sheet_module.LIST_PAGE and sheet.windowTitle() == "Housekeeping"
    sheet.archive.button.click()
    slide_item = next(sheet.files.item(i) for i in range(2) if sheet.files.item(i).text().startswith("slide"))
    slide_item.setCheckState(Qt.CheckState.Unchecked)
    assert sheet.archive_button.text() == "Archive 1 file"
    sheet.archive_button.click()
    wait_for_archive(sheet)
    assert (folders / "media" / "archive" / "gone.png").is_file()
    assert (folders / "slides" / "abd-EN-Gone-current.tex").is_file()      # unticked: stays
    assert sheet.pages.currentIndex() == sheet_module.LIST_PAGE
    assert sheet.archive.sub.text() == "Moved 1 media file to media/archive/ and 0 slides to slides/archive/"


def test_closing_the_sheet_lets_a_running_move_finish(folders, qapp, ctx):
    sheet = HousekeepingSheet(Window(ctx), NO_JOBS, ARCHIVE_PAGE)
    sheet.archive_button.click()
    sheet.reject()                                   # the move is short: the sheet gives it a moment, then lets go
    assert sheet._worker is None
    QApplication.processEvents()
    assert (Path(folders) / "media" / "archive" / "gone.png").is_file()
