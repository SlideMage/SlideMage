# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Import PPTX/ODP sheet: a file, a deck and a language go to slide_import (tested on its own)."""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QMessageBox, QWidget

from conftest import wait_until
from slidemage.project import ProjectContext
from slidemage import deck_editor, deck_scan, slide_import
from slidemage.ui.workspace.chat.gui_workspace import GuiWorkspace
from slidemage.ui.dialogs.import_presentation import ImportPresentationSheet


class FakeWindow(QWidget):
    def __init__(self, project):
        super().__init__()
        self.project = project
        self.edits, self.logged = [], []
        self.centre = SimpleNamespace(is_dirty=lambda _path: False)
        self.assistant = SimpleNamespace(workspace=GuiWorkspace(self))

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


def test_it_starts_on_the_open_deck_and_needs_a_file_and_clean_deck(sheet):
    assert sheet.deck_combo.currentText() == "beta" and sheet.language.current() == "EN"
    sheet.import_button.click()
    assert sheet.errors == ["Choose a file to import first."] and sheet.window.edits == []
    sheet.file_edit.setText(str(sheet.tmp / "talk.pptx"))
    sheet.window.centre.is_dirty = lambda path: path == sheet.tmp / "decks/beta.tex"
    sheet.import_button.click()
    assert "beta.tex has unsaved edits" in sheet.errors[-1]
    assert sheet._worker is None and sheet.window.edits == []


def test_the_import_runs_on_a_worker_and_the_sheet_closes_in_done(sheet, monkeypatch):
    calls, release = [], threading.Event()
    summary = slide_import.ImportSummary(imported=[1, 2, 3], skipped_blank=1, after="committed")

    def fake(_ctx, path, deck, language, log=None, on_progress=None, is_dirty=None):
        log("Imported x")                            # the app log is a widget: it is written on the GUI thread
        release.wait(5)
        calls.append((path.name, deck.name, language, threading.current_thread() is threading.main_thread()))
        return summary

    monkeypatch.setattr(slide_import, "import_presentation", fake)
    sheet.file_edit.setText(str(sheet.tmp / "talk.pptx"))
    sheet.deck_combo.setCurrentText("alpha")
    sheet.language.set_current("DE")
    sheet.show()
    sheet.import_button.click()
    assert not sheet.import_button.isEnabled() and not sheet.cancel_button.isEnabled()
    sheet.reject()                                   # Escape, Cancel and close cannot end it
    assert sheet.isVisible() and sheet.window.edits == []
    release.set()
    wait_until(lambda: sheet.window.edits)
    assert calls == [("talk.pptx", "alpha", "DE", False)] and sheet.window.logged == ["Imported x"]
    assert sheet.window.edits[0][:2] == (
        "alpha.tex", "Imported 3 slide(s) from talk.pptx into alpha (1 blank source slide(s) skipped). "
        "Undo keeps the library slides and their IDs.")
    assert sheet.window.edits[0][2] == deck_editor.DeckUndo(
        "Undo", {sheet.tmp / "decks/alpha.tex": (sheet.deck_combo.currentData().text, "committed")})
    assert sheet.result() == sheet.DialogCode.Accepted


def test_a_failed_import_is_reported_and_the_sheet_stays_open(sheet, monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("not a presentation")

    monkeypatch.setattr(slide_import, "import_presentation", fail)
    sheet.file_edit.setText(str(sheet.tmp / "bad.odp"))
    sheet.import_button.click()
    wait_until(lambda: sheet.errors)
    assert sheet.import_button.isEnabled()
    assert sheet.errors == ["Could not import bad.odp:\n\nnot a presentation"] and sheet.window.edits == []
