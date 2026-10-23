# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Shift+Tab takes one indentation level off the lines the cursor or selection is on; Tab on several lines adds
one (v8.58.0)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest

from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.workspace.source_editor import LatexPlainTextEdit


def make_editor(text, start, end=None):
    editor = LatexPlainTextEdit(ThemeManager(), tab_width=4)
    editor.set_text(text)
    cursor = editor.textCursor()
    cursor.setPosition(start)
    if end is not None:
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    return editor


def test_shift_tab_outdents_the_cursor_line(qapp):
    editor = make_editor("a\n\t\t\\item b\nc", 5)
    QTest.keyClick(editor, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
    assert editor.text() == "a\n\t\\item b\nc"


def test_shift_tab_outdents_every_selected_line_as_one_undo_step(qapp):
    text = "\t\\item a\n    \\item b\nc\n\td"
    editor = make_editor(text, 1, text.index("c") + 1)
    QTest.keyClick(editor, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
    assert editor.text() == "\\item a\n\\item b\nc\n\td"
    editor.undo()
    assert editor.text() == text


def test_tab_on_several_lines_indents_them_and_shift_tab_takes_it_back(qapp):
    text = "\\item a\n\n\\item b"
    editor = make_editor(text, 0, len(text))
    QTest.keyClick(editor, Qt.Key.Key_Tab)
    assert editor.text() == "\t\\item a\n\n\t\\item b"           # an empty line stays empty
    QTest.keyClick(editor, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
    assert editor.text() == text


def test_tab_within_one_line_still_types_a_tab(qapp):
    editor = make_editor("ab", 1)
    QTest.keyClick(editor, Qt.Key.Key_Tab)
    assert editor.text() == "a\tb"


def test_a_read_only_editor_is_left_alone(qapp):
    editor = make_editor("\tx", 1)
    editor.set_read_only(True)
    QTest.keyClick(editor, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
    assert editor.text() == "\tx"
