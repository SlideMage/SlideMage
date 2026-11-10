# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Rerender all previews for this deck: the command, its item in the ⋮ menu and the action, which runs the
shared batch_render.render_batch() on the current deck through the window's compile flow (job
panel, Log drawer), asking first like the project-wide Render all previews now."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from conftest import command_context, filled_menu, menu_actions, qapp as qapp, wait_until  # noqa: F401 -- fixture
from PySide6.QtWidgets import QInputDialog, QMessageBox

from slidemage import batch_render
from slidemage.ui.workspace import compile_actions
from slidemage.ui.workspace.actions import DECK
from slidemage.ui.workspace.palette import command_entries

from test_workspace_window import COURSE as EMPTY_COURSE, window as window  # noqa: F401 -- fixture

COURSE = replace(EMPTY_COURSE, text=r'\slide{abc-EN-One}' + '\n' + r'\slide{abd-EN-Two}')
LABEL = "Rerender all previews for this deck"


@pytest.fixture
def run(window, monkeypatch):
    """The action with its questions answered and the compile replaced: records what it was given."""
    r = SimpleNamespace(calls=[], asked=[], needed_for=[], lint_ok=True)

    real_plan = batch_render.plan_deck
    def plan(ctx, deck, **options):
        r.needed_for.append(deck)
        return real_plan(ctx, deck, **options)

    def render(service, requests, **options):
        from slidemage.preview_requests import PreviewResult
        r.calls.append((service, requests))
        return tuple(PreviewResult(spec) for spec in requests)

    def question(_parent, title, text, *args):
        r.asked.append((title, text))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(batch_render, "plan_deck", plan)
    monkeypatch.setattr(batch_render, "render_batch", render)
    monkeypatch.setattr(QMessageBox, "question", question)
    r.scope = ("All course views", True)        # the "Views to refresh" choice (QInputDialog.getItem)
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a: r.scope)
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


def test_the_command_is_in_the_deck_menu_and_update_previews_in_housekeeping(qapp):
    context = command_context(COURSE)
    assert menu_actions(filled_menu(context, "Deck"))["rerender_deck_previews"].isEnabled()
    assert "update_previews" in menu_actions(filled_menu(context, "Housekeeping"))


# -- the action ----------------------------------------------------------------------

@pytest.mark.parametrize("choice, scope", [("All course views", "all"), ("Selected course view", "selected")])
def test_the_action_runs_the_shared_function_on_the_current_deck_through_the_compile_flow(window, run, choice, scope):
    window.state.set_deck(COURSE)
    run.scope = (choice, True)
    assert window.commands.run("rerender_deck_previews", window)
    assert window.compile.running
    run.finished()
    (service, requests), = run.calls
    assert service is window.centre.preview._renders
    assert all(spec.target.deck is COURSE and spec.options.force for spec in requests)
    assert {spec.view for spec in requests} == (set(batch_render.VIEWS) if scope == 'all' else {window.state.view})
    assert run.needed_for == [COURSE]                                        # only this deck was looked at
    row, = window.compile.run.rows.values()
    assert row.label == "Rerender previews of course"
    assert not window.compile._opens_pdfs                                    # a throw-away deck never pops open


def test_declining_the_question_or_the_syntax_check_starts_nothing(window, run, monkeypatch):
    window.state.set_deck(COURSE)
    run.lint_ok = False
    compile_actions.rerender_deck_previews(window)
    assert not window.compile.running and run.calls == []
    run.lint_ok = True
    run.scope = ("All course views", False)                                  # the view choice cancelled
    compile_actions.rerender_deck_previews(window)
    assert not window.compile.running and run.calls == []


def test_a_deck_without_slides_says_so_and_a_busy_slot_is_respected(window, run, monkeypatch):
    window.state.set_deck(COURSE)
    monkeypatch.setattr(batch_render, "plan_deck", lambda *a, **k: ())
    compile_actions.rerender_deck_previews(window)
    assert run.asked[-1][0] == "Nothing to do" and run.calls == []
    monkeypatch.setattr(type(window.compile), "running", property(lambda _self: True))
    compile_actions.rerender_deck_previews(window)
    assert run.asked[-1][0] == "Busy" and run.calls == []
