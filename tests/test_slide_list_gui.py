# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The slide list (left column): what it shows and every edit it can make to the
deck file -- through keys, drops, the context menu and the bulk bar."""
from __future__ import annotations

from dataclasses import replace
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt, QTimer
from PySide6.QtGui import QDropEvent, QFontMetrics, QGuiApplication, QImage, QPainter, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView, QLineEdit, QStyleOptionViewItem, QWidget

from conftest import wait_until
from slidemage import deck_editor, deck_outline
from slidemage.fileio import read_text_exact as read
from slidemage.deck_scan import Deck, parse_chapters
from slidemage.ui.dialogs import remove_section
from slidemage.ui.kit import kit_qss
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.kit.widgets import Toast
from slidemage.ui.workspace import compile_actions
from slidemage.ui.workspace import slide_list as slide_list_module
from slidemage.ui.workspace.actions import build_registry
from slidemage.ui.workspace.slide_list import ABOVE_ITEM, BELOW_ITEM, ON_ITEM, SlideList
from slidemage.ui.workspace.slide_tree import DATA, THUMB_H, THUMB_W, meta_text
from slidemage.ui.workspace.state import WorkspaceState

HEAD = "\\documentclass{beamer}\n\\begin{document}\n"
TAIL = "\\end{document}\n"


class FakeWindow:
    project = property(lambda self: self.state.project)
    """What the list needs of the main window: the rescan after an edit, the dialogs, and
    the command registry its context menus show."""

    def __init__(self, state):
        self.state = state
        self.commands = build_registry()
        self.compiling = False
        self.list = None
        self.added = []
        self.started = []     # what the Add slide sheet was asked to start on
        self.opened = []
        self.open_kwargs = []
        self.edits = []

    def after_deck_edit(self, path, summary, previous_text=None):
        text = read(self.state.deck.path)
        self.state.set_deck(replace(self.state.deck, text=text, chapters=parse_chapters(text)))
        self.list.rebuild()
        self.list.deck_edited(path, summary, previous_text)
        self.edits.append(summary)

    def open_add_slide_dialog(self, deck, insert_at, indent, **start):
        self.added.append((insert_at, indent))
        self.started.append(start)

    def open_slide_editor(self, path, **kwargs):
        self.opened.append(path)
        self.open_kwargs.append(kwargs)

    def open_images_for_slide(self, id_slug):
        self.opened.append(("images", id_slug))

    @property
    def slide_list(self):
        return self.list


@pytest.fixture
def make_list(tmp_path, qapp, monkeypatch, ctx):
    keep = []
    errors = []
    monkeypatch.setattr(slide_list_module.QMessageBox, "critical", lambda *args: errors.append(args[2]))

    def make(body, newline="\n"):
        text = (HEAD + body + TAIL).replace("\n", newline)
        path = tmp_path / "course.tex"
        path.write_bytes(text.encode("utf-8"))
        deck = Deck(
            name="course", path=path, archived=False, text=text, supports_version=True,
            uses_biblatex=False, preamble_end=text.index("\\begin{document}") + len("\\begin{document}"),
            chapters=parse_chapters(text), output_folders={}, tags=[])
        state = WorkspaceState(ctx)
        window = FakeWindow(state)
        host = QWidget()
        window.list = SlideList(window, state, ThemeManager(), Toast(host))
        window.list._background_thumbnails = False  # legacy edit tests control synchronous row updates
        window.list.toast_host = host
        state.set_deck(deck)
        keep.append(window)
        return window.list, window, path

    make.errors = errors
    yield make
    for window in keep:         # free the widgets now, not whenever the garbage collector gets to them
        window.list.toast_host.deleteLater()
        window.list.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def ids(slide_list):
    return [slide_list.tree.data_of(item).call.id for item in slide_list.tree.slide_items()]


def item_of(slide_list, slide_id, nth=0):
    return [i for i in slide_list.tree.slide_items() if slide_list.tree.data_of(i).call.id == slide_id][nth]


def head_of(slide_list, title):
    return next(h for h in slide_list.tree.section_items() if slide_list.tree.data_of(h).title == title)


def focus(slide_list, slide_id, nth=0):
    slide_list.tree.setCurrentItem(item_of(slide_list, slide_id, nth), 0,
                                   slide_list_module.QItemSelectionModel.SelectionFlag.ClearAndSelect)


def select(slide_list, *slide_ids):
    slide_list.tree.clearSelection()
    for slide_id in slide_ids:
        item_of(slide_list, slide_id).setSelected(True)


def deck_lines(path):
    return [line for line in read(path).splitlines() if line.startswith(("\\slide", "\\section", "\\omit", "\\cond"))]


def key(slide_list, key_code, modifier=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(slide_list.tree, key_code, modifier)


FRONT_AND_SECTIONS = (
    "\\slide{aaa-Front}\n\\section{One}\n\\slide{bbb-One}\n\\section{Empty}\n"
    "\\section{Two}\n\\slide{ccc-Two}\n\\slide{ddd-Two}\n")


@pytest.mark.parametrize("width", [220, 520])
def test_long_slide_titles_and_meta_elide_and_thumbnails_keep_their_size(make_list, qapp, width):
    slide_list, _window, _path = make_list("\\slide{aaa-EN-One}\n")
    item = item_of(slide_list, "aaa")
    row = replace(slide_list.tree.data_of(item),
                  title="A very long slide title that cannot fit in a narrow slide list " * 3,
                  lint_error=True, stale_preview=True, missing_translation=True)
    item.setData(0, DATA, row)
    slide_list.resize(width, 400)
    slide_list.show()
    qapp.processEvents()
    tree = slide_list.tree
    option = QStyleOptionViewItem()
    option.rect = tree.visualItemRect(item)
    canvas = QPixmap(tree.viewport().size())
    painter = QPainter(canvas)
    recorded = Mock(wraps=painter)
    try:
        tree.delegate.paint(recorded, option, tree.indexFromItem(item))
    finally:
        painter.end()
    text_calls = recorded.drawText.call_args_list
    title_rect, _, title = text_calls[-1].args
    assert title.endswith("…") and row.title.startswith(title[:-1])
    title_font = recorded.setFont.call_args_list[-1].args[0]
    assert QFontMetrics(title_font).horizontalAdvance(title) <= title_rect.width()
    meta = "".join(call.args[2] for call in text_calls[:-1])
    expected_meta = meta_text(row, "EN")
    if width == 220:
        assert meta.endswith("…") and expected_meta.startswith(meta[:-1])
    else:
        assert meta == expected_meta
    thumb = next(call.args[0] for call in recorded.drawRoundedRect.call_args_list
                 if call.args[0].left() == option.rect.left() + 6)
    assert (thumb.width(), thumb.height()) == (THUMB_W, THUMB_H)


def test_a_thumbnail_is_reduced_once_to_the_screens_own_pixel_size_and_never_enlarged(make_list, tmp_path):
    """Use the screen pixel ratio so Qt can draw the cached pixmap at 1:1."""
    slide_list, _window, _path = make_list("\\slide{aaa-EN-One}\n")
    delegate = slide_list.tree.delegate
    big, small = tmp_path / "big.png", tmp_path / "small.png"
    QImage(168, 95, QImage.Format.Format_RGB32).save(str(big))
    QImage(60, 34, QImage.Format.Format_RGB32).save(str(small))
    for ratio, width in ((1.0, 56), (1.25, 70), (2.0, 112), (3.0, 168)):
        pixmap = delegate._thumbnail(big, ratio)
        assert pixmap.width() == width and pixmap.deviceIndependentSize().width() == pytest.approx(THUMB_W)
    pixmap = delegate._thumbnail(small, 3.0)                                     # too small for 3x: kept as it is
    assert pixmap.width() == 60 and pixmap.deviceIndependentSize().width() == pytest.approx(THUMB_W)
    delegate.forget_pixmaps([big])
    assert not [key for key in delegate._pixmaps if key[0] == big] and (small, 3.0) in delegate._pixmaps


def test_an_empty_deck_says_so_and_a_missing_deck_shows_no_rows(make_list):
    slide_list, window, _path = make_list("")
    assert not slide_list.note.isHidden() and "no slides" in slide_list.note.text()
    window.state.set_deck(None)
    assert window.state.current_outline() is None
    assert slide_list.tree.topLevelItemCount() == 0
    assert slide_list.note.isHidden()


def test_de_rows_keep_focus_selection_and_edit_the_original_slot(make_list, tmp_path):
    slides = tmp_path / "slides"
    slides.mkdir()
    for slug, header in (("aaa-EN-One", "%% DE translation: ddd-DE-Eins\n"),
                         ("ddd-DE-Eins", "%% Translation of: aaa-EN-One\n")):
        (slides / f"{slug}-current.tex").write_text(header + "\\begin{standardframe}{Title}Text\\end{standardframe}\n")
    slide_list, window, path = make_list(
        "\\slide{aaa-EN-One}\n\\slide{bbb-EN-Two}\n\\section{Late}\n\\slide{ddd-DE-Eins}\n")
    assert ids(slide_list) == ["aaa", "bbb"]
    focus(slide_list, "aaa")
    select(slide_list, "aaa", "bbb")
    window.state.set_language("DE")
    assert ids(slide_list) == ["ddd", "bbb"]
    assert window.state.focused_slide == "ddd" and window.state.selection == ("ddd", "bbb")
    slide_list._open_source(slide_list.rows()[0])
    assert window.opened[-1].name == "ddd-DE-Eins-current.tex"
    slide_list._set_visibility([slide_list.rows()[0]], "after-course", False)
    assert "\\conditionalslide[instructor,during-course]{aaa-EN-One}" in path.read_text()
    assert not make_list.errors
    slide_list._remove([slide_list.rows()[0]])
    assert "aaa-EN-One" not in path.read_text() and "ddd-DE-Eins" not in path.read_text()
    assert ids(slide_list) == ["bbb"]


def test_a_slide_that_shares_its_line_is_locked(make_list):
    slide_list, _window, path = make_list("\\slide{aaa-A} \\slide{bbb-B}\n\\section{S} % a note\n\\section{T} \\slide{ccc-C}\n")
    first = item_of(slide_list, "aaa")
    assert not first.flags() & Qt.ItemFlag.ItemIsDragEnabled
    assert head_of(slide_list, "S").flags() & Qt.ItemFlag.ItemIsEditable          # a comment after it is fine
    locked = head_of(slide_list, "T")
    assert not locked.flags() & (Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsDragEnabled)
    before = read(path)
    slide_list._remove([slide_list.tree.data_of(first)])
    assert "shares its line" in make_list.errors[-1] and read(path) == before
    focus(slide_list, "aaa")
    menu = slide_list._slide_menu()
    assert not _entry(menu, "slide:remove")[6] and not _entry(menu, "variant:omitslide")[6]
    assert _entry(menu, "slide:open")[6]                # reading it is fine
    choose_section(slide_list, "T")
    section_menu = slide_list._section_menu()
    assert not _entry(section_menu, "section:rename")[6] and not _entry(section_menu, "section:remove_section")[6]


def removing(monkeypatch, choice):
    """The Remove section sheet, answered with `choice`; returns what it was asked (title, slides, sections)."""
    asked = []

    class Sheet:
        def __init__(self, _parent, title, slides, sections):
            asked.append((title, slides, sections))
            self.choice = choice

        def exec(self):
            return True

    monkeypatch.setattr(slide_list_module, "RemoveSectionSheet", Sheet)
    return asked


def choose_section(slide_list, title):
    slide_list.tree.setCurrentItem(head_of(slide_list, title), 0,
                                   slide_list_module.QItemSelectionModel.SelectionFlag.NoUpdate)


def flyout(menu, key_):
    """The flyout the submenu row `key_` of `menu` opens."""
    return menu._submenus[key_][1](menu)


def _entry(menu, key_):
    """The row `key_` of `menu`, or of one of its flyouts."""
    for entry in menu._entries:
        if entry[0] == "item" and entry[1] == key_:
            return entry
    for sub in menu._submenus:
        for entry in flyout(menu, sub)._entries:
            if entry[0] == "item" and entry[1] == key_:
                return entry
    raise StopIteration(key_)


def test_the_find_box_filters_by_id_or_title_and_enter_goes_to_the_first_match(make_list):
    slide_list, window, _path = make_list(FRONT_AND_SECTIONS)
    assert ids(slide_list) == ["aaa", "bbb", "ccc", "ddd"]
    assert head_of(slide_list, "Empty").childCount() == 0
    slide_list.find.setText("two")
    visible = [i for i in slide_list.tree.slide_items() if not i.isHidden()]
    assert [slide_list.tree.data_of(i).call.id for i in visible] == ["ccc", "ddd"]
    assert [h.isHidden() for h in slide_list.tree.section_items()] == [True, True, True, False]
    slide_list.find.setText("bbb")
    assert [slide_list.tree.data_of(h).title for h in slide_list.tree.section_items() if not h.isHidden()] == ["One"]
    slide_list.find.setText("nothing like it")
    assert "No slide matches" in slide_list.note.text() and not slide_list.note.isHidden()
    slide_list.find.setText("ddd")
    slide_list.find.returnPressed.emit()
    assert slide_list.find.text() == "" and window.state.focused_slide == "ddd"
    assert all(not i.isHidden() for i in slide_list.tree.slide_items())


def test_a_slide_focused_from_elsewhere_is_shown_though_the_filter_hides_it_or_its_section_is_closed(make_list):
    slide_list, window, _path = make_list(FRONT_AND_SECTIONS)
    slide_list.find.setText("bbb")                          # the filter hides ddd
    assert item_of(slide_list, "ddd").isHidden()
    window.state.set_focused_slide("ddd")
    assert slide_list.find.text() == "" and not item_of(slide_list, "ddd").isHidden()
    assert slide_list.tree.currentItem() is item_of(slide_list, "ddd")
    two = head_of(slide_list, "Two")
    slide_list.tree.itemClicked.emit(two, 0)
    assert not two.isExpanded()
    slide_list.find.setText("ccc")
    assert two.isExpanded()
    slide_list.find.clear()
    assert not two.isExpanded()
    slide_list.rebuild()
    two = head_of(slide_list, "Two")
    assert not two.isExpanded()
    window.state.set_focused_slide("ccc")
    assert two.isExpanded() and "Two" not in slide_list.tree.collapsed
    assert slide_list.tree.currentItem() is item_of(slide_list, "ccc")


def test_focus_and_selection_go_through_the_workspace_state(make_list):
    slide_list, window, _path = make_list(FRONT_AND_SECTIONS)
    assert window.state.focused_slide is None
    slide_list.focus_first_slide()
    assert window.state.focused_slide == "aaa"
    focus(slide_list, "ccc")
    slide_list.focus_first_slide()
    assert window.state.focused_slide == "ccc" and window.state.selection == ("ccc",)
    window.state.set_focused_slide("bbb")                    # e.g. a slide opened in the source editor
    assert slide_list.tree.data_of(slide_list.tree.currentItem()).call.id == "bbb"
    select(slide_list, "aaa", "ddd")
    assert window.state.selection == ("aaa", "ddd")
    assert not slide_list.bulk_bar.isHidden()
    slide_list.tree.clearSelection()
    assert slide_list.bulk_bar.isHidden() and window.state.selection == ()
    slide_list._select_all()
    assert window.state.selection == tuple(ids(slide_list))


def test_arrow_keys_pass_a_closed_section_and_slides_the_filter_hides(make_list):
    slide_list, window, _path = make_list(FRONT_AND_SECTIONS)
    slide_list.tree.toggle_section(head_of(slide_list, "One"))
    focus(slide_list, "aaa")
    key(slide_list, Qt.Key.Key_Down)
    assert window.state.focused_slide == "ccc"
    key(slide_list, Qt.Key.Key_Up)
    assert window.state.focused_slide == "aaa"
    slide_list.tree.toggle_section(head_of(slide_list, "One"))
    slide_list.find.setText("-")
    item_of(slide_list, "bbb").setHidden(True)
    key(slide_list, Qt.Key.Key_Down)
    assert window.state.focused_slide == "ccc"
    slide_list.find.clear()
    for code, expected in ((Qt.Key.Key_Home, "aaa"), (Qt.Key.Key_End, "ddd")):
        key(slide_list, code)
        assert window.state.focused_slide == expected
    for code in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown):
        key(slide_list, code)
        assert isinstance(slide_list.tree.data_of(slide_list.tree.currentItem()), deck_outline.SlideRow)


def test_a_section_heading_stays_reachable_by_keyboard(make_list):
    slide_list, window, path = make_list(FRONT_AND_SECTIONS)
    focus(slide_list, "ccc")
    key(slide_list, Qt.Key.Key_Left)                    # up to the slide's heading, for F2 and Alt+Up
    assert slide_list.tree.data_of(slide_list.tree.currentItem()).title == "Two"
    assert window.state.focused_slide == "ccc"
    key(slide_list, Qt.Key.Key_Down)                    # and on from the heading to a slide
    assert window.state.focused_slide == "ccc"
    key(slide_list, Qt.Key.Key_Left)
    key(slide_list, Qt.Key.Key_Up)
    assert window.state.focused_slide == "bbb"
    slide_list.tree.setCurrentItem(head_of(slide_list, "Two"))
    key(slide_list, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier)     # Alt+Up still moves the heading itself
    assert deck_lines(path).index("\\section{Two}") < deck_lines(path).index("\\section{Empty}")


def test_open_in_new_tab_asks_for_a_tab_of_that_row_through_the_command_route(make_list):
    slide_list, window, _path = make_list("\\slide{aaa-First}\n\\slide{bbb-Second}\n\\slide{aaa-First}\n")
    focus(slide_list, "aaa", 1)
    menu = slide_list._slide_menu()
    assert "slide:open_tab" in keys_of(menu)
    row = slide_list.tree.data_of(item_of(slide_list, "aaa", 1))
    window.commands.run("slide:open_tab", window)
    assert [p.name for p in window.opened] == ["aaa-First-current.tex"]
    assert window.open_kwargs == [{"keep_mode": False, "tab": True, "occurrence": row.key}]
    assert "slide:open_tab" not in keys_of(slide_list._bulk_menu())


def test_alt_up_and_down_move_the_slide_past_a_slide_or_a_section_marker(make_list):
    slide_list, _window, path = make_list(FRONT_AND_SECTIONS)
    focus(slide_list, "ccc")
    key(slide_list, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier)    # past \section{Two}, into "Empty"
    assert deck_lines(path) == ["\\slide{aaa-Front}", "\\section{One}", "\\slide{bbb-One}",
                                "\\section{Empty}", "\\slide{ccc-Two}", "\\section{Two}", "\\slide{ddd-Two}"]
    key(slide_list, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier)    # past \section{Empty}
    key(slide_list, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier)    # past bbb
    assert deck_lines(path)[:4] == ["\\slide{aaa-Front}", "\\section{One}", "\\slide{ccc-Two}", "\\slide{bbb-One}"]
    focus(slide_list, "aaa")
    before = read(path)
    key(slide_list, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier)    # nothing above the first slide
    assert read(path) == before
    key(slide_list, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)
    assert deck_lines(path)[:2] == ["\\section{One}", "\\slide{aaa-Front}"]
    assert slide_list.tree.data_of(slide_list.tree.currentItem()).call.id == "aaa"     # the focus follows it


def test_alt_arrows_move_a_section_with_all_its_slides(make_list):
    front = "\\slide{zzz-Front}\n"
    one = "\\section{One}\n\\slide{aaa-First}\n"
    two = "\\section{Two}\n% Section note\n\\slide{bbb-Second}\n\\slide{ccc-Third}\n"
    slide_list, _window, path = make_list(front + one + two, "\r\n")
    original = path.read_bytes()
    choose_section(slide_list, "Two")
    key(slide_list, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)
    assert path.read_bytes() == original
    key(slide_list, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier)
    assert path.read_bytes() == (HEAD + front + two + one + TAIL).replace("\n", "\r\n").encode()
    choose_section(slide_list, "Two")
    key(slide_list, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)
    assert path.read_bytes() == original


def test_delete_moves_focus_and_bulk_delete_undo_restores_the_deck(make_list):
    slide_list, window, path = make_list(FRONT_AND_SECTIONS)
    original = read(path)
    focus(slide_list, "bbb")
    key(slide_list, Qt.Key.Key_Delete)
    assert ids(slide_list) == ["aaa", "ccc", "ddd"] and window.state.focused_slide == "ccc"
    slide_list.undo()

    select(slide_list, "bbb", "ddd")
    window.edits.clear()
    key(slide_list, Qt.Key.Key_Delete)
    assert deck_lines(path) == ["\\slide{aaa-Front}", "\\section{One}", "\\section{Empty}",
                                "\\section{Two}", "\\slide{ccc-Two}"]
    assert not slide_list.toast.isHidden() and len(window.edits) == 1
    slide_list.toast.action_triggered.emit("undo")
    assert read(path) == original and ids(slide_list) == ["aaa", "bbb", "ccc", "ddd"]


def test_undo_goes_back_one_edit_at_a_time_and_refuses_after_an_outside_change(make_list):
    slide_list, _window, path = make_list(FRONT_AND_SECTIONS)
    original = read(path)
    slide_list._remove([row_of(slide_list, "aaa")])
    slide_list._remove([row_of(slide_list, "bbb")])
    slide_list.undo()
    assert "\\slide{bbb-One}" in read(path) and "\\slide{aaa-Front}" not in read(path)
    committed = read(path)
    path.write_bytes((committed + "% edited elsewhere\n").encode())
    slide_list.deck.text = read(path)                       # rescan already saw the outside edit
    slide_list.undo()
    assert "changed on disk" in make_list.errors[-1]
    assert read(path).endswith("% edited elsewhere\n")
    path.write_bytes(committed.encode())
    slide_list.undo()                                       # the refused step is still there
    assert read(path) == original


def test_undo_refuses_a_change_between_commit_and_rescan(make_list, monkeypatch):
    slide_list, window, path = make_list(FRONT_AND_SECTIONS)
    refresh = window.after_deck_edit

    def change_then_rescan(path, summary, entry):
        path.write_bytes(path.read_bytes() + b"% outside edit\n")
        refresh(path, summary, entry)

    monkeypatch.setattr(window, "after_deck_edit", change_then_rescan)
    slide_list._remove([row_of(slide_list, "aaa")])
    assert slide_list.deck.text.endswith("% outside edit\n")
    slide_list.undo()
    assert "changed on disk" in make_list.errors[-1] and read(path) == slide_list.deck.text


def test_the_bulk_bar_hides_and_shows_the_slides_in_the_current_view(make_list):
    slide_list, window, path = make_list(FRONT_AND_SECTIONS)
    select(slide_list, "bbb", "ccc")
    slide_list.bulk_visibility_button.click()
    assert "\\conditionalslide[during-course,after-course]{bbb-One}" in read(path)
    assert "\\conditionalslide[during-course,after-course]{ccc-Two}" in read(path)
    assert [slide_list.tree.data_of(i).hidden for i in slide_list.tree.slide_items()] == [False, True, True, False]
    select(slide_list, "bbb", "ccc")
    slide_list.bulk_visibility_button.click()
    assert "\\slide{bbb-One}" in read(path) and "\\slide{ccc-Two}" in read(path)     # plain again
    window.state.set_view("after-course")
    select(slide_list, "aaa", "bbb")
    slide_list.bulk_visibility_button.click()
    assert "\\conditionalslide[instructor,during-course]{aaa-Front}" in read(path)


def keys_of(menu):
    return [e[1] for e in menu._entries if e[0] == "item"]


def test_the_slide_menu_offers_every_way_to_call_a_slide(make_list, monkeypatch, tmp_path, request):
    slides = tmp_path / "slides"
    slides.mkdir()
    (slides / "aaa-First-v1-0-0.tex").write_text("x", encoding="utf-8")
    slide_list, _window, path = make_list("\\slide{aaa-First}\n\\slide{bbb-Second}\n")
    focus(slide_list, "aaa")
    menu = slide_list._slide_menu()
    assert "slide:translate" not in keys_of(menu)
    request.getfixturevalue("fake_routes")
    menu = slide_list._slide_menu()
    assert "slide:translate" in keys_of(menu)
    assert keys_of(flyout(menu, "submenu:visibility")) == [
        "variant:slide", "variant:slidefinal", "variant:omitslide", "variant:conditionalslide",
        "variant:slidestep", "variant:slideversion:1-0-0", "variant:omitslideversion:1-0-0",
        "slide:visible:instructor", "slide:visible:during-course", "slide:visible:after-course"]
    assert keys_of(flyout(menu, "submenu:move")) == ["move:0"]
    assert _entry(menu, "variant:slide")[4] == "check"             # the current call is ticked
    for macro, expected in (
            ("slidefinal", "\\slidefinal{aaa-First}"), ("omitslide", "\\omitslide{aaa-First}"),
            ("conditionalslide", "\\conditionalslide[instructor,during-course,after-course]{aaa-First}"),
            ("slideversion:1-0-0", "\\slideversion{aaa-First}{1-0-0}"), ("slide", "\\slide{aaa-First}")):
        slide_list._run(f"variant:{macro}", [row_of(slide_list, "aaa")])
        assert deck_lines(path)[0] == expected
    monkeypatch.setattr(slide_list_module.QInputDialog, "getText", lambda *a, **k: ("1,2", True))
    slide_list._run("variant:slidestep", [row_of(slide_list, "aaa")])
    assert deck_lines(path)[0] == "\\slidestep{aaa-First}[instructor,during-course,after-course]{1,2}"
    monkeypatch.setattr(slide_list_module.QInputDialog, "getText", lambda *a, **k: ("x", True))
    slide_list._run("variant:slidestep", [row_of(slide_list, "aaa")])
    assert "not a valid step list" in make_list.errors[-1]
    asked = []
    monkeypatch.setattr(slide_list_module.QInputDialog, "getText", lambda *a, **k: asked.append(k["text"]) or ("", False))
    slide_list._run("variant:slidestep", [row_of(slide_list, "bbb")])
    assert asked == ["1-"]                                          # all steps to start from, not only the first


def test_the_slide_menu_hides_a_slide_in_one_view_and_opens_the_other_tools(make_list, monkeypatch):
    slide_list, window, path = make_list("\\slide{aaa-First}\n\\slide{bbb-Second}\n")
    focus(slide_list, "aaa")
    run = lambda command: window.commands.run(command, window)   # noqa: E731 -- what a menu entry does
    menu = slide_list._slide_menu()
    assert _entry(menu, "slide:visible:during-course")[6]
    run("slide:visible:during-course")
    assert deck_lines(path)[0] == "\\conditionalslide[instructor,after-course]{aaa-First}"
    focus(slide_list, "aaa")
    slide_list.state.set_mode("details")
    run("slide:preview")
    assert (slide_list.state.focused_slide, slide_list.state.mode) == ("aaa", "preview")
    run("slide:images")
    run("slide:open")
    assert window.opened[0] == ("images", "aaa-First")
    assert window.opened[1].name == "aaa-First-current.tex"
    # adding next to a slide, or a section before it
    row = row_of(slide_list, "aaa")
    run("slide:before")
    run("slide:after")
    assert window.added == [(row.call.line_start, ""), (row.call.line_end, "")]
    assert [(s["where"], s["source"], s["slide"]) for s in window.started] == [
        ("before aaa-First", "new", "aaa-First"), ("after aaa-First", "new", "aaa-First")]
    monkeypatch.setattr(slide_list_module.QInputDialog, "getText", lambda *a, **k: ("Intro", True))
    run("slide:section_before")
    assert deck_lines(path)[0] == "\\section{Intro}"


def test_the_bulk_menu_compiles_and_moves_selected_slides(make_list, monkeypatch):
    slide_list, window, path = make_list(FRONT_AND_SECTIONS)
    select(slide_list, "aaa", "ddd")
    menu = slide_list._bulk_menu()
    assert keys_of(flyout(menu, "submenu:move")) == ["move:0", "move:1", "move:2", "move:3"]
    compiled = []
    monkeypatch.setattr(compile_actions, "compile_slides", lambda _window, ids: compiled.append(ids))
    window.commands.run("compile:slides", window)
    assert [sorted(batch) for batch in compiled] == [["aaa", "ddd"]]
    slide_list._on_menu_chosen("move:2")               # into the empty section
    assert deck_lines(path) == ["\\section{One}", "\\slide{bbb-One}", "\\section{Empty}", "\\slide{aaa-Front}",
                                "\\slide{ddd-Two}", "\\section{Two}", "\\slide{ccc-Two}"]
    select(slide_list, "bbb", "ccc")
    slide_list._on_menu_chosen("slide:clear")
    assert slide_list.tree.selected_rows() == []


def row_of(slide_list, slide_id):
    return slide_list.tree.data_of(item_of(slide_list, slide_id))


def section_of(slide_list, title):
    return slide_list.tree.data_of(head_of(slide_list, title))


def test_dropping_slides_above_or_below_another_moves_them_in_order(make_list, qapp):
    slide_list, _window, path = make_list(FRONT_AND_SECTIONS)
    slide_list._on_moved([row_of(slide_list, "ddd")], row_of(slide_list, "aaa"), ABOVE_ITEM)
    assert deck_lines(path)[:2] == ["\\slide{ddd-Two}", "\\slide{aaa-Front}"]
    select(slide_list, "ddd", "aaa")
    slide_list.tree.moved.emit(slide_list.tree.selected_rows(), row_of(slide_list, "bbb"), BELOW_ITEM)
    assert deck_lines(path)[0] == "\\slide{ddd-Two}"  # the drop runs after Qt returns
    qapp.processEvents()
    assert deck_lines(path) == ["\\section{One}", "\\slide{bbb-One}", "\\slide{ddd-Two}", "\\slide{aaa-Front}",
                                "\\section{Empty}", "\\section{Two}", "\\slide{ccc-Two}"]


def test_dropping_on_section_headings_moves_slides_or_whole_sections(make_list):
    slide_list, _window, path = make_list(FRONT_AND_SECTIONS)
    original = read(path)
    slide_list._on_moved([section_of(slide_list, "One")], section_of(slide_list, deck_outline.UNSECTIONED), ON_ITEM)
    assert read(path) == original
    slide_list._on_moved([row_of(slide_list, "bbb")], section_of(slide_list, "Empty"), ON_ITEM)
    assert deck_lines(path)[:4] == ["\\slide{aaa-Front}", "\\section{One}", "\\section{Empty}", "\\slide{bbb-One}"]
    slide_list._on_moved([row_of(slide_list, "ddd")], section_of(slide_list, "Two"), BELOW_ITEM)
    assert deck_lines(path)[-2:] == ["\\slide{ddd-Two}", "\\slide{ccc-Two}"]
    slide_list._on_moved([row_of(slide_list, "bbb")], section_of(slide_list, "Empty"), ABOVE_ITEM)
    assert deck_lines(path)[1:4] == ["\\section{One}", "\\slide{bbb-One}", "\\section{Empty}"]
    slide_list._on_moved([row_of(slide_list, "aaa")], section_of(slide_list, "Two"), ON_ITEM)
    assert deck_lines(path)[-2:] == ["\\slide{ccc-Two}", "\\slide{aaa-Front}"]
    slide_list._on_moved([section_of(slide_list, "Two")], section_of(slide_list, "One"), ON_ITEM)
    assert deck_lines(path) == ["\\section{Two}", "\\slide{ddd-Two}", "\\slide{ccc-Two}", "\\slide{aaa-Front}",
                                "\\section{One}", "\\slide{bbb-One}", "\\section{Empty}"]
    slide_list._on_moved([section_of(slide_list, "Empty")], row_of(slide_list, "ccc"), ABOVE_ITEM)
    assert deck_lines(path)[0] == "\\section{Empty}"


def drop_event(point):
    return Mock(spec=QDropEvent, **{"position.return_value": QPointF(point)})


def test_the_tree_reports_a_drop_instead_of_moving_items_itself(make_list, monkeypatch, qapp):
    slide_list, _window, _path = make_list(FRONT_AND_SECTIONS)
    tree = slide_list.tree
    slide_list.resize(280, 600)
    slide_list.show()
    qapp.processEvents()
    drops = []
    tree.moved.connect(lambda *args: drops.append(args), Qt.ConnectionType.DirectConnection)
    monkeypatch.setattr(tree, "dropIndicatorPosition",
                        lambda: QAbstractItemView.DropIndicatorPosition.AboveItem)
    target = item_of(slide_list, "ddd")
    event = drop_event(tree.visualItemRect(target).center())
    focus(slide_list, "aaa")
    tree.dropEvent(event)
    event.accept.assert_called_once()
    event.setDropAction.assert_called_once_with(Qt.DropAction.IgnoreAction)
    sources, dropped_on, position = drops[-1]
    assert [r.call.id for r in sources] == ["aaa"] and dropped_on.call.id == "ddd" and position == ABOVE_ITEM
    tree.setCurrentItem(head_of(slide_list, "Two"))                           # a section is dragged alone
    tree.dropEvent(drop_event(tree.visualItemRect(head_of(slide_list, "One")).center()))
    assert drops[-1][0][0].title == "Two" and drops[-1][1].title == "One"
    tree.dropEvent(drop_event(tree.viewport().rect().bottomRight()))           # below the last row: no target
    assert len(drops) == 2
    slide_list.hide()


def test_a_section_is_renamed_in_place_and_remembers_a_collapsed_heading(make_list, qapp):
    slide_list, _window, path = make_list(FRONT_AND_SECTIONS)
    choose_section(slide_list, "One")
    key(slide_list, Qt.Key.Key_F2)
    editor = slide_list.tree.findChild(QLineEdit, kit_qss.SLIDES_RENAME)
    assert editor is not None
    editor.setText("First")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    qapp.processEvents()
    assert "\\section{First}" in read(path) and head_of(slide_list, "First").childCount() == 1

    two = head_of(slide_list, "Two")
    slide_list.tree.toggle_section(two)
    expected_collapsed = (slide_list.tree.collapsed - {"Two"}) | {"Second"}
    slide_list._rename_section(slide_list.tree.data_of(two), "Second")
    renamed = head_of(slide_list, "Second")
    assert "\\section{Two}" not in read(path) and "\\section{Second}" in read(path)
    assert renamed.childCount() == 2 and not renamed.isExpanded()
    assert slide_list.tree.collapsed == expected_collapsed

    slide_list.tree.rename(head_of(slide_list, "First"))
    QTest.keyClick(slide_list.tree.findChild(QLineEdit, kit_qss.SLIDES_RENAME), Qt.Key.Key_Escape)
    qapp.processEvents()
    assert "\\section{First}" in read(path)


def test_sections_are_added_removed_and_get_slides(make_list, monkeypatch):
    slide_list, window, path = make_list(FRONT_AND_SECTIONS)
    monkeypatch.setattr(slide_list_module.QInputDialog, "getText", lambda *a, **k: ("New", True))
    choose_section(slide_list, "Two")
    slide_list.run_section("section_after")
    assert deck_lines(path)[-1] == "\\section{New}"
    choose_section(slide_list, "Empty")
    slide_list.run_section("section_before")
    assert deck_lines(path)[2:5] == ["\\slide{bbb-One}", "\\section{New}", "\\section{Empty}"]
    choose_section(slide_list, "One")
    removing(monkeypatch, remove_section.HEADING)
    slide_list.run_section("remove_section")                              # its slides stay
    assert "\\section{One}" not in read(path) and "bbb" in ids(slide_list)
    choose_section(slide_list, "Two")
    slide_list.run_section("add_slide")
    deck = window.state.deck
    two = next(c for c in deck.chapters if c.title == "Two")
    assert window.added[-1] == (deck_editor.section_append_point(deck, two), "")     # after ddd, indented like it
    monkeypatch.setattr(slide_list_module.QInputDialog, "getText", lambda *a, **k: ("{bad}", True))
    choose_section(slide_list, "Two")
    slide_list.run_section("section_after")
    assert "braces" in make_list.errors[-1]


@pytest.mark.parametrize("body", [FRONT_AND_SECTIONS, ""], ids=["populated", "empty"])
def test_add_slide_commands_insert_after_the_source_or_at_the_end(make_list, body):
    slide_list, window, _path = make_list(body)
    slide_list.add_slide()
    deck = window.state.deck
    if not body:
        assert window.added == [deck_editor.empty_deck_insert_point(deck.text)]
        return
    assert window.added[-1] == deck_editor.append_position(deck)
    focus(slide_list, "bbb")
    call = row_of(slide_list, "bbb").call
    slide_list.add_slide()
    slide_list.run("duplicate")
    slide_list.run("translate:DE")
    slide_list.add_slide("translate", call.id_slug)
    assert window.added[1:] == [(call.line_end, call.indent)] * 4
    assert [(start["source"], start["target"]) for start in window.started[1:]] == [
        ("new", None), ("duplicate", None), ("translate", "DE"), ("translate", None)]
    assert all(start["slide"] == call.id_slug for start in window.started[1:])
    slide_list.add_slide("duplicate", "zzz-EN-Elsewhere")
    assert window.added[-1] == deck_editor.append_position(deck)


def test_the_slides_before_the_first_section_are_named_by_rename(make_list, monkeypatch):
    slide_list, _window, path = make_list(FRONT_AND_SECTIONS)
    front = next(s for s in slide_list.tree.section_items() if slide_list.tree.data_of(s).chapter is None)
    slide_list.tree.setCurrentItem(front)
    assert slide_list.section_enabled("rename")
    monkeypatch.setattr(slide_list_module.QInputDialog, "getText", lambda *a, **k: ("Intro", True))
    slide_list.run_section("rename")
    assert read(path).index("\\section{Intro}") < read(path).index("\\slide{aaa-Front}")


def test_duplicate_occurrence_keeps_focus_selection_and_preview_target(make_list):
    from slidemage.ai.tools.slidemage import slide_target

    step_three = "\\slidestep{aaa-EN-One}{3}\n"
    body = "\\slidestep{aaa-EN-One}{1}\n\\slide{bbb-EN-Two}\n" + step_three * 2
    listing, window, _ = make_list(body)
    state = window.state
    focus(listing, "aaa", 2)
    last = listing.tree.data_of(item_of(listing, "aaa", 2))
    item_of(listing, "bbb").setSelected(True)
    assert state.focused_occurrence == last.key
    target = slide_target(window.project, state.deck, window.project.slides_dir / "aaa-EN-One-current.tex",
                          "instructor", "EN", occurrence_key=last.key)
    assert (target.steps, target.frame_number) == ("3", 4)
    listing.rebuild()
    assert state.focused_occurrence == last.key
    assert listing.tree.data_of(listing.tree.currentItem()).key == last.key

    def update(text):
        state.set_deck(replace(state.deck, text=text, chapters=parse_chapters(text)))
        listing.rebuild()
        return [(row.call.id, row.position) for row in listing.tree.selected_rows()]

    text = state.deck.text.replace(body, "\\slide{new-Top}\n" + body)
    assert update(text) == [("bbb", 3), ("aaa", 5)]
    assert update(text.replace("\\slide{bbb-EN-Two}\n", "")) == [("aaa", 4)]


def test_rebuild_keeps_thumbnails_across_section_edits_but_not_deck_view_or_language_changes(make_list, monkeypatch):
    listing, window, path = make_list("\\slide{abc-EN-One}\n\\conditionalslide[instructor]{def-EN-Two}\n")
    state = window.state
    listing._background_thumbnails = True
    queued = Mock()
    monkeypatch.setattr(listing, "_queue_preview_images", queued)
    thumbnails = {"abc": (path.with_name("abc.png"), True, False, "verified"),
                  "def": (path.with_name("def.png"), False, True, "stale")}

    def patch(row):
        image, verified, stale, note = thumbnails[row.call.id]
        return replace(row, thumbnail=image, thumbnail_verified=verified, stale_preview=stale, thumbnail_note=note)

    def add_thumbnails():
        listing._apply_preview_rows([replace(section, rows=[patch(row) for row in section.rows])
                                     for section in listing._outline])

    def thumbnail_state():
        return {row.call.id: (row.thumbnail, row.thumbnail_verified, row.stale_preview, row.thumbnail_note)
                for row in listing.rows()}

    add_thumbnails()
    monkeypatch.setattr(slide_list_module.QInputDialog, "getText", lambda *a, **k: ("Intro", True))
    listing._add_section(row_of(listing, "def").call.line_start)
    queued.assert_called_once()
    assert thumbnail_state() == thumbnails
    assert row_of(listing, "def") is state.current_outline().row("def")

    for change in (lambda: state.set_deck(replace(state.deck, path=path.with_name("other.tex"))),
                   lambda: state.set_view("during-course"), lambda: state.set_language("DE")):
        add_thumbnails()
        queued.reset_mock()
        change()
        queued.assert_called_once()
        assert thumbnail_state() == dict.fromkeys(thumbnails, (None, False, False, ""))
    outline = state.current_outline()
    assert (outline.view, outline.language) == ("during-course", "DE") and outline.row("def").hidden


def test_thumbnail_refresh_keeps_tree_selection_and_updates_the_shared_outline(make_list, monkeypatch):
    listing, window, _ = make_list("\\slide{abc-EN-One}\n\\slide{def-EN-Two}\n\\slide{abc-EN-One}\n")
    state = window.state
    outline = state.current_outline()
    assert outline.sections is listing._outline and outline.row("abc", outline.rows[2].key) is outline.rows[2]
    focus(listing, "abc")
    select(listing, "abc", "def")
    tree = listing.tree
    current, selected = tree.currentItem(), tree.selectedItems()
    source = window.project.slides_dir / "abc-EN-One-current.tex"
    images = Mock(side_effect=lambda _ctx, _deck, outline, view, _language, **_kwargs: [
        replace(section, rows=[replace(row, thumbnail_note=view) for row in section.rows])
        for section in outline
    ])
    monkeypatch.setattr(slide_list_module.preview_thumbnails, "for_outline", images)
    listing.preview_source_changed(source)
    listing._refresh_preview_rows()
    assert tree.currentItem() is current and tree.selectedItems() == selected
    assert images.call_args.kwargs["paths"] == {source}
    published = state.current_outline()
    assert published.row("abc").thumbnail_note == "instructor" and published.links is outline.links
    assert published.instructor_frames == outline.instructor_frames

    listing.preview_source_changed(source)
    state.set_view("during-course")
    assert images.call_args.args[3] == "during-course" and images.call_args.kwargs["paths"] is None
    assert not listing._thumbnail_timer.isActive()
    state.drop_outline()
    listing._set_outline(listing._outline)
    assert state.outline is None


@pytest.mark.parametrize("full", [False, True], ids=["targeted", "full"])
def test_async_thumbnail_refresh_coalesces_edits_without_narrowing_a_full_pass(make_list, monkeypatch, full):
    body = "".join(f"\\slide{{a{index:02d}-EN-Slide{index}}}\n" for index in range(80))
    listing, window, _ = make_list(body)
    listing._background_thumbnails = True
    a, b = (window.project.slides_dir / f"a{i:02d}-EN-Slide{i}-current.tex" for i in range(2))
    text = "\\begin{standardframe}{Whole}\n\\end{standardframe}\n"
    window.centre = SimpleNamespace(source=SimpleNamespace(buffer=lambda path: text if path == a else None))
    assert listing._thumbnail_source(a) == text and listing._thumbnail_source(b) is None
    started, release = Event(), Event()
    calls = []

    def images(ctx, _deck, outline, _view, _language, **kwargs):
        paths = kwargs["paths"]
        calls.append(paths)
        if len(calls) == 1:
            started.set()
            assert release.wait(3)
        return [replace(section, rows=[
            replace(row, thumbnail_note="updated")
            if paths is None or (ctx.slides_dir / row.call.source_filename).resolve() in paths else row
            for row in section.rows]) for section in outline]

    monkeypatch.setattr(slide_list_module.preview_thumbnails, "for_outline", images)
    if full:
        listing._queue_preview_images(listing._outline)
    else:
        listing.preview_source_changed(a)
        listing._refresh_preview_rows()
    assert started.wait(2)
    ticked = Event()
    QTimer.singleShot(0, ticked.set)
    wait_until(ticked.is_set, seconds=2)
    if full:
        listing.preview_source_changed(a)
    listing.preview_source_changed(b)
    listing._refresh_preview_rows()
    release.set()
    wait_until(lambda: len(calls) >= 2 and listing._thumbnail_future is None)
    assert calls == ([None, None] if full else [{a.resolve()}, {a.resolve(), b.resolve()}])
    for slide in ("a00", "a01", "a79") if full else ("a00", "a01"):
        assert row_of(listing, slide).thumbnail_note == "updated"


def test_async_thumbnail_rejects_same_mtime_external_source_edit(make_list, monkeypatch):
    import hashlib
    import os

    listing, window, _ = make_list('\\slide{abc-EN-One}\n')
    listing._background_thumbnails = True
    source = window.project.slides_dir / 'abc-EN-One-current.tex'
    source.parent.mkdir(exist_ok=True)
    source.write_text('FIRST')
    started, release = Event(), Event()
    calls = []

    def images(_ctx, _deck, outline, _view, _language, **kwargs):
        text = source.read_text()
        kwargs['revision_sink'][source.resolve()] = hashlib.sha256(text.encode()).hexdigest()
        calls.append(text)
        if len(calls) == 1:
            started.set()
            assert release.wait(3)
        return [replace(section, rows=[replace(row, thumbnail_note=text) for row in section.rows])
                for section in outline]

    monkeypatch.setattr(slide_list_module.preview_thumbnails, 'for_outline', images)
    listing.preview_source_changed(source)
    listing._refresh_preview_rows()
    assert started.wait(2)
    before = source.stat()
    source.write_text('OTHER')
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    release.set()
    wait_until(lambda: len(calls) >= 2 and listing._thumbnail_future is None)
    assert calls == ['FIRST', 'OTHER']
    assert row_of(listing, 'abc').thumbnail_note == 'OTHER'


def test_click_opens_in_preview_ctrl_click_only_selects_and_enter_opens_source(make_list, monkeypatch):
    slide_list, window, _path = make_list("\\slide{aaa-One}\n\\slide{bbb-Two}\n")
    modifiers = Qt.KeyboardModifier.NoModifier
    monkeypatch.setattr(QGuiApplication, "keyboardModifiers", staticmethod(lambda: modifiers))
    focus(slide_list, "aaa")
    slide_list.tree.itemClicked.emit(item_of(slide_list, "aaa"), 0)
    modifiers = Qt.KeyboardModifier.ControlModifier
    slide_list.tree.itemClicked.emit(item_of(slide_list, "bbb"), 0)
    assert [p.name for p in window.opened] == ["aaa-One-current.tex"]
    key(slide_list, Qt.Key.Key_Return)
    assert [p.name for p in window.opened] == ["aaa-One-current.tex"] * 2
    assert window.open_kwargs == [{"keep_mode": True}, {"keep_mode": False}]
    slide_list.tree._extends_selection = False
    slide_list.tree._on_clicked(None, 0)  # Qt can lose the item between press and release
    assert len(window.opened) == 2


def test_remove_section_can_remove_its_slides_or_keep_slides_when_removing_all_headings(make_list, monkeypatch):
    slide_list, _window, path = make_list(FRONT_AND_SECTIONS)
    choose_section(slide_list, "Two")
    asked = removing(monkeypatch, remove_section.WITH_SLIDES)
    slide_list.run_section("remove_section")
    assert asked == [("Two", 2, 3)]
    assert deck_lines(path) == ["\\slide{aaa-Front}", "\\section{One}", "\\slide{bbb-One}", "\\section{Empty}"]
    assert ids(slide_list) == ["aaa", "bbb"]
    choose_section(slide_list, "One")
    removing(monkeypatch, remove_section.ALL_SECTIONS)
    slide_list.run_section("remove_section")
    assert deck_lines(path) == ["\\slide{aaa-Front}", "\\slide{bbb-One}"]


def test_the_placeholder_offers_open_in_each_deck_that_uses_the_slide(make_list):
    slide_list, window, _path = make_list("\\section{S}\n\\slide{a}\n")
    first, second = window.state.deck, replace(window.state.deck, name="lecture")
    slide_list.resize(300, 500)
    slide_list.show()
    geometry = slide_list.stack.geometry()
    asked = []
    slide_list.open_in_requested.connect(asked.append)
    slide_list.show_placeholder("abx is not in an open deck.", "Back to course", (first, second), "")
    assert slide_list.stack.currentWidget() is slide_list.placeholder and not slide_list.find.isEnabled()
    assert len(slide_list.placeholder_deck_buttons) == 2 and slide_list.stack.geometry() == geometry
    backed = []
    slide_list.back_requested.connect(lambda: backed.append(True))
    slide_list.placeholder_back.click()
    assert backed == [True]
    slide_list.placeholder_deck_buttons[1].click()
    assert asked == [second]
    slide_list.show_placeholder("abx is not in an open deck.", "", (), "No deck uses this slide yet.")
    assert slide_list.placeholder_deck_buttons == [] and not slide_list.placeholder_note.isHidden()
    slide_list.show_placeholder(None)
    assert slide_list.stack.currentWidget() is slide_list.tree and slide_list.find.isEnabled()


def test_a_slide_is_marked_for_review_in_its_deck_from_the_menu(make_list, monkeypatch):
    slide_list, _, path = make_list("\\slide{aaa-EN-One}\n\\omitslide{bbb-EN-Two}\n\\slide{ccc-EN-Three}\n")
    focus(slide_list, "aaa")
    slide_list._on_menu_chosen("slide:review_mark")
    assert read(path).splitlines()[2] == "\\SMReview{\\slide{aaa-EN-One}}"
    row = row_of(slide_list, "aaa")
    assert row.review and "review" in meta_text(row, "EN")
    slide_list.tree.grab()  # paint the review watermark

    monkeypatch.setattr(slide_list_module.QInputDialog, "getText", lambda *a, **k: ("ask Anna", True))
    select(slide_list, "aaa", "bbb")
    slide_list._on_menu_chosen("review:note")
    assert read(path).splitlines()[2:4] == ["\\SMReview[ask Anna]{\\slide{aaa-EN-One}}",
                                            "\\SMReview[ask Anna]{\\omitslide{bbb-EN-Two}}"]
    assert row_of(slide_list, "bbb").review_note == "ask Anna"

    select(slide_list, "aaa", "bbb")
    slide_list._on_menu_chosen("slide:review_mark")
    assert "SMReview" not in read(path)
    monkeypatch.setattr(slide_list_module.QInputDialog, "getText", lambda *a, **k: ("50% sure", True))
    focus(slide_list, "ccc")
    slide_list._on_menu_chosen("review:note")
    assert "plain text" in make_list.errors[-1] and "SMReview" not in read(path)
