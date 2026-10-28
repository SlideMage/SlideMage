# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Keyboard and live-region support of the assistant (workspace v6, step 7): the Tab order of its header, the task
card's initial focus, focus kept on a phase's buttons and given back when the card closes, the announcements of its
phases and of an image batch's end, and the accessible names of the icons. The tasks run on the stand-in for `claude`
(fake_claude.py); the project is a throwaway one."""
from __future__ import annotations

import sys

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from test_claude_code_gui import env as claude_env, pump, wait_until  # noqa: F401 -- a fixture
from test_tasks_gui import buttons, click, fake  # noqa: F401 -- a fixture
from test_image_batches_gui import result_of

from slidemage.ai import ai_profile
from slidemage.ai.agent_types import EDIT_ASK
from slidemage.batch_result import CANCELLED, DONE, FAILED
from slidemage.ui.pages import image_results
from slidemage.ui.pages.image_results import BatchResultView
from slidemage.ui.workspace import task_card as task_card_module
from slidemage.ui.workspace import task_card_model as model

pytest.importorskip("PySide6.QtWebEngineWidgets")
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the stand-in for claude is a POSIX script")


def area(env):
    return env.window.assistant


def card(env):
    return area(env).tasks.card


def activate(env):
    env.window.activateWindow()
    pump(0.1)                                   # the window is active a moment later


def focus_on(env, widget):
    activate(env)
    widget.setFocus(Qt.FocusReason.TabFocusReason)
    assert QApplication.focusWidget() is widget
    return widget


def tab(times: int = 1) -> list:
    reached = []
    for _ in range(times):
        QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Tab)
        reached.append(QApplication.focusWidget())
    return reached


def action_buttons(env):
    layout = area(env).task_card._buttons
    return [layout.itemAt(i).widget() for i in range(layout.count())]


@pytest.fixture
def asked(fake):  # noqa: F811
    fake.env.window.assistant.chat.session.set_mode(EDIT_ASK)
    return fake


# -- the header -----------------------------------------------------------------------------------------------------

def test_the_headers_tab_order_is_focus_new_conversation_scope_tasks_all_actions_then_the_pill(fake):  # noqa: F811
    env = fake.env
    head = area(env).header
    wait_until(lambda: len(buttons(env)) >= 2)
    head.refresh_content()
    fake.reply({"answer": {"title": "T"}, "delay": 5})
    task_buttons = [w for w in (head._actions.itemAt(i).widget() for i in range(head._actions.count()))
                    if w is not head.all_actions]
    assert task_buttons                                                      # two contextual tasks on this slide
    scope = list(head.scope._buttons.values())
    first = focus_on(env, head.focus_button)
    expected = [head.new_button, scope[0], *task_buttons, head.all_actions]
    assert tab(len(expected)) == expected
    assert first is head.focus_button
    click(env, "Better title")                                               # its card, then Back: the pill
    area(env).task_card.back.click()
    wait_until(lambda: head.pill.isVisibleTo(head))
    assert head.pill.open_button.focusPolicy() == Qt.FocusPolicy.TabFocus
    assert head.pill.open_button.accessibleName() == f"Open: {head.pill.label.full_text()}"
    focus_on(env, head.all_actions)
    assert tab() == [head.pill.open_button]                                  # the pill comes after All actions…
    head.pill.open_button.click()                                            # the keyboard's Open
    assert area(env)._stack.currentWidget() is area(env).task_card
    area(env).task_card.back.click()
    area(env).tasks.stop()
    wait_until(lambda: card(env).phase == model.STOPPED)


def test_the_headers_icons_have_names(fake):  # noqa: F811
    head = area(fake.env).header
    assert head.ai_switch.segments.accessibleName() == "AI for all tasks"      # the route is the switch since v8.61.0
    assert head.focus_button.accessibleName().startswith("Focus assistant")
    assert head.new_button.accessibleName().startswith("New conversation")
    assert head.scope.accessibleName() == "Scope of the assistant"


# -- the task card --------------------------------------------------------------------------------------------------

def test_a_task_card_that_opens_takes_the_focus_on_its_first_action_and_keeps_it_across_phases(asked):
    env = asked.env
    activate(env)
    asked.reply({"answer": {"title": "A new title"}})
    click(env, "Better title")
    view = area(env).task_card
    wait_until(lambda: card(env).phase == model.REVIEW)
    assert [b.text() for b in action_buttons(env)][:1] == ["Apply"]
    assert QApplication.focusWidget() is action_buttons(env)[0]              # the primary action of the phase
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Return)            # Apply, with the keyboard
    wait_until(lambda: card(env).phase == model.DONE)
    focused = QApplication.focusWidget()
    assert focused is action_buttons(env)[0] and view.isAncestorOf(focused)  # kept on the new phase's first button
    assert view.steps_toggle.focusPolicy() == Qt.FocusPolicy.TabFocus and view.back.focusPolicy() == Qt.FocusPolicy.TabFocus


def test_closing_the_card_gives_the_keyboard_back_to_the_conversation(fake):  # noqa: F811
    env = fake.env
    activate(env)
    fake.reply({"answer": {"title": "T"}, "delay": 5})
    click(env, "Better title")
    assert QApplication.focusWidget() is action_buttons(env)[0]                  # Stop
    area(env).task_card.back.click()                                             # Back to conversation: the terminal
    assert not area(env).task_card.isAncestorOf(QApplication.focusWidget())
    area(env).tasks.show_card()
    area(env).tasks.stop()
    wait_until(lambda: card(env).phase == model.STOPPED)
    focus_on(env, action_buttons(env)[-1])                                       # Close
    action_buttons(env)[-1].click()
    assert card(env) is None and area(env)._stack.currentWidget() is area(env).surface_for("claude_code")


def test_closing_a_card_on_the_chat_route_focuses_the_message_box(fake):  # noqa: F811
    env = fake.env
    ai_profile.mark_cloud_seen(env.window.project)
    env.window.state.set_ai_route(ai_profile.LOCAL)
    pump(0.05)
    click(env, "Better title")                                                   # Local cannot run it: Setup needed
    assert card(env).phase == model.SETUP and area(env)._stack.currentWidget() is area(env).task_card
    close = focus_on(env, action_buttons(env)[-1])
    assert close.text() == "Close"
    close.click()
    assert area(env)._stack.currentWidget() is area(env).chat
    assert QApplication.focusWidget() is area(env).chat.composer


def test_the_state_line_is_announced_when_the_phase_changes_not_on_every_tick(asked, monkeypatch):
    env = asked.env
    told = []
    monkeypatch.setattr(task_card_module, "announce", lambda widget, text: told.append((widget, text)))
    asked.reply({"answer": {"title": "A new title"}, "delay": 1})
    click(env, "Better title")
    view = area(env).task_card
    generating = model.state_text(card(env))
    assert told == [(view.state, generating)]
    card(env).t0 -= 3
    area(env).tasks._tick()
    area(env).tasks._tick()
    assert len(told) == 1                                                        # the seconds are not announced
    wait_until(lambda: card(env).phase == model.REVIEW)
    assert told[-1] == (view.state, model.state_text(card(env))) and len(told) == 2
    action_buttons(env)[1].click()                                               # Reject
    assert card(env) is None


def test_the_step_icons_say_in_words_what_they_show_and_the_toggle_whether_it_is_open(asked):
    env = asked.env
    asked.reply({"answer": {"title": "A new title"}})
    click(env, "Better title")
    wait_until(lambda: card(env).phase == model.REVIEW)
    view = area(env).task_card
    assert view.route_icon.accessibleName() == "Cloud"
    assert view.steps_toggle.accessibleName() == "Steps · 1 of 4 done" and view.steps_toggle.accessibleDescription() == "Collapsed"
    view.steps_toggle.click()
    assert view.steps_toggle.accessibleDescription() == "Expanded"
    rows = view._steps
    names = [rows.itemAt(i).layout().itemAt(0).widget().accessibleName() for i in range(rows.count())]
    assert names == ["done", "in progress", "not started", "not started"]
    action_buttons(env)[1].click()


def test_every_icon_of_a_step_has_a_word():
    for icon in {step.icon for phase in (model.GENERATE, model.REVIEW, model.CONFLICT, model.PREVIEW_FAILED, model.STOPPED,
                                          model.SETUP, model.DONE)
                 for step in model.steps(SimpleCard(phase))}:
        assert icon in model.STEP_WORDS


class SimpleCard:
    """The few things `model.steps` reads of a card."""

    def __init__(self, phase):
        self.phase, self.skipped, self.auto, self.preview_skipped = phase, (), False, False


# -- the image results ----------------------------------------------------------------------------------------------

def test_the_end_of_a_batch_announces_the_results_title_and_summary(qapp, monkeypatch):
    told = []
    monkeypatch.setattr(image_results, "announce", lambda widget, text: told.append((widget, text)))
    panel = BatchResultView()
    result = result_of(a=DONE, b=FAILED, c=CANCELLED)
    panel.show_result(result)
    assert told == [(panel.title, f"{result.title}. {result.summary}")]
    assert panel.route_icon.accessibleName() == "Local"


def test_closing_the_results_panel_does_not_lose_the_keyboard(qapp, monkeypatch):
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    host = QWidget()
    layout = QVBoxLayout(host)
    panel = BatchResultView()
    after = QWidget()
    after.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    layout.addWidget(panel)
    layout.addWidget(after)
    host.show()
    panel.closed.connect(panel.clear)
    panel.show_result(result_of(a=DONE, b=FAILED))
    host.activateWindow()
    qapp.processEvents()
    assert [panel.retry.focusPolicy(), panel.close_button.focusPolicy()] == [Qt.FocusPolicy.TabFocus] * 2
    panel.close_button.setFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(panel.close_button, Qt.Key.Key_Return)                        # Close with the keyboard
    assert not panel.isVisible()
    assert QApplication.focusWidget() is after
    host.deleteLater()


def test_the_assistants_results_panel_hands_the_keyboard_back_to_the_conversation(fake):  # noqa: F811
    env = fake.env
    ai_profile.mark_cloud_seen(env.window.project)
    env.window.state.set_ai_route(ai_profile.LOCAL)
    pump(0.05)
    tasks = area(env).tasks
    tasks.result = result_of(a=DONE, b=FAILED)
    tasks.result_changed.emit()
    assert area(env)._stack.currentWidget() is area(env)._results_page
    focus_on(env, area(env).image_results.close_button)
    QTest.keyClick(area(env).image_results.close_button, Qt.Key.Key_Space)
    assert area(env)._stack.currentWidget() is area(env).chat and tasks.result is None
    assert QApplication.focusWidget() is area(env).chat.composer
