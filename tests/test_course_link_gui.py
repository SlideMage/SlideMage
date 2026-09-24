"""The course-link row action saves and opens the entered URL."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton

from slidemage import deck_editor, qt_gui
from slidemage.deck_scan import Deck
from slidemage.qt_course_link_dialog import CourseLinkDialog
from slidemage.qt_deck_table import DeckTable
from slidemage.qt_theme import ThemeManager


COURSE_URL = "https://online.uni-graz.at/kfu_online/wbLv.wbShowLVDetail?pStpSpNr=1002516"


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def test_course_link_dialog_accepts_url_for_open(qapp):
    dialog = CourseLinkDialog(None, "BachelorCourse", None)
    assert not dialog.open_button.isEnabled()
    dialog.url_edit.setText(COURSE_URL)
    assert dialog.open_button.isEnabled()
    dialog._finish("open")
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.action == "open"
    assert dialog.url == COURSE_URL


def test_enter_saves_the_course_url(qapp):
    dialog = CourseLinkDialog(None, "BachelorCourse", None)
    dialog.url_edit.setText(COURSE_URL)
    dialog.show()
    QTest.keyClick(dialog.url_edit, Qt.Key.Key_Return)
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.action == "save"
    assert dialog.url == COURSE_URL


def test_course_link_action_saves_then_opens(tmp_path, monkeypatch, qapp):
    path = tmp_path / "course.tex"
    text = "\\documentclass{beamer}\n\\begin{document}\n"
    path.write_text(text, encoding="utf-8", newline="")
    deck = Deck(
        name="course", path=path, archived=False, text=text,
        supports_version=False, uses_biblatex=False, preamble_end=0,
        chapters=[], output_folders={}, tags=[],
    )

    class AcceptedDialog:
        def __init__(self, _parent, _name, _url):
            self.action = "open"
            self.url = COURSE_URL

        def exec(self):
            return 1

    opened = []
    refreshed = []
    monkeypatch.setattr(qt_gui, "CourseLinkDialog", AcceptedDialog)
    monkeypatch.setattr(qt_gui.open_path, "open_in_default_app", opened.append)
    window = SimpleNamespace(
        _slide_source_tabs={}, _log=lambda _line: None,
        refresh_open_deck_editors=lambda: refreshed.append(True),
    )

    qt_gui.SlideMageWindow._on_course_link(window, deck)

    assert deck_editor.normalize_course_url(COURSE_URL) == COURSE_URL
    assert f"%% SlideMage course URL: {COURSE_URL}" in path.read_text()
    assert opened == [COURSE_URL]
    assert refreshed == [True]


@pytest.mark.parametrize("archivable", [True, False])
def test_course_link_button_is_available_in_deck_tables(tmp_path, qapp, archivable):
    deck = Deck(
        name="course", path=tmp_path / "course.tex", archived=not archivable,
        text="", supports_version=False, uses_biblatex=False, preamble_end=0,
        chapters=[], output_folders={}, tags=[],
    )
    clicked = []
    table = DeckTable(
        ThemeManager(), archivable=archivable,
        on_open=lambda _deck: None,
        on_archive=None, on_edit=None, on_duplicate=None, on_export_pptx=None,
        on_compile_selected=lambda _rows: None,
        on_stop_compilation=lambda: None,
        on_create_transcript=lambda _rows: None,
        on_refresh=lambda: None,
        on_course_link=clicked.append,
    )
    table.rebuild([deck])

    buttons = [button for button in table.findChildren(QPushButton)
               if button.text() == "Course link..."]
    assert len(buttons) == 1
    buttons[0].click()
    assert clicked == [deck]
