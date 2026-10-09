"""Find and Replace behavior in the shared source editor."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from slidemage.qt_slide_source_tab import SlideSourceTab
from slidemage.ui.kit.theme import ThemeManager


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def make_editor(tmp_path, text, qapp):
    path = tmp_path / "deck.tex"
    path.write_text(text, encoding="utf-8", newline="")
    app = SimpleNamespace(theme=ThemeManager(), log=lambda _line: None)
    return SlideSourceTab(app, path), path


def test_replace_selected_match_and_advance(tmp_path, qapp):
    tab, path = make_editor(tmp_path, "cat CAT cat", qapp)
    tab.find_entry.setText("cat")
    tab.replace_entry.setText("dog")
    tab._on_find_next()

    tab._on_replace()

    assert tab.widget.toPlainText() == "dog CAT cat"
    assert tab.widget.textCursor().selectedText() == "CAT"
    assert tab.widget.document().isModified()
    assert path.read_text(encoding="utf-8") == "cat CAT cat"  # Save remains explicit.
    tab.widget.undo()
    assert tab.widget.toPlainText() == "cat CAT cat"


def test_replace_all_is_literal_case_insensitive_and_one_undo_step(tmp_path, qapp):
    tab, _ = make_editor(tmp_path, "😀 a+b A+B a+b", qapp)
    tab.find_entry.setText("a+b")
    tab.replace_entry.setText("a+b a+b")

    tab._on_replace_all()

    assert tab.widget.toPlainText() == "😀 a+b a+b a+b a+b a+b a+b"
    assert tab.find_status_label.text() == "Replaced 3 matches"
    tab.widget.undo()
    assert tab.widget.toPlainText() == "😀 a+b A+B a+b"


def test_empty_and_absent_queries_leave_text_unchanged(tmp_path, qapp):
    tab, _ = make_editor(tmp_path, "alpha beta", qapp)
    tab.replace_entry.setText("gamma")
    tab._on_replace_all()
    assert tab.find_status_label.text() == "Enter text to find"
    tab.find_entry.setText("missing")
    tab._on_replace()
    assert tab.find_status_label.text() == "Not found"
    tab._on_replace_all()
    assert tab.find_status_label.text() == "Not found"
    assert tab.widget.toPlainText() == "alpha beta"


def test_replace_controls_and_ctrl_h_are_available(tmp_path, qapp):
    tab, _ = make_editor(tmp_path, "alpha", qapp)
    labels = {button.text() for button in tab.find_bar.findChildren(QPushButton)}
    assert {"Replace", "Replace All"} <= labels
    assert any(shortcut.key() == QKeySequence("Ctrl+H")
               for shortcut in tab.findChildren(QShortcut))
    tab.show()
    tab.widget.setFocus()
    qapp.processEvents()
    QTest.keyClick(tab.widget, Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier)
    qapp.processEvents()
    assert tab.find_bar.isVisible()
