# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The centre's tab model (ui/workspace/centre_tabs.py): which tabs are open, the one shown, the most-recently-used
order and the Ctrl+Tab series. No window is needed for any of it."""
from __future__ import annotations

from pathlib import Path

import pytest

from slidemage.ui.workspace.centre_tabs import FILE, SLIDE, CentreTabs

DECK, BIB, TEST = Path("course.tex"), Path("SlideMage.bib"), Path("test-slides.tex")


@pytest.fixture
def tabs():
    return CentreTabs("preview")


def test_it_starts_with_the_slide_tab_alone_and_file_tabs_open_at_the_end_once_per_file(tabs):
    slide = tabs.slide_tab
    assert tabs.tabs == [slide] and tabs.active is slide and slide.kind == SLIDE and slide.mode == "preview"
    assert not slide.closable and not slide.source_only
    with pytest.raises(ValueError):
        tabs.close(slide)
    changed = []
    tabs.tabs_changed.connect(lambda: changed.append(True))
    deck = tabs.add_file(DECK)
    bib = tabs.add_file(BIB)
    assert tabs.tabs == [slide, deck, bib] and changed == [True, True]
    assert deck.kind == FILE and deck.closable and deck.source_only and deck.mode == "source"
    assert tabs.add_file(DECK) is deck and len(tabs.tabs) == 3 and len(changed) == 2     # never a second tab
    assert tabs.tab_for(BIB) is bib and tabs.tab_for(TEST) is None
    assert tabs.active is slide                                                          # opened, not shown
    path = BIB.with_name("aaa-EN-One-current.tex")                                       # a slide file tab has every mode
    opened = tabs.add_file(path, slide=True, occurrence=("k", 1), mode="preview")
    assert opened.slide and not opened.source_only and opened.mode == "preview" and opened.occurrence == ("k", 1)
    assert tabs.add_file(path) is opened and tabs.add_file(BIB, mode="preview").mode == "source"


def test_opening_a_tab_again_replaces_its_save_hook(tabs):
    first, second = (lambda text: None), (lambda text: None)
    tab = tabs.add_file(DECK, first)
    assert tab.on_saved is first
    tabs.add_file(DECK)
    assert tab.on_saved is first                                                         # none given: kept
    tabs.add_file(DECK, second)
    assert tab.on_saved is second


def test_activating_shows_the_tab_and_makes_it_the_most_recently_used(tabs):
    shown = []
    tabs.active_changed.connect(shown.append)
    deck, bib = tabs.add_file(DECK), tabs.add_file(BIB)
    assert tabs.mru == [tabs.slide_tab, deck, bib]
    tabs.activate(bib)
    tabs.activate(deck)
    tabs.activate(deck)                                                                  # again: no change to tell
    assert shown == [bib, deck] and tabs.active is deck
    assert tabs.mru == [deck, bib, tabs.slide_tab]
    tabs.slide_tab.mode = "split"                                                        # each tab remembers its mode
    tabs.activate(tabs.slide_tab)
    tabs.activate(deck)
    assert tabs.slide_tab.mode == "split" and deck.mode == "source"


def test_closing_the_tab_on_show_returns_to_the_most_recently_used_not_the_neighbour(tabs):
    slide = tabs.slide_tab
    deck, bib, test = tabs.add_file(DECK), tabs.add_file(BIB), tabs.add_file(TEST)
    tabs.activate(deck)
    tabs.activate(test)
    tabs.activate(bib)                                                                   # used last: bib, test, deck, slide
    shown = []
    tabs.active_changed.connect(shown.append)
    assert tabs.close(bib) is test and tabs.active is test and shown == [test]
    assert tabs.tabs == [slide, deck, test]
    assert tabs.close(test) is deck and tabs.close(deck) is slide
    assert tabs.tabs == [slide] and tabs.mru == [slide]


def test_closing_a_tab_that_is_not_shown_changes_nothing_else_and_a_closed_tab_is_gone(tabs):
    deck, bib = tabs.add_file(DECK), tabs.add_file(BIB)
    tabs.activate(bib)
    shown = []
    tabs.active_changed.connect(shown.append)
    assert tabs.close(deck) is None and tabs.active is bib and shown == []
    assert tabs.tabs == [tabs.slide_tab, bib]
    with pytest.raises(ValueError):
        tabs.close(deck)
    with pytest.raises(ValueError):
        tabs.activate(deck)


def test_a_ctrl_tab_series_walks_on_through_the_order_and_wraps(tabs):
    slide = tabs.slide_tab
    deck, bib = tabs.add_file(DECK), tabs.add_file(BIB)
    tabs.activate(deck)
    tabs.activate(bib)                                                                   # bib, deck, slide
    assert tabs.cycling is False
    assert [tabs.cycle(1) for _ in range(4)] == [deck, slide, bib, deck]
    assert tabs.cycling and tabs.mru == [bib, deck, slide]                               # not reordered until Ctrl is up
    tabs.end_cycle()
    assert not tabs.cycling and tabs.mru == [deck, bib, slide]
    assert tabs.cycle(-1) is slide and tabs.cycle(-1) is bib                             # Ctrl+Shift+Tab: the other way
    tabs.end_cycle()
    assert tabs.mru[0] is bib


def test_a_click_or_a_close_ends_a_series(tabs):
    deck, bib = tabs.add_file(DECK), tabs.add_file(BIB)
    tabs.activate(deck)
    tabs.cycle(1)
    tabs.activate(bib)
    assert not tabs.cycling and tabs.mru[0] is bib
    tabs.cycle(1)
    tabs.close(deck)
    assert not tabs.cycling


def test_step_moves_to_the_next_or_previous_tab_in_strip_order_and_wraps(tabs):
    slide = tabs.slide_tab
    deck, bib, test = tabs.add_file(DECK), tabs.add_file(BIB), tabs.add_file(TEST)
    tabs.activate(bib)                                                                  # bib, deck, test, slide
    shown = []
    tabs.active_changed.connect(shown.append)
    assert tabs.step(1) is test and tabs.step(1) is slide and tabs.step(1) is deck      # wraps past the end
    assert tabs.step(-1) is slide and tabs.step(-1) is test                             # wraps past the start
    assert shown == [test, slide, deck, slide, test]
    assert tabs.mru[0] is test                                                          # each step is its own switch


def test_close_others_and_close_right_are_the_closable_tabs_in_strip_order(tabs):
    slide = tabs.slide_tab
    deck, bib, test = tabs.add_file(DECK), tabs.add_file(BIB), tabs.add_file(TEST)
    assert tabs.close_others(bib) == [deck, test]
    assert tabs.close_others(slide) == [deck, bib, test]
    assert tabs.close_right(deck) == [bib, test]
    assert tabs.close_right(test) == []
    assert tabs.close_right(slide) == [deck, bib, test]                                 # the slide tab is always first
