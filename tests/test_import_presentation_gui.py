"""The Import PPTX/ODP sheet: a file, a deck and a language go to slide_import (tested on its own)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QMessageBox, QWidget

from slidemage.project import ProjectContext
from slidemage import deck_scan, slide_import
from slidemage.ui.dialogs.import_presentation import ImportPresentationSheet


class FakeWindow(QWidget):
    def __init__(self, project):
        super().__init__()
        self.project = project
        self.edits, self.logged = [], []

    def log(self, line):
        self.logged.append(line)

    def after_deck_edit(self, path, summary, previous_text=None):
        self.edits.append((path.name, summary, previous_text))


@pytest.fixture
def sheet(tmp_path, monkeypatch, qapp):
    context = ProjectContext.at(tmp_path)
    context.decks_dir.mkdir()
    for name in ("alpha", "beta"):
        (context.decks_dir / f"{name}.tex").write_text("\\documentclass{beamer}\n\\begin{document}\n\\end{document}\n",
                                              encoding="utf-8")
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: errors.append(args[2]))
    window = FakeWindow(context)
    made = ImportPresentationSheet(window, next(d for d in deck_scan.scan_decks(context) if d.name == "beta"))
    made.errors, made.window, made.tmp = errors, window, tmp_path
    yield made
    made.deleteLater()
    window.deleteLater()


def test_it_starts_on_the_open_deck_and_needs_a_file(sheet):
    assert sheet.deck_combo.currentText() == "beta" and sheet.language.current() == "EN"
    sheet.import_button.click()
    assert sheet.errors == ["Choose a file to import first."] and sheet.window.edits == []


def test_the_slides_are_imported_into_the_chosen_deck(sheet, monkeypatch):
    calls = []
    summary = SimpleNamespace(imported=[1, 2, 3], skipped_blank=1)
    monkeypatch.setattr(slide_import, "import_presentation",
                        lambda path, deck, language, log=None: calls.append((path.name, deck.name, language)) or summary)
    sheet.file_edit.setText(str(sheet.tmp / "talk.pptx"))
    sheet.deck_combo.setCurrentText("alpha")
    sheet.language.set_current("DE")
    sheet.import_button.click()
    assert calls == [("talk.pptx", "alpha", "DE")]
    assert sheet.window.edits[0][:2] == (
        "alpha.tex", "Imported 3 slide(s) from talk.pptx into alpha (1 blank source slide(s) skipped)")
    assert sheet.result() == sheet.DialogCode.Accepted


def test_a_failed_import_is_reported_and_the_sheet_stays_open(sheet, monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("not a presentation")

    monkeypatch.setattr(slide_import, "import_presentation", fail)
    sheet.file_edit.setText(str(sheet.tmp / "bad.odp"))
    sheet.import_button.click()
    assert sheet.errors == ["Could not import bad.odp:\n\nnot a presentation"] and sheet.window.edits == []
