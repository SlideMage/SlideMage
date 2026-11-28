# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Assistant body, route, scope, task buttons and running pill on scripted routes."""
from __future__ import annotations

import pytest

from assistant_accessibility_helpers import BROKEN, LF, env as assistant_env, pump, slide_file, wait_until  # noqa: F401
from slidemage.ai import ai_profile
from slidemage.ui.kit.widgets import Button

LOCAL, CLOUD = ai_profile.LOCAL, ai_profile.CLOUD


@pytest.fixture(name="env")
def _env(assistant_env):  # noqa: F811
    return assistant_env


def shown(env) -> list[str]:
    head = env.window.assistant.header
    buttons = (head._actions.itemAt(i).widget() for i in range(head._actions.count()))
    return [b.text() for b in buttons if b.isVisibleTo(head)]


def go(env, mode):
    ai_profile.mark_cloud_seen(env.window.project)
    env.window.state.set_ai_route(mode)
    pump(0.05)


def refreshed(env):
    head = env.window.assistant.header
    head.refresh_content()
    return head


def test_leaving_a_live_route_surface_asks_to_end_the_session(env):
    assistant = env.window.assistant
    assert assistant._stack.currentWidget() is assistant.chat
    go(env, CLOUD)
    surface = assistant.surface_for("fake_cloud")
    assert assistant._stack.currentWidget() is surface
    surface.session_live = True
    env.window.ai_route.request(LOCAL)
    assert env.window.ai_route.popover_kind == "session"
    assert surface.session_live and env.window.state.ai_route == "fake_cloud"
    env.window.ai_route._popover.spec.actions[-1][2]()
    assert env.window.state.ai_route == "fake_local" and not surface.session_live
    assert assistant._stack.currentWidget() is assistant.chat


def test_new_conversation_clears_only_the_route_on_show(env):
    assistant = env.window.assistant
    chat = assistant.chat
    assert not hasattr(chat, "new_button")
    chat.composer.setPlainText("local draft")
    chat.session.history.append("local history")
    go(env, CLOUD)
    surface = assistant.surface_for("fake_cloud")
    surface.composer.setText("cloud message")
    surface.send()
    assistant.header.new_button.click()
    assert surface.turns == [] and surface.restarts == [("", False)]
    go(env, LOCAL)
    assert chat.composer.toPlainText() == "local draft" and chat.session.history == ["local history"]
    assistant.header.new_button.click()
    assert chat.session.history == []


def test_the_scope_tracks_the_target_and_is_shared_between_routes(env):
    assistant = env.window.assistant
    head = refreshed(env)
    assert head.target.full_text() == "abc · Hello" and assistant.chat.scope is assistant.scope
    assistant.scope._buttons["deck"].click()
    assert assistant.chat.scope.current() == "deck" and head.target.full_text() == "test · 2 slides"
    go(env, CLOUD)
    surface = assistant.surface_for("fake_cloud")
    assert surface.scope.current() == "deck"
    assistant.scope._buttons["slide"].click()
    assert surface.scope.current() == "slide"
    editor = slide_file(env).editor
    editor.set_read_only(True)
    editor.replace_all_text(LF + "% typed\n")
    wait_until(lambda: head.target.full_text() == "abc · Hello · not saved")
    editor.undo()
    editor.set_read_only(False)
    wait_until(lambda: head.target.full_text() == "abc · Hello")
    env.window.centre.open_file(env.root / "decks" / "test.tex")
    wait_until(lambda: head.target.full_text() == "test.tex")
    env.window.state.set_focused_slide("abd")
    wait_until(lambda: head.target.full_text() == "abd · Second")


def break_slide(env):
    slide_file(env).editor.replace_all_text(BROKEN)
    wait_until(lambda: "Fix LaTeX errors" in [b.label for b in env.window.assistant.header.offers("slide")])


def test_task_buttons_follow_route_readiness_and_offer_the_top_two(env, monkeypatch):
    break_slide(env)
    wait_until(lambda: shown(env) == ["Translate to German", "All actions…"])
    go(env, CLOUD)
    assistant = env.window.assistant
    surface = assistant.surface_for("fake_cloud")
    surface.needs_setup = True
    surface.setup_changed.emit()
    wait_until(lambda: shown(env) == ["All actions…"])
    assert env.window.state.ai_route == "fake_cloud"
    surface.needs_setup = False
    surface.setup_changed.emit()
    wait_until(lambda: shown(env) == ["Translate to German", "Fix LaTeX errors", "All actions…"])
    assert len(assistant.header.offers("slide")) == 3
    started = []
    monkeypatch.setattr(assistant.tasks, "start", lambda task, paths=(), title="": started.append((task.name, paths)))
    next(b for b in assistant.header.findChildren(Button) if b.text() == "Translate to German").click()
    assert started == [("translate", ())]
    slide_file(env).editor.replace_all_text(LF)
    assistant.scope._buttons["deck"].click()
    wait_until(lambda: shown(env) == ["Translate missing slides (2)", "Summarise this deck", "All actions…"])


def test_all_actions_opens_the_command_palette(env):
    palette = env.window.palette
    assert not palette.isVisible()
    next(b for b in env.window.assistant.header.findChildren(Button) if b.text() == "All actions…").click()
    assert palette.isVisible()
    palette.hide()


def test_every_offered_task_is_a_palette_command_and_a_refused_one_says_why(env):
    shown_messages = []
    env.window.toast.show_message = shown_messages.append
    break_slide(env)
    commands = env.window.commands
    visible = [c.id for c in commands if c.id.startswith("task:slide:") and c.visible(env.window)]
    assert visible == ["task:slide:translate", "task:slide:fix_latex", "task:slide:title"]
    assert {c.title(env.window) for c in commands if c.id in visible} == {"Translate to German", "Fix LaTeX errors", "Better title"}
    assert commands.run("task:slide:fix_latex", env.window)
    card = env.window.assistant.tasks.card
    assert card.phase == "setup_needed" and "is not available on Local · Fake local" in card.note
    assert env.window.assistant._stack.currentWidget() is env.window.assistant.task_card
    assert not env.window.assistant.tasks.busy and not shown_messages
    env.window.assistant.scope._buttons["deck"].click()
    assert [c.title(env.window) for c in commands if c.id.startswith("task:deck:") and c.visible(env.window)] \
        == ["Translate missing slides (2)", "Fix LaTeX errors (1 slides)", "Summarise this deck"]


def test_a_running_task_shows_its_pill_with_open_and_the_buttons_wait(env):
    from fake_chat import FakeTaskRunner
    from slidemage.ai.task_result import CANCELLED, Outcome

    def delayed(task, captured, request, cancel, span):
        if cancel.wait(60):
            return Outcome(CANCELLED)
        return {"title": "T"}
    env.routes.cloud.runner = FakeTaskRunner(env.window.project, delayed)
    go(env, CLOUD)
    assistant = env.window.assistant
    head = refreshed(env)
    assert not head.pill.isVisibleTo(head)
    bubble = next(b for b in head.offers("slide") if b.label == "Better title")
    assistant.run_task(bubble)
    assert assistant._stack.currentWidget() is assistant.task_card and not head.pill.isVisibleTo(head)
    assert shown(env) == ["All actions…"]
    assistant.task_card.back.click()
    assert assistant._stack.currentWidget() is assistant.surface_for("fake_cloud")
    assert head.pill.isVisibleTo(head) and head.pill.label.full_text() == "Better title · generating"
    assert shown(env) == ["All actions…"]
    head.pill.clicked.emit()
    assert assistant._stack.currentWidget() is assistant.task_card and not head.pill.isVisibleTo(head)
    next(b for b in assistant.task_card.findChildren(Button) if b.text() == "Stop").click()
    wait_until(lambda: not assistant.tasks.busy)
    pump(0.1)
    assert assistant.tasks.card.phase == "stopped" and not head.pill.isVisibleTo(head)
    assistant.tasks.close_card()
    pump(0.1)
    assert "Translate to German" in shown(env)


def test_slide_selection_defers_rebuilding_and_disables_stale_actions(env, monkeypatch):
    from slidemage.ui.workspace import assistant_header

    head, state = env.window.assistant.header, env.window.state
    refreshed(env)
    buttons = head._task_buttons()
    assert buttons
    worked_out = []
    real = assistant_header.bubbles
    monkeypatch.setattr(assistant_header, "bubbles", lambda app: worked_out.append(1) or real(app))
    for slide in ("abd", "abc", "abd"):
        state.set_focused_slide(slide)
    assert worked_out == [] and head._settle.isActive()
    chosen = []
    head.task_chosen.connect(chosen.append)
    head.check_chosen.connect(chosen.append)
    for button in head._task_buttons():
        assert button.isEnabled()
        button.click()
    assert chosen == []
    wait_until(lambda: not head._settle.isActive())
    pump(0.05)
    assert len(worked_out) == 1
    assert head.target.full_text().startswith("abd")
