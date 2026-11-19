# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Source view's text editor (docs/UI_REDESIGN_PLAN.md, step 5): LaTeX
highlighting, a line-number gutter, smart Enter, matching braces, a foldable
header comment and a find/replace bar.

The rest of the workspace talks to an editor through the `SourceEditor`
protocol below and never touches a Qt text cursor, so EMBEDDED_EDITOR_PLAN.md
can swap in another implementation. What each command does to the text is in
latex_edit.py (Qt-free, unit-tested); `LatexPlainTextEdit` only turns a cursor
and a selection into its arguments and puts the result back. Positions that
Qt reports count UTF-16 code units, latex_edit's count characters;
`utf16_len()`/`utf16_units()` convert.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Optional, Protocol

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QKeySequence,
    QPainter,
    QShortcut,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QTextEdit, QToolTip, QVBoxLayout, QWidget

from ... import latex_edit, latex_help
from ...latex_edit import DEFAULT_TAB_WIDTH_CHARS, Edit, Insert, utf16_len, utf16_units
from ...tex_source import COMMENT_RE
from ..kit.tokens import SPACE
from ..kit import kit_qss as q
from ..kit.theme import ThemeManager
from ..kit.tokens import FONT_MONO, TYPE
from ..kit.widgets import Button, IconButton

# Comments, commands and braces as before; the rest (environments, math, TODO
# markers) cost nothing extra, since a QSyntaxHighlighter re-runs only the
# blocks that changed.
COMMAND_RE = re.compile(r"\\[a-zA-Z]+\*?|\\.")
BRACE_RE = re.compile(r"(?<!\\)[{}]")
ENV_RE = re.compile(r"\\(?:begin|end)\{([a-zA-Z*]+)\}")
MATH_RE = re.compile(r"(?<!\\)\$[^$]*\$")
TODO_RE = re.compile(r"\b(?:TODO|FIXME|XXX)\b")

FONT_PX = TYPE.body


class SourceEditor(Protocol):
    """What the Source view needs from a text editor. Line numbers count from
    1, offsets are characters into `text()`.

    Signals: `modified_changed(bool)` (the buffer differs from what was last
    marked saved), `text_changed()` and `escape_pressed()`."""

    modified_changed: Any
    text_changed: Any
    escape_pressed: Any

    def widget(self) -> QWidget: ...
    def text(self) -> str: ...
    def set_text(self, text: str) -> None:
        """Load `text`: undo history gone, buffer marked saved."""
    def mark_saved(self) -> None: ...
    def is_modified(self) -> bool: ...
    def patch_text(self, text: str) -> None:
        """Change the buffer to `text` by replacing only what differs, so cursor,
        scroll position and undo history stay (a save rewrites the version line)."""
    def replace_all_text(self, text: str) -> None:
        """Replace the whole buffer as one undo step."""
    def undo(self) -> None: ...
    def redo(self) -> None: ...
    def replace_line(self, line: int, text: str) -> None: ...
    def selected_text(self) -> str: ...
    def selection_range(self) -> tuple[int, int]:
        """(start, end) of the selection as offsets into `text()`; equal when nothing is selected."""
    def replace_selection(self, text: str) -> None:
        """Insert `text` at the cursor, replacing the selection."""
    def go_to_line(self, line: int) -> None: ...
    def go_to_offset(self, offset: int) -> None: ...
    def set_read_only(self, read_only: bool) -> None: ...
    def is_read_only(self) -> bool: ...
    # commands (what each does is latex_edit's)
    def wrap_macro(self, macro: str) -> None: ...
    def apply_insert(self, insert: Insert) -> bool:
        """False if `insert` needs the user's input first (a hyperlink)."""
    def toggle_comment(self) -> None: ...
    def reindent(self, kind: str = "slide") -> bool:
        """False if the indentation was already right. `kind`: "slide", "deck" or "bib"."""
    # header comment
    def header_line_count(self) -> int: ...
    def is_header_folded(self) -> bool: ...
    def set_header_folded(self, folded: bool) -> None: ...
    # search
    def find_text(self, query: str, backward: bool = False) -> bool:
        """Select the next (previous) match from the cursor, wrapping around once."""
    def replace_all(self, query: str, replacement: str) -> int:
        """Replace every match (case-insensitive, literal) as one undo step."""
    # settings
    def set_tab_width(self, chars: int) -> None: ...
    def set_hover_help(self, on: bool) -> None:
        """Show the help of a LaTeX command under the pointer (latex_help.py); Shift+F1 works either way."""
    def refresh_colors(self) -> None: ...


def spelling_selections(edit: QPlainTextEdit, marks: list[tuple[int, int]], color: str) -> list:
    """Red wavy underlines (ExtraSelections) of `edit` on the character ranges `marks` (offsets into its plain text;
    Qt counts UTF-16 code units, so a character outside the BMP counts twice there)."""
    text = edit.toPlainText()
    fmt = QTextCharFormat()
    # The platform's spell-check underline is a hairline that is easy to overlook; a wavy line plus a faint
    # tint behind the word makes an unknown word visible at a glance.
    fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
    fmt.setUnderlineColor(QColor(color))
    tint = QColor(color)
    tint.setAlpha(45)
    fmt.setBackground(tint)
    selections, done, position = [], 0, 0
    for start, end in sorted(marks):
        if not done <= start < end <= len(text):
            continue
        position += utf16_len(text[done:start])
        length = utf16_len(text[start:end])
        selection = QTextEdit.ExtraSelection()
        selection.format = fmt
        selection.cursor = QTextCursor(edit.document())
        selection.cursor.setPosition(position)
        selection.cursor.setPosition(position + length, QTextCursor.MoveMode.KeepAnchor)
        selections.append(selection)
        position += length
        done = end
    return selections


def char_offset_at(edit: QPlainTextEdit, pos: QPoint) -> int:
    """The character offset into `edit`'s plain text under `pos` (viewport coordinates), on the character the
    pointer is over."""
    cursor = edit.cursorForPosition(pos)
    position = cursor.position()
    if edit.cursorRect(cursor).x() > pos.x() and cursor.positionInBlock() > 0:
        position -= 1
    units = utf16_units(edit.toPlainText())
    return position - sum("\ud800" <= unit <= "\udbff" for unit in units[:position])


def source_font() -> QFont:
    font = QFont(FONT_MONO)
    font.setPixelSize(FONT_PX)
    return font


class LatexSyntaxHighlighter(QSyntaxHighlighter):
    def __init__(self, document: QTextDocument, theme: ThemeManager) -> None:
        super().__init__(document)
        self.theme = theme
        self._formats: dict[str, QTextCharFormat] = {}
        self.refresh_colors()

    def refresh_colors(self) -> None:
        """Rebuild the formats from the current theme and re-highlight every block."""
        colors = self.theme.syntax_colors()

        def make_format(color_key: str, *, bold: bool = False, italic: bool = False) -> QTextCharFormat:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(colors[color_key]))
            if bold:
                fmt.setFontWeight(QFont.Weight.Bold)
            if italic:
                fmt.setFontItalic(True)
            return fmt

        self._formats = {
            "comment": make_format("comment", italic=True),
            "command": make_format("command"),
            "brace": make_format("brace"),
            "env": make_format("env", bold=True),
            "math": make_format("math"),
            "todo": make_format("todo", bold=True),
        }
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        comment_spans = [m.span() for m in COMMENT_RE.finditer(text)]

        def in_comment(pos: int) -> bool:
            return any(start <= pos < end for start, end in comment_spans)

        # Math and \begin/\end{env} only outside comments; painted before
        # comment/command/brace so those don't cover the more specific formats.
        for m in MATH_RE.finditer(text):
            if not in_comment(m.start()):
                self.setFormat(m.start(), m.end() - m.start(), self._formats["math"])
        for m in ENV_RE.finditer(text):
            if not in_comment(m.start()):
                self.setFormat(m.start(), m.end() - m.start(), self._formats["command"])
                self.setFormat(m.start(1), m.end(1) - m.start(1), self._formats["env"])
        for m in COMMAND_RE.finditer(text):
            if not in_comment(m.start()):
                self.setFormat(m.start(), m.end() - m.start(), self._formats["command"])
        for m in BRACE_RE.finditer(text):
            if not in_comment(m.start()):
                self.setFormat(m.start(), m.end() - m.start(), self._formats["brace"])
        # Comments (and TODO/FIXME/XXX inside them) last, so they win over
        # whatever a comment happens to contain (a literal "{" ...).
        for start, end in comment_spans:
            self.setFormat(start, end - start, self._formats["comment"])
        for start, end in comment_spans:
            for m in TODO_RE.finditer(text, start, end):
                self.setFormat(m.start(), m.end() - m.start(), self._formats["todo"])


class _LineNumberArea(QWidget):
    """The gutter; sizing and painting live on the editor, which knows the blocks."""

    def __init__(self, editor: "LatexPlainTextEdit") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:
        self._editor.paint_line_numbers(event)


class LatexPlainTextEdit(QPlainTextEdit):
    """A QPlainTextEdit that is a SourceEditor.

    The gutter numbers real file lines: a line hidden by the header fold is
    skipped, not renumbered around, so the numbers match TeX's own "l.123"
    error lines."""

    modified_changed = Signal(bool)
    text_changed = Signal()
    escape_pressed = Signal()
    # Ctrl+. : the spelling menu for the word at the text cursor (character offset, global position for it).
    spelling_menu_requested = Signal(int, QPoint)

    def __init__(self, theme: ThemeManager, tab_width: int = DEFAULT_TAB_WIDTH_CHARS,
                 hover_help: bool = True) -> None:
        super().__init__()
        self._brace_selections: list[QTextEdit.ExtraSelection] = []
        self._spell_selections: list[QTextEdit.ExtraSelection] = []
        self._spelling_marks: list[tuple[int, int]] = []
        self.setObjectName(q.SOURCE)
        self._theme = theme
        self._hover_help = hover_help
        self._help_provider: Optional[Callable[[], latex_help.HelpSet]] = None
        self._header_lines = 0
        self._header_folded = True
        self.setFont(source_font())
        self.set_tab_width(tab_width)
        self.highlighter = LatexSyntaxHighlighter(self.document(), theme)
        self._line_area = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_area_width)
        self.updateRequest.connect(self._update_line_area)
        self.cursorPositionChanged.connect(self._line_area.update)
        self.cursorPositionChanged.connect(self._highlight_matching_brace)
        self.document().modificationChanged.connect(self.modified_changed)
        self.textChanged.connect(self.text_changed)
        self._update_line_area_width()

    # -- the SourceEditor protocol: the buffer -----------------------------------------

    def widget(self) -> QWidget:
        return self

    def text(self) -> str:
        return self.toPlainText()

    def set_text(self, text: str) -> None:
        self.setPlainText(text)
        self.document().setModified(False)
        # setPlainText() rebuilds every block, so the fold has to be applied again.
        self._header_lines = latex_edit.header_comment_lines(text)
        self.set_header_folded(self._header_folded)

    def mark_saved(self) -> None:
        self.document().setModified(False)

    def is_modified(self) -> bool:
        return self.document().isModified()

    def patch_text(self, text: str) -> None:
        start, end, replacement = latex_edit.minimal_replacement(self.toPlainText(), text)
        if start == end and not replacement:
            return
        scrollbar = self.verticalScrollBar()
        scroll_value = scrollbar.value()
        visible = self.textCursor()
        old_pos = visible.position()
        new_length = utf16_len(replacement)
        if old_pos <= start:
            new_pos = old_pos
        elif old_pos >= end:
            new_pos = old_pos - end + start + new_length
        else:
            new_pos = start + new_length   # the cursor was in the changed part: after the new text
        edit = QTextCursor(self.document())
        edit.beginEditBlock()
        edit.setPosition(start)
        edit.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        edit.insertText(replacement)
        edit.endEditBlock()
        visible.setPosition(new_pos)
        self.setTextCursor(visible)
        scrollbar.setValue(scroll_value)

    def replace_all_text(self, text: str) -> None:
        cursor = self.textCursor()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText(text)
        cursor.endEditBlock()
        self.setTextCursor(cursor)

    def replace_line(self, line: int, text: str) -> None:
        cursor = QTextCursor(self.document().findBlockByNumber(line - 1))
        # StartOfBlock/EndOfBlock, not the LineUnderCursor selection type: that
        # selects one *visual* line, which a long line wrapped on screen would truncate.
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        cursor.beginEditBlock()
        cursor.insertText(text)
        cursor.endEditBlock()

    def selected_text(self) -> str:
        # selectedText() uses U+2029 for a line break; left in, a wrapped
        # multi-line selection would write that character into the .tex file.
        return self.textCursor().selectedText().replace("\u2029", "\n")

    def selection_range(self) -> tuple[int, int]:
        cursor, units = self.textCursor(), utf16_units(self.toPlainText())

        def offset(position: int) -> int:     # Qt counts a character outside the BMP twice
            return position - sum("\ud800" <= unit <= "\udbff" for unit in units[:position])

        return offset(cursor.selectionStart()), offset(cursor.selectionEnd())

    def replace_selection(self, text: str) -> None:
        cursor = self.textCursor()
        cursor.insertText(text)
        self.setTextCursor(cursor)
        self.setFocus()

    def go_to_line(self, line: int) -> None:
        block = self.document().findBlockByNumber(max(0, line - 1))
        if block.isValid():
            self.setTextCursor(QTextCursor(block))
            self.centerCursor()
            self.setFocus()

    def go_to_offset(self, offset: int) -> None:
        cursor = self.textCursor()
        cursor.setPosition(utf16_len(self.toPlainText()[:offset]))
        self.setTextCursor(cursor)
        self.centerCursor()
        self.setFocus()

    def set_read_only(self, read_only: bool) -> None:
        self.setReadOnly(read_only)

    def is_read_only(self) -> bool:
        return self.isReadOnly()

    # -- commands ----------------------------------------------------------------------

    def _insert(self, edit: Edit) -> None:
        """Replace the selection with `edit.text` as one undo step, cursor as it says."""
        cursor = self.textCursor()
        start = cursor.selectionStart()
        cursor.beginEditBlock()
        cursor.insertText(edit.text)
        cursor.setPosition(start + utf16_len(edit.text[:edit.caret]))
        cursor.endEditBlock()
        self.setTextCursor(cursor)
        self.setFocus()

    def _line_indent(self) -> str:
        """Leading whitespace of the line the selection starts on (not of the cursor,
        which is at either end of a selection)."""
        cursor = QTextCursor(self.document())
        cursor.setPosition(self.textCursor().selectionStart())
        return re.match(r"[ \t]*", cursor.block().text()).group(0)

    def wrap_macro(self, macro: str) -> None:
        self._insert(latex_edit.wrap_macro(self.selected_text(), macro))

    def apply_insert(self, insert: Insert) -> bool:
        edit = latex_edit.insert_edit(insert, self.selected_text(), self._line_indent())
        if edit is None:
            return False
        self._insert(edit)
        return True

    def toggle_comment(self) -> None:
        """Ctrl+/ on every line the selection touches (the cursor's own line
        with no selection), as one undo step."""
        cursor = self.textCursor()
        doc = self.document()
        first = doc.findBlock(cursor.selectionStart()).blockNumber()
        last = doc.findBlock(cursor.selectionEnd()).blockNumber()
        # A selection that ends exactly at the start of a line doesn't take that line.
        if cursor.hasSelection() and last > first:
            end = QTextCursor(doc)
            end.setPosition(cursor.selectionEnd())
            if end.atBlockStart():
                last -= 1
        blocks = [doc.findBlockByNumber(n) for n in range(first, last + 1)]
        cursor.beginEditBlock()
        for block, (column, delete, insert) in zip(blocks, latex_edit.comment_ops([b.text() for b in blocks])):
            line = QTextCursor(block)
            line.setPosition(block.position() + column)
            line.setPosition(block.position() + column + delete, QTextCursor.MoveMode.KeepAnchor)
            line.insertText(insert)
        cursor.endEditBlock()
        self.setFocus()

    def _selected_blocks(self) -> list:
        """The lines the selection touches (the cursor's own line with no selection); a selection that ends at the
        start of a line does not take that line."""
        cursor, doc = self.textCursor(), self.document()
        first = doc.findBlock(cursor.selectionStart()).blockNumber()
        last = doc.findBlock(cursor.selectionEnd()).blockNumber()
        if cursor.hasSelection() and last > first:
            end = QTextCursor(doc)
            end.setPosition(cursor.selectionEnd())
            if end.atBlockStart():
                last -= 1
        return [doc.findBlockByNumber(n) for n in range(first, last + 1)]

    def shift_lines(self, outdent: bool) -> None:
        """Tab on a selection of several lines, Shift+Tab on any: one indentation level more (a tab) or less (a
        tab or up to a tab's width of spaces) on every line touched, as one undo step; the selection stays on
        the same text."""
        blocks = self._selected_blocks()
        cursor = self.textCursor()
        cursor.beginEditBlock()
        for block in blocks:
            line = QTextCursor(block)
            if outdent:
                line.setPosition(block.position() + latex_edit.outdent_width(block.text(), self._tab_chars),
                                 QTextCursor.MoveMode.KeepAnchor)
                line.removeSelectedText()
            elif block.text():
                line.insertText("\t")
        cursor.endEditBlock()

    def event(self, event) -> bool:  # noqa: N802 -- Qt's name
        # Tab and Shift+Tab reach the widget's event() first, which would move the focus on Shift+Tab.
        modifiers = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier
        if event.type() == QEvent.Type.KeyPress and not self.isReadOnly() and not event.modifiers() & modifiers:
            key, shift = event.key(), bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if key == Qt.Key.Key_Backtab or (key == Qt.Key.Key_Tab and shift):
                self.shift_lines(outdent=True)
                return True
            if key == Qt.Key.Key_Tab and len(self._selected_blocks()) > 1:
                self.shift_lines(outdent=False)
                return True
        return super().event(event)

    def reindent(self, kind: str = "slide") -> bool:
        """`kind` picks the rules (latex_edit.REINDENTERS): "slide", "deck" or "bib"."""
        old = self.toPlainText()
        new = latex_edit.REINDENTERS[kind](old)
        if new == old:
            return False
        self.replace_all_text(new)
        # Every line's length changed, so "the same offset" means nothing: the top is saner.
        self.go_to_line(1)
        return True

    # -- header comment fold -----------------------------------------------------------

    def header_line_count(self) -> int:
        return self._header_lines

    def is_header_folded(self) -> bool:
        return self._header_folded

    def set_header_folded(self, folded: bool) -> None:
        self._header_folded = folded
        block = self.document().firstBlock()
        for _ in range(self._header_lines):
            if not block.isValid():
                break
            block.setVisible(not folded)
            block = block.next()
        self.document().markContentsDirty(0, self.document().characterCount())
        self.viewport().update()
        # The vertical scrollbar is block-indexed and not remapped when the set of
        # visible blocks changes: without this, unfolding left the viewport on the
        # same (now wrong) blocks instead of the newly revealed top.
        self.verticalScrollBar().setValue(0)

    # -- search ------------------------------------------------------------------------

    def find_text(self, query: str, backward: bool = False) -> bool:
        # find() searches from the cursor onward only; a retry from the far end
        # once it comes up empty gives the usual wrap-around without looping
        # forever on a query that is not there.
        flags = QTextDocument.FindFlag.FindBackward if backward else QTextDocument.FindFlag(0)
        if self.find(query, flags):
            return True
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End if backward else QTextCursor.MoveOperation.Start)
        self.setTextCursor(cursor)
        return self.find(query, flags)

    def replace_all(self, query: str, replacement: str) -> int:
        document = self.document()
        matches: list[tuple[int, int]] = []
        search = QTextCursor(document)
        while True:
            match = document.find(query, search)
            if match.isNull():
                break
            matches.append((match.selectionStart(), match.selectionEnd()))
            search = match
        if not matches:
            return 0
        # Offsets first, edits backwards: the replacement may contain the query,
        # and all of it undoes at once.
        edit = QTextCursor(document)
        edit.beginEditBlock()
        for start, end in reversed(matches):
            edit.setPosition(start)
            edit.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            edit.insertText(replacement)
        edit.endEditBlock()
        edit.setPosition(matches[0][0])
        self.setTextCursor(edit)
        return len(matches)

    # -- settings ----------------------------------------------------------------------

    def set_tab_width(self, chars: int) -> None:
        """A tab `chars` characters wide in the editor's font (Qt's own default of
        80 px is unrelated to the font and far too wide for code)."""
        self._tab_chars = chars
        self.setTabStopDistance(QFontMetricsF(self.font()).horizontalAdvance(" ") * chars)

    def set_help_provider(self, provider: Optional[Callable[[], latex_help.HelpSet]]) -> None:
        """`provider()` gives the current theme's help (a help.toml), asked at each tooltip."""
        self._help_provider = provider

    def _extra_help(self) -> latex_help.HelpSet:
        try:
            return self._help_provider() if self._help_provider is not None else latex_help.NO_EXTRA
        except Exception:                      # a tooltip must never raise
            return latex_help.NO_EXTRA

    def set_hover_help(self, on: bool) -> None:
        self._hover_help = on
        if not on:
            QToolTip.hideText()

    def refresh_colors(self) -> None:
        self.highlighter.refresh_colors()
        self.set_spelling_marks(self._spelling_marks)
        self.viewport().update()

    # -- spelling marks (spell_check.py decides which words) -----------------------------

    def char_offset(self, position: int) -> int:
        """The character offset into text() of a Qt position (which counts UTF-16 code units)."""
        units = utf16_units(self.toPlainText())
        return position - sum("\ud800" <= unit <= "\udbff" for unit in units[:position])

    def offset_at(self, pos: QPoint) -> int:
        """The character offset under `pos` (viewport coordinates), on the character the pointer is over."""
        return char_offset_at(self, pos)

    def spelling_marks(self) -> list[tuple[int, int]]:
        return list(self._spelling_marks)

    def set_spelling_marks(self, marks: list[tuple[int, int]]) -> None:
        """Underline the character ranges `marks` (offsets into text()) with a red wavy line; [] clears them."""
        self._spelling_marks = list(marks)
        self._spell_selections = spelling_selections(self, self._spelling_marks, self._theme.tokens.error)
        self._apply_extra_selections()

    def _apply_extra_selections(self) -> None:
        self.setExtraSelections(self._spell_selections + self._brace_selections)

    # -- line numbers ------------------------------------------------------------------

    def line_number_area_width(self) -> int:
        digits = max(3, len(str(max(1, self.blockCount()))))
        return 16 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_line_area_width(self, _new_block_count: int = 0) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_area(self, rect: QRect, dy: int) -> None:
        if dy:
            self._line_area.scroll(0, dy)
        else:
            self._line_area.update(0, rect.y(), self._line_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_area_width()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        area = self.contentsRect()
        self._line_area.setGeometry(QRect(area.left(), area.top(), self.line_number_area_width(), area.height()))

    def paint_line_numbers(self, event) -> None:
        tokens = self._theme.tokens
        painter = QPainter(self._line_area)
        painter.fillRect(event.rect(), QColor(tokens.surface))
        painter.setFont(self.font())
        height = self.fontMetrics().height()
        width = self._line_area.width() - 8
        current = self.textCursor().blockNumber()
        normal, strong = QColor(tokens.text_4), QColor(tokens.text_2)

        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        while block.isValid() and top <= event.rect().bottom():
            # A line hidden by the header fold takes no height and is skipped
            # without shifting the numbers.
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(strong if number == current else normal)
                painter.drawText(0, top, width, height, Qt.AlignmentFlag.AlignRight, str(number + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            number += 1

    # -- keys and braces ---------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_F1 and event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
            self.show_help_at_cursor()
            return
        if event.key() == Qt.Key.Key_Period and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            caret = self.cursorRect()
            self.spelling_menu_requested.emit(self.char_offset(self.textCursor().position()),
                                              self.viewport().mapToGlobal(caret.bottomLeft()))
            return
        if event.key() == Qt.Key.Key_Escape:
            self.escape_pressed.emit()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not self.isReadOnly() \
                and not self.textCursor().hasSelection():
            cursor = self.textCursor()
            self._insert(latex_edit.smart_return(cursor.block().text(), cursor.atBlockEnd(), self.toPlainText()))
            return
        super().keyPressEvent(event)

    # -- help for LaTeX commands (latex_help.py) ---------------------------------------

    def viewportEvent(self, event) -> bool:  # noqa: N802 -- Qt's name
        # A QPlainTextEdit's ToolTip events arrive at its viewport.
        if event.type() == QEvent.Type.ToolTip:
            found = self.help_at_point(event.pos()) if self._hover_help else None
            if found is None:
                QToolTip.hideText()
                event.ignore()
            else:
                hit, rect = found
                QToolTip.showText(event.globalPos(), latex_help.help_html(hit, FONT_MONO), self.viewport(), rect)
            return True
        return super().viewportEvent(event)

    def help_at_point(self, pos: QPoint) -> Optional[tuple[latex_help.HelpHit, QRect]]:
        """The help for the character under `pos` (viewport coordinates), with the hovered token's rectangle:
        the tooltip goes away once the pointer leaves it."""
        cursor = self.cursorForPosition(pos)
        caret = self.cursorRect(cursor)
        if not caret.top() <= pos.y() <= caret.bottom():
            return None                         # below the last line
        position = cursor.position()
        # cursorForPosition gives the gap nearest to the pointer: a gap right of the pointer means the pointer is
        # on the character before it.
        if caret.x() > pos.x() and cursor.positionInBlock() > 0:
            position -= 1
        hit = latex_help.help_at(utf16_units(self.toPlainText()), position, self._extra_help())
        if hit is None:
            return None
        return hit, self._token_rect(hit, caret)

    def _token_rect(self, hit: latex_help.HelpHit, line: QRect) -> QRect:
        start, end = QTextCursor(self.document()), QTextCursor(self.document())
        start.setPosition(hit.start)
        end.setPosition(hit.end)
        left, right = self.cursorRect(start), self.cursorRect(end)
        if left.top() != right.top():           # an entry that wraps: the hovered line
            return QRect(0, line.top(), self.viewport().width(), line.height())
        return QRect(left.x(), left.top(), max(1, right.x() - left.x()), left.height())

    def show_help_at_cursor(self) -> bool:
        """Shift+F1: the help for the command at the text cursor (on it, or right after it)."""
        text = utf16_units(self.toPlainText())
        position = self.textCursor().position()
        extra = self._extra_help()
        hit = latex_help.help_at(text, position, extra) or latex_help.help_at(text, position - 1, extra)
        if hit is None:
            QToolTip.hideText()
            return False
        caret = self.cursorRect()
        QToolTip.showText(self.viewport().mapToGlobal(caret.bottomLeft()), latex_help.help_html(hit, FONT_MONO),
                          self.viewport())
        return True

    def _highlight_matching_brace(self) -> None:
        """Mark the brace pair the cursor touches, so a deeply nested
        \\slide{...}{...}{...} call is easier to scan."""
        selections: list[QTextEdit.ExtraSelection] = []
        pair = latex_edit.brace_pair(utf16_units(self.toPlainText()), self.textCursor().position())
        if pair is not None:
            fmt = QTextCharFormat()
            fmt.setBackground(QColor(self._theme.syntax_colors()["brace_match_bg"]))
            for pos in pair:
                selection = QTextEdit.ExtraSelection()
                selection.format = fmt
                selection.cursor = QTextCursor(self.document())
                selection.cursor.setPosition(pos)
                selection.cursor.setPosition(pos + 1, QTextCursor.MoveMode.KeepAnchor)
                selections.append(selection)
        self._brace_selections = selections
        self._apply_extra_selections()


class FindBar(QWidget):
    """Find and replace for any SourceEditor: Next/Previous wrap around, Replace
    replaces the selected match (or finds the next one first) and moves on,
    Replace All is one undo step. Esc in either entry closes it."""

    def __init__(self, editor: SourceEditor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.editor = editor
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE.md, SPACE.sm, SPACE.md, SPACE.sm)
        layout.setSpacing(SPACE.xs)

        find_row = QHBoxLayout()
        find_row.addWidget(QLabel("Find"))
        self.find_entry = QLineEdit()
        self.find_entry.returnPressed.connect(self._on_next)
        find_row.addWidget(self.find_entry, 1)
        self.status_label = QLabel()
        self.status_label.setObjectName(q.SOURCE_NOTE)
        find_row.addWidget(self.status_label)
        previous = Button("Previous", "ghost")
        previous.clicked.connect(lambda: self._find(backward=True))
        find_row.addWidget(previous)
        following = Button("Next", "ghost")
        following.clicked.connect(self._on_next)
        find_row.addWidget(following)
        close = IconButton("close", "Close (Esc)")
        close.clicked.connect(self.hide_bar)
        find_row.addWidget(close)
        layout.addLayout(find_row)

        replace_row = QHBoxLayout()
        replace_row.addWidget(QLabel("Replace"))
        self.replace_entry = QLineEdit()
        self.replace_entry.returnPressed.connect(self._on_replace)
        replace_row.addWidget(self.replace_entry, 1)
        replace = Button("Replace", "ghost")
        replace.clicked.connect(self._on_replace)
        replace_row.addWidget(replace)
        replace_all = Button("Replace All", "ghost")
        replace_all.clicked.connect(self._on_replace_all)
        replace_row.addWidget(replace_all)
        layout.addLayout(replace_row)

        for entry in (self.find_entry, self.replace_entry):
            escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), entry)
            escape.setContext(Qt.ShortcutContext.WidgetShortcut)
            escape.activated.connect(self.hide_bar)
        self.setVisible(False)

    def show_find(self) -> None:
        self.setVisible(True)
        selected = self.editor.selected_text()
        if selected:
            self.find_entry.setText(selected)
        self.find_entry.setFocus()
        self.find_entry.selectAll()

    def show_replace(self) -> None:
        self.show_find()
        if self.find_entry.text():
            self.replace_entry.setFocus()

    def hide_bar(self) -> None:
        self.setVisible(False)
        self.status_label.setText("")
        self.editor.widget().setFocus()

    def _find(self, backward: bool) -> bool:
        query = self.find_entry.text()
        if not query:
            self.status_label.setText("")
            return False
        found = self.editor.find_text(query, backward)
        self.status_label.setText("" if found else "Not found")
        return found

    def _on_next(self) -> None:
        self._find(backward=False)

    def _on_replace(self) -> None:
        query = self.find_entry.text()
        if not query:
            self.status_label.setText("Enter text to find")
            return
        if self.editor.selected_text().casefold() != query.casefold() and not self._find(backward=False):
            return
        self.editor.replace_selection(self.replace_entry.text())
        self._find(backward=False)

    def _on_replace_all(self) -> None:
        query = self.find_entry.text()
        if not query:
            self.status_label.setText("Enter text to find")
            return
        count = self.editor.replace_all(query, self.replace_entry.text())
        self.status_label.setText(f"Replaced {count} match{'es' if count != 1 else ''}" if count else "Not found")
