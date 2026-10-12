"""The Source view: the editor's commands, files with unsaved edits that survive
switching, saving with the version prompt, frozen versions, the .bib."""
from __future__ import annotations


import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from slidemage import latex_edit
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.workspace import source_file
from slidemage.ui.workspace.source_editor import LatexPlainTextEdit
from slidemage.ui.workspace.insert_popovers import LinkPopover
from slidemage.ui.workspace.source_view import SourcePane
from conftest import use_project
from slidemage.project import transitional_context

BODY = "\\begin{standardframe}{Demo}\nText\n\\end{standardframe}\n"


class FakeApp:
    project = property(lambda self: transitional_context())
    """What the Source view needs of the window."""

    def __init__(self):
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
    use_project(monkeypatch, tmp_path)
    return folder


@pytest.fixture
def pane(qapp):
    app = FakeApp()
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

def test_a_clean_file_is_dropped_when_another_is_shown_and_a_dirty_one_is_kept(pane, slides):
    states, closed = [], []
    pane.dirty_changed.connect(states.append)
    pane.file_closed.connect(closed.append)
    first, second = slides / "abc-EN-Demo-current.tex", slides / "def-EN-Other-current.tex"

    pane.show_path(first)
    pane.show_path(second)
    assert list(pane._files) == [second] and closed == [first]      # the clean one is gone

    pane.current.editor.insertPlainText("edit ")
    assert pane.current.dirty and states == [True]
    pane.show_path(first)
    assert set(pane._files) == {first, second}                      # the edited one stays
    assert [f.path for f in pane.dirty_files()] == [second]
    assert pane._elsewhere_chip.isVisibleTo(pane)
    pane._show_other_dirty()                                        # the chip asks for it back
    shown = []
    pane.file_requested.connect(shown.append)
    pane._show_other_dirty()
    assert shown == [second]

    pane.show_path(second)
    assert pane.current.editor.text().startswith("edit ")
    pane.current.reload()
    assert states == [True, False]


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
    assert not pane._format_row.isEnabled() and not pane._save_button.isEnabled()
    pane.insert(latex_edit.INSERT_LIST_COMMANDS[0])                  # a format command is refused too
    assert pane.current.editor.text().startswith("\\setSlideVersion{1-0-0}")
    restored = []
    pane.restore_requested.connect(restored.append)
    pane._frozen_bar.findChildren(type(pane._unlock_button))[-1].click()
    assert restored == [slides / "abc-EN-Demo-v1-0-0.tex"]
    pane._unlock_button.click()
    assert not pane.current.editor.is_read_only() and not pane._unlock_button.isEnabled()
    assert pane._format_row.isEnabled() and pane._save_button.isEnabled()
    pane.show_path(slides / "abc-EN-Demo-current.tex")
    assert not pane._frozen_bar.isVisibleTo(pane)


def test_the_toolbar_follows_the_kind_of_file(pane, slides, tmp_path, monkeypatch):
    bib = tmp_path / "Slidemaster.bib"
    bib.write_text("@book{alpha, title={A}}\n\n@book{beta, title={B}}\n", encoding="utf-8")
    use_project(monkeypatch, tmp_path)
    pane.show_path(None)
    assert not pane._save_button.isEnabled() and not pane._find_button.isEnabled()
    pane.show_path(bib)
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

def test_saving_a_slide_with_a_minor_bump_freezes_the_old_text_and_patches_the_buffer(pane, slides, monkeypatch):
    path = slides / "abc-EN-Demo-current.tex"
    monkeypatch.setattr(source_file, "prompt_version_choice", lambda _parent, old: "minor")
    saved, on_saved = [], []
    pane.saved.connect(saved.append)
    pane.show_path(path, on_saved.append)
    editor = pane.current.editor
    place(editor, len(editor.text()))
    editor.insertPlainText("% note\n")
    place(editor, editor.text().index("Text"))

    assert pane.save()

    assert saved == [path] and on_saved == ["\\setSlideVersion{1-1-0}\n" + BODY]
    assert path.read_text(encoding="utf-8") == "\\setSlideVersion{1-2-0}\n" + BODY + "% note\n"
    assert (slides / "abc-EN-Demo-v1-1-0.tex").read_text(encoding="utf-8").startswith("\\setSlideVersion{1-1-0}")
    assert editor.text() == path.read_text(encoding="utf-8")      # the buffer shows the bumped version
    assert not editor.is_modified() and editor.textCursor().position() == editor.text().index("Text")


def test_overwrite_saves_without_a_new_version(pane, slides, monkeypatch):
    path = slides / "abc-EN-Demo-current.tex"
    monkeypatch.setattr(source_file, "prompt_version_choice", lambda _parent, old: "overwrite")
    pane.show_path(path)
    place(pane.current.editor, len(pane.current.editor.text()))
    pane.current.editor.insertPlainText("x")
    assert pane.save()
    assert path.read_text(encoding="utf-8") == "\\setSlideVersion{1-1-0}\n" + BODY + "x"
    assert not (slides / "abc-EN-Demo-v1-1-0.tex").exists()


def test_cancelling_the_version_prompt_saves_nothing(pane, slides, monkeypatch):
    path = slides / "abc-EN-Demo-current.tex"
    monkeypatch.setattr(source_file, "prompt_version_choice", lambda _parent, old: None)
    pane.show_path(path)
    pane.current.editor.insertPlainText("x")
    assert not pane.save()
    assert path.read_text(encoding="utf-8").startswith("\\setSlideVersion{1-1-0}") and pane.current.dirty


def test_other_files_save_plainly_and_a_file_that_changed_on_disk_is_refused(pane, slides, tmp_path, monkeypatch):
    monkeypatch.setattr(source_file, "prompt_version_choice", lambda *_a: pytest.fail("a deck has no version prompt"))
    deck = tmp_path / "decks.tex"
    deck.write_text("deck text\r\n", encoding="utf-8", newline="")
    previous = []
    pane.show_path(deck, previous.append)
    pane.current.editor.insertPlainText("new ")
    assert pane.save()
    assert deck.read_bytes() == b"new deck text\r\n" and previous == ["deck text\n"]      # the line ending stays

    pane.current.editor.insertPlainText("more ")
    deck.write_text("someone else's text", encoding="utf-8")
    told = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: told.append(args[2]))
    assert not pane.save()
    assert "changed on disk" in told[0] and pane.current.dirty
    assert deck.read_text(encoding="utf-8") == "someone else's text"


def test_revert_asks_and_reloads_the_saved_file(pane, slides, monkeypatch):
    path = slides / "def-EN-Other-current.tex"
    pane.show_path(path)
    pane.current.editor.insertPlainText("x")
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No)
    pane._revert_button.click()
    assert pane.current.dirty
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    pane._revert_button.click()
    assert not pane.current.dirty and pane.current.editor.text() == BODY


def test_buffer_gives_the_text_and_selection_of_a_slide_only(pane, slides, tmp_path):
    pane.show_path(slides / "def-EN-Other-current.tex")
    select(pane.current.editor, 0, 5)
    assert pane.buffer() == (BODY, "\\begi")
    deck = tmp_path / "decks.tex"
    deck.write_text("x", encoding="utf-8")
    pane.show_path(deck)
    assert pane.buffer() is None


def test_a_stale_slide_is_refused_before_anything_is_frozen_or_asked(pane, slides, monkeypatch):
    path = slides / "abc-EN-Demo-current.tex"
    monkeypatch.setattr(source_file, "prompt_version_choice", lambda _parent, old: "minor")
    monkeypatch.setattr(source_file, "ask_deck_versions", lambda *_a: pytest.fail("nothing to ask for a stale file"))
    pane.show_path(path)
    pane.current.editor.insertPlainText("x")
    path.write_text("\\setSlideVersion{1-1-0}\nsomeone else's text", encoding="utf-8")
    told = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: told.append(args[2]))
    assert not pane.save()
    assert "changed on disk" in told[0] and pane.current.dirty
    assert not (slides / "abc-EN-Demo-v1-1-0.tex").exists()             # no outgoing version frozen
    assert pane.current.conflict_bar.isVisibleTo(pane.current)         # the buffer's own edits get the choice


def test_a_file_changed_while_the_deck_questions_were_open_is_not_frozen(pane, slides, monkeypatch):
    path = slides / "abc-EN-Demo-current.tex"
    monkeypatch.setattr(source_file, "prompt_version_choice", lambda _parent, old: "minor")

    def ask(*_args):
        path.write_text("\\setSlideVersion{1-1-0}\nchanged while asking", encoding="utf-8")
        return source_file.DeckVersions({}, None)

    monkeypatch.setattr(source_file, "ask_deck_versions", ask)
    pane.show_path(path)
    pane.current.editor.insertPlainText("x")
    told = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: told.append(args[2]))
    assert not pane.save()
    assert "changed on disk" in told[0] and pane.current.dirty and pane.current.conflict_bar.isVisibleTo(pane.current)
    assert not (slides / "abc-EN-Demo-v1-1-0.tex").exists() and "changed while asking" in path.read_text(encoding="utf-8")
