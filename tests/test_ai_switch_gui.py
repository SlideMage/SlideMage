"""The AI switch of the top bar (workspace v6, step 2): its request flow and popovers, the commit (labels, pickers,
per-route conversations, toast), AI setup, the keyboard, and the commands. Nothing here reaches Ollama or the cloud."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from slidemage.ai import ai_profile
from slidemage.ai.ai_profile import API, CLAUDE_CODE, CLOUD, LOCAL
from slidemage.ai.providers import InstalledModel, OllamaProvider
from slidemage.ui.kit.fonts import load_fonts
from slidemage.ui.workspace.ai_work import RunningWork
from conftest import build_window, qapp as qapp

INSTALLED = [InstalledModel("chat-model", 1, "", ("tools",)), InstalledModel("vision-model", 1, "", ("vision",)),
             InstalledModel("plain-model", 1, "")]


@pytest.fixture
def window(qapp, monkeypatch):
    assert load_fonts()
    monkeypatch.setattr(OllamaProvider, "installed", lambda self, **_: list(INSTALLED))
    window = build_window(monkeypatch)
    window.resize(1700, 800)
    window.show()
    window.state.set_mode("source")           # no preview render
    qapp.processEvents()
    return window


class Work:
    """AI work the test starts and ends: what a source of ai_work.py would report."""

    def __init__(self, window, monkeypatch, text="Update DE translation · 1y8", route="Claude Code · Haiku · effort medium"):
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


# -- the state -----------------------------------------------------------------------------------

def test_the_state_follows_ai_profile_and_tells_only_about_a_changed_route(window):
    seen = []
    window.state.ai_route_changed.connect(seen.append)
    assert (window.state.ai_mode, window.state.ai_route) == (LOCAL, LOCAL)
    assert window.state.set_ai_route(CLOUD) and seen == [CLAUDE_CODE]
    assert not window.state.set_ai_route(CLOUD) and seen == [CLAUDE_CODE]
    assert window.state.set_ai_route(CLOUD, API) and seen == [CLAUDE_CODE, API]
    assert window.state.set_ai_route(LOCAL) and seen[-1] == LOCAL
    assert not window.state.set_ai_route(LOCAL, CLAUDE_CODE)           # the connection matters only on Cloud
    assert ai_profile.cloud_conn(window.project) == CLAUDE_CODE


# -- the request flow ------------------------------------------------------------------------------

def test_to_cloud_while_the_project_is_local_warns_every_time_and_replaces_the_first_use_question(window):
    ai_profile.mark_cloud_seen(window.project)
    route(window).request(CLOUD)
    assert kind(window) == "policy" and window.state.ai_mode == LOCAL
    popover = route(window)._popover
    assert popover.width() == 360 and [a[0] for a in popover.spec.actions] == ["Cancel", "Switch to Cloud for this session"]
    press_escape(window)                                               # Esc is the secondary button
    assert kind(window) == "" and window.state.ai_mode == LOCAL
    route(window).request(CLOUD)
    choose_primary(window)
    assert window.state.ai_mode == CLOUD and ai_profile.policy(window.project) == LOCAL    # the setting stays
    route(window).request(LOCAL)
    assert kind(window) == "" and window.state.ai_mode == LOCAL        # going back asks nothing
    route(window).request(CLOUD)
    assert kind(window) == "policy"                                     # and every time again


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


def test_a_click_outside_does_not_dismiss_a_decision_popover(window, qapp):
    route(window).request(CLOUD)
    assert kind(window) == "policy"
    QTest.mouseClick(window.slide_list, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
    qapp.processEvents()
    assert kind(window) == "policy"


def test_the_policy_popover_links_to_ai_setup(window):
    route(window).request(CLOUD)
    window.ai_route._popover.spec.link[1]()
    window.ai_route._popover.close()
    assert kind(window) == "" and window.ai_route.setup.isVisible() and window.state.ai_mode == LOCAL


def test_running_work_stops_the_switch_with_a_busy_popover_that_lists_it_and_keep_running_leaves_it(window, monkeypatch):
    work = Work(window, monkeypatch)
    route(window).request(CLOUD)
    popover = route(window)._popover
    assert kind(window) == "busy" and popover.spec.title == "AI work is running"
    assert popover.spec.lines == ("Update DE translation · 1y8 · Claude Code · Haiku · effort medium",)
    assert [a[0] for a in popover.spec.actions] == ["Keep running", "Stop and switch"]
    press_escape(window)
    assert window.state.ai_mode == LOCAL and kind(window) == "" and work.stopped == []


def test_stop_and_switch_waits_for_the_end_of_the_work_and_then_asks_the_rest_of_the_flow(window, monkeypatch, qapp):
    work = Work(window, monkeypatch)
    route(window).request(CLOUD)
    choose_primary(window)
    assert work.stopped == [True] and route(window).stopping and window.topbar.ai_switch.state_label.text() == "stopping…"
    settle(qapp, window)
    assert route(window).stopping and window.state.ai_mode == LOCAL     # the work is still ending
    route(window).request(LOCAL)                                        # a request while stopping is ignored
    work.running = False
    settle(qapp, window)
    assert not route(window).stopping and window.topbar.ai_switch.state_label.text() == ""
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
    popover = route(window)._popover
    assert kind(window) == "finished" and popover.spec.title == "The running work has finished"
    assert [a[0] for a in popover.spec.actions] == ["Cancel", "Switch now"]
    choose_primary(window)
    assert window.state.ai_mode == CLOUD


def test_the_session_popover_asks_before_the_claude_code_terminal_is_ended(window, monkeypatch):
    window.state.set_ai_route(CLOUD)
    claude = window.assistant.claude_code
    ended = []
    monkeypatch.setattr(type(claude), "session_live", property(lambda self: not ended))
    monkeypatch.setattr(claude, "end_session", lambda: ended.append(True))
    route(window).request(LOCAL)
    popover = route(window)._popover
    assert kind(window) == "session" and [a[0] for a in popover.spec.actions] == ["Stay", "End session and switch"]
    press_escape(window)
    assert ended == [] and window.state.ai_mode == CLOUD
    route(window).request(LOCAL)
    choose_primary(window)
    assert ended == [True] and window.state.ai_mode == LOCAL
    window.state.set_ai_route(CLOUD, API)
    ended.clear()
    route(window).request(CLOUD, CLAUDE_CODE)                           # another connection is no session to end
    assert kind(window) == "" and window.state.ai_route == CLAUDE_CODE


# -- the commit ----------------------------------------------------------------------------------

def commit_to_cloud(window):
    ai_profile.set_policy(window.project, CLOUD)
    ai_profile.mark_cloud_seen(window.project)
    route(window).request(CLOUD)


def test_a_commit_sets_the_route_tells_everyone_and_sends_nothing(window, qapp):
    commit_to_cloud(window)
    switch = window.topbar.ai_switch
    assert window.state.ai_route == CLAUDE_CODE and switch.segments.current() == CLOUD
    assert switch.property("cloud") is True and switch.state_label.text() == "Claude Code"
    assert switch.toolTip() == "Cloud · Claude Code · AI requests send content to the cloud"
    assert window.toast.isVisible() and window.toast.findChildren(type(switch.state_label))[0].text() == \
        "All AI tasks now use Cloud · Claude Code"
    assert window.assistant.chat.route_chip.text().startswith("Claude Code")
    assert window.images_page.draft_model.currentText() == "Haiku · medium"       # the pickers follow the route
    route(window).request(LOCAL)
    assert window.toast.findChildren(type(switch.state_label))[0].text() == \
        "All AI tasks use Local · Ollama again. Your Ollama models are restored."
    assert window.assistant.chat.route_chip.text().endswith("· Ollama")
    assert window.assistant.chat.session.running is False


def test_the_switch_reads_running_and_drops_the_name_below_1320_px(window, monkeypatch, qapp):
    commit_to_cloud(window)
    work = Work(window, monkeypatch)
    route(window)._show_running()
    switch = window.topbar.ai_switch
    assert switch.state_label.text() == "Claude Code · running"
    switch.set_shrink(1)
    assert switch.state_label.text() == "running"
    work.running = False
    route(window)._show_running()
    assert not switch.state_label.isVisible()


def test_each_route_keeps_its_own_draft_and_conversation(window, monkeypatch):
    chat = window.assistant.chat
    chat.composer.setPlainText("a Local draft")
    chat.session.history.append("local history")
    chat._add(chat.status.__class__())             # a message widget of the Local conversation
    local_messages = chat._messages.count()
    commit_to_cloud(window)
    assert chat.composer.toPlainText() == "" and chat.session.history == [] and chat._messages.count() == 3
    assert not chat._empty.isHidden()
    chat.composer.setPlainText("a Cloud draft")
    route(window).request(CLOUD, API)
    assert chat.composer.toPlainText() == ""
    route(window).request(CLOUD, CLAUDE_CODE)
    assert chat.composer.toPlainText() == "a Cloud draft"
    route(window).request(LOCAL)
    assert chat.composer.toPlainText() == "a Local draft" and chat.session.history == ["local history"]
    assert chat._messages.count() == local_messages
    chat.new_chat()                                                  # clears this route only
    commit_to_cloud(window)
    assert chat.composer.toPlainText() == "a Cloud draft"


# -- the keyboard --------------------------------------------------------------------------------

def test_the_arrow_keys_and_enter_move_the_switch_and_only_the_current_segment_is_a_tab_stop(window, qapp):
    commit_to_cloud(window)
    route(window).request(LOCAL)
    segments = window.topbar.ai_switch.segments
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


# -- AI setup ------------------------------------------------------------------------------------

def open_setup(window):
    window.topbar.ai_switch.caret.click()
    return window.ai_route.setup


def test_ai_setup_saves_every_cell_as_a_default_and_says_so(window, qapp):
    window.local_models.fill(INSTALLED)
    setup = open_setup(window)
    assert setup.isVisible() and setup.width() == 480
    chat, image = setup.cells[(LOCAL, ai_profile.CHAT)], setup.cells[(LOCAL, ai_profile.IMAGE_DESCRIPTION)]
    assert [chat.itemData(i) for i in range(chat.count())] == ["", "chat-model"]            # models that call tools
    assert [image.itemData(i) for i in range(image.count())] == ["", "vision-model"]
    assert setup.heads[CLAUDE_CODE].text() == "Cloud · Claude Code"
    cloud_chat = setup.cells[(CLOUD, ai_profile.CHAT)]
    assert cloud_chat.isVisible() and cloud_chat.currentData() == ""
    cloud_chat.setCurrentIndex(cloud_chat.findData("sonnet:high"))
    cloud_chat.activated.emit(cloud_chat.currentIndex())
    assert ai_profile.model_choice(window.project, CLAUDE_CODE, ai_profile.CHAT) == "sonnet:high"
    setup.refresh()
    assert cloud_chat.currentData() == "sonnet:high"
    assert ai_profile.route_for(window.project, CLAUDE_CODE, ai_profile.CHAT).model == "sonnet"
    image.setCurrentIndex(1)
    image.activated.emit(1)
    assert ai_profile.model_choice(window.project, LOCAL, ai_profile.IMAGE_DESCRIPTION) == "vision-model"
    assert window.toast.findChildren(type(setup.heads[LOCAL]))[0].text() == \
        "Default for Local · Image descriptions: vision-model"
    assert window.images_page.draft_model.currentData() == "vision-model"      # the pickers start on it
    cloud = setup.cells[(CLOUD, ai_profile.TRANSLATION)]
    cloud.setCurrentIndex(cloud.findData("opus:high"))
    cloud.activated.emit(cloud.currentIndex())
    assert ai_profile.model_choice(window.project, CLAUDE_CODE, ai_profile.TRANSLATION) == "opus:high"
    assert ai_profile.model_choice(window.project, LOCAL, ai_profile.TRANSLATION) == ""      # each side its own


def test_the_side_not_in_use_is_greyed_but_editable(window):
    setup = open_setup(window)
    assert setup.cells[(CLOUD, ai_profile.FIXES)].property("active") is False
    assert setup.cells[(LOCAL, ai_profile.FIXES)].property("active") is True
    assert setup.cells[(CLOUD, ai_profile.FIXES)].isEnabled()


def test_the_cloud_connection_of_ai_setup_changes_the_route_like_the_switch_when_on_cloud(window, monkeypatch):
    setup = open_setup(window)
    setup.conn.changed.emit(API)                                         # on Local it only saves the connection
    assert ai_profile.cloud_conn(window.project) == API and window.state.ai_route == LOCAL
    assert setup.heads[CLAUDE_CODE].text() == "Cloud · API"
    commit_to_cloud(window)
    assert window.state.ai_route == API
    setup = open_setup(window) if not window.ai_route.setup.isVisible() else window.ai_route.setup
    chat = window.assistant.chat
    chat.composer.setPlainText("api draft")
    setup.conn.changed.emit(CLAUDE_CODE)
    assert window.state.ai_route == CLAUDE_CODE and chat.composer.toPlainText() == ""
    Work(window, monkeypatch)
    setup = window.ai_route.setup
    setup.conn.changed.emit(API)
    assert kind(window) == "busy" and window.state.ai_route == CLAUDE_CODE    # a route change asks like a switch
    assert setup.conn.current() == CLAUDE_CODE


def test_the_project_setting_changes_only_where_the_switch_starts(window):
    setup = open_setup(window)
    setup.policy.changed.emit(CLOUD)
    assert ai_profile.policy(window.project) == CLOUD and window.state.ai_mode == LOCAL
    window.state.set_ai_route(CLOUD)
    setup.policy.changed.emit(LOCAL)
    assert ai_profile.policy(window.project) == LOCAL and window.state.ai_mode == CLOUD


def test_ai_setup_closes_on_escape_and_on_a_click_outside_but_not_on_its_anchor(window, qapp):
    setup = open_setup(window)
    QTest.keyClick(setup, Qt.Key.Key_Escape)
    assert not setup.isVisible()
    setup = open_setup(window)
    # A real outside click lands on the overlay; QTest sends directly to the supplied widget.
    QTest.mouseClick(setup._scrim, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
    assert not setup.isVisible()
    open_setup(window)
    window.topbar.ai_switch.caret.click()                                  # the ▾ again closes it
    assert not window.ai_route.setup.isVisible()


def test_settings_link_opens_the_ai_tab(window, monkeypatch):
    opened = []
    monkeypatch.setattr(type(window), "open_settings", lambda self, tab=0: opened.append(tab))
    setup = open_setup(window)
    setup._open_settings()
    from slidemage.ui.dialogs.settings import AI
    assert opened == [AI] and not setup.isVisible()


# -- commands and the Images button ------------------------------------------------------------

def test_the_palette_has_the_switch_and_ai_setup_and_they_go_through_the_request_flow(window):
    ai_profile.set_policy(window.project, CLOUD)
    ai_profile.mark_cloud_seen(window.project)
    titles = {c.id: c.title(window) for c in window.commands if c.group == "AI" and c.id.startswith("ai:")}
    assert titles == {"ai:local": "Use Local AI", "ai:cloud": "Use Cloud AI", "ai:setup": "AI setup…"}
    window.commands.run("ai:cloud", window)
    assert window.state.ai_mode == CLOUD
    window.commands.run("ai:local", window)
    assert window.state.ai_mode == LOCAL
    window.commands.run("ai:setup", window)
    assert window.ai_route.setup.isVisible()
    window.ai_route.setup.close()
    ai_profile.set_policy(window.project, LOCAL)
    window.commands.run("ai:cloud", window)
    assert kind(window) == "policy"


def test_images_is_not_a_top_bar_button_any_more_but_a_close_button_while_it_is_open(window, monkeypatch):
    monkeypatch.setattr(window.images_page, "ensure_loaded", lambda: None)
    bar = window.topbar
    assert bar._images.isHidden() and "images" in window.commands
    window.commands.run("images", window)
    assert not bar._images.isHidden() and bar._images.text() == "Close images" and bar._images.property("kind") == "primary"
    bar._images.click()
    assert bar._images.isHidden()
    from slidemage.ui.workspace.menus import MORE_COLUMNS
    assert "images" in dict(MORE_COLUMNS[1])["Project"]


def test_the_busy_query_lists_ask_ai_to_fix_and_the_ollama_slot(window):
    assert window.running_ai_work() == []
    assert window.try_start_ollama_task("translating a slide")
    work = window.running_ai_work()
    assert [(w.text, w.route, w.local, w.stop) for w in work] == [("Translating a slide", "Local · Ollama", True, None)]
    window.end_ollama_task()
    assert window.running_ai_work() == []
