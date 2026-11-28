# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Source editor commands, saving, and version controls."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from slidemage import latex_edit
from slidemage.ui import layout_settings
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.kit.widgets import PopoverMenu
from slidemage.ui.workspace import source_file
from slidemage.ui.workspace.source_editor import LatexPlainTextEdit
from slidemage.ui.workspace.insert_popovers import LinkPopover
from slidemage.ui.workspace.source_view import SourcePane
from conftest import pause, wait_until, write_test_file

BODY = "\\begin{standardframe}{Demo}\nText\n\\end{standardframe}\n"


CURRENT = "abc-EN-Demo-current.tex"
FROZEN = "abc-EN-Demo-v1-0-0.tex"
OTHER = "def-EN-Other-current.tex"
HYPERLINK = next(command for command in latex_edit.INSERT_COMMANDS if command.kind == "hyperlink")


class FakeApp:
    def __init__(self, project):
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
def slides(tmp_path):
    folder = tmp_path / "slides"
    folder.mkdir()
    (folder / CURRENT).write_text("\\setSlideVersion{1-1-0}\n" + BODY, encoding="utf-8")
    (folder / FROZEN).write_text("\\setSlideVersion{1-0-0}\n" + BODY, encoding="utf-8")
    (folder / OTHER).write_text(BODY, encoding="utf-8")
    return folder


@pytest.fixture
def pane(ctx, qapp):
    return SourcePane(FakeApp(ctx))


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


def test_a_multiline_selection_becomes_list_items_and_keeps_the_indent(qapp):
    editor = make_editor("\tone\n\ttwo")
    select(editor, 1, 9)
    assert editor.apply_insert(latex_edit.INSERT_LIST_COMMANDS[0])
    assert editor.text() == "\t\\begin{itemize}\n\t\t\\item one\n\t\t\\item two\n\t\\end{itemize}"
    assert not editor.apply_insert(HYPERLINK)


def test_formatting_and_patching_track_the_cursor_in_utf16(qapp):
    editor = make_editor("😀 word")
    select(editor, 3, 7)
    editor.wrap_macro("textit")
    assert editor.text() == "😀 \\textit{word}"
    assert editor.textCursor().position() == len(editor.text().encode("utf-16-le")) // 2
    editor.undo()
    assert editor.text() == "😀 word"
    place(editor, 2)
    editor.wrap_macro("textbf")
    assert editor.text() == "😀\\textbf{} word" and editor.textCursor().position() == 10

    new = "😀\\textbf{} revised words"
    place(editor, len(editor.text().encode("utf-16-le")) // 2)
    editor.patch_text(new)
    assert editor.text() == new
    assert editor.textCursor().position() == len(new.encode("utf-16-le")) // 2


def test_enter_after_a_begin_line_opens_the_end_and_after_an_item_continues_the_list(qapp):
    editor = make_editor("\\begin{itemize}")
    place(editor, len(editor.text()))
    QTest.keyClick(editor, Qt.Key.Key_Return)
    assert editor.text() == "\\begin{itemize}\n\t\\item \n\\end{itemize}"
    assert editor.textCursor().position() == len("\\begin{itemize}\n\t\\item ")
    editor.insertPlainText("first")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    assert editor.text().splitlines()[2] == "\t\\item "


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


def test_the_cursor_next_to_a_brace_marks_both_ends(qapp):
    editor = make_editor("\\a{b{c}}")
    place(editor, 2)
    assert len(editor.extraSelections()) == 2
    place(editor, 0)
    assert editor.extraSelections() == []


def test_switching_files_autosaves_or_keeps_a_conflicted_slide_open(pane, slides):
    states, requested = [], []
    pane.dirty_changed.connect(states.append)
    pane.file_requested.connect(requested.append)
    first, second = slides / CURRENT, slides / OTHER
    pane.show_path(second)
    second.write_text(BODY + "% external\n", encoding="utf-8")
    pane.show_path(second)
    assert pane.current.editor.text() == BODY + "% external\n"
    pane.current.editor.insertPlainText("edit ")
    pane.show_path(first)
    assert list(pane._files) == [first] and states == []
    assert second.read_text(encoding="utf-8").startswith("\\setSlideVersion{1-0-0+}\nedit ")

    pane.current.editor.insertPlainText("mine ")
    external = "\\setSlideVersion{1-1-0}\nsomeone else's\n"
    first.write_text(external, encoding="utf-8")
    pane.show_path(second)
    assert first.read_text(encoding="utf-8") == external
    assert not (slides / "abc-EN-Demo-v1-1-0.tex").exists()
    conflicted = pane.file_for(first)
    assert pane.dirty_files() == pane.blocked_files() == [conflicted]
    assert conflicted.conflicted and states == [True] and pane._elsewhere_chip.isVisibleTo(pane)
    pane._show_other_dirty()
    assert requested == [first]
    pane.show_path(first)
    assert pane.current.editor.text().startswith("mine ") and pane._unsaved_chip.isVisibleTo(pane)


def test_a_frozen_version_is_read_only_until_unlocked_then_saves_plainly(pane, slides, quick):
    path = slides / FROZEN
    pane.show_path(path)
    assert pane.current.editor.is_read_only()
    before = pane.current.editor.text()
    QTest.keyClick(pane.current.editor, Qt.Key.Key_Return)
    assert pane.current.editor.text() == before
    assert pane._frozen_bar.isVisibleTo(pane) and pane._unlock_button.isEnabled()
    assert not pane._format_row.isEnabled() and not pane._version_button.isVisibleTo(pane)
    pane.insert(latex_edit.INSERT_LIST_COMMANDS[0])                  # a format command is refused too
    assert pane.current.editor.text() == before
    restored = []
    pane.restore_requested.connect(restored.append)
    pane._frozen_bar.findChildren(type(pane._unlock_button))[-1].click()
    assert restored == [path]
    pane._unlock_button.click()
    assert not pane.current.editor.is_read_only() and pane._format_row.isEnabled()
    place(pane.current.editor, len(before))
    pane.current.editor.insertPlainText("% fixed\n")
    wait_until(lambda: not pane.current.dirty)
    assert path.read_text(encoding="utf-8") == before + "% fixed\n"


def test_the_toolbar_and_slide_buffer_follow_the_kind_of_file(pane, ctx, slides):
    bib = write_test_file(ctx.bibliography_path, "@book{alpha, title={A}}\n\n@book{beta, title={B}}\n")
    deck = write_test_file(ctx.decks_dir / "talk.tex", "\\begin{document}\nwords\n\\end{document}\n")
    pane.show_path(None)
    assert not pane._version_button.isVisibleTo(pane) and not pane._find_button.isEnabled()
    pane.show_path(bib)
    assert pane._jump_bar.isVisibleTo(pane) and not pane._version_button.isVisibleTo(pane)
    assert pane.current.jump_to_bib_letter("B")
    assert pane.current.editor.textCursor().position() == pane.current.editor.text().index("@book{beta")
    assert not pane.current.jump_to_bib_letter("Q")
    pane.show_path(slides / OTHER)
    assert not pane._jump_bar.isVisibleTo(pane) and not pane._frozen_bar.isVisibleTo(pane)
    assert pane._format_row.isVisibleTo(pane)
    select(pane.current.editor, 0, 5)
    assert pane.buffer() == BODY
    pane.show_path(deck)
    assert not pane._format_row.isVisibleTo(pane) and pane.buffer() is None
    pane._wrap("textbf")
    assert pane.current.editor.text() == deck.read_text(encoding="utf-8")


def link_popover():
    popovers = [w for w in QApplication.topLevelWidgets() if isinstance(w, LinkPopover) and w.isVisible()]
    assert len(popovers) == 1
    return popovers[0]


def test_hyperlink_popover_rejects_a_bad_url_and_escapes_latex_on_insert(pane, slides):
    path = write_test_file(slides / OTHER, "Word appears here")
    pane.show_path(path)
    editor = pane.current.editor
    select(editor, 0, 4)
    pane.insert(HYPERLINK)
    popover = link_popover()
    assert popover.word.text() == "Word"
    popover.url.setText("javascript:x")
    popover._on_insert()
    assert popover.isVisible() and "http" in popover.note.text()
    assert editor.text() == "Word appears here"
    popover.close()
    assert editor.text() == "Word appears here"

    select(editor, 0, 4)
    pane.insert(HYPERLINK)
    popover = link_popover()
    popover.word.setText("R&D")
    popover.url.setText("https://example.org/page?x=1&y=2")
    popover._on_insert()
    assert editor.text() == r"\href{https://example.org/page?x=1\&y=2}{R\&D} appears here"
    assert path.read_text(encoding="utf-8") == "Word appears here"
    assert not popover.isVisible()


@pytest.fixture
def quick(monkeypatch):
    monkeypatch.setattr(source_file, "AUTOSAVE_DELAY_MS", 20)


def test_slide_autosave_freezes_first_and_marks_the_buffer_without_requesting_a_render(pane, slides, quick):
    path = slides / CURRENT
    before = path.read_text(encoding="utf-8")
    saved, changes = [], []
    pane.saved.connect(saved.append)
    pane.show_path(path, changes.append)
    editor = pane.current.editor
    place(editor, len(before))
    editor.insertPlainText("% note\n")
    place(editor, editor.text().index("Text"))
    assert path.read_text(encoding="utf-8") == before
    wait_until(lambda: not pane.current.dirty, seconds=10)

    after = before.replace("1-1-0}", "1-1-0+}") + "% note\n"
    assert path.read_text(encoding="utf-8") == editor.text() == after
    assert (slides / "abc-EN-Demo-v1-1-0.tex").read_text(encoding="utf-8") == before
    assert not editor.is_modified() and editor.textCursor().position() == after.index("Text")
    assert saved == [] and [(old.replace("\r\n", "\n"), new.replace("\r\n", "\n")) for old, new in changes] == [(before, after)]
    editor.insertPlainText("x")
    assert pane.save() and saved == [path]
    assert path.read_text(encoding="utf-8") == after.replace("Text", "xText")
    assert len(list((pane.app.project.slide_backups_dir / path.name).glob("*.tex"))) == 1


def test_plain_files_autosave_with_crlf_and_pause_on_disk_conflict(pane, tmp_path, monkeypatch, quick):
    monkeypatch.setattr(QMessageBox, "critical", lambda *_a: pytest.fail("an autosave asks nothing"))
    deck = write_test_file(tmp_path / "decks.tex", b"deck text\r\n")
    previous = []
    pane.show_path(deck, previous.append)
    pane.current.editor.insertPlainText("new ")
    wait_until(lambda: not pane.current.dirty)
    assert deck.read_bytes() == b"new deck text\r\n" and previous == [("deck text\r\n", "new deck text\r\n")]

    pane.current.editor.insertPlainText("more ")
    deck.write_text("someone else's text", encoding="utf-8")
    wait_until(lambda: pane.current.conflicted)
    assert pane.current.dirty and deck.read_text(encoding="utf-8") == "someone else's text"
    pane.current.editor.insertPlainText("still ")
    pause(150)
    assert deck.read_text(encoding="utf-8") == "someone else's text"           # paused while in conflict

    pane.current.keep_edits()
    wait_until(lambda: not pane.current.dirty)
    assert deck.read_text(encoding="utf-8").startswith("new more still deck text")


def test_releasing_a_dirty_file_keeps_edits_until_autosave_is_reenabled(pane, slides, quick):
    layout_settings.set(source_file.AUTOSAVE_KEY, False)
    path = slides / OTHER
    pane.hold(path)
    pane.show_path(path)
    file = pane.current
    file.editor.insertPlainText("% later\n")
    pane.release(path)
    assert pane.file_for(path) is file and not pane.is_held(path)
    pane.show_path(slides / CURRENT)
    assert path.read_text(encoding="utf-8") == BODY
    assert pane.blocked_files() == [file] and not file._autosave_timer.isActive()
    layout_settings.set(source_file.AUTOSAVE_KEY, True)
    pane.autosave_changed()
    assert file._autosave_timer.isActive() and pane.blocked_files() == []
    wait_until(lambda: not file.dirty)
    assert "% later" in path.read_text(encoding="utf-8")


def test_a_long_file_name_is_cut_in_a_narrow_pane_and_whole_in_its_tooltip(pane, slides):
    path = slides / "xyz-EN-A-Very-Long-Slide-Title-That-Does-Not-Fit-Even-Beside-The-Whole-Toolbar-current.tex"
    path.write_text(BODY, encoding="utf-8")
    pane.resize(320, 400)
    pane.show()
    pane.show_path(path)
    QApplication.processEvents()
    assert pane._name.toolTip() == path.name and pane._name.text().endswith("…")


def test_a_file_stays_open_until_the_last_tab_releases_it(pane, slides):
    held, other = slides / CURRENT, slides / OTHER
    closed = []
    pane.file_closed.connect(closed.append)
    pane.hold(held)
    pane.hold(held)
    pane.show_path(held)
    file = pane.current
    pane.release(held)
    assert pane.current is file and pane.is_held(held) and closed == []
    file.editor.insertPlainText("mine ")
    pane.show_path(other)
    assert pane.file_for(held) is file and "mine " in held.read_text(encoding="utf-8")
    held.write_text("changed on disk\n", encoding="utf-8")
    pane.show_path(held)
    assert pane.current is file and file.editor.text().endswith("changed on disk\n")
    assert "mine " not in file.editor.text()
    pane.release(held)
    assert pane.current is None and pane.file_for(held) is None and closed == [other, held]
    pane.unhold(held)
    pane.hold(held)
    assert pane.is_held(held)
    pane.show_path(held)
    pane.unhold(held)
    assert not pane.is_held(held) and pane.current is not None
    pane.show_path(other)
    assert pane.file_for(held) is None


def test_the_update_version_caret_offers_each_level_directly(pane, slides):
    path = slides / CURRENT
    pane.show_path(path)
    assert pane._version_button.isVisibleTo(pane) and not pane._version_button.isEnabled()
    pane.current.editor.insertPlainText("edit ")
    assert pane._version_button.isEnabled()
    assert pane.current.write_now() and pane._version_button.isEnabled()
    initial = []
    pane.version_requested.connect(initial.append)
    pane._version_button.buttons()[0].click()
    assert initial == [path]
    pane._set_revert_menu(pane.current, True)
    menu = pane._version_button._menu
    items = {entry[1]: (entry[2], entry[6]) for entry in menu._entries if entry[0] == "item"}
    assert items == {"revert": ("Revert to v1.1.0…", True), "level:patch": ("Update as patch · v1.1.1", True),
                     "level:minor": ("Update as minor · v1.2.0", True), "level:major": ("Update as major · v2.0.0", True)}
    asked = []
    pane.version_level_requested.connect(lambda slide, level: asked.append((slide, level)))
    pane.revert_requested.connect(asked.append)
    menu.triggered.emit("revert")
    assert asked.pop() == path
    menu.triggered.emit("level:minor")
    assert asked == [(path, "minor")]
    pane._set_revert_menu(pane.current, False)                # nothing to freeze: the levels are greyed out
    again = {entry[1]: entry[6] for entry in pane._version_button._menu._entries if entry[0] == "item"}
    assert again["level:patch"] is False and again["revert"] is True


@pytest.fixture
def popup_menu(monkeypatch):
    shown = []
    monkeypatch.setattr(PopoverMenu, "popup_below", lambda menu, *_a, **_kw: shown.append(menu))

    def open_menu(action):
        action()
        return shown.pop()

    return open_menu


def color_swatches(menu):
    return {entry[1]: entry[7] for entry in menu._entries if entry[0] == "item"}


def test_color_menu_takes_the_decks_theme_colors_and_follows_switches(pane, ctx, popup_menu):
    write_test_file(ctx.root / "SlideMage_template_acme.tex",
                    "\\input{SlideMage_setup}\n\\definecolor{c_primary_highlight}{HTML}{b45309}\n"
                    "\\definecolor{c_secondary_blue}{RGB}{0,128,255} % comment \\definecolor{c_secondary_blue}{HTML}{000000}\n")
    def deck(template):
        return SimpleNamespace(text=f"\\documentclass{{beamer}}\n\\input{{SlideMage_template_{template}}}\n")

    pane.app.state = SimpleNamespace(deck=deck("acme"))
    acme = color_swatches(popup_menu(pane._open_color_menu))
    assert acme["c_primary_highlight"] == "#b45309" and acme["c_secondary_blue"] == "#0080ff"
    assert acme["c_secondary_violet"] == "#ba68c8"                  # not redefined: the framework's catalog value

    pane.app.state.deck = deck("grayscale")                # the shipped grayscale template
    grey = color_swatches(popup_menu(pane._open_color_menu))
    assert grey["c_primary_highlight"] == "#555555"
    assert all(v[1:3] == v[3:5] == v[5:7] for v in grey.values())
    pane.app.state.deck = None                             # no deck: the default render template
    assert color_swatches(popup_menu(pane._open_color_menu))["c_primary_highlight"] == "#0066cc"
    write_test_file(ctx.root / "SlideMage_template_acme.tex", "\\input{SlideMage_setup}\n\\definecolor{c_primary_highlight}{HTML}{111111}\n")
    pane.app.state.deck = deck("acme")                     # the theme edited
    assert color_swatches(popup_menu(pane._open_color_menu))["c_primary_highlight"] == "#111111"


def test_color_menu_leads_with_the_roles_in_the_mode_of_the_view_shown(pane, monkeypatch, popup_menu):
    text = ("\\documentclass{beamer}\n\\newcommand{\\SMModeOverride}{dark}\n\\input{SlideMage_template_slidemage}\n"
            "% SlideMage view themes: after-course=slidemage:light\n\\begin{document}\n\\end{document}\n")
    pane.app.state = SimpleNamespace(deck=SimpleNamespace(text=text), view="instructor")
    entries = popup_menu(pane._open_color_menu)._entries
    items = [e for e in entries if e[0] == "item"]
    assert [e[1] for e in items[:7]] == ["c_text", "c_text_muted", "c_text_on_accent", "c_link", "c_canvas",
                                          "c_card", "c_line"]
    dark = {e[1]: e[7] for e in items}
    assert dark["c_text"] == "#ffffff" and dark["c_canvas"] == "#444444"
    assert dark["c_primary_highlight"] == "#8bbcec"                     # v0.16.5: the template's dark value
    assert dark["c_secondary_blue"] == "#3d8fe0"                        # a color the mode leaves alone

    pane.app.state.view = "after-course"                       # this view is light
    light = color_swatches(popup_menu(pane._open_color_menu))
    assert light["c_text"] == "#1e1e1e" and light["c_canvas"] == "#ffffff"
    choose = []
    monkeypatch.setattr(pane, "_wrap", choose.append)
    popup_menu(pane._open_color_menu).triggered.emit("c_text")
    assert choose == ["textcolor{c_text}"]


def test_reindent_is_offered_for_a_deck_and_the_bib_with_their_own_rules(pane, ctx, slides, popup_menu):
    def reindent_enabled():
        menu = popup_menu(pane._open_tools_menu)
        return next(entry[6] for entry in menu._entries if entry[:2] == ("item", "reindent"))

    deck = write_test_file(ctx.decks_dir / "course.tex", "\\begin{document}\n\\section{A}\n\\slide{abc-EN-Demo}\n\\end{document}\n")
    bib = write_test_file(ctx.bibliography_path, "@book{alpha,\ntitle={A},\n  }\n")
    other = write_test_file(ctx.root / "notes.tex", "x\n")

    for path, kind, expected in (
        (deck, "deck", "\\begin{document}\n\t\\section{A}\n\t\\slide{abc-EN-Demo}\n\\end{document}\n"),
        (bib, "bib", "@book{alpha,\n\ttitle={A},\n}\n"),
    ):
        pane.show_path(path)
        assert pane.current.reindent_kind == kind and reindent_enabled()
        pane.reindent()
        assert pane.current.editor.text() == expected
    pane.reindent()
    assert "already correct" in pane.app.logged[-1]

    pane.show_path(slides / OTHER)
    assert pane.current.reindent_kind == "slide" and reindent_enabled()
    pane.show_path(other)                                       # any other file: not offered
    assert pane.current.reindent_kind is None and not reindent_enabled()
    pane.reindent()
    assert pane.current.editor.text() == "x\n"


def test_line_endings_alone_can_make_a_mixed_source_snapshot_stale(pane, slides):
    path = slides / "xyz-EN-Mixed-current.tex"
    raw = b"first\r\nsecond\n"
    path.write_bytes(raw)
    pane.show_path(path)
    file = pane.current
    file.editor.insertPlainText("edited ")
    path.write_bytes(raw.replace(b"\r\n", b"\n"))
    assert not file.write_now(force=True) and file.conflicted
    assert not (slides / "xyz-EN-Mixed-v1-0-0.tex").exists()
    path.write_bytes(raw)
    file.keep_edits()
    assert file.write_now(force=True)
    assert (slides / "xyz-EN-Mixed-v1-0-0.tex").read_bytes() == raw
    assert next((pane.app.project.slide_backups_dir / path.name).glob("*.tex")).read_bytes() == raw
    assert file.raw_text.encode() == path.read_bytes()


def _color_menu(pane, monkeypatch):
    shown = []
    monkeypatch.setattr(PopoverMenu, "popup_below", lambda self, anchor, **kw: shown.append(self))
    pane._open_color_menu()
    return {e[1]: e[7] for e in shown[0]._entries if e[0] == "item"}


def test_custom_color_asks_for_any_color_and_wraps_the_selection_with_its_hex(pane, slides, monkeypatch):
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QColorDialog
    from slidemage.ui.workspace.source_view import CUSTOM_COLOR

    shown = _color_menu(pane, monkeypatch)
    assert CUSTOM_COLOR in shown                                    # the menu's last entry
    pane.show_path(slides / "abc-EN-Demo-current.tex", lambda *_: None)
    editor = pane.current.editor
    editor.setPlainText("a word b")
    select(editor, 2, 6)
    monkeypatch.setattr(QColorDialog, "getColor", lambda *a, **k: QColor("#1a2b3c"))
    pane._on_color_chosen(CUSTOM_COLOR)
    assert editor.text() == "a \\textcolor[HTML]{1A2B3C}{word} b"
    monkeypatch.setattr(QColorDialog, "getColor", lambda *a, **k: QColor())      # cancelled: nothing changes
    pane._on_color_chosen(CUSTOM_COLOR)
    assert editor.text() == "a \\textcolor[HTML]{1A2B3C}{word} b"
