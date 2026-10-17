"""Find and Replace behavior in the shared source editor."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton

from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.workspace.source_editor import FindBar, LatexPlainTextEdit
from slidemage.ui.workspace.source_file import SourceFile
from conftest import EXAMPLE_PROJECT


def make_editor(text):
    editor = LatexPlainTextEdit(ThemeManager())
    editor.set_text(text)
    return editor, FindBar(editor)


@pytest.mark.parametrize("text, select_match, expected, next_match", [
    ("cat CAT cat", True, "dog CAT cat", "CAT"),
    ("a cat b cat", False, "a dog b cat", "cat"),
])
def test_replace_match_and_advance(qapp, text, select_match, expected, next_match):
    editor, bar = make_editor(text)
    bar.find_entry.setText("cat")
    bar.replace_entry.setText("dog")
    if select_match:
        bar._on_next()
    bar._on_replace()
    assert editor.text() == expected
    assert editor.selected_text() == next_match
    assert editor.is_modified()
    editor.undo()
    assert editor.text() == text


def test_next_and_previous_wrap_around(qapp):
    editor, bar = make_editor("one two one")
    bar.find_entry.setText("one")
    bar._on_next()
    bar._on_next()
    assert editor.textCursor().selectionStart() == 8
    bar._on_next()
    assert editor.textCursor().selectionStart() == 0
    bar._find(backward=True)
    assert editor.textCursor().selectionStart() == 8


def test_replace_all_is_literal_case_insensitive_and_one_undo_step(qapp):
    editor, bar = make_editor("😀 a+b A+B a+b")
    bar.find_entry.setText("a+b")
    bar.replace_entry.setText("a+b a+b")

    bar._on_replace_all()

    assert editor.text() == "😀 a+b a+b a+b a+b a+b a+b"
    assert bar.status_label.text() == "Replaced 3 matches"
    editor.undo()
    assert editor.text() == "😀 a+b A+B a+b"


def test_empty_and_absent_queries_leave_text_unchanged(qapp):
    editor, bar = make_editor("alpha beta")
    bar.replace_entry.setText("gamma")
    bar._on_replace_all()
    assert bar.status_label.text() == "Enter text to find"
    bar.find_entry.setText("missing")
    bar._on_replace()
    assert bar.status_label.text() == "Not found"
    bar._on_replace_all()
    assert bar.status_label.text() == "Not found"
    assert editor.text() == "alpha beta"


def test_replace_controls_and_ctrl_h_are_available(tmp_path, qapp):
    path = tmp_path / "deck.tex"
    path.write_text("alpha", encoding="utf-8")
    file = SourceFile(type("App", (), {"theme": ThemeManager(), "project": EXAMPLE_PROJECT})(), path)
    labels = {button.text() for button in file.find_bar.findChildren(QPushButton)}
    assert {"Replace", "Replace All"} <= labels
    assert any(shortcut.key() == QKeySequence("Ctrl+H") for shortcut in file.findChildren(QShortcut))
    file.show()
    file.editor.setFocus()
    qapp.processEvents()
    QTest.keyClick(file.editor, Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier)
    qapp.processEvents()
    assert file.find_bar.isVisible()
    QTest.keyClick(file.find_bar.find_entry, Qt.Key.Key_Escape)
    assert not file.find_bar.isVisible()
