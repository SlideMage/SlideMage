"""Rerender all previews for this deck: the command, its item in the ⋮ menu and the action, which runs the
shared update_all_previews.rerender_deck() on the current deck through the window's compile flow (job
panel, Log drawer), asking first like the project-wide Update slide previews."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from conftest import command_context, qapp as qapp, wait_until  # noqa: F401 -- fixture
from PySide6.QtWidgets import QMessageBox

from slidemage import update_all_previews
from slidemage.ui.workspace import compile_actions
from slidemage.ui.workspace.actions import DECK, build_registry
from slidemage.ui.workspace.menus import MORE_COLUMNS, build_more_menu
from slidemage.ui.workspace.palette import command_entries

from test_workspace_window import COURSE, window as window  # noqa: F401 -- fixture

LABEL = "Rerender all previews for this deck"
NEEDED = {"uni-graz": {"aaa-EN-One", "bbb-EN-Two"}}


@pytest.fixture
def run(window, monkeypatch):
    """The action with its questions answered and the compile replaced: records what it was given."""
    r = SimpleNamespace(calls=[], asked=[], needed_for=[], lint_ok=True,
                        result=update_all_previews.DeckResult(refreshed=["aaa-EN-One", "bbb-EN-Two"]))

    def needed(_ctx, deck=None):
        r.needed_for.append(deck)
        return NEEDED

    def rerender(ctx, deck, log, cancel=None, base_jobnames=None, needed=None):
        r.calls.append((ctx, deck, base_jobnames, needed))
        log("==== Rerender previews of course: 2 slide(s) ====")
        return r.result

    def question(_parent, title, text, *args):
        r.asked.append((title, text))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(update_all_previews, "needed_slides_by_template", needed)
    monkeypatch.setattr(update_all_previews, "rerender_deck", rerender)
    monkeypatch.setattr(QMessageBox, "question", question)
    monkeypatch.setattr(compile_actions, "_confirm_previews_lint", lambda _window, _needed: r.lint_ok)
    monkeypatch.setattr(QMessageBox, "information", lambda *a: r.asked.append(a[1:3]))
    r.finished = lambda: wait_until(lambda: not window.compile.running)
    return r


# -- the command and the menu item --------------------------------------------------------

def test_the_command_is_a_deck_command_in_the_palette_and_needs_a_deck(window):
    command = window.commands["rerender_deck_previews"]
    assert (command.title(window), command.group) == (LABEL, DECK)
    window.state.set_deck(None)
    assert not command.enabled(window)
    window.state.set_deck(COURSE)
    assert command.enabled(window)
    assert LABEL in {e.label for e in command_entries(window, [])}


def test_the_menu_item_follows_create_deck_snapshot_and_is_enabled_with_a_deck(qapp):
    left = next(ids for header, ids in MORE_COLUMNS[0] if header == "This deck")
    assert left[left.index("create_snapshot") + 1] == "rerender_deck_previews"
    for deck, enabled in ((None, False), (COURSE, True)):
        entries = {e[1]: e for e in build_more_menu(None, command_context(deck))._entries if e[0] == "item"}
        assert (entries["rerender_deck_previews"][2], entries["rerender_deck_previews"][6]) == (LABEL, enabled)
    assert "update_previews" not in left and "rerender_deck_previews" in build_registry()     # the project-wide one stays apart


# -- the action ----------------------------------------------------------------------

def test_the_action_runs_the_shared_function_on_the_current_deck_through_the_compile_flow(window, run):
    window.state.set_deck(COURSE)
    assert window.commands.run("rerender_deck_previews", window)
    assert window.compile.running
    run.finished()
    (ctx, deck, base_jobnames, needed), = run.calls
    assert ctx is window.project and deck is COURSE and needed == NEEDED and list(base_jobnames) == ["uni-graz"]
    assert run.needed_for == [COURSE]                                        # only this deck was looked at
    assert "course" in run.asked[0][1] and "2 slide(s)" in run.asked[0][1] and "other decks" in run.asked[0][1]
    row, = window.compile.run.rows.values()
    assert row.label == "Rerender previews of course (UniGraz)" and row.jobname.startswith(update_all_previews.JOBNAME_PREFIX)
    assert not window.compile._opens_pdfs                                    # a throw-away deck never pops open


def test_declining_the_question_or_the_syntax_check_starts_nothing(window, run, monkeypatch):
    window.state.set_deck(COURSE)
    run.lint_ok = False
    compile_actions.rerender_deck_previews(window)
    assert not window.compile.running and run.calls == []
    run.lint_ok = True
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No)
    compile_actions.rerender_deck_previews(window)
    assert not window.compile.running and run.calls == []


def test_a_deck_without_slides_says_so_and_a_busy_slot_is_respected(window, run, monkeypatch):
    window.state.set_deck(COURSE)
    monkeypatch.setattr(update_all_previews, "needed_slides_by_template", lambda _ctx, deck=None: {})
    compile_actions.rerender_deck_previews(window)
    assert run.asked[-1][0] == "Nothing to do" and run.calls == []
    monkeypatch.setattr(update_all_previews, "needed_slides_by_template", lambda _ctx, deck=None: NEEDED)
    monkeypatch.setattr(type(window.compile), "running", property(lambda _self: True))
    compile_actions.rerender_deck_previews(window)
    assert run.asked[-1][0] == "Busy" and run.calls == []


def test_the_project_wide_update_still_runs_every_deck_and_prunes(window, run, monkeypatch):
    seen = {}
    monkeypatch.setattr(update_all_previews, "run", lambda ctx, log, cancel=None, base_jobnames=None, needed=None:
                        seen.update(needed=needed) or True)
    compile_actions.update_previews(window)
    run.finished()
    assert seen["needed"] == NEEDED and run.needed_for == [None] and run.calls == []
    assert "Cached previews no longer used by any deck are deleted" in run.asked[0][1]
