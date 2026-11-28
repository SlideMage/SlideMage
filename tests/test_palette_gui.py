# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Command palette filtering, navigation and project text search."""
from __future__ import annotations

from dataclasses import replace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from conftest import build_window, wait_until
from slidemage import slide_ids
from slidemage.ui.workspace import palette as palette_module
from slidemage.ui.workspace.palette import CHAT, GO_TO_DECK, GO_TO_SLIDE, TEXT_HITS


@pytest.fixture
def window(qapp, monkeypatch):
    window = build_window(monkeypatch)
    window.show()
    window.palette._debounce.setInterval(0)
    yield window
    window.palette.stop_search()


def labels(palette, group=None):
    """The labels listed, without the always-present chat placeholder unless asked for."""
    return [e.label for e in palette._entries if e.group == group or (group is None and e.group != CHAT)]


def groups(palette):
    return [g for g in dict.fromkeys(e.group for e in palette._entries) if g != CHAT]


def press(palette, key):
    QTest.keyClick(palette.input, key)


def test_palette_toggles_and_groups_visible_commands(window, fake_routes):
    palette = window.palette
    window.slide_list.tree.setCurrentItem(window.slide_list.tree.slide_items()[0])
    window.commands.run("palette", window)
    assert palette.isVisible()
    window.commands.run("palette", window)
    assert not palette.isVisible()
    window.commands.run("palette", window)
    assert groups(palette) == ["View & build", f"Slide {window.state.focused_slide}", "Deck", "Project", "AI"]
    assert {"View as Instructor", "Find anything…"} <= set(labels(palette))
    assert not any(e.group in (GO_TO_SLIDE, CHAT) for e in palette._entries)
    press(palette, Qt.Key.Key_Escape)
    assert not palette.isVisible()


def test_arrows_move_over_what_can_run_and_enter_runs_and_closes(window):
    palette = window.palette
    palette.open()
    palette.input.setText("show")
    assert palette._current == 0
    for _ in range(len(palette._entries) + 2):          # round and round, never on a disabled entry
        press(palette, Qt.Key.Key_Down)
        assert palette._entries[palette._current].enabled
    press(palette, Qt.Key.Key_Up)
    palette.input.setText("compile after")
    assert labels(palette) == ["Compile PDF · After course"]
    palette.input.setText("show zzz")
    assert labels(palette) == [] and palette._entries[palette._current].group == CHAT
    palette.input.setText("show source")
    press(palette, Qt.Key.Key_Return)
    assert window.state.mode == "source" and not palette.isVisible()


def test_mouse_runs_enabled_rows_and_dismisses_the_palette_outside(window):
    palette = window.palette
    palette.open()
    palette.input.setText("show split")
    QTest.mouseClick(palette._rows[0], Qt.MouseButton.LeftButton)
    assert window.state.mode == "split" and not palette.isVisible()
    palette.open()
    QTest.mouseClick(palette, Qt.MouseButton.LeftButton, pos=palette.rect().bottomRight() - palette.rect().topLeft())
    assert not palette.isVisible()

    window.state.set_deck(None)
    palette.open()
    palette.input.setText("open latest pdf")
    assert labels(palette) == ["Open latest PDF"] and not palette._entries[0].enabled
    assert palette._entries[palette._current].group == CHAT
    QTest.mouseClick(palette._rows[0], Qt.MouseButton.LeftButton)
    assert palette.isVisible()


def test_a_slide_is_found_by_title_and_focused_even_when_hidden(window):
    palette = window.palette
    slides = window.slide_list
    row = slides.rows()[3]
    item = next(item for item in slides.tree.slide_items() if slides.tree.data_of(item).call.id == row.call.id)
    slides.find.setText(slides.rows()[0].call.id)
    assert item.isHidden()
    palette.open()
    palette.input.setText(row.title.split()[0])
    entry = next(e for e in palette._entries if e.group == GO_TO_SLIDE and e.meta == row.call.id_slug)
    assert entry.label == f"{row.call.id} · {row.title}"
    palette._run(palette._entries.index(entry))
    assert window.state.focused_slide == row.call.id
    assert slides.find.text() == "" and not item.isHidden() and slides.tree.currentItem() is item


def test_a_slide_from_outside_the_deck_opens_a_tab_and_keeps_the_focus_when_it_is_saved(window):
    rows = window.slide_list.rows()
    before = rows[0].call.id
    window.state.set_focused_slide(before)
    in_deck = {r.call.id_slug for r in rows}
    outside = next(s for s in slide_ids.list_id_slugs(window.project) if s not in in_deck)
    palette = window.palette
    palette.open()
    palette.input.setText(outside)
    palette._run(palette._entries.index(next(e for e in palette._entries if e.label == outside)))
    tab = window.centre.tabs.active
    assert tab.kind == "file" and tab.slide and tab.path.name.startswith(outside)
    assert window.state.focused_slide == before                        # a tab does not move the focus
    assert window.slide_list.tree.data_of(window.slide_list.tree.currentItem()).call.id == before
    window.state.set_mode("source")                                   # the tab opened in the mode it came from
    window.centre.source.current.editor.insertPlainText("% edit\n")
    window.centre.save()                                            # Ctrl+S, which also renders
    window.slide_list.rebuild()                                       # what a save does after its pause
    assert window.state.focused_slide == before
    window.state.set_focused_slide(rows[1].call.id)                   # another slide: the slide tab, the file tab stays
    assert window.centre.tabs.active is window.centre.tabs.slide_tab and tab in window.centre.tabs.tabs


def test_another_deck_is_found_by_name_and_switched_to(window):
    other = replace(window.state.deck, name="other-deck", path=window.state.deck.path.with_name("other-deck.tex"))
    window.decks.append(other)
    palette = window.palette
    palette.open()
    palette.input.setText(window.state.deck.name)
    assert window.state.deck.name not in labels(palette, GO_TO_DECK)
    palette.input.setText(other.name)
    entry = next(e for e in palette._entries if e.group == GO_TO_DECK and e.label == other.name)
    palette._run(palette._entries.index(entry))
    assert window.state.deck.path == other.path


def test_search_hits_keep_selection_and_open_at_the_matching_line(window, monkeypatch):
    opened = []
    monkeypatch.setattr(window, "open_slide_editor", lambda path, *, line, tab: opened.append((path, line, tab)))
    palette = window.palette
    palette.open()
    palette.input.setText("ci")
    assert palette._worker is None and not palette._debounce.isActive()
    assert not any(e.group in (TEXT_HITS, CHAT) for e in palette._entries)

    palette.input.setText("citation")
    press(palette, Qt.Key.Key_Up)
    chat = palette._entries[palette._current]
    assert chat.group == CHAT
    wait_until(lambda: palette._hits_query == "citation")
    last = palette._entries[-1]
    assert palette._entries[palette._current] is last
    assert last.group == CHAT and last.label == chat.label
    index, hit = next((i, e) for i, e in enumerate(palette._entries) if e.group.startswith(TEXT_HITS))
    palette._run(index)
    [(path, line, tab)] = opened
    assert tab and line == int(hit.meta.removeprefix("line "))
    assert "citation" in path.read_text(encoding="utf-8").splitlines()[line - 1].lower()


def test_show_all_lists_every_match_and_keeps_the_palette_open(window):
    from slidemage import slide_search

    palette = window.palette
    palette.open()
    palette.input.setText("slide")
    many = [slide_search.SearchHit(window.project.root / "slides" / f"x{i}.tex", i + 1, f"hit {i}", "slide")
            for i in range(palette_module.MAX_HITS + 5)]
    palette._on_found("slide", many)
    group = [e for e in palette._entries if e.group.startswith(TEXT_HITS)]
    show_all = group[-1]
    assert show_all.keep_open and len(group) == palette_module.MAX_HITS + 1
    palette._run(palette._entries.index(show_all))
    assert palette.isVisible()
    group = [e for e in palette._entries if e.group.startswith(TEXT_HITS)]
    assert [e.label for e in group] == [f"hit {i}" for i in range(len(many))]
    assert palette._entries[palette._current].label == f"hit {palette_module.MAX_HITS}"   # where Show all was
    palette.input.setText("slides")                                                           # a new search: 10 again
    palette._on_found("slides", many)
    assert len([e for e in palette._entries if e.group.startswith(TEXT_HITS)]) == palette_module.MAX_HITS + 1


def test_typing_on_discards_the_hits_of_the_old_text_and_closing_stops_the_search(window):
    palette = window.palette
    palette.open()
    palette.input.setText("citation")
    wait_until(lambda: palette._hits_query == "citation")
    palette.input.setText("citations")
    assert palette._hits == [] and palette._worker is None and palette._debounce.isActive()
    palette._start_search()
    assert palette._worker is not None
    palette.hide()
    assert palette._worker is None and not palette._debounce.isActive()
