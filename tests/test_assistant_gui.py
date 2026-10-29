# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Assistant body, route, scope, task buttons and running pill on scripted routes."""
from __future__ import annotations

import pytest

from assistant_accessibility_helpers import BROKEN, LF, env as assistant_env, pump, slide_file, wait_until  # noqa: F401
from slidemage.ai import ai_profile
from slidemage.ui.kit.widgets import Button

LOCAL, CLOUD = ai_profile.LOCAL, ai_profile.CLOUD
PROSE = LF.replace("First point", "This first point explains the main idea of the slide with enough ordinary words")



@pytest.fixture(name="env")
def _env(assistant_env):  # noqa: F811
    return assistant_env


def area(env):
    return env.window.assistant


def header(env):
    return env.window.assistant.header


def shown(env) -> list[str]:
    """The labels of the task buttons on show, and All actions… last."""
    row = header(env)._actions
    return [row.itemAt(i).widget().text() for i in range(row.count()) if row.itemAt(i).widget().isVisibleTo(header(env))]


def go(env, mode, conn=None):
    ai_profile.mark_cloud_seen(env.window.project)
    env.window.state.set_ai_route(mode, conn)
    pump(0.05)


def refreshed(env):
    header(env).refresh_content()
    return header(env)


# -- the body ------------------------------------------------------------------------------------------------------

def test_the_body_follows_the_route(env):
    a = area(env)
    assert a._stack.currentWidget() is a.chat
    go(env, CLOUD)
    assert a._stack.currentWidget() is a.surface_for("fake_cloud")
    go(env, LOCAL)
    assert a._stack.currentWidget() is a.chat



def test_leaving_a_live_route_surface_asks_to_end_the_session(env):
    go(env, CLOUD)
    surface = area(env).surface_for("fake_cloud")
    surface.session_live = True
    env.window.ai_route.request(LOCAL)
    assert env.window.ai_route.popover_kind == "session"
    env.window.ai_route._popover.spec.actions[-1][2]()
    assert env.window.state.ai_route == "fake_local" and not surface.session_live
    assert area(env)._stack.currentWidget() is area(env).chat



def test_the_chat_has_no_scope_or_new_button_of_its_own(env):
    chat = area(env).chat
    assert chat.scope is area(env).scope and not hasattr(chat, "new_button")
    assert not any(b.toolTip().startswith("New chat") for b in chat.findChildren(Button))


def test_a_surface_needing_setup_blocks_tasks_until_ready(env):
    go(env, CLOUD)
    surface = area(env).surface_for("fake_cloud")
    surface.needs_setup = True
    surface.setup_changed.emit()
    wait_until(lambda: shown(env) == ["All actions…"])
    assert env.window.state.ai_route == "fake_cloud"
    surface.needs_setup = False
    surface.setup_changed.emit()
    wait_until(lambda: "Translate to German" in shown(env))


# -- row 1: the route ----------------------------------------------------------------------------------------------

def test_the_header_names_each_route_and_what_its_conversation_runs_on(env):
    head = header(env)
    assert head.ai_switch.toolTip().startswith("Local · Fake local")
    assert head.route_note == "Chat with fake-1" and head.route_note in head.ai_switch.toolTip()
    assert head.ai_switch.segments.current() == LOCAL and head.ai_switch.property("cloud") is False
    go(env, CLOUD)
    assert head.ai_switch.toolTip().startswith("Cloud · Fake cloud")
    assert head.route_note == "Scripted conversation"
    assert head.ai_switch.segments.current() == CLOUD and head.ai_switch.property("cloud") is True
    go(env, LOCAL)
    assert head.route_note == "Chat with fake-1"






def test_new_conversation_clears_only_the_route_on_show(env):
    chat = area(env).chat
    chat.composer.setPlainText("local draft")
    chat.session.history.append("local history")
    go(env, CLOUD)
    surface = area(env).surface_for("fake_cloud")
    surface.composer.setText("cloud message")
    surface.send()
    header(env).new_button.click()
    assert surface.turns == [] and surface.restarts == [("", False)]
    go(env, LOCAL)
    assert chat.composer.toPlainText() == "local draft"
    header(env).new_button.click()
    assert chat.session.history == []






# -- row 2: the scope and its target ------------------------------------------------------------------------------

def test_the_scope_names_the_slide_with_its_title_and_the_not_saved_state_or_the_deck(env):
    head = refreshed(env)
    assert head.target.full_text() == "abc · Hello"
    area(env).scope._buttons["deck"].click()
    assert head.target.full_text() == "test · 2 slides"
    area(env).scope._buttons["slide"].click()
    slide_file(env).editor.set_read_only(True)                       # edits that cannot be written
    slide_file(env).editor.replace_all_text(LF + "% typed\n")
    wait_until(lambda: head.target.full_text() == "abc · Hello · not saved")
    slide_file(env).editor.undo()                                    # back to what is saved
    slide_file(env).editor.set_read_only(False)
    wait_until(lambda: head.target.full_text() == "abc · Hello")
    env.window.centre.open_file(env.root / "decks" / "test.tex")      # not a slide: the file's name
    wait_until(lambda: head.target.full_text() == "test.tex")
    env.window.state.set_focused_slide("abd")
    wait_until(lambda: head.target.full_text() == "abd · Second")


def test_the_scope_is_shared_with_the_core_chat(env):
    a = area(env)
    a.scope._buttons["deck"].click()
    assert a.chat.scope.current() == "deck" and "whole deck" in a.chat._suggestion_widgets[0].text()
    go(env, CLOUD)
    surface = a.surface_for("fake_cloud")
    assert surface.scope.current() == "deck"
    a.scope._buttons["slide"].click()
    assert surface.scope.current() == "slide"



# -- row 3: the two task buttons and All actions… -----------------------------------------------------------------

def break_slide(env):
    slide_file(env).editor.replace_all_text(BROKEN)
    wait_until(lambda: "Fix LaTeX errors" in [b.label for b in header(env).offers("slide")])


def test_at_most_the_two_most_relevant_tasks_show_with_all_actions_last(env):
    go(env, CLOUD)
    break_slide(env)
    wait_until(lambda: shown(env) == ["Translate to German", "Fix LaTeX errors", "All actions…"])
    assert len(header(env).offers("slide")) == 3                      # the title task is offered, but not shown
    slide_file(env).editor.replace_all_text(PROSE)
    wait_until(lambda: shown(env) == ["Translate to German", "Make more concise", "All actions…"])
    area(env).scope._buttons["deck"].click()
    wait_until(lambda: shown(env) == ["Translate missing slides (2)", "Summarise this deck", "All actions…"])


def test_only_the_tasks_the_route_can_run_are_offered(env):
    break_slide(env)
    wait_until(lambda: shown(env) == ["Translate to German", "All actions…"])
    go(env, CLOUD)
    wait_until(lambda: shown(env) == ["Translate to German", "Fix LaTeX errors", "All actions…"])



def test_a_button_runs_the_task_through_the_task_runner(env, monkeypatch):
    go(env, CLOUD)
    started = []
    monkeypatch.setattr(area(env).tasks, "start", lambda task, paths=(), title="": started.append((task.name, paths)))
    refreshed(env)
    next(b for b in header(env).findChildren(Button) if b.text() == "Translate to German").click()
    assert started == [("translate", ())]


def test_all_actions_opens_the_command_palette(env):
    palette = env.window.palette
    assert not palette.isVisible()
    next(b for b in header(env).findChildren(Button) if b.text() == "All actions…").click()
    assert palette.isVisible()
    palette.hide()


def test_every_offered_task_is_a_palette_command_and_a_refused_one_says_why(env, monkeypatch):
    shown_messages = []
    env.window.toast.show_message = shown_messages.append
    break_slide(env)
    commands = env.window.commands
    visible = [c.id for c in commands if c.id.startswith("task:slide:") and c.visible(env.window)]
    assert visible == ["task:slide:translate", "task:slide:fix_latex", "task:slide:title"]
    assert {c.title(env.window) for c in commands if c.id in visible} == {"Translate to German", "Fix LaTeX errors", "Better title"}
    fix = next(c for c in commands if c.id in visible and c.title(env.window) == "Fix LaTeX errors")
    assert commands.run(fix.id, env.window)                                # Local cannot run it: the card asks for setup
    card = area(env).tasks.card
    assert card.phase == "setup_needed" and "is not available on Local · Fake local" in card.note
    assert area(env)._stack.currentWidget() is area(env).task_card
    assert not area(env).tasks.busy and not shown_messages
    area(env).scope._buttons["deck"].click()
    assert [c.title(env.window) for c in commands if c.id.startswith("task:deck:") and c.visible(env.window)] \
        == ["Translate missing slides (2)", "Fix LaTeX errors (1 slides)", "Summarise this deck"]


# -- row 4: the running pill ----------------------------------------------------------------------------------------

def test_a_running_task_shows_its_pill_with_open_and_the_buttons_wait(env):
    from fake_chat import FakeTaskRunner
    from slidemage.ai.task_result import CANCELLED, Outcome

    def delayed(task, captured, request, cancel, span):
        if cancel.wait(60):
            return Outcome(CANCELLED)
        return {"title": "T"}
    env.routes.cloud.runner = FakeTaskRunner(env.window.project, delayed)
    go(env, CLOUD)
    head = refreshed(env)
    assert not head.pill.isVisibleTo(head)
    bubble = next(b for b in head.offers("slide") if b.label == "Better title")
    area(env).run_task(bubble)
    assert area(env)._stack.currentWidget() is area(env).task_card and not head.pill.isVisibleTo(head)
    assert shown(env) == ["All actions…"]
    area(env).task_card.back.click()
    assert area(env)._stack.currentWidget() is area(env).surface_for("fake_cloud")
    assert head.pill.isVisibleTo(head) and head.pill.label.full_text() == "Better title · generating"
    assert shown(env) == ["All actions…"]
    head.pill.clicked.emit()
    assert area(env)._stack.currentWidget() is area(env).task_card and not head.pill.isVisibleTo(head)
    next(b for b in area(env).task_card.findChildren(Button) if b.text() == "Stop").click()
    wait_until(lambda: not area(env).tasks.busy)
    pump(0.1)
    assert area(env).tasks.card.phase == "stopped" and not head.pill.isVisibleTo(head)
    area(env).tasks.close_card()
    pump(0.1)
    assert "Translate to German" in shown(env)




















# -- a change of slide waits for the selection to rest (v8.39.9) --------------------------------------------------

def test_a_change_of_slide_works_the_offers_out_once_it_has_rested_and_switches_the_buttons_off_meanwhile(env, monkeypatch):
    from slidemage.ui.workspace import assistant_header

    head, state = header(env), env.window.state
    refreshed(env)
    buttons = head._task_buttons()
    assert buttons
    worked_out = []
    real = assistant_header.bubbles
    monkeypatch.setattr(assistant_header, "bubbles", lambda app: worked_out.append(1) or real(app))
    for slide in ("abd", "abc", "abd"):                       # a held arrow key
        state.set_focused_slide(slide)
    assert worked_out == [] and head._settle.isActive()       # nothing is worked out per row
    chosen = []
    head.task_chosen.connect(chosen.append)
    head.check_chosen.connect(chosen.append)
    for button in head._task_buttons():                       # the buttons belong to a slide that was left
        assert button.isEnabled()                             # not greyed out per click ...
        button.click()
    assert chosen == []                                       # ... but they do nothing
    wait_until(lambda: not head._settle.isActive())
    pump(0.05)
    assert len(worked_out) == 1
    assert head.target.full_text().startswith("abd")
