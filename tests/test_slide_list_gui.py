"""The slide list (left column): what it shows and every edit it can make to the
deck file -- through keys, drops, the context menu and the bulk bar."""
from __future__ import annotations

from dataclasses import replace
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView, QApplication, QLineEdit, QWidget

from slidemage import deck_editor, deck_outline
from slidemage.archive import _read
from slidemage.deck_scan import Deck, _parse_chapters
from slidemage.ui.kit import kit_qss
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.kit.widgets import Toast
from slidemage.ui.workspace import slide_list as slide_list_module
from slidemage.ui.workspace.actions import build_registry
from slidemage.ui.workspace.slide_list import ABOVE_ITEM, BELOW_ITEM, ON_ITEM, SlideList
from slidemage.ui.workspace.slide_tree import meta_text, tooltip_text, variant_label
from slidemage.ui.workspace.state import WorkspaceState

HEAD = "\\documentclass{beamer}\n\\begin{document}\n"
TAIL = "\\end{document}\n"


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class FakeWindow:
    """What the list needs of the main window: the rescan after an edit, the dialogs, and
    the command registry its context menus show."""

    def __init__(self, state):
        self.state = state
        self.commands = build_registry()
        self.compiling = False
        self.list = None
        self.added = []
        self.opened = []
        self.compiled = []
        self.edits = []

    def after_deck_edit(self, path, summary, previous_text=None):
        text = _read(path)
        self.state.set_deck(replace(self.state.deck, text=text, chapters=_parse_chapters(text)))
        self.list.rebuild()
        self.list.deck_edited(path, summary, previous_text)
        self.edits.append(summary)

    def open_add_slide_dialog(self, deck, insert_at, indent):
        self.added.append((insert_at, indent))

    def open_slide_editor(self, path, **_kwargs):
        self.opened.append(path)

    def open_images_for_slide(self, id_slug):
        self.opened.append(("images", id_slug))

    @property
    def slide_list(self):
        return self.list

    def _compile_slides(self, slide_ids):
        self.compiled.append(slide_ids)


@pytest.fixture
def make_list(tmp_path, qapp, monkeypatch):
    keep = []
    errors = []
    monkeypatch.setattr(slide_list_module.QMessageBox, "critical", lambda *args: errors.append(args[2]))

    def make(body, newline="\n", tags=()):
        text = (HEAD + body + TAIL).replace("\n", newline)
        path = tmp_path / "course.tex"
        path.write_bytes(text.encode("utf-8"))
        deck = Deck(
            name="course", path=path, archived=False, text=text, supports_version=True,
            uses_biblatex=False, preamble_end=text.index("\\begin{document}") + len("\\begin{document}"),
            chapters=_parse_chapters(text), output_folders={}, tags=list(tags))
        state = WorkspaceState()
        window = FakeWindow(state)
        host = QWidget()
        window.list = SlideList(window, state, ThemeManager(), Toast(host))
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
    return [line for line in _read(path).splitlines() if line.startswith(("\\slide", "\\section", "\\omit", "\\cond"))]


def key(slide_list, key_code, modifier=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(slide_list.tree, key_code, modifier)


FRONT_AND_SECTIONS = (
    "\\slide{aaa-Front}\n\\section{One}\n\\slide{bbb-One}\n\\section{Empty}\n"
    "\\section{Two}\n\\slide{ccc-Two}\n\\slide{ddd-Two}\n")


# -- what it shows -------------------------------------------------------------------

def test_sections_and_slides_are_listed_in_deck_order(make_list):
    slide_list, _window, _path = make_list(FRONT_AND_SECTIONS)
    assert [(slide_list.tree.data_of(h).title, h.childCount()) for h in slide_list.tree.section_items()] == [
        (deck_outline.UNSECTIONED, 1), ("One", 1), ("Empty", 0), ("Two", 2)]
    assert ids(slide_list) == ["aaa", "bbb", "ccc", "ddd"]
    assert slide_list.note.isHidden()
    assert not slide_list.add_bar.isHidden() and slide_list.bulk_bar.isHidden()


def test_an_empty_deck_says_so_and_a_missing_deck_disables_adding(make_list):
    slide_list, window, _path = make_list("")
    assert slide_list.note.text() == "This deck has no slides yet."
    assert slide_list.add_bar.isEnabled()
    window.state.set_deck(None)
    assert slide_list.tree.topLevelItemCount() == 0 and not slide_list.add_bar.isEnabled()
    assert slide_list.note.isHidden()


def test_a_test_deck_has_no_slide_list(make_list):
    slide_list, _window, _path = make_list("\\slide{aaa-One}\n", tags=["test"])
    assert slide_list.deck is None and slide_list.tree.topLevelItemCount() == 0


def test_rows_say_what_is_worth_a_glance(make_list):
    slide_list, window, _path = make_list(
        "\\slide{aaa-EN-One}\n\\slidefinal{bbb-EN-Two}\n\\conditionalslide[instructor]{ccc-EN-Three}\n"
        "\\slidestep{ddd-EN-Four}[instructor,after-course]{1,2}\n\\slideversion{eee-EN-Five}{1-0-0}\n"
        "\\omitslide{fff-EN-Six}\n")
    rows = [slide_list.tree.data_of(i) for i in slide_list.tree.slide_items()]
    assert [variant_label(r.call) for r in rows] == [
        "", "final", "I", "step 1,2 · I·A", "v1-0-0", "omit"]
    window.state.set_view("during-course")
    rows = [slide_list.tree.data_of(i) for i in slide_list.tree.slide_items()]
    assert [r.hidden for r in rows] == [False, False, True, True, False, True]
    assert "hidden" in meta_text(rows[2], "EN") and meta_text(rows[0], "EN").startswith("1 · aaa [EN]")
    assert "Not typeset in During course" in tooltip_text(rows[2], "During course", "EN")
    window.state.set_language("DE")
    rows = [slide_list.tree.data_of(i) for i in slide_list.tree.slide_items()]
    assert all(r.missing_translation for r in rows) and "no DE" in meta_text(rows[0], "DE")


def test_a_slide_that_shares_its_line_is_locked(make_list):
    slide_list, _window, path = make_list("\\slide{aaa-A} \\slide{bbb-B}\n\\section{S} % a note\n\\section{T} \\slide{ccc-C}\n")
    first = item_of(slide_list, "aaa")
    assert not first.flags() & Qt.ItemFlag.ItemIsDragEnabled
    assert head_of(slide_list, "S").flags() & Qt.ItemFlag.ItemIsEditable          # a comment after it is fine
    locked = head_of(slide_list, "T")
    assert not locked.flags() & (Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsDragEnabled)
    before = _read(path)
    slide_list._remove([slide_list.tree.data_of(first)])
    assert "shares its line" in make_list.errors[-1] and _read(path) == before
    focus(slide_list, "aaa")
    menu = slide_list._slide_menu()
    assert not _entry(menu, "slide:remove")[6] and not _entry(menu, "variant:omitslide")[6]
    assert _entry(menu, "slide:open")[6]                # reading it is fine
    choose_section(slide_list, "T")
    section_menu = slide_list._section_menu()
    assert not _entry(section_menu, "section:rename")[6] and not _entry(section_menu, "section:remove_section")[6]


def choose_section(slide_list, title):
    slide_list.tree.setCurrentItem(head_of(slide_list, title), 0,
                                   slide_list_module.QItemSelectionModel.SelectionFlag.NoUpdate)


def _entry(menu, key_):
    return next(e for e in menu._entries if e[0] == "item" and e[1] == key_)


# -- find, focus and selection -----------------------------------------------------------

def test_the_find_box_filters_by_id_or_title_and_enter_goes_to_the_first_match(make_list):
    slide_list, window, _path = make_list(FRONT_AND_SECTIONS)
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
    slide_list.tree.itemClicked.emit(two, 0)                # a click closes the section
    assert not two.isExpanded()
    window.state.set_focused_slide("ccc")
    assert two.isExpanded() and "Two" not in slide_list.tree.collapsed
    assert slide_list.tree.currentItem() is item_of(slide_list, "ccc")
    slide_list.find.setText("aaa")                          # the focused slide itself is hidden
    window.state.set_focused_slide(None)
    window.state.set_focused_slide("ccc")
    assert slide_list.find.text() == "" and not item_of(slide_list, "ccc").isHidden()


def test_filtering_opens_closed_sections_and_clearing_closes_them_again(make_list):
    slide_list, _window, _path = make_list(FRONT_AND_SECTIONS)
    two = head_of(slide_list, "Two")
    slide_list.tree.itemClicked.emit(two, 0)                # a click closes the section
    assert not two.isExpanded() and slide_list.tree.collapsed == {"Two"}
    slide_list.find.setText("ccc")
    assert two.isExpanded()
    slide_list.find.setText("")
    assert not two.isExpanded()
    slide_list.rebuild()
    assert not head_of(slide_list, "Two").isExpanded()      # an edit elsewhere leaves it closed


def test_focus_and_selection_go_through_the_workspace_state(make_list):
    slide_list, window, _path = make_list(FRONT_AND_SECTIONS)
    focus(slide_list, "ccc")
    assert window.state.focused_slide == "ccc" and window.state.selection == ("ccc",)
    window.state.set_focused_slide("bbb")                    # e.g. a slide opened in the source editor
    assert slide_list.tree.data_of(slide_list.tree.currentItem()).call.id == "bbb"
    select(slide_list, "aaa", "ddd")
    assert window.state.selection == ("aaa", "ddd")
    assert not slide_list.bulk_bar.isHidden() and slide_list.add_bar.isHidden()
    assert slide_list.bulk_label.text() == "2 slides selected"
    slide_list.tree.clearSelection()
    assert slide_list.bulk_bar.isHidden() and window.state.selection == ()
    slide_list._select_all()
    assert slide_list.bulk_label.text() == "4 slides selected"


def test_selected_slides_stay_selected_when_the_deck_changes(make_list):
    body = "\\slide{aaa-First}\n\\slide{bbb-Second}\n\\slidestep{ccc-Step}[instructor]{1}\n" \
           "\\slidestep{ccc-Step}[instructor]{1}\n\\slide{ddd-Last}\n"
    slide_list, window, _path = make_list(body)

    def selected():
        return [(r.call.id, r.position) for r in slide_list.tree.selected_rows()]

    items = slide_list.tree.slide_items()
    items[1].setSelected(True)                       # bbb
    items[3].setSelected(True)                       # the second of the two identical ccc steps
    assert selected() == [("bbb", 2), ("ccc", 4)]
    text = window.state.deck.text.replace("\\slide{aaa-First}\n", "\\slide{new-Top}\n\\slide{aaa-First}\n")
    window.state.set_deck(replace(window.state.deck, text=text, chapters=_parse_chapters(text)))
    slide_list.rebuild()                             # a slide was added above: every position moves
    assert selected() == [("bbb", 3), ("ccc", 5)]
    text = text.replace("\\slide{ddd-Last}\n", "").replace("\\slide{bbb-Second}\n", "")
    window.state.set_deck(replace(window.state.deck, text=text, chapters=_parse_chapters(text)))
    slide_list.rebuild()
    assert selected() == [("ccc", 4)]                # removed slides drop out


def test_removing_the_focused_slide_moves_the_focus_to_the_next_one(make_list):
    slide_list, window, _path = make_list(FRONT_AND_SECTIONS)
    focus(slide_list, "bbb")
    key(slide_list, Qt.Key.Key_Delete)
    assert ids(slide_list) == ["aaa", "ccc", "ddd"] and window.state.focused_slide == "ccc"


# -- keys --------------------------------------------------------------------------------

def test_arrow_keys_move_the_focus_and_enter_or_a_double_click_open_the_source(make_list):
    slide_list, window, _path = make_list("\\slide{aaa-One}\n\\slide{bbb-Two}\n")
    focus(slide_list, "aaa")
    key(slide_list, Qt.Key.Key_Down)
    assert window.state.focused_slide == "bbb"
    key(slide_list, Qt.Key.Key_Return)
    slide_list.tree.itemDoubleClicked.emit(item_of(slide_list, "aaa"), 0)
    assert [p.name for p in window.opened] == ["bbb-Two-current.tex", "aaa-One-current.tex"]


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
    before = _read(path)
    key(slide_list, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier)    # nothing above the first slide
    assert _read(path) == before
    key(slide_list, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)
    assert deck_lines(path)[:2] == ["\\section{One}", "\\slide{aaa-Front}"]
    assert slide_list.tree.data_of(slide_list.tree.currentItem()).call.id == "aaa"     # the focus follows it


@pytest.mark.parametrize("direction", ["up", "down"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_alt_arrows_move_a_section_with_all_its_slides(make_list, direction, newline):
    one = "\\section{One}\n\\slide{aaa-First}\n\\slide{bbb-Second}\n"
    two = "\\section{Two}\n% Section note\n\\slide{ccc-Third}\n\\slide{ddd-Fourth}\n"
    three = "\\section{Three}\n\\slide{eee-Fifth}\n\\slide{fff-Sixth}\n"
    slide_list, _window, path = make_list("\\slide{zzz-Front}\n" + one + two + three, newline)
    arrow = Qt.Key.Key_Up if direction == "up" else Qt.Key.Key_Down
    for title in ("One", "Three"):           # nothing beyond the first and the last
        slide_list.tree.setCurrentItem(head_of(slide_list, title))
        before = path.read_bytes()
        key(slide_list, Qt.Key.Key_Up if title == "One" else Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)
        assert path.read_bytes() == before
    slide_list.tree.setCurrentItem(head_of(slide_list, "Two"))
    key(slide_list, arrow, Qt.KeyboardModifier.AltModifier)
    blocks = two + one + three if direction == "up" else one + three + two
    expected = (HEAD + "\\slide{zzz-Front}\n" + blocks + TAIL).replace("\n", newline)
    assert path.read_bytes() == expected.encode("utf-8")


def test_a_section_moves_up_with_its_legacy_block(make_list):
    body = ("\\section{Before}\n%% Block: legacy\n%%\n\\slide{aaa-First}\n\\slide{bbb-Second}\n"
            "%% End block: legacy\n%%\n\\section{After}\n")
    slide_list, _window, path = make_list(body)
    choose_section(slide_list, "After")
    menu = slide_list._section_menu()
    assert _entry(menu, "section:section_up")[6] and not _entry(menu, "section:section_down")[6]
    slide_list.run_section("section_up")
    assert _read(path) == HEAD + "\\section{After}\n" + body.replace("\\section{After}\n", "") + TAIL


def test_delete_removes_the_slides_and_undo_brings_them_back(make_list):
    slide_list, window, path = make_list(FRONT_AND_SECTIONS)
    original = _read(path)
    select(slide_list, "bbb", "ddd")
    key(slide_list, Qt.Key.Key_Delete)
    assert deck_lines(path) == ["\\slide{aaa-Front}", "\\section{One}", "\\section{Empty}",
                                "\\section{Two}", "\\slide{ccc-Two}"]
    assert not slide_list.toast.isHidden()
    slide_list.toast.action_triggered.emit("undo")          # the toast's Undo button
    assert _read(path) == original and ids(slide_list) == ["aaa", "bbb", "ccc", "ddd"]
    assert window.edits[-1] == "Undid last change to course"
    slide_list.undo()                                       # nothing left to undo
    assert _read(path) == original


def test_undo_goes_back_one_edit_at_a_time_and_refuses_after_an_outside_change(make_list):
    slide_list, _window, path = make_list(FRONT_AND_SECTIONS)
    original = _read(path)
    slide_list._remove([slide_list.tree.data_of(item_of(slide_list, "aaa"))])
    slide_list._remove([slide_list.tree.data_of(item_of(slide_list, "bbb"))])
    slide_list.undo()
    assert "\\slide{bbb-One}" in _read(path) and "\\slide{aaa-Front}" not in _read(path)
    path.write_text(_read(path) + "% edited elsewhere\n", encoding="utf-8")
    slide_list.deck.text = "stale"                          # the list is behind the file
    slide_list.undo()
    assert "changed on disk" in make_list.errors[-1]
    slide_list.deck.text = _read(path)
    slide_list.undo()                                       # the refused step is still there
    assert _read(path) == original


def test_ctrl_z_undoes(make_list, qapp):
    slide_list, _window, path = make_list(FRONT_AND_SECTIONS)
    original = _read(path)
    slide_list.show()
    slide_list.activateWindow()
    qapp.processEvents()
    slide_list._remove([slide_list.tree.data_of(item_of(slide_list, "aaa"))])
    slide_list.tree.setFocus()
    key(slide_list, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert _read(path) == original
    slide_list.hide()


# -- the bulk bar ------------------------------------------------------------------------

def test_the_bulk_bar_hides_and_shows_the_slides_in_the_current_view(make_list):
    slide_list, window, path = make_list(FRONT_AND_SECTIONS)
    select(slide_list, "bbb", "ccc")
    assert slide_list.bulk_visibility_button.text() == "Hide in Instructor"
    slide_list.bulk_visibility_button.click()
    assert "\\conditionalslide[during-course,after-course]{bbb-One}" in _read(path)
    assert "\\conditionalslide[during-course,after-course]{ccc-Two}" in _read(path)
    assert [slide_list.tree.data_of(i).hidden for i in slide_list.tree.slide_items()] == [False, True, True, False]
    select(slide_list, "bbb", "ccc")
    assert slide_list.bulk_visibility_button.text() == "Show in Instructor"
    slide_list.bulk_visibility_button.click()
    assert "\\slide{bbb-One}" in _read(path) and "\\slide{ccc-Two}" in _read(path)     # plain again
    window.state.set_view("after-course")
    select(slide_list, "aaa", "bbb")
    assert slide_list.bulk_visibility_button.text() == "Hide in After course"


def test_the_bulk_bar_removes_in_one_edit_and_hands_over_the_slide_ids_to_compile(make_list):
    slide_list, window, path = make_list(
        "\\slide{aaa-A}\n\\slide{bbb-B}\n\\slide{ccc-C}\n\\slide{ddd-D}\n")
    select(slide_list, "ddd", "aaa")
    window.commands.run("compile:slides", window)
    assert [sorted(ids) for ids in window.compiled] == [["aaa", "ddd"]]
    select(slide_list, "aaa", "ccc")
    window.edits.clear()
    slide_list._remove(slide_list.tree.selected_rows())
    assert deck_lines(path) == ["\\slide{bbb-B}", "\\slide{ddd-D}"]
    assert len(window.edits) == 1                     # one edit, one undo step


# -- the context menu --------------------------------------------------------------------

def keys_of(menu):
    return [e[1] for e in menu._entries if e[0] == "item"]


def test_the_slide_menu_offers_every_way_to_call_a_slide(make_list, monkeypatch, tmp_path):
    slides = tmp_path / "slides"
    slides.mkdir()
    (slides / "aaa-First-v1-0-0.tex").write_text("x", encoding="utf-8")
    monkeypatch.setattr(deck_editor, "SLIDES_DIR", slides)
    slide_list, window, path = make_list("\\slide{aaa-First}\n\\slide{bbb-Second}\n")
    row = slide_list.tree.data_of(item_of(slide_list, "aaa"))
    focus(slide_list, "aaa")
    menu = slide_list._slide_menu()
    assert keys_of(menu) == [
        "slide:open", "slide:preview", "slide:images",
        "variant:slide", "variant:slidefinal", "variant:omitslide", "variant:conditionalslide",
        "variant:slidestep", "variant:slideversion:1-0-0", "variant:omitslideversion:1-0-0",
        "slide:visible:instructor", "slide:visible:during-course", "slide:visible:after-course",
        "slide:before", "slide:after", "slide:section_before", "move:0", "slide:remove"]
    assert _entry(menu, "variant:slide")[4] == "check"             # the current call is ticked
    for macro, expected in (
            ("slidefinal", "\\slidefinal{aaa-First}"), ("omitslide", "\\omitslide{aaa-First}"),
            ("conditionalslide", "\\conditionalslide[instructor,during-course,after-course]{aaa-First}"),
            ("slideversion:1-0-0", "\\slideversion{aaa-First}{1-0-0}"), ("slide", "\\slide{aaa-First}")):
        slide_list._run(f"variant:{macro}", [slide_list.tree.data_of(item_of(slide_list, "aaa"))])
        assert deck_lines(path)[0] == expected
    monkeypatch.setattr(slide_list_module.QInputDialog, "getText", lambda *a, **k: ("1,2", True))
    slide_list._run("variant:slidestep", [slide_list.tree.data_of(item_of(slide_list, "aaa"))])
    assert deck_lines(path)[0] == "\\slidestep{aaa-First}[instructor,during-course,after-course]{1,2}"
    monkeypatch.setattr(slide_list_module.QInputDialog, "getText", lambda *a, **k: ("x", True))
    slide_list._run("variant:slidestep", [slide_list.tree.data_of(item_of(slide_list, "aaa"))])
    assert "not a valid step list" in make_list.errors[-1]
    assert window.edits[0] == "Changed aaa-First in course: \\slide -> \\slidefinal"


def test_the_slide_menu_hides_a_slide_in_one_view_and_opens_the_other_tools(make_list, monkeypatch):
    slide_list, window, path = make_list("\\slide{aaa-First}\n\\slide{bbb-Second}\n")
    focus(slide_list, "aaa")
    run = lambda command: window.commands.run(command, window)   # noqa: E731 -- what a menu entry does
    menu = slide_list._slide_menu()
    assert [e[2] for e in menu._entries if e[0] == "item" and e[1].startswith("slide:visible")] == [
        "Hide in Instructor", "Hide in During course", "Hide in After course"]
    run("slide:visible:during-course")
    assert deck_lines(path)[0] == "\\conditionalslide[instructor,after-course]{aaa-First}"
    focus(slide_list, "aaa")
    assert [e[2] for e in slide_list._slide_menu()._entries if e[0] == "item" and e[1] == "slide:visible:during-course"] \
        == ["Show in During course"]
    run("slide:preview")
    assert (slide_list.state.focused_slide, slide_list.state.mode) == ("aaa", "preview")
    slide_list.state.set_mode("details")
    run("slide:preview")
    assert slide_list.state.mode == "preview"
    run("slide:images")
    run("slide:open")
    assert window.opened[0] == ("images", "aaa-First")
    assert window.opened[1].name == "aaa-First-current.tex"
    # adding next to a slide, or a section before it
    row = slide_list.tree.data_of(item_of(slide_list, "aaa"))
    run("slide:before")
    run("slide:after")
    assert window.added == [(row.call.line_start, ""), (row.call.line_end, "")]
    monkeypatch.setattr(slide_list_module.QInputDialog, "getText", lambda *a, **k: ("Intro", True))
    run("slide:section_before")
    assert deck_lines(path)[0] == "\\section{Intro}"


def test_the_bulk_menu_moves_slides_into_a_section(make_list):
    slide_list, window, path = make_list(FRONT_AND_SECTIONS)
    select(slide_list, "aaa", "ddd")
    rows = slide_list.tree.selected_rows()
    menu = slide_list._bulk_menu()
    assert keys_of(menu) == [
        "slide:visible:instructor", "slide:visible:during-course", "slide:visible:after-course",
        "move:0", "move:1", "move:2", "move:3", "compile:slides", "slide:clear", "slide:remove"]
    assert _entry(menu, "slide:remove")[2] == "Remove 2 from the deck"
    slide_list._on_menu_chosen("move:2")               # into the empty section
    assert deck_lines(path) == ["\\section{One}", "\\slide{bbb-One}", "\\section{Empty}", "\\slide{aaa-Front}",
                                "\\slide{ddd-Two}", "\\section{Two}", "\\slide{ccc-Two}"]
    assert rows
    select(slide_list, "bbb", "ccc")
    slide_list._on_menu_chosen("slide:clear")
    assert slide_list.tree.selected_rows() == []


# -- drag and drop -----------------------------------------------------------------------

def row_of(slide_list, slide_id):
    return slide_list.tree.data_of(item_of(slide_list, slide_id))


def section_of(slide_list, title):
    return slide_list.tree.data_of(head_of(slide_list, title))


def test_dropping_a_slide_above_or_below_another_moves_it_there(make_list):
    slide_list, _window, path = make_list(FRONT_AND_SECTIONS)
    slide_list._on_moved([row_of(slide_list, "ddd")], row_of(slide_list, "aaa"), ABOVE_ITEM)
    assert deck_lines(path)[:2] == ["\\slide{ddd-Two}", "\\slide{aaa-Front}"]
    slide_list._on_moved([row_of(slide_list, "ddd")], row_of(slide_list, "bbb"), BELOW_ITEM)
    assert deck_lines(path) == ["\\slide{aaa-Front}", "\\section{One}", "\\slide{bbb-One}", "\\slide{ddd-Two}",
                                "\\section{Empty}", "\\section{Two}", "\\slide{ccc-Two}"]


def test_dropping_on_a_section_heading_puts_the_slide_in_that_section(make_list):
    slide_list, _window, path = make_list(FRONT_AND_SECTIONS)
    slide_list._on_moved([row_of(slide_list, "aaa")], section_of(slide_list, "Two"), ON_ITEM)        # its end
    assert deck_lines(path)[-3:] == ["\\slide{ccc-Two}", "\\slide{ddd-Two}", "\\slide{aaa-Front}"]
    slide_list._on_moved([row_of(slide_list, "bbb")], section_of(slide_list, "Empty"), ON_ITEM)      # an empty one
    assert deck_lines(path)[:3] == ["\\section{One}", "\\section{Empty}", "\\slide{bbb-One}"]
    slide_list._on_moved([row_of(slide_list, "ddd")], section_of(slide_list, "Two"), BELOW_ITEM)     # its top
    assert deck_lines(path)[-4:] == ["\\section{Two}", "\\slide{ddd-Two}", "\\slide{ccc-Two}", "\\slide{aaa-Front}"]
    slide_list._on_moved([row_of(slide_list, "ccc")], section_of(slide_list, "Empty"), ABOVE_ITEM)   # the end of the one above
    assert deck_lines(path)[:4] == ["\\section{One}", "\\slide{ccc-Two}", "\\section{Empty}", "\\slide{bbb-One}"]


def test_a_drop_moves_all_selected_slides_and_a_queued_signal_gets_there(make_list, qapp):
    slide_list, _window, path = make_list(FRONT_AND_SECTIONS)
    select(slide_list, "aaa", "ccc")
    slide_list.tree.moved.emit(slide_list.tree.selected_rows(), row_of(slide_list, "ddd"), BELOW_ITEM)
    assert len(deck_lines(path)) == 7 and deck_lines(path)[0] == "\\slide{aaa-Front}"     # queued: not yet
    qapp.processEvents()
    assert deck_lines(path) == ["\\section{One}", "\\slide{bbb-One}", "\\section{Empty}", "\\section{Two}",
                                "\\slide{ddd-Two}", "\\slide{aaa-Front}", "\\slide{ccc-Two}"]


def test_dropping_a_section_on_another_one_takes_its_place(make_list):
    slide_list, _window, path = make_list(FRONT_AND_SECTIONS)
    slide_list._on_moved([section_of(slide_list, "Two")], section_of(slide_list, "One"), ON_ITEM)
    assert deck_lines(path) == ["\\slide{aaa-Front}", "\\section{Two}", "\\slide{ccc-Two}", "\\slide{ddd-Two}",
                                "\\section{One}", "\\slide{bbb-One}", "\\section{Empty}"]
    slide_list._on_moved([section_of(slide_list, "Empty")], row_of(slide_list, "ccc"), ABOVE_ITEM)   # onto a slide of Two
    assert deck_lines(path)[1] == "\\section{Empty}"
    before = _read(path)
    slide_list._on_moved([section_of(slide_list, "One")], section_of(slide_list, deck_outline.UNSECTIONED), ON_ITEM)
    assert _read(path) == before                                      # the unsectioned slides are no target


class DropEvent:
    """The part of a QDropEvent the tree reads."""

    def __init__(self, point):
        self._point = point
        self.action = None
        self.accepted = False

    def position(self):
        return QPointF(self._point)

    def setDropAction(self, action):
        self.action = action

    def accept(self):
        self.accepted = True


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
    event = DropEvent(tree.visualItemRect(target).center())
    focus(slide_list, "aaa")
    tree.dropEvent(event)
    assert event.accepted and event.action == Qt.DropAction.IgnoreAction      # Qt must not remove anything
    sources, dropped_on, position = drops[-1]
    assert [r.call.id for r in sources] == ["aaa"] and dropped_on.call.id == "ddd" and position == ABOVE_ITEM
    tree.setCurrentItem(head_of(slide_list, "Two"))                           # a section is dragged alone
    tree.dropEvent(DropEvent(tree.visualItemRect(head_of(slide_list, "One")).center()))
    assert drops[-1][0][0].title == "Two" and drops[-1][1].title == "One"
    tree.dropEvent(DropEvent(tree.viewport().rect().bottomRight()))           # below the last row: no target
    assert len(drops) == 2
    slide_list.hide()


def test_a_drop_that_changes_nothing_is_not_an_edit(make_list):
    slide_list, window, _path = make_list(FRONT_AND_SECTIONS)
    slide_list._on_moved([row_of(slide_list, "ccc")], row_of(slide_list, "ddd"), ABOVE_ITEM)
    assert window.edits == []


# -- sections -----------------------------------------------------------------------------

def test_a_section_is_renamed_in_place(make_list, qapp):
    slide_list, _window, path = make_list(FRONT_AND_SECTIONS)
    slide_list.tree.setCurrentItem(head_of(slide_list, "Two"))
    key(slide_list, Qt.Key.Key_F2)
    editor = slide_list.tree.findChild(QLineEdit, kit_qss.SLIDES_RENAME)
    assert editor is not None and editor.text() == "Two"
    editor.setText("Second")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    qapp.processEvents()                                   # the delegate commits through the event loop
    assert "\\section{Second}" in _read(path) and "\\section{Two}" not in _read(path)
    assert head_of(slide_list, "Second").childCount() == 2
    slide_list.tree.rename(head_of(slide_list, "One"))
    QTest.keyClick(slide_list.tree.findChild(QLineEdit, kit_qss.SLIDES_RENAME), Qt.Key.Key_Escape)
    qapp.processEvents()
    assert "\\section{One}" in _read(path)


def test_sections_are_added_removed_and_get_slides(make_list, monkeypatch):
    slide_list, window, path = make_list(FRONT_AND_SECTIONS)
    monkeypatch.setattr(slide_list_module.QInputDialog, "getText", lambda *a, **k: ("New", True))
    slide_list.add_section_button.click()
    assert deck_lines(path)[-1] == "\\section{New}"
    choose_section(slide_list, "Empty")
    slide_list.run_section("section_before")
    assert deck_lines(path)[2:5] == ["\\slide{bbb-One}", "\\section{New}", "\\section{Empty}"]
    choose_section(slide_list, "One")
    slide_list.run_section("remove_section")                              # its slides stay
    assert "\\section{One}" not in _read(path) and "bbb" in ids(slide_list)
    choose_section(slide_list, "Two")
    slide_list.run_section("add_slide")
    deck = window.state.deck
    two = next(c for c in deck.chapters if c.title == "Two")
    assert window.added[-1] == (deck_editor.section_append_point(deck, two), "")     # after ddd, indented like it
    monkeypatch.setattr(slide_list_module.QInputDialog, "getText", lambda *a, **k: ("{bad}", True))
    slide_list.add_section_button.click()
    assert "braces" in make_list.errors[-1]


def test_the_add_slide_button_adds_after_the_focused_slide_or_at_the_end(make_list):
    slide_list, window, _path = make_list(FRONT_AND_SECTIONS)
    slide_list.add_slide_button.click()
    deck = window.state.deck
    assert window.added[-1] == deck_editor.append_position(deck)
    focus(slide_list, "bbb")
    slide_list.add_slide_button.click()
    call = row_of(slide_list, "bbb").call
    assert window.added[-1] == (call.line_end, call.indent)


def test_the_add_slide_button_of_an_empty_deck_adds_before_the_end_of_the_document(make_list):
    slide_list, window, _path = make_list("")
    slide_list.add_slide_button.click()
    assert window.added == [deck_editor.empty_deck_insert_point(window.state.deck.text)]
