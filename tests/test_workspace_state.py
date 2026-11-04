# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The workspace's shared state: one signal per field, emitted only on a real
change, and the view, language and mode remembered for each deck."""
from __future__ import annotations

from pathlib import Path

import pytest

from slidemage import app_settings, languages
from slidemage.deck_scan import Deck
from slidemage.project import ProjectContext
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
def test_view_and_mode_are_remembered_per_deck_and_the_language_is_the_decks(same_name):
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
    assert (state.view, state.language, state.mode) == ("after-course", "EN", "split")     # the deck's language
    assert views == ["after-course"] and modes == ["split"]
    state.set_deck(second)
    assert state.view == "during-course"

    # ... and across a restart: a new state reads the same settings file
    reopened = WorkspaceState(EXAMPLE_PROJECT)
    reopened.set_deck(first)
    assert (reopened.view, reopened.language, reopened.mode) == ("after-course", "EN", "split")
    assert app_settings.get(EXAMPLE_PROJECT, SETTINGS_KEY)[str(first.path)] == {"view": "after-course", "mode": "split"}


def test_set_mode_remembers_for_the_deck_only_while_remember_mode_says_so():
    """The centre narrows this to "the slide tab is on show" (centre-tabs.md step 3): a file tab's own mode must
    never clobber the deck's remembered one."""
    state = WorkspaceState(EXAMPLE_PROJECT)
    deck = make_deck("remember-mode")
    state.set_deck(deck)
    modes = record(state.mode_changed)
    state.remember_mode = lambda: False
    state.set_mode("source")
    assert state.mode == "source" and modes == ["source"]            # shown, but not remembered
    assert app_settings.get(EXAMPLE_PROJECT, SETTINGS_KEY, {}).get(str(deck.path), {}).get("mode") is None
    state.remember_mode = lambda: True
    state.set_mode("split")
    assert app_settings.get(EXAMPLE_PROJECT, SETTINGS_KEY)[str(deck.path)]["mode"] == "split"


def test_a_deck_without_a_saved_language_starts_in_its_own():
    state = WorkspaceState(EXAMPLE_PROJECT)
    state.set_deck(make_deck("german", text="\\decklanguage[de]\n\\begin{document}\n"))
    assert state.language == "DE"
    state.set_deck(make_deck("english", text="\\decklanguage[en]\n\\begin{document}\n"))
    assert state.language == "EN"


def language_deck(name: str, code: str) -> Deck:
    return make_deck(name, text=f"\\decklanguage[{code}]\n\\begin{{document}}\n")


@pytest.fixture
def french_project(tmp_path) -> ProjectContext:
    ctx = ProjectContext.at(tmp_path)
    languages.set_project_languages(ctx, "en", ["de", "fr"])
    return ctx


def test_the_switch_follows_the_deck_also_after_a_look_at_another_language(french_project):
    state = WorkspaceState(french_project)
    english, german = language_deck("english", "en"), language_deck("german", "de")
    assert state.languages() == ("EN", "DE", "FR")
    state.set_deck(english)
    state.set_language("FR")
    assert state.language == "FR"
    state.set_deck(german)
    assert state.language == "DE"
    state.set_deck(english)
    assert state.language == "EN"
    state.set_language("IT")                        # not a language of the project
    assert state.language == "EN"
    state.set_deck(None)
    assert state.language == "EN"                   # the main language, without a deck


def test_changing_the_decks_language_moves_the_switch(french_project):
    state = WorkspaceState(french_project)
    state.set_deck(language_deck("deck", "en"))
    shown = record(state.language_changed)
    assert state.set_deck(language_deck("deck", "fr")) is False       # the same deck, scanned again
    assert state.language == "FR" and shown == ["FR"]


def test_a_stored_per_deck_language_is_ignored_and_dropped(french_project):
    deck = language_deck("deck", "en")
    app_settings.set(french_project, SETTINGS_KEY, {str(deck.path): {"view": "after-course", "language": "DE"}})
    state = WorkspaceState(french_project)
    state.set_deck(deck)
    assert (state.view, state.language) == ("after-course", "EN")
    assert app_settings.get(french_project, SETTINGS_KEY)[str(deck.path)] == {"view": "after-course"}


def test_a_deck_in_another_language_adds_it_to_the_switch(french_project):
    state = WorkspaceState(french_project)
    changed = record(state.languages_changed)
    state.set_deck(language_deck("italian", "it"))
    assert state.languages() == ("EN", "DE", "FR", "IT") and state.language == "IT"
    state.set_deck(language_deck("english", "en"))
    assert state.languages() == ("EN", "DE", "FR") and changed == [("EN", "DE", "FR", "IT"), ("EN", "DE", "FR")]


def test_the_projects_languages_rebuild_the_switch(french_project):
    state = WorkspaceState(french_project)
    state.set_deck(language_deck("deck", "en"))
    state.set_language("FR")
    changed = record(state.languages_changed)
    languages.set_project_languages(french_project, "en", ["de"])
    state.refresh_languages()
    assert changed == [("EN", "DE")] and state.language == "EN"


def test_the_selection_falls_back_to_the_focus():
    state = WorkspaceState(EXAMPLE_PROJECT)
    assert state.selected_or_focused() == ()
    state.set_focused_slide("1ab")
    assert state.selected_or_focused() == ("1ab",)
    state.set_selection(("2cd", "3ef"))
    assert state.selected_or_focused() == ("2cd", "3ef")
