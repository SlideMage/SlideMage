# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The workspace's shared state: one signal per field, emitted only on a real
change, and the view, language and mode remembered for each deck."""
from __future__ import annotations

from pathlib import Path

import pytest

from slidemage import app_settings
from slidemage.deck_scan import Deck
from slidemage.ui.workspace.state import SETTINGS_KEY, WorkspaceState
from conftest import EXAMPLE_PROJECT


def make_deck(name: str, text: str = "") -> Deck:
    return Deck(
        name=name, path=Path(f"decks/{name}.tex"), archived=False, text=text,
        supports_version=True, uses_biblatex=False, preamble_end=0,
        chapters=[], output_folders={}, tags=[])


def record(signal) -> list:
    seen: list = []
    signal.connect(seen.append)
    return seen


@pytest.mark.parametrize("field, initial, changed, equivalent", [
    ("view", "instructor", "during-course", "during-course"),
    ("language", "EN", "DE", "DE"),
    ("focused_slide", None, "1y8", "1y8"),
    ("selection", (), ("1y8", "1ym"), ["1y8", "1ym"]),
    ("mode", "preview", "source", "source"),
    ("dirty", False, True, True),
])
def test_a_setter_emits_only_when_the_value_changes(field, initial, changed, equivalent):
    state = WorkspaceState(EXAMPLE_PROJECT)
    seen = {name: record(getattr(state, f"{name}_changed"))
            for name in ("view", "language", "focused_slide", "selection", "mode", "dirty")}
    setter = getattr(state, f"set_{field}")
    setter(initial)
    setter(changed)
    setter(equivalent)
    assert seen == {name: [changed] if name == field else [] for name in seen}
    assert getattr(state, field) == changed


def test_dirty_is_the_or_of_every_source_that_has_unsaved_edits():
    state = WorkspaceState(EXAMPLE_PROJECT)
    dirty = record(state.dirty_changed)
    state.set_dirty(True)
    state.set_dirty(True, "panels")
    state.set_dirty(False)
    assert state.dirty and dirty == [True]           # the panels still have a pending edit
    state.set_dirty(False, "panels")
    assert not state.dirty and dirty == [True, False]


def test_switching_decks_resets_focus_and_selection_but_a_rescan_keeps_them():
    state = WorkspaceState(EXAMPLE_PROJECT)
    first, second = make_deck("first", text="old"), make_deck("second")
    decks = record(state.deck_changed)
    focus, selection = record(state.focused_slide_changed), record(state.selection_changed)

    assert state.set_deck(first) is True
    assert decks == [first] and focus == [] and selection == []      # nothing to reset yet
    state.set_focused_slide("1y8")
    state.set_selection(("1y8",))
    rescanned = make_deck("first", text="new")
    assert state.set_deck(rescanned) is False
    assert state.deck is rescanned and state.focused_slide == "1y8"
    assert decks == [first] and focus == ["1y8"] and selection == [("1y8",)]
    assert state.set_deck(second) is True
    assert decks == [first, second]
    assert focus == ["1y8", None] and selection == [("1y8",), ()]
    assert state.focused_slide is None and state.selection == ()


@pytest.mark.parametrize("same_name", [False, True], ids=["distinct-names", "same-name-different-folders"])
def test_view_language_and_mode_are_remembered_per_deck(same_name):
    state = WorkspaceState(EXAMPLE_PROJECT)
    state.set_view("after-course")
    state.set_deck(None)
    assert app_settings.get(EXAMPLE_PROJECT, SETTINGS_KEY) is None
    first, second = make_deck("same" if same_name else "first"), make_deck("same" if same_name else "second")
    if same_name:  # Regression: live and archived decks must be remembered by path, not name.
        second.path = Path("decks/archive/same.tex")
    state.set_deck(first)
    state.set_view("after-course")
    state.set_language("DE")
    state.set_mode("split")
    state.set_deck(second)
    assert (state.view, state.language, state.mode) == ("instructor", "EN", "preview")   # a deck of its own
    state.set_view("during-course")

    views, modes = record(state.view_changed), record(state.mode_changed)
    state.set_deck(first)
    assert (state.view, state.language, state.mode) == ("after-course", "DE", "split")
    assert views == ["after-course"] and modes == ["split"]
    state.set_deck(second)
    assert state.view == "during-course"

    # ... and across a restart: a new state reads the same settings file
    reopened = WorkspaceState(EXAMPLE_PROJECT)
    reopened.set_deck(first)
    assert (reopened.view, reopened.language, reopened.mode) == ("after-course", "DE", "split")
    assert app_settings.get(EXAMPLE_PROJECT, SETTINGS_KEY)[str(first.path)] == {"view": "after-course", "language": "DE", "mode": "split"}


def test_a_deck_without_a_saved_language_starts_in_its_own():
    state = WorkspaceState(EXAMPLE_PROJECT)
    state.set_deck(make_deck("german", text="\\decklanguage[de]\n\\begin{document}\n"))
    assert state.language == "DE"
    state.set_deck(make_deck("english", text="\\decklanguage[en]\n\\begin{document}\n"))
    assert state.language == "EN"


def test_the_selection_falls_back_to_the_focus():
    state = WorkspaceState(EXAMPLE_PROJECT)
    assert state.selected_or_focused() == ()
    state.set_focused_slide("1ab")
    assert state.selected_or_focused() == ("1ab",)
    state.set_selection(("2cd", "3ef"))
    assert state.selected_or_focused() == ("2cd", "3ef")
