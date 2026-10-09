"""The workspace's shared state: one signal per field, emitted only on a real
change, and the view, language and mode remembered for each deck."""
from __future__ import annotations

from pathlib import Path

from slidemage import app_settings
from slidemage.deck_scan import Deck
from slidemage.ui.workspace.state import MODES, SETTINGS_KEY, UI_LANGUAGES, VIEWS, WorkspaceState


def make_deck(name: str, text: str = "") -> Deck:
    return Deck(
        name=name, path=Path(f"decks/{name}.tex"), archived=False, text=text,
        supports_version=True, uses_biblatex=False, preamble_end=0,
        chapters=[], output_folders={}, tags=[])


def record(signal) -> list:
    seen: list = []
    signal.connect(seen.append)
    return seen


def test_views_and_languages_are_the_projects_own_names():
    assert VIEWS == ("instructor", "during-course", "after-course")
    assert UI_LANGUAGES == ("EN", "DE")


def test_a_setter_emits_only_when_the_value_changes():
    state = WorkspaceState()
    views, languages = record(state.view_changed), record(state.language_changed)
    focus, selection = record(state.focused_slide_changed), record(state.selection_changed)

    state.set_view("instructor")                 # already the view
    state.set_view("during-course")
    state.set_view("during-course")
    state.set_language("EN")
    state.set_language("DE")
    state.set_language("DE")
    state.set_focused_slide("1y8")
    state.set_focused_slide("1y8")
    state.set_selection(("1y8", "1ym"))
    state.set_selection(["1y8", "1ym"])          # the same slides, any sequence type

    assert views == ["during-course"] and languages == ["DE"]
    assert focus == ["1y8"] and selection == [("1y8", "1ym")]


def test_unknown_views_languages_and_modes_are_ignored():
    state = WorkspaceState()
    seen = record(state.view_changed)
    state.set_view("presenter")
    state.set_language("FR")
    state.set_language("mult")
    state.set_mode("grid")
    assert seen == [] and (state.view, state.language, state.mode) == ("instructor", "EN", "preview")
    assert MODES == ("preview", "split", "source", "details")


def test_mode_and_dirty_signal_only_real_changes():
    state = WorkspaceState()
    modes, dirty = record(state.mode_changed), record(state.dirty_changed)
    state.set_mode("preview")
    state.set_mode("source")
    state.set_mode("source")
    state.set_dirty(False)
    state.set_dirty(True)
    state.set_dirty(True)
    assert modes == ["source"] and dirty == [True]


def test_dirty_is_the_or_of_every_source_that_has_unsaved_edits():
    state = WorkspaceState()
    dirty = record(state.dirty_changed)
    state.set_dirty(True)
    state.set_dirty(True, "panels")
    state.set_dirty(False)
    assert state.dirty and dirty == [True]           # the panels still have a pending edit
    state.set_dirty(False, "panels")
    assert not state.dirty and dirty == [True, False]


def test_switching_decks_resets_focus_and_selection_and_reports_each_only_if_it_changed():
    state = WorkspaceState()
    first, second = make_deck("first"), make_deck("second")
    decks = record(state.deck_changed)
    focus, selection = record(state.focused_slide_changed), record(state.selection_changed)

    state.set_deck(first)
    assert decks == [first] and focus == [] and selection == []      # nothing to reset yet
    state.set_focused_slide("1y8")
    state.set_selection(("1y8",))
    state.set_deck(second)
    assert decks == [first, second]
    assert focus == ["1y8", None] and selection == [("1y8",), ()]
    assert state.focused_slide is None and state.selection == ()


def test_a_fresh_scan_of_the_open_deck_is_not_a_switch():
    state = WorkspaceState()
    deck = make_deck("course", text="old")
    state.set_deck(deck)
    state.set_focused_slide("1y8")
    decks, focus = record(state.deck_changed), record(state.focused_slide_changed)

    rescanned = make_deck("course", text="new")
    state.set_deck(rescanned)

    assert state.deck is rescanned and state.focused_slide == "1y8"
    assert decks == [] and focus == []


def test_view_language_and_mode_are_remembered_per_deck():
    state = WorkspaceState()
    first, second = make_deck("first"), make_deck("second")
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
    reopened = WorkspaceState()
    reopened.set_deck(first)
    assert (reopened.view, reopened.language, reopened.mode) == ("after-course", "DE", "split")
    assert app_settings.get(SETTINGS_KEY)["first"] == {"view": "after-course", "language": "DE", "mode": "split"}


def test_a_deck_without_a_saved_language_starts_in_its_own():
    state = WorkspaceState()
    state.set_deck(make_deck("german", text="\\decklanguage[de]\n\\begin{document}\n"))
    assert state.language == "DE"
    state.set_deck(make_deck("english", text="\\decklanguage[en]\n\\begin{document}\n"))
    assert state.language == "EN"


def test_no_deck_leaves_the_settings_alone():
    state = WorkspaceState()
    state.set_view("after-course")               # nothing to remember it for
    state.set_deck(None)
    assert app_settings.get(SETTINGS_KEY) is None
