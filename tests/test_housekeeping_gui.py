"""Housekeeping: what pdf/ and the temp folders hold (housekeeping.py), the actions of the
window, and the sheet that offers them in one place."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QWidget

from slidemage import housekeeping, unused_content
from slidemage.ui.dialogs import housekeeping as sheet_module
from slidemage.ui.dialogs.housekeeping import ARCHIVE_PAGE, HousekeepingSheet
from slidemage.ui.workspace.maintenance import MaintenanceMixin


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def folders(tmp_path, monkeypatch):
    """A project of its own: pdf/, .build/, decks/ with a leftover wrapper, .temp/ and unused content."""
    root = tmp_path
    for name in ("pdf", "build", "decks", ".temp", "media", "slides"):
        (root / name).mkdir()
    (root / "pdf" / "a.pdf").write_bytes(b"x" * 2048)
    (root / "pdf" / "b.pdf").write_bytes(b"x")
    (root / "build" / "t-Deck-instructor-abc").mkdir()
    (root / "build" / "legacy.log").write_text("log", encoding="utf-8")
    (root / "decks" / "_slidemage_t.tex").write_text("wrapper", encoding="utf-8")
    (root / "decks" / "deck.tex").write_text(r"\slide{abc-EN-Kept}", encoding="utf-8")
    (root / ".temp" / "scratch.pptx").write_text("scratch", encoding="utf-8")
    (root / "slides" / "abc-EN-Kept-current.tex").write_text(r"\includegraphics{media/kept.png}", encoding="utf-8")
    (root / "slides" / "abd-EN-Gone-current.tex").write_text("x", encoding="utf-8")
    (root / "media" / "kept.png").write_bytes(b"i")
    (root / "media" / "gone.png").write_bytes(b"i")
    monkeypatch.setattr(housekeeping, "PDF_DIR", root / "pdf")
    monkeypatch.setattr(housekeeping, "DECKS_DIR", root / "decks")
    monkeypatch.setattr(housekeeping, "TEMP_DIR", root / ".temp")
    monkeypatch.setattr(housekeeping.compiler, "removable_build_entries",
                        lambda: sorted((root / "build").iterdir()))
    for name, value in (("MEDIA_DIR", root / "media"), ("MEDIA_ARCHIVE_DIR", root / "media" / "archive"),
                        ("SLIDES_DIR", root / "slides"), ("SLIDES_ARCHIVE_DIR", root / "slides" / "archive"),
                        ("DECKS_DIR", root / "decks"), ("ARCHIVE_DIR", root / "decks" / "archive")):
        monkeypatch.setattr(unused_content, name, value)
    return root


# -- housekeeping.py -------------------------------------------------------------------------------

def test_the_temp_files_are_the_build_items_the_wrappers_and_the_scratch_folder(folders):
    found = housekeeping.find_temp_files()
    assert [p.name for p in found.build] == ["legacy.log", "t-Deck-instructor-abc"]
    assert [p.name for p in found.wrappers] == ["_slidemage_t.tex"]
    assert [p.name for p in found.scratch] == ["scratch.pptx"]
    assert found.count == 4 and found
    housekeeping.remove_temp_files(found)
    assert not housekeeping.find_temp_files()
    assert (folders / "decks" / "deck.tex").is_file()           # a real deck stays


def test_pdf_files_lists_only_files_and_delete_removes_them(folders):
    (folders / "pdf" / "sub").mkdir()
    assert sorted(p.name for p in housekeeping.pdf_files()) == ["a.pdf", "b.pdf"]
    housekeeping.delete_files(housekeeping.pdf_files())
    assert housekeeping.pdf_files() == []


def test_archive_files_moves_only_what_it_is_given(folders):
    media, slides = unused_content.find_unused_media(), unused_content.find_unused_slides()
    assert [p.name for p in media] == ["gone.png"] and [p.name for p in slides] == ["abd-EN-Gone-current.tex"]
    logged: list = []
    assert unused_content.archive_files([], slides, logged.append) == (0, 1)
    assert (folders / "media" / "gone.png").is_file() and (folders / "slides" / "archive" / slides[0].name).is_file()
    assert logged[-1].startswith("==== Archive unused content done")


# -- the window's actions --------------------------------------------------------------------------

class Window(MaintenanceMixin, QWidget):
    compiling = False

    def __init__(self):
        super().__init__()
        self.logged: list[str] = []

    def _log(self, line):
        self.logged.append(line)


def test_empty_pdf_asks_first(folders, monkeypatch, qapp):
    window = Window()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    window._empty_pdf_folder()
    assert len(housekeeping.pdf_files()) == 2
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    window._empty_pdf_folder()
    assert housekeeping.pdf_files() == [] and window.logged == ["Emptied pdf/ (2 file(s) deleted)"]


def test_remove_temp_files_is_refused_while_compiling(folders, monkeypatch, qapp):
    window = Window()
    window.compiling = True
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    window._remove_temp_files()
    assert housekeeping.find_temp_files()


# -- the sheet ---------------------------------------------------------------------------------------

def rows(sheet):
    return {"pdf": sheet.pdf, "temp": sheet.temp, "archive": sheet.archive, "previews": sheet.previews,
            "links": sheet.links}


def test_each_row_says_what_there_is_to_do(folders, qapp):
    sheet = HousekeepingSheet(Window())
    assert sheet.pdf.sub.text().startswith("2 files in pdf/ · 2 KB")
    assert "2 items in .build/, 1 leftover wrapper file in decks/, 1 item in .temp/" in sheet.temp.sub.text()
    assert sheet.archive.sub.text() == "1 slide and 1 media file nothing uses"
    assert all(row.button.isEnabled() for row in rows(sheet).values())


def test_rows_with_nothing_to_do_are_disabled_and_a_compile_blocks_the_dangerous_ones(folders, qapp):
    housekeeping.delete_files(housekeeping.pdf_files())
    window = Window()
    window.compiling = True
    sheet = HousekeepingSheet(window)
    state = {name: row.button.isEnabled() for name, row in rows(sheet).items()}
    assert state == {"pdf": False, "temp": False, "archive": False, "previews": False, "links": True}
    assert sheet.pdf.sub.text() == "pdf/ is empty"


def test_the_buttons_run_the_windows_actions_and_the_sheet_follows(folders, qapp, monkeypatch):
    window = Window()
    window._empty_pdf_folder = lambda: housekeeping.delete_files(housekeeping.pdf_files())
    window._on_sync_translation_links = lambda: 3
    sheet = HousekeepingSheet(window)
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


def test_archive_review_lists_the_files_and_moves_the_ticked_ones(folders, qapp):
    window = Window()
    sheet = HousekeepingSheet(window, ARCHIVE_PAGE)
    assert sheet.windowTitle() == "Archive unused content" and sheet.files.count() == 2
    assert sheet.archive_button.text() == "Archive 2 files"
    slide_item = next(sheet.files.item(i) for i in range(2) if sheet.files.item(i).text().startswith("slide"))
    slide_item.setCheckState(Qt.CheckState.Unchecked)
    assert sheet.archive_button.text() == "Archive 1 file"
    sheet.archive_button.click()
    wait_for_archive(sheet)
    assert (folders / "media" / "archive" / "gone.png").is_file()
    assert (folders / "slides" / "abd-EN-Gone-current.tex").is_file()      # unticked: stays
    assert sheet.pages.currentIndex() == sheet_module.LIST_PAGE
    assert sheet.archive.sub.text() == "Moved 1 media file to media/archive/ and 0 slides to slides/archive/"
    assert any("Archived media file: gone.png" in line for line in window.logged)


def test_select_none_leaves_nothing_to_archive_and_cancel_goes_back(folders, qapp):
    sheet = HousekeepingSheet(Window(), ARCHIVE_PAGE)
    next(b for b in sheet.findChildren(QPushButton) if b.text() == "Select none").click()
    assert not sheet.archive_button.isEnabled() and sheet.archive_button.text() == "Archive 0 files"
    sheet.back_button.click()
    assert sheet.pages.currentIndex() == sheet_module.LIST_PAGE and sheet.windowTitle() == "Housekeeping"


def test_closing_the_sheet_lets_a_running_move_finish(folders, qapp):
    sheet = HousekeepingSheet(Window(), ARCHIVE_PAGE)
    sheet.archive_button.click()
    sheet.reject()                                   # the move is short: the sheet gives it a moment, then lets go
    assert sheet._worker is None
    QApplication.processEvents()
    assert (Path(folders) / "media" / "archive" / "gone.png").is_file()
