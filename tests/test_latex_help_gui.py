# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Source view shows a command's help when the pointer rests on it, and with Shift+F1 at the text cursor
(latex_help.py, docs/plans/latex-hover-help.md)."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QHelpEvent, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolTip

from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.workspace.source_editor import LatexPlainTextEdit

TEXT = "Some text\n\\cornerfigure[height=5cm, corner=se]{media/x.png}\n% \\cornerfigure in a comment"


def make_editor(text=TEXT, hover_help=True):
    editor = LatexPlainTextEdit(ThemeManager(), hover_help=hover_help)
    editor.resize(900, 300)
    editor.set_text(text)
    editor.show()
    QApplication.processEvents()
    return editor


def point_at(editor, offset, right_half=False):
    """The viewport point over the character at `offset` (its left or right half)."""
    cursor = QTextCursor(editor.document())
    cursor.setPosition(offset)
    left = editor.cursorRect(cursor)
    cursor.setPosition(offset + 1)
    right = editor.cursorRect(cursor)
    x = left.x() + (3 * (right.x() - left.x()) // 4 if right_half else 1)
    return QPoint(x, left.center().y())


def hide_tooltip():
    """QToolTip.hideText() hides after a short delay; wait for it, so a later check sees only a new tooltip."""
    QToolTip.hideText()
    for _ in range(60):
        if not QToolTip.isVisible():
            return
        QTest.qWait(50)


def tooltip(editor, point):
    hide_tooltip()
    event = QHelpEvent(QEvent.Type.ToolTip, point, editor.viewport().mapToGlobal(point))
    QApplication.sendEvent(editor.viewport(), event)
    QApplication.processEvents()
    return QToolTip.text() if QToolTip.isVisible() else ""


def test_help_at_point_on_the_command_and_on_a_key(qapp):
    editor = make_editor()
    start = TEXT.index("\\cornerfigure")
    for offset, right_half in ((start, False), (start + 5, True), (start + len("\\cornerfigure") - 1, True)):
        hit, rect = editor.help_at_point(point_at(editor, offset, right_half))
        assert hit.help.name == "cornerfigure" and hit.key is None
        assert rect.contains(point_at(editor, offset, right_half))
    hit, _rect = editor.help_at_point(point_at(editor, TEXT.index("se]")))
    assert hit.key == "corner"


def test_no_help_on_plain_text_a_comment_or_past_the_line(qapp):
    editor = make_editor()
    assert editor.help_at_point(point_at(editor, 2)) is None
    assert editor.help_at_point(point_at(editor, TEXT.rindex("cornerfigure"))) is None
    # the right half of the line's last character, then far right of the line's end
    end_of_line = TEXT.index("\n", TEXT.index("cornerfigure"))
    assert editor.help_at_point(point_at(editor, end_of_line - 1, right_half=True)) is None
    assert editor.help_at_point(QPoint(880, point_at(editor, end_of_line - 1).y())) is None
    assert editor.help_at_point(QPoint(10, 290)) is None                 # below the last line


def test_the_tooltip_shows_on_hover_and_not_when_switched_off(qapp):
    editor = make_editor()
    point = point_at(editor, TEXT.index("\\cornerfigure") + 3)
    text = tooltip(editor, point)
    assert "\\cornerfigure[keys]{image file or content}" in text and "=ne | nw" in text
    assert tooltip(editor, point_at(editor, 2)) == ""
    editor.set_hover_help(False)
    assert tooltip(editor, point) == ""
    hide_tooltip()


def test_hover_help_off_from_the_start(qapp):
    editor = make_editor(hover_help=False)
    assert tooltip(editor, point_at(editor, TEXT.index("\\cornerfigure") + 3)) == ""


def test_shift_f1_shows_the_help_at_the_text_cursor_even_when_hover_is_off(qapp):
    editor = make_editor(hover_help=False)
    cursor = editor.textCursor()
    cursor.setPosition(TEXT.index("[height"))           # right after the command's name
    editor.setTextCursor(cursor)
    hide_tooltip()
    QTest.keyClick(editor, Qt.Key.Key_F1, Qt.KeyboardModifier.ShiftModifier)
    assert QToolTip.isVisible() and "cornerfigure" in QToolTip.text()
    assert editor.text() == TEXT                         # nothing typed
    cursor.setPosition(3)
    editor.setTextCursor(cursor)
    assert editor.show_help_at_cursor() is False
    hide_tooltip()


def test_characters_outside_the_bmp_before_the_command(qapp):
    text = "\U0001F600 \\fitfigure[top=margin]{x.png}"
    editor = make_editor(text)
    # Qt counts the emoji as two positions; the editor reads Qt positions on utf16_units() text.
    position = 2 + len(" \\fitfigure[")
    hit, _rect = editor.help_at_point(point_at(editor, position + 1))
    assert hit.help.name == "fitfigure" and hit.key == "top"


def test_the_help_provider_adds_a_themes_commands_and_the_standard_ones_show():
    from slidemage.latex_help import parse_help

    extra = parse_help('[[command]]\nname = "mytitle"\nsignature = "\\\\mytitle{text}"\nsummary = "The theme title."\n')
    text = r"\mytitle{A}" + "
" + r"\includegraphics[width=3cm]{x}"
    editor = make_editor(text)
    point = point_at(editor, 3)
    assert tooltip(editor, point) is None or "theme title" not in QToolTip.text()    # no provider yet
    editor.set_help_provider(lambda: extra)
    tooltip(editor, point)
    assert "The theme title." in QToolTip.text()
    tooltip(editor, point_at(editor, text.index("includegraphics") + 2))
    assert "includegraphics" in QToolTip.text()
    editor.set_help_provider(lambda: 1 / 0)                  # a failing provider never breaks the tooltip
    tooltip(editor, point_at(editor, text.index("includegraphics") + 2))
    assert "includegraphics" in QToolTip.text()
