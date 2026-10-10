"""The transcript preview sheet: one slide's entry, rendered from text, nothing written."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from slidemage.ui.dialogs import transcript_preview


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def window_stand_in():
    window = QWidget()
    window.logged = []
    window.log = window.logged.append
    return window


def test_the_sheet_shows_the_rendered_entry_of_the_text(qapp, monkeypatch):
    shown = []
    monkeypatch.setattr(transcript_preview.TranscriptPreviewSheet, "exec", lambda sheet: shown.append(sheet))
    window = window_stand_in()
    source = "\\begin{standardframe}{Hello}\n\\begin{itemize}\\item First point\\end{itemize}\n\\end{standardframe}\n"
    transcript_preview.show_transcript_preview(window, source, "abc", "abc-EN-Hello", "after-course", "EN")
    [sheet] = shown
    assert sheet.windowTitle() == "Transcript: abc-EN-Hello"
    assert "First point" in sheet.browser.toPlainText()
    assert window.logged == []


def test_an_undescribed_image_is_logged_and_a_failure_is_shown(qapp, monkeypatch):
    window = window_stand_in()
    shown, errors = [], []
    monkeypatch.setattr(transcript_preview.TranscriptPreviewSheet, "exec", lambda sheet: shown.append(sheet))
    monkeypatch.setattr(transcript_preview.transcript, "generate_single_slide",
                        lambda *args: SimpleNamespace(undescribed=2, markdown="# T", language="en"))
    transcript_preview.show_transcript_preview(window, "x", "abc", "abc-EN-Hello", "during-course", "EN")
    assert shown and "undescribed image" in window.logged[0]

    def broken(*args):
        raise RuntimeError("no frame")

    monkeypatch.setattr(transcript_preview.transcript, "generate_single_slide", broken)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: errors.append(args[2]))
    shown.clear()
    transcript_preview.show_transcript_preview(window, "x", "abc", "abc-EN-Hello", "during-course", "EN")
    assert errors == ["no frame"] and shown == []
    assert QApplication.overrideCursor() is None
