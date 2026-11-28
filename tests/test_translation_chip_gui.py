# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Keyboard navigation between translation partners in Preview."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from conftest import build_window, make_project
from slidemage import slide_templates
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
    monkeypatch.setattr(slide_templates, "render_template", lambda root=None: "acme")
    monkeypatch.setattr(PreviewPane, "render_after_save", lambda self: None)
    window = build_window(monkeypatch, ProjectContext.at(root))
    window.show()
    window.state.set_mode("preview")
    window.state.set_deck(next(d for d in scan_decks(window.project) if d.name == "test"))
    window.state.set_focused_slide("abc")
    return window


def chip(window):
    layout = window.centre.preview._chips
    return next(w for w in (layout.itemAt(i).widget() for i in range(layout.count()))
                if w is not None and w._icon.text() == "language")


def test_the_chip_moves_between_partners_without_changing_the_list_or_top_bar(window):
    state, centre = window.state, window.centre
    button = chip(window)
    assert button.text() == "EN + DE" and button.focusPolicy() == Qt.FocusPolicy.TabFocus
    window.activateWindow()
    button.setFocus(Qt.FocusReason.TabFocusReason)
    QApplication.processEvents()
    QTest.keyClick(button, Qt.Key.Key_Return)
    assert centre.path.name == GERMAN and state.mode == "preview" and state.language == "EN"
    assert state.focused_slide == "abe" and centre.preview._target.id_slug == "abe-DE-Hallo"
    assert [row.call.id for row in window.slide_list.tree.selected_rows()] == ["abc"]
    button = chip(window)
    assert button.text() == "DE + EN" and button.accessibleName() == "Go to the English original"
    QTest.keyClick(button, Qt.Key.Key_Return)
    QApplication.processEvents()
    assert centre.path.name == "abc-EN-Hello-current.tex" and state.focused_slide == "abc"
    assert state.language == "EN" and chip(window).text() == "EN + DE"
