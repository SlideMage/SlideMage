"""The command palette (Ctrl+K): what it lists for a text, the keys, going to a slide, and the
text search of the project's files."""
from __future__ import annotations

import time
from dataclasses import replace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from conftest import build_window
from slidemage import slide_ids
from slidemage.ui.workspace import palette as palette_module
from slidemage.ui.workspace.palette import CHAT, GO_TO_DECK, GO_TO_SLIDE, TEXT_HITS, matches, words_of


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, monkeypatch):
    window = build_window(monkeypatch)
    window.show()
    window.palette._debounce.setInterval(0)
    yield window
    window.palette.stop_search()


def wait_until(condition, seconds=5):
    end = time.time() + seconds
    while not condition() and time.time() < end:
        QApplication.processEvents()
        time.sleep(0.01)
    assert condition()


def labels(palette, group=None):
    """The labels listed, without the always-present chat placeholder unless asked for."""
    return [e.label for e in palette._entries if e.group == group or (group is None and e.group != CHAT)]


def groups(palette):
    return [g for g in dict.fromkeys(e.group for e in palette._entries) if g != CHAT]


def type_text(palette, text):
    palette.input.setText(text)


def press(palette, key):
    QTest.keyClick(palette.input, key)


# -- filtering -----------------------------------------------------------------------

def test_every_word_must_match_the_label_or_the_group():
    assert matches(words_of("show prev"), "Show Preview", "View & build")
    assert matches(words_of("build  COMPILE"), "Compile PDF", "View & build")
    assert not matches(words_of("show zzz"), "Show Preview", "View & build")
    assert matches([], "anything")


def test_it_opens_on_every_visible_command_grouped_and_closes_on_escape(window):
    palette = window.palette
    window.slide_list.tree.setCurrentItem(window.slide_list.tree.slide_items()[0])
    palette.open()
    assert palette.isVisible()
    focused = window.state.focused_slide
    assert groups(palette) == ["View & build", f"Slide {focused}", "Deck", "Project"]
    assert "View as Instructor" in labels(palette) and "Find anything…" in labels(palette)
    assert not [e for e in palette._entries if e.group in (GO_TO_SLIDE, CHAT)]    # only for a text
    press(palette, Qt.Key.Key_Escape)
    assert not palette.isVisible()


def test_typing_filters_the_commands_and_adds_the_slides_and_decks_that_match(window):
    palette = window.palette
    palette.open()
    type_text(palette, "show source")
    assert labels(palette) == ["Show Source"]
    type_text(palette, "compile after")
    assert labels(palette) == ["Compile PDF · After course"]
    deck = window.state.deck
    type_text(palette, deck.name)
    assert deck.name not in labels(palette, GO_TO_DECK)                            # not the open one
    type_text(palette, "zzzqqq")
    assert labels(palette) == [] and palette._entries[0].group == CHAT and palette._current == -1


def test_the_slide_group_follows_the_focused_slide_and_the_selection(window):
    palette = window.palette
    items = window.slide_list.tree.slide_items()
    window.slide_list.tree.setCurrentItem(items[1])
    palette.open()
    type_text(palette, "hide in")
    first = window.state.focused_slide
    assert groups(palette) == [f"Slide {first}"] and len(labels(palette)) == 3
    palette.hide()
    items[2].setSelected(True)
    palette.open()
    type_text(palette, "hide in")
    assert groups(palette) == ["2 slides"]


# -- keys and clicks ------------------------------------------------------------------

def test_arrows_move_over_what_can_run_and_enter_runs_and_closes(window):
    palette = window.palette
    palette.open()
    type_text(palette, "show")
    assert palette._current == 0
    for _ in range(len(palette._entries) + 2):          # round and round, never on a disabled entry
        press(palette, Qt.Key.Key_Down)
        assert palette._entries[palette._current].enabled
    press(palette, Qt.Key.Key_Up)
    type_text(palette, "show source")
    press(palette, Qt.Key.Key_Return)
    assert window.state.mode == "source" and not palette.isVisible()


def test_a_click_runs_the_row_and_a_click_outside_closes(window):
    palette = window.palette
    palette.open()
    type_text(palette, "show split")
    QTest.mouseClick(palette._rows[0], Qt.MouseButton.LeftButton)
    assert window.state.mode == "split" and not palette.isVisible()
    palette.open()
    QTest.mouseClick(palette, Qt.MouseButton.LeftButton, pos=palette.rect().bottomRight() - palette.rect().topLeft())
    assert not palette.isVisible()


def test_a_disabled_command_is_listed_but_does_not_run(window):
    palette = window.palette
    window.state.set_deck(None)
    palette.open()
    type_text(palette, "open latest pdf")
    assert labels(palette) == ["Open latest PDF"] and not palette._entries[0].enabled
    assert palette._current == -1
    press(palette, Qt.Key.Key_Return)
    assert palette.isVisible()


def test_the_shortcut_toggles_the_palette(window):
    window.commands.run("palette", window)
    assert window.palette.isVisible()
    window.commands.run("palette", window)
    assert not window.palette.isVisible()


# -- go to slide and deck ----------------------------------------------------------------

def test_a_slide_of_the_deck_is_found_by_id_or_title_and_focused(window):
    palette = window.palette
    row = window.slide_list.rows()[3]
    palette.open()
    type_text(palette, row.call.id)
    entry = next(e for e in palette._entries if e.group == GO_TO_SLIDE)
    assert entry.label == f"{row.call.id} · {row.title}" and entry.meta == row.call.id_slug
    type_text(palette, row.title.split()[0])
    assert any(e.label == f"{row.call.id} · {row.title}" for e in palette._entries)
    type_text(palette, row.call.id)
    palette._run(palette._entries.index(next(e for e in palette._entries if e.group == GO_TO_SLIDE)))
    assert window.state.focused_slide == row.call.id


def test_going_to_a_slide_shows_it_in_the_list_though_the_find_box_hides_it(window):
    palette, slide_list = window.palette, window.slide_list
    rows = slide_list.rows()
    target = rows[-1]
    slide_list.find.setText(rows[0].call.id)
    item = next(i for i in slide_list.tree.slide_items() if slide_list.tree.data_of(i) is not None
                and slide_list.tree.data_of(i).call.id == target.call.id)
    assert item.isHidden()
    palette.open()
    type_text(palette, target.call.id)
    palette._run(palette._entries.index(next(e for e in palette._entries if e.group == GO_TO_SLIDE)))
    assert window.state.focused_slide == target.call.id
    assert slide_list.find.text() == "" and not item.isHidden() and slide_list.tree.currentItem() is item


def test_a_slide_outside_the_deck_opens_in_the_source_view(window, monkeypatch):
    in_deck = {r.call.id_slug for r in window.slide_list.rows()}
    outside = next(s for s in slide_ids.list_id_slugs() if s not in in_deck)
    opened = []
    monkeypatch.setattr(window, "open_slide_editor", lambda path, **kwargs: opened.append(path))
    palette = window.palette
    palette.open()
    type_text(palette, outside)
    entry = next(e for e in palette._entries if e.group == GO_TO_SLIDE and e.label == outside)
    assert entry.meta == "not in this deck"
    palette._run(palette._entries.index(entry))
    assert [p.name for p in opened] == [f"{outside}-current.tex"]


def test_another_deck_is_found_by_name_and_switched_to(window):
    other = replace(window.state.deck, name="other-deck", path=window.state.deck.path.with_name("other-deck.tex"))
    window.decks.append(other)
    palette = window.palette
    palette.open()
    type_text(palette, other.name)
    entry = next(e for e in palette._entries if e.group == GO_TO_DECK and e.label == other.name)
    palette._run(palette._entries.index(entry))
    assert window.state.deck.path == other.path


# -- text in the project's files ------------------------------------------------------------

def test_a_short_text_is_not_searched_and_has_no_chat_entry(window):
    palette = window.palette
    palette.open()
    type_text(palette, "ci")
    assert palette._worker is None and not palette._debounce.isActive()
    assert not [e for e in palette._entries if e.group in (TEXT_HITS, CHAT)]


def test_from_three_characters_the_files_are_searched_and_a_hit_opens_at_its_line(window, monkeypatch):
    opened = []
    monkeypatch.setattr(window, "open_slide_editor", lambda path, on_saved=None, line=None: opened.append((path, line)))
    palette = window.palette
    palette.open()
    type_text(palette, "citation")
    chat = palette._entries[-1]
    assert (chat.group, chat.label, chat.enabled) == (CHAT, "Ask the chat: “citation”", False)
    assert palette._debounce.isActive()
    wait_until(lambda: palette._hits_query == "citation")
    hits = [e for e in palette._entries if e.group.startswith(TEXT_HITS)]
    assert hits and len(hits) <= palette_module.MAX_HITS and all(e.detail and e.meta.startswith("line ") for e in hits)
    assert palette._entries[-1] is not hits[-1] and palette._entries[-1].group == CHAT      # the chat stays last
    palette._run(palette._entries.index(hits[0]))
    path, line = opened[0]
    assert path.is_file() and line == int(hits[0].meta.removeprefix("line "))
    assert path.read_text(encoding="utf-8").splitlines()[line - 1].lower().count("citation")


def test_typing_on_discards_the_hits_of_the_old_text_and_closing_stops_the_search(window):
    palette = window.palette
    palette.open()
    type_text(palette, "citation")
    wait_until(lambda: palette._hits_query == "citation")
    type_text(palette, "citations")
    assert palette._hits == [] and palette._worker is None and palette._debounce.isActive()
    palette._start_search()
    assert palette._worker is not None
    palette.hide()
    assert palette._worker is None and not palette._debounce.isActive()


def test_the_entry_that_was_current_stays_when_the_hits_arrive(window):
    palette = window.palette
    palette.open()
    type_text(palette, "view")
    press(palette, Qt.Key.Key_Down)
    current = palette._entries[palette._current].label
    palette._hits = []
    palette._refresh()
    assert palette._entries[palette._current].label == current
