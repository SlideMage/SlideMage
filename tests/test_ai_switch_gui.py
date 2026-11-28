# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""AI route switching and setup with in-memory routes."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel

from slidemage.ai import ai_profile
from slidemage.ai.ai_profile import CLOUD, LOCAL
from slidemage.ai import routes
from fake_chat import FakeChatSurface
from fake_routes import FakeRoute
from slidemage.ui.kit.fonts import load_fonts
from slidemage.ui.workspace.ai_work import RunningWork
from conftest import build_window, qapp as qapp

@pytest.fixture
def window(qapp, monkeypatch, fake_routes):
    assert load_fonts()
    fake_routes.cloud.surface_factory = FakeChatSurface
    routes.register(FakeRoute(id="second_cloud", service="Second cloud"))
    window = build_window(monkeypatch)
    window.resize(1700, 800)
    window.show()
    window.state.set_mode("source")           # no preview render
    qapp.processEvents()
    return window


class Work:
    """AI work the test starts and ends: what a source of ai_work.py would report."""

    def __init__(self, window, monkeypatch, text="Update DE translation · 1y8", route="Fake cloud · fake-1"):
        self.running, self.stopped = True, []
        self.item = lambda: RunningWork(text, route, False, lambda: self.stopped.append(True))
        monkeypatch.setattr(window.assistant.chat, "running_work", lambda: [self.item()] if self.running else [])


def route(window):
    return window.ai_route


def kind(window):
    return window.ai_route.popover_kind


def press_escape(window):
    QTest.keyClick(window.ai_route._popover, Qt.Key.Key_Escape)


def choose_primary(window):
    window.ai_route._popover.spec.actions[-1][2]()
    window.ai_route._popover.close()


def settle(qapp, window):
    window.ai_route._on_watch()
    qapp.processEvents()


def test_local_policy_requires_a_cloud_decision_every_time(window, qapp):
    window.commands.run("ai:cloud", window)
    assert kind(window) == "policy" and window.state.ai_mode == LOCAL
    QTest.mouseClick(window.slide_list, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
    qapp.processEvents()
    assert kind(window) == "policy"
    popover = route(window)._popover
    popover.spec.link[1]()
    popover.close()
    assert kind(window) == "" and route(window).setup.isVisible() and window.state.ai_mode == LOCAL
    route(window).setup.close()

    route(window).request(CLOUD)
    press_escape(window)
    assert kind(window) == "" and window.state.ai_mode == LOCAL
    route(window).request(CLOUD)
    choose_primary(window)
    assert window.state.ai_mode == CLOUD and ai_profile.policy(window.project) == LOCAL
    window.commands.run("ai:local", window)
    assert kind(window) == "" and window.state.ai_mode == LOCAL
    route(window).request(CLOUD)
    assert kind(window) == "policy"


def test_the_first_use_popover_is_asked_once_per_project(window):
    ai_profile.set_policy(window.project, CLOUD)
    window.state.set_ai_route(LOCAL)
    route(window).request(CLOUD)
    assert kind(window) == "first" and not ai_profile.cloud_seen(window.project)
    press_escape(window)
    assert window.state.ai_mode == LOCAL and not ai_profile.cloud_seen(window.project)
    route(window).request(CLOUD)
    choose_primary(window)
    assert window.state.ai_mode == CLOUD and ai_profile.cloud_seen(window.project)
    route(window).request(LOCAL)
    route(window).request(CLOUD)
    assert kind(window) == "" and window.state.ai_mode == CLOUD


def test_stop_and_switch_waits_for_the_end_of_the_work_and_then_asks_the_rest_of_the_flow(window, monkeypatch, qapp):
    work = Work(window, monkeypatch)
    route(window).request(CLOUD)
    assert kind(window) == "busy" and "Update DE translation" in route(window)._popover.spec.lines[0]
    press_escape(window)
    assert window.state.ai_mode == LOCAL and kind(window) == "" and not work.stopped
    route(window).request(CLOUD)
    choose_primary(window)
    assert work.stopped == [True] and route(window).stopping and window.ai_switch.state_label.text() == "stopping…"
    settle(qapp, window)
    assert route(window).stopping and window.state.ai_mode == LOCAL     # the work is still ending
    route(window).request(LOCAL)                                        # a request while stopping is ignored
    work.running = False
    settle(qapp, window)
    assert not route(window).stopping and window.ai_switch.state_label.text() == ""
    assert kind(window) == "policy"                                     # the checks still apply
    choose_primary(window)
    assert window.state.ai_mode == CLOUD


def test_work_that_ends_by_itself_turns_the_popover_into_the_finished_one(window, monkeypatch, qapp):
    ai_profile.set_policy(window.project, CLOUD)
    ai_profile.mark_cloud_seen(window.project)
    work = Work(window, monkeypatch)
    route(window).request(CLOUD)
    work.running = False
    settle(qapp, window)
    assert kind(window) == "finished" and not work.stopped
    choose_primary(window)
    assert window.state.ai_mode == CLOUD


def test_the_session_popover_asks_before_a_route_session_is_ended(window):
    window.state.set_ai_route(CLOUD)
    surface = window.assistant.surface_for("fake_cloud")
    surface.session_live = True
    route(window).request(LOCAL)
    assert kind(window) == "session"
    press_escape(window)
    assert surface.session_live and window.state.ai_mode == CLOUD
    route(window).request(LOCAL)
    choose_primary(window)
    assert not surface.session_live and window.state.ai_mode == LOCAL


def commit_to_cloud(window):
    ai_profile.set_policy(window.project, CLOUD)
    ai_profile.mark_cloud_seen(window.project)
    route(window).request(CLOUD)


def test_the_assistant_switch_keeps_running_status_when_narrow(window, monkeypatch):
    from slidemage.ui.workspace.assistant_header import SWITCH_LABELS_WIDTH, SWITCH_NAMED_WIDTH

    header, switch = window.assistant.header, window.ai_switch
    assert switch is header.ai_switch and header.isAncestorOf(switch)
    commit_to_cloud(window)
    work = Work(window, monkeypatch)
    header.resizeEvent(QResizeEvent(QSize(SWITCH_NAMED_WIDTH, header.height()), header.size()))
    route(window)._show_running()
    assert switch.state_label.text() == "Fake cloud · running"
    header.resizeEvent(QResizeEvent(QSize(SWITCH_LABELS_WIDTH - 1, header.height()), header.size()))
    assert switch.state_label.text() == "running"
    assert all(not button.text() for button in switch.segments._buttons.values())
    work.running = False
    route(window)._show_running()
    assert not switch.state_label.isVisible()


def test_switching_routes_keeps_drafts_and_conversation_without_sending(window, fake_routes):
    chat = window.assistant.chat
    chat.composer.setPlainText("a Local draft")
    chat.session.history.append("local history")
    seen = []
    window.state.ai_route_changed.connect(seen.append)
    commit_to_cloud(window)
    surface = window.assistant.surface_for("fake_cloud")
    assert window.assistant._stack.currentWidget() is surface
    assert window.ai_switch.segments.current() == CLOUD and seen == ["fake_cloud"]
    commit_to_cloud(window)
    assert seen == ["fake_cloud"]
    surface.composer.setText("a Cloud draft")
    route(window).request(LOCAL)
    assert window.assistant._stack.currentWidget() is chat and seen[-1] == "fake_local"
    assert chat.composer.toPlainText() == "a Local draft" and chat.session.history == ["local history"]
    commit_to_cloud(window)
    assert surface.composer.text() == "a Cloud draft" and not fake_routes.cloud.providers


def test_the_arrow_keys_and_enter_move_the_switch_and_only_the_current_segment_is_a_tab_stop(window, qapp):
    commit_to_cloud(window)
    route(window).request(LOCAL)
    segments = window.ai_switch.segments
    buttons = segments._buttons
    assert buttons[LOCAL].focusPolicy() == Qt.FocusPolicy.TabFocus and buttons[CLOUD].focusPolicy() == Qt.FocusPolicy.NoFocus
    buttons[LOCAL].setFocus()
    QTest.keyClick(buttons[LOCAL], Qt.Key.Key_Right)
    assert window.state.ai_mode == CLOUD and segments.current() == CLOUD
    assert buttons[CLOUD].focusPolicy() == Qt.FocusPolicy.TabFocus and buttons[LOCAL].focusPolicy() == Qt.FocusPolicy.NoFocus
    QTest.keyClick(buttons[CLOUD], Qt.Key.Key_Left)
    assert window.state.ai_mode == LOCAL
    QTest.keyClick(buttons[LOCAL], Qt.Key.Key_Return)                  # activating the current one changes nothing
    assert window.state.ai_mode == LOCAL and kind(window) == ""
    ai_profile.set_policy(window.project, LOCAL)
    QTest.keyClick(buttons[LOCAL], Qt.Key.Key_Right)
    assert kind(window) == "policy" and segments.current() == LOCAL    # the switch shows what is, until it is committed


def open_setup(window):
    window.ai_switch.caret.click()
    return window.ai_route.setup


def test_ai_setup_saves_inactive_defaults_without_changing_the_current_route(window):
    setup = open_setup(window)
    cloud_chat = setup.cells[(CLOUD, ai_profile.CHAT)]
    assert cloud_chat.isEnabled()
    cloud_chat.setCurrentIndex(cloud_chat.findData("fake-2"))
    cloud_chat.activated.emit(cloud_chat.currentIndex())
    assert ai_profile.model_choice(window.project, "fake_cloud", ai_profile.CHAT) == "fake-2"
    setup.refresh()
    assert cloud_chat.currentData() == "fake-2"
    image = setup.cells[(LOCAL, ai_profile.IMAGE_DESCRIPTION)]
    image.setCurrentIndex(image.findData("fake-2"))
    image.activated.emit(image.currentIndex())
    assert window.images_page.draft_model.currentData() == "fake-2"
    assert ai_profile.model_choice(window.project, "fake_local", ai_profile.CHAT) == "fake-1"
    setup.policy.changed.emit(CLOUD)
    assert ai_profile.policy(window.project) == CLOUD and window.state.ai_mode == LOCAL


def test_a_new_default_asks_a_running_route_session_to_switch_or_start_afresh(window, monkeypatch, fake_routes):
    from slidemage.ui.workspace import ai_setup
    surface = window.assistant.surface_for("fake_cloud")
    surface.session_live = True
    monkeypatch.setattr(fake_routes.cloud, "default_choice", lambda task: "")
    setup = open_setup(window)
    cloud_chat = setup.cells[(CLOUD, ai_profile.CHAT)]
    asked = []
    def pick(choice, answer):
        surface.session_live = True
        monkeypatch.setattr(ai_setup, "ask_session_model", lambda _parent, label, _service: asked.append(label) or answer)
        cloud_chat.setCurrentIndex(cloud_chat.findData(choice))
        cloud_chat.activated.emit(cloud_chat.currentIndex())
        return window.toast.findChildren(QLabel)[0].text()
    assert pick("fake-2", ai_setup.SWITCH).endswith("switches to it and continues the conversation.")
    assert asked == ["FAKE-2"] and surface.restarts == [("fake-2", True)]
    assert pick("fake-1", ai_setup.NEW_CONVERSATION).endswith("restarted on it with a new conversation.")
    assert surface.restarts[-1] == ("fake-1", False)
    assert pick("fake-2", None).endswith("keeps its model until it is restarted.")


def test_ai_setup_lists_show_full_model_names_when_opened(window, fake_routes, qapp):
    long_name = "a-very-long-model-name-that-does-not-fit-the-closed-combo-box"
    fake_routes.local.choices.append(long_name)
    setup = open_setup(window)
    combo = setup.cells[(LOCAL, ai_profile.TRANSLATION)]
    index = combo.findData(long_name)
    assert index >= 0
    combo.setCurrentIndex(index)
    combo.activated.emit(index)
    assert combo.width() < combo.view().fontMetrics().horizontalAdvance(long_name.upper())
    combo.showPopup()
    qapp.processEvents()
    assert combo.view().width() >= combo.view().fontMetrics().horizontalAdvance(long_name.upper())
    combo.hidePopup()


def test_the_cloud_connection_of_ai_setup_changes_the_route_like_the_switch_when_on_cloud(window, monkeypatch):
    setup = open_setup(window)
    setup.conn.changed.emit("second_cloud")
    assert ai_profile.cloud_conn(window.project) == "second_cloud" and window.state.ai_route == "fake_local"
    commit_to_cloud(window)
    assert window.state.ai_route == "second_cloud"
    setup = open_setup(window) if not window.ai_route.setup.isVisible() else window.ai_route.setup
    setup.conn.changed.emit("fake_cloud")
    assert window.state.ai_route == "fake_cloud"
    Work(window, monkeypatch)
    setup.conn.changed.emit("second_cloud")
    assert kind(window) == "busy" and window.state.ai_route == "fake_cloud"
    assert setup.conn.current() == "fake_cloud"


def test_ai_setup_closes_on_escape_and_on_a_click_outside_but_not_on_its_anchor(window, qapp):
    setup = open_setup(window)
    QTest.keyClick(setup, Qt.Key.Key_Escape)
    assert not setup.isVisible()
    setup = open_setup(window)
    # Click through the window so the popover's catcher receives it on Windows.
    QTest.mouseClick(window.windowHandle(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     window.slide_list.mapTo(window, QPoint(5, 5)))
    qapp.processEvents()
    assert not setup.isVisible()
    open_setup(window)
    window.ai_switch.caret.click()                                  # the ▾ again closes it
    assert not window.ai_route.setup.isVisible()


def test_settings_link_opens_the_ai_tab(window, monkeypatch):
    opened = []
    monkeypatch.setattr(type(window), "open_settings", lambda self, tab=0: opened.append(tab))
    window.commands.run("ai:setup", window)
    setup = route(window).setup
    assert setup.isVisible()
    setup._open_settings()
    from slidemage.ui.dialogs.settings import AI
    assert opened == [AI] and not setup.isVisible()
