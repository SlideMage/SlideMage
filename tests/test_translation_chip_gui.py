# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The language chip above the Preview in the whole workspace window: it shows the translation partner of the
slide (and back) while the slide list, the editor and the top bar keep their place. Nothing is rendered here."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from conftest import build_window, make_project
from slidemage import slide_snapshot
from slidemage.deck_scan import scan_decks
from slidemage.project import ProjectContext
from slidemage.ui.workspace.preview_view import PreviewPane

GERMAN = "abe-DE-Hallo-current.tex"


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    root = make_project(monkeypatch, tmp_path / "project")
    slides = root / "slides"
    english = slides / "abc-EN-Hello-current.tex"
    english.write_bytes(b"%% DE translation: abe-DE-Hallo\r\n" + english.read_bytes())
    (slides / GERMAN).write_bytes(b"%% Translation of: abc-EN-Hello\r\n"
                                  + english.read_bytes().split(b"\r\n", 1)[1].replace(b"Hello", b"Hallo"))
    monkeypatch.setattr(slide_snapshot, "render_template", lambda root=None: "uni-graz")
    monkeypatch.setattr(PreviewPane, "render_after_save", lambda self: None)
    window = build_window(monkeypatch, ProjectContext.at(root))
    window.show()
    window.state.set_mode("preview")
    window.state.set_deck(next(d for d in scan_decks(window.project) if d.name == "test"))
    window.state.set_focused_slide("abc")
    window.root = root
    return window


def chip(window):
    layout = window.centre.preview._chips
    return next(w for w in (layout.itemAt(i).widget() for i in range(layout.count()))
                if w is not None and w._icon.text() == "language")


def test_the_chip_moves_one_slide_to_its_partner_and_back_while_the_list_and_top_bar_stay(window):
    state, centre = window.state, window.centre
    assert chip(window).text() == "EN + DE"
    chip(window).clicked.emit()
    QApplication.processEvents()
    assert centre.path == window.root / "slides" / GERMAN and state.mode == "preview" and state.language == "EN"
    assert state.focused_slide == "abe" and centre.preview._target.id_slug == "abe-DE-Hallo"
    assert [row.call.id for row in window.slide_list.tree.selected_rows()] == ["abc"]     # the slot stays selected in the list
    assert chip(window).text() == "DE + EN" and chip(window).toolTip() == "Go to the English original"
    chip(window).clicked.emit()
    QApplication.processEvents()
    assert centre.path == window.root / "slides" / "abc-EN-Hello-current.tex" and state.focused_slide == "abc"
    assert state.language == "EN" and chip(window).text() == "EN + DE"


def test_the_chip_by_keyboard(window):
    window.activateWindow()
    chip(window).setFocus(Qt.FocusReason.TabFocusReason)
    QApplication.processEvents()
    assert chip(window).focusPolicy() == Qt.FocusPolicy.TabFocus
    QTest.keyClick(chip(window), Qt.Key.Key_Return)
    assert window.centre.path.name == GERMAN
    assert chip(window).accessibleName() == "Go to the English original"
