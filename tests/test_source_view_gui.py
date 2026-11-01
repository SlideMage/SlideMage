# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Source view: the editor's commands, saving as you type (and edits that survive
switching when they cannot be saved), Update Version, frozen versions, the .bib."""
from __future__ import annotations


import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from slidemage import latex_edit
from slidemage.ui import layout_settings
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.workspace import source_file
from slidemage.ui.workspace.source_editor import LatexPlainTextEdit
from slidemage.ui.workspace.insert_popovers import LinkPopover
from slidemage.ui.workspace.source_view import SourcePane
from conftest import EXAMPLE_PROJECT

BODY = "\\begin{standardframe}{Demo}\nText\n\\end{standardframe}\n"


class FakeApp:
    """What the Source view needs of the window."""

    def __init__(self, project=EXAMPLE_PROJECT):
        self.project = project
        self.theme = ThemeManager()
        self.logged = []
        self.opened = []

    def log(self, line):
        self.logged.append(line)

    def open_slide_editor(self, path, **_kwargs):
        self.opened.append(path)

    def refresh_open_deck_editors(self):
        pass


@pytest.fixture
def slides(tmp_path, monkeypatch):
    """A throwaway slides/ folder: the current file of a slide with one frozen version."""
    folder = tmp_path / "slides"
    folder.mkdir()
    (folder / "abc-EN-Demo-current.tex").write_text("\\setSlideVersion{1-1-0}\n" + BODY, encoding="utf-8")
    (folder / "abc-EN-Demo-v1-0-0.tex").write_text("\\setSlideVersion{1-0-0}\n" + BODY, encoding="utf-8")
    (folder / "def-EN-Other-current.tex").write_text(BODY, encoding="utf-8")
    return folder


@pytest.fixture
def pane(ctx, qapp):
    app = FakeApp(ctx)
    pane = SourcePane(app)
    pane.app_for_test = app
    return pane


def make_editor(text):
    editor = LatexPlainTextEdit(ThemeManager())
    editor.set_text(text)
    return editor


def select(editor, start, end):
    cursor = editor.textCursor()
    cursor.setPosition(start)
    cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)


def place(editor, position):
    cursor = editor.textCursor()
    cursor.setPosition(position)
    editor.setTextCursor(cursor)


# -- the editor's commands ---------------------------------------------------------

def test_a_format_button_wraps_the_selection_or_leaves_the_cursor_inside_the_braces(qapp):
    editor = make_editor("a word b")
    select(editor, 2, 6)
    editor.wrap_macro("textit")
    assert editor.text() == "a \\textit{word} b" and editor.textCursor().position() == 15
    editor.undo()
    assert editor.text() == "a word b"          # one undo step
    place(editor, 1)
    editor.wrap_macro("textbf")
    assert editor.text() == "a\\textbf{} word b" and editor.textCursor().position() == 9


def test_a_multiline_selection_becomes_list_items_and_keeps_the_indent(qapp):
    editor = make_editor("\tone\n\ttwo")
    select(editor, 1, 9)
    assert editor.apply_insert(latex_edit.INSERT_LIST_COMMANDS[0])
    assert editor.text() == "\t\\begin{itemize}\n\t\t\\item one\n\t\t\\item two\n\t\\end{itemize}"
    assert not editor.apply_insert(next(i for i in latex_edit.INSERT_COMMANDS if i.kind == "hyperlink"))    # the hyperlink needs input first


def test_positions_after_an_emoji_are_utf16_positions(qapp):
    editor = make_editor("😀 word")
    select(editor, 3, 7)
    editor.wrap_macro("textit")
    assert editor.text() == "😀 \\textit{word}"
    assert editor.textCursor().position() == len(editor.text().encode("utf-16-le")) // 2


def test_enter_after_a_begin_line_opens_the_end_and_after_an_item_continues_the_list(qapp):
    editor = make_editor("\\begin{itemize}")
    place(editor, len(editor.text()))
    QTest.keyClick(editor, Qt.Key.Key_Return)
    assert editor.text() == "\\begin{itemize}\n\t\\item \n\\end{itemize}"
    assert editor.textCursor().position() == len("\\begin{itemize}\n\t\\item ")
    editor.insertPlainText("first")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    assert editor.text().splitlines()[2] == "\t\\item "
    editor.undo()
    editor.undo()


def test_comment_toggle_works_on_every_selected_line_in_one_undo_step(qapp):
    editor = make_editor("a\n\tb\nc")
    select(editor, 0, 5)                        # a and b
    editor.toggle_comment()
    assert editor.text() == "%a\n%\tb\nc"
    editor.toggle_comment()
    assert editor.text() == "a\n\tb\nc"
    editor.undo()
    assert editor.text() == "%a\n%\tb\nc"
    select(editor, 0, 3)                         # ends at the start of line 2: that line is not taken
    editor.toggle_comment()
    assert editor.text() == "a\n%\tb\nc"


def test_reindent_is_one_undo_step_and_reports_when_nothing_changed(qapp):
    editor = make_editor("\\begin{x}\ny\n\\end{x}")
    assert editor.reindent()
    assert editor.text() == "\\begin{x}\n\ty\n\\end{x}"
    assert not editor.reindent()
    editor.undo()
    assert editor.text() == "\\begin{x}\ny\n\\end{x}"


def test_the_header_comment_is_folded_and_the_gutter_keeps_real_line_numbers(qapp):
    editor = make_editor("% one\n% two\n\\slide{a}\n")
    assert editor.header_line_count() == 2 and editor.is_header_folded()
    assert [b.isVisible() for b in (editor.document().findBlockByNumber(n) for n in range(3))] == [False, False, True]
    editor.set_header_folded(False)
    assert editor.document().findBlockByNumber(0).isVisible()
    editor.set_header_folded(True)
    editor.set_text("% still\n% folded\n\\slide{b}")           # a reload keeps the fold
    assert not editor.document().findBlockByNumber(0).isVisible()
    assert not editor.document().isModified()


def test_patching_the_buffer_keeps_the_cursor_and_counts_utf16(qapp):
    old = "😀\n\\setSlideVersion{1.0.0}\nBODY"
    editor = make_editor(old)
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    editor.setTextCursor(cursor)
    new = old.replace("1.0.0", "12.0.1")
    editor.patch_text(new)
    assert editor.text() == new
    assert editor.textCursor().position() == len(new.encode("utf-16-le")) // 2


def test_the_cursor_next_to_a_brace_marks_both_ends(qapp):
    editor = make_editor("\\a{b{c}}")
    place(editor, 2)
    assert len(editor.extraSelections()) == 2
    place(editor, 0)
    assert editor.extraSelections() == []


# -- files: switching, unsaved edits, frozen versions -------------------------------

def test_a_file_is_written_and_dropped_when_another_is_shown_unless_it_cannot_be(pane, slides):
    states, closed = [], []
    pane.dirty_changed.connect(states.append)
    pane.file_closed.connect(closed.append)
    first, second = slides / "abc-EN-Demo-current.tex", slides / "def-EN-Other-current.tex"

    pane.show_path(first)
    pane.show_path(second)
    assert list(pane._files) == [second] and closed == [first]      # the clean one is gone

    pane.current.editor.insertPlainText("edit ")
    assert pane.current.dirty and states == []                      # a pending autosave is not an unsaved edit
    pane.show_path(first)
    assert list(pane._files) == [first] and states == []            # written, then dropped
    assert second.read_text(encoding="utf-8").startswith("\\setSlideVersion{1-0-0+}\nedit ")

    pane.current.editor.insertPlainText("mine ")
    first.write_text("someone else's\n", encoding="utf-8")         # Claude Code in the terminal
    pane.show_path(second)
    assert set(pane._files) == {first, second}                      # the one in conflict stays
    assert [f.path for f in pane.dirty_files()] == [first] and pane.file_for(first).conflicted
    assert [f.path for f in pane.blocked_files()] == [first] and states == [True]   # only this is reported
    assert pane._elsewhere_chip.isVisibleTo(pane)
    shown = []
    pane.file_requested.connect(shown.append)
    pane._show_other_dirty()                                        # the chip asks for it back
    assert shown == [first]
    pane.show_path(first)
    assert pane.current.editor.text().startswith("mine ")
    assert pane._unsaved_chip.isVisibleTo(pane) and pane._unsaved_chip.text() == "Not saved: changed on disk"


def test_a_clean_file_picks_up_a_change_made_elsewhere_but_a_dirty_one_does_not(pane, slides):
    path = slides / "def-EN-Other-current.tex"
    pane.show_path(path)
    path.write_text("changed on disk\n", encoding="utf-8")
    pane.show_path(path)
    assert pane.current.editor.text() == "changed on disk\n"
    pane.current.editor.insertPlainText("mine ")
    path.write_text("changed again\n", encoding="utf-8")
    pane.show_path(path)
    assert pane.current.editor.text().startswith("mine ")


def test_a_frozen_version_is_read_only_until_unlocked_and_its_toolbar_follows(pane, slides):
    pane.show_path(slides / "abc-EN-Demo-v1-0-0.tex")
    assert pane.current.editor.is_read_only()
    before = pane.current.editor.text()
    QTest.keyClick(pane.current.editor, Qt.Key.Key_Return)
    assert pane.current.editor.text() == before
    assert pane._frozen_bar.isVisibleTo(pane) and pane._unlock_button.isEnabled()
    assert not pane._format_row.isEnabled() and not pane._version_button.isVisibleTo(pane)
    pane.insert(latex_edit.INSERT_LIST_COMMANDS[0])                  # a format command is refused too
    assert pane.current.editor.text().startswith("\\setSlideVersion{1-0-0}")
    restored = []
    pane.restore_requested.connect(restored.append)
    pane._frozen_bar.findChildren(type(pane._unlock_button))[-1].click()
    assert restored == [slides / "abc-EN-Demo-v1-0-0.tex"]
    pane._unlock_button.click()
    assert not pane.current.editor.is_read_only() and not pane._unlock_button.isEnabled()
    assert pane._format_row.isEnabled() and not pane._version_button.isVisibleTo(pane)
    pane.show_path(slides / "abc-EN-Demo-current.tex")
    assert not pane._frozen_bar.isVisibleTo(pane)
    # v8.23.0: Update version is off until there is something to make a version of
    assert pane._version_button.isVisibleTo(pane) and not pane._version_button.isEnabled()
    assert pane._version_button.toolTip() == "No changes since v1.1.0."
    pane.current.editor.insertPlainText("edit ")
    assert pane._version_button.isEnabled()                          # an edit waiting for its autosave
    assert pane.current.write_now() and "1-1-0+" in (slides / "abc-EN-Demo-current.tex").read_text()
    assert pane._version_button.isEnabled()                          # the "+" once written
    asked = []
    pane.version_requested.connect(asked.append)
    pane._version_button.click()
    assert asked == ["abc-EN-Demo"]


def test_the_toolbar_follows_the_kind_of_file(pane, slides, tmp_path, monkeypatch):
    bib = tmp_path / "SlideMage.bib"
    bib.write_text("@book{alpha, title={A}}\n\n@book{beta, title={B}}\n", encoding="utf-8")
    pane.show_path(None)
    assert not pane._version_button.isVisibleTo(pane) and not pane._find_button.isEnabled()
    pane.show_path(bib)
    assert not pane._version_button.isVisibleTo(pane)
    assert pane._jump_bar.isVisibleTo(pane) and not pane._frozen_bar.isVisibleTo(pane)
    assert pane.current.is_bib and not pane.current.is_slide
    assert pane.current.jump_to_bib_letter("B")
    assert pane.current.editor.textCursor().position() == pane.current.editor.text().index("@book{beta")
    assert not pane.current.jump_to_bib_letter("Q")
    pane.show_path(slides / "def-EN-Other-current.tex")
    assert not pane._jump_bar.isVisibleTo(pane)


def popover_of(pane, kind):
    """The popover an insert of `kind` opened under the Insert button (shown, so top level)."""
    popovers = [w for w in QApplication.topLevelWidgets() if isinstance(w, kind) and w.isVisible()]
    assert len(popovers) == 1
    return popovers[0]


def test_the_hyperlink_command_asks_in_a_popover_and_replaces_the_selection(pane, slides):
    path = slides / "def-EN-Other-current.tex"
    path.write_text("Word appears here", encoding="utf-8")
    pane.show_path(path)
    select(pane.current.editor, 0, 4)
    hyperlink = next(i for i in latex_edit.INSERT_COMMANDS if i.kind == "hyperlink")
    pane.insert(hyperlink)
    popover = popover_of(pane, LinkPopover)
    assert popover.word.text() == "Word"                        # the selection is the visible text
    popover.word.setText("R&D")
    popover.url.setText("https://example.org/page?x=1&y=2")
    popover._on_insert()
    assert pane.current.editor.text() == r"\href{https://example.org/page?x=1\&y=2}{R\&D} appears here"
    assert path.read_text(encoding="utf-8") == "Word appears here"        # Save stays explicit
    assert not popover.isVisible()


def test_a_bad_hyperlink_stays_in_the_popover_with_the_reason(pane, slides):
    path = slides / "def-EN-Other-current.tex"
    path.write_text("Word", encoding="utf-8")
    pane.show_path(path)
    pane.insert(next(i for i in latex_edit.INSERT_COMMANDS if i.kind == "hyperlink"))
    popover = popover_of(pane, LinkPopover)
    popover.word.setText("Word")
    popover.url.setText("javascript:x")
    popover._on_insert()
    assert popover.isVisible() and "http" in popover.note.text()
    assert pane.current.editor.text() == "Word"
    popover.close()
    assert pane.current.editor.text() == "Word"                # cancelling leaves the source alone


# -- saving ----------------------------------------------------------------------------

@pytest.fixture
def quick(monkeypatch):
    """Autosave a moment after the last keystroke, not 1.5 s."""
    monkeypatch.setattr(source_file, "AUTOSAVE_DELAY_MS", 20)


def test_a_slide_is_saved_as_you_type_with_its_version_frozen_first_and_the_plus(pane, slides, quick):
    path = slides / "abc-EN-Demo-current.tex"
    saved, written, on_saved = [], [], []
    pane.saved.connect(saved.append)
    pane.show_path(path, on_saved.append)
    pane.current.written.connect(lambda: written.append(1))
    editor = pane.current.editor
    place(editor, len(editor.text()))
    editor.insertPlainText("% note\n")
    place(editor, editor.text().index("Text"))
    assert path.read_text(encoding="utf-8") == "\\setSlideVersion{1-1-0}\n" + BODY      # not yet

    QTest.qWait(150)

    assert path.read_text(encoding="utf-8") == "\\setSlideVersion{1-1-0+}\n" + BODY + "% note\n"
    assert (slides / "abc-EN-Demo-v1-1-0.tex").read_text(encoding="utf-8") == "\\setSlideVersion{1-1-0}\n" + BODY
    assert editor.text() == path.read_text(encoding="utf-8")                  # the buffer shows the "+"
    assert not editor.is_modified() and editor.textCursor().position() == editor.text().index("Text")
    assert written == [1] and saved == [] and on_saved == ["\\setSlideVersion{1-1-0}\n" + BODY]

    editor.insertPlainText("x")
    assert pane.save()                                                        # Ctrl+S: now, and rendered
    assert saved == [path] and "\\setSlideVersion{1-1-0+}\nx" not in path.read_text(encoding="utf-8")
    assert path.read_text(encoding="utf-8").startswith("\\setSlideVersion{1-1-0+}\n")
    assert len(list((pane.app.project.slide_backups_dir / path.name).glob("*.tex"))) == 1   # one per session


def test_other_files_save_plainly_and_a_file_that_changed_on_disk_gets_the_conflict_bar(pane, slides, tmp_path,
                                                                                         monkeypatch, quick):
    monkeypatch.setattr(QMessageBox, "critical", lambda *_a: pytest.fail("an autosave asks nothing"))
    deck = tmp_path / "decks.tex"
    deck.write_text("deck text\r\n", encoding="utf-8", newline="")
    previous = []
    pane.show_path(deck, previous.append)
    pane.current.editor.insertPlainText("new ")
    QTest.qWait(150)
    assert deck.read_bytes() == b"new deck text\r\n" and previous == ["deck text\n"]      # the line ending stays

    pane.current.editor.insertPlainText("more ")
    deck.write_text("someone else's text", encoding="utf-8")
    QTest.qWait(150)
    assert pane.current.dirty and pane.current.conflicted
    assert deck.read_text(encoding="utf-8") == "someone else's text"
    pane.current.editor.insertPlainText("still ")
    QTest.qWait(150)
    assert deck.read_text(encoding="utf-8") == "someone else's text"           # paused while in conflict

    pane.current.keep_edits()                                                 # "Keep my edits"
    QTest.qWait(150)
    assert deck.read_text(encoding="utf-8").startswith("new more still deck text") and not pane.current.dirty


def test_a_stale_slide_is_not_frozen_or_overwritten(pane, slides, quick):
    path = slides / "abc-EN-Demo-current.tex"
    pane.show_path(path)
    pane.current.editor.insertPlainText("x")
    path.write_text("\\setSlideVersion{1-1-0}\nsomeone else's text", encoding="utf-8")
    assert not pane.current.write_now()
    assert pane.current.dirty and pane.current.conflicted
    assert not (slides / "abc-EN-Demo-v1-1-0.tex").exists()
    assert "someone else's text" in path.read_text(encoding="utf-8")


def test_an_unlocked_frozen_version_saves_plainly(pane, slides, quick):
    path = slides / "abc-EN-Demo-v1-0-0.tex"
    pane.show_path(path)
    QTest.keyClick(pane.current.editor, Qt.Key.Key_X)      # read-only: refused
    QTest.qWait(80)
    assert not pane.current.dirty
    pane._unlock_button.click()
    place(pane.current.editor, len(pane.current.editor.text()))
    pane.current.editor.insertPlainText("% fixed\n")
    QTest.qWait(150)
    assert path.read_text(encoding="utf-8") == "\\setSlideVersion{1-0-0}\n" + BODY + "% fixed\n"


def test_the_toolbar_has_no_revert_button(pane):
    assert not hasattr(pane, "_revert_button")


def test_buffer_gives_the_text_and_selection_of_a_slide_only(pane, slides, tmp_path):
    pane.show_path(slides / "def-EN-Other-current.tex")
    select(pane.current.editor, 0, 5)
    assert pane.buffer() == (BODY, "\\begi")
    deck = tmp_path / "decks.tex"
    deck.write_text("x", encoding="utf-8")
    pane.show_path(deck)
    assert pane.buffer() is None


# -- what is no slide; AutoSave off (v8.56.0) ------------------------------------------------------------

def test_a_deck_source_and_the_bib_have_no_formatting_row(pane, ctx, slides):
    deck = ctx.root / "decks" / "talk.tex"
    deck.parent.mkdir()
    deck.write_text("\\begin{document}\nwords\n\\end{document}\n", encoding="utf-8")
    pane.show_path(slides / "abc-EN-Demo-current.tex")
    assert pane._format_row.isVisibleTo(pane)
    pane.show_path(deck)
    assert not pane._format_row.isVisibleTo(pane)
    pane._wrap("textbf")                                          # Ctrl+B does nothing in plain text
    assert pane.current.editor.text() == deck.read_text(encoding="utf-8")


def test_a_held_file_stays_open_out_of_view_is_written_and_synced_and_goes_with_its_release(pane, slides):
    closed = []
    pane.file_closed.connect(closed.append)
    held, other = slides / "abc-EN-Demo-current.tex", slides / "def-EN-Other-current.tex"
    pane.hold(held)
    pane.show_path(held)
    file = pane.current
    file.editor.insertPlainText("mine ")
    undo_depth = file.editor.document().availableUndoSteps()
    pane.show_path(other)                                         # not dropped, but written before it left
    assert pane.file_for(held) is file and closed == []
    assert "mine " in held.read_text(encoding="utf-8")
    held.write_text("changed on disk\n", encoding="utf-8")        # elsewhere, while it is out of view
    pane.show_path(held)
    assert pane.current is file and "changed on disk" in file.editor.text() and "mine" not in file.editor.text()
    file.editor.insertPlainText("again ")
    assert file.editor.document().availableUndoSteps() >= 1 and undo_depth >= 1
    pane.show_path(other)
    pane.release(held)
    assert pane.file_for(held) is None and closed == [other, held] and pane.file_for(other) is not None


def test_releasing_the_file_on_show_empties_the_view_and_a_file_with_unwritten_edits_stays(pane, slides):
    held = slides / "abc-EN-Demo-current.tex"
    pane.hold(held)
    pane.show_path(held)
    pane.release(held)
    assert pane.current is None and pane.file_for(held) is None
    pane.hold(held)
    pane.show_path(held)
    layout_settings.set(source_file.AUTOSAVE_KEY, False)
    pane.current.editor.insertPlainText("% not saved\n")
    pane.release(held)                                            # edits that would be lost keep it open
    assert pane.file_for(held) is not None and not pane.is_held(held)


def test_with_autosave_off_edits_wait_for_ctrl_s_and_stay_open(pane, slides):
    layout_settings.set(source_file.AUTOSAVE_KEY, False)
    path, other = slides / "def-EN-Other-current.tex", slides / "abc-EN-Demo-current.tex"
    pane.show_path(path)
    file = pane.current
    file.editor.insertPlainText("% a note\n")
    assert not file._autosave_timer.isActive()
    pane.show_path(other)                                         # leaving it writes nothing
    assert path.read_text(encoding="utf-8") == BODY and pane.file_for(path) is file
    assert pane.blocked_files() == [file] and file.unsaved
    assert file.write_now(explicit=True) and "% a note" in path.read_text(encoding="utf-8")
    assert pane.blocked_files() == []


def test_switching_autosave_on_saves_what_waits(pane, slides):
    layout_settings.set(source_file.AUTOSAVE_KEY, False)
    pane.show_path(slides / "def-EN-Other-current.tex")
    file = pane.current
    file.editor.insertPlainText("% later\n")
    layout_settings.set(source_file.AUTOSAVE_KEY, True)
    pane.autosave_changed()
    assert file._autosave_timer.isActive() and pane.blocked_files() == []


def test_a_long_file_name_is_cut_in_a_narrow_pane_and_whole_in_its_tooltip(pane, slides):
    path = slides / "xyz-EN-A-Very-Long-Slide-Title-That-Does-Not-Fit-Even-Beside-The-Whole-Toolbar-current.tex"
    path.write_text(BODY, encoding="utf-8")
    pane.resize(320, 400)
    pane.show()
    pane.show_path(path)
    QApplication.processEvents()
    assert pane._name.toolTip() == path.name and pane._name.full_text() == path.name
    assert pane._name.text() != path.name and pane._name.text().endswith("…")
