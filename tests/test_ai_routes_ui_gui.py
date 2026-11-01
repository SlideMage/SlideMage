# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The AI UI over the route registry (plugins step 3b): a route nobody hard-coded shows up in the switch, AI setup and
the pickers; a side with no route is a disabled half of the switch; with no route at all the AI UI is gone."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QComboBox, QMenu

from slidemage.ai import ai_profile, routes
from slidemage.ai.ai_profile import CHAT, CLOUD, LOCAL, TRANSLATION
from fake_routes import FakeRoute
from slidemage.ui import ai_models
from slidemage.ui.dialogs.settings import PLUGINS
from slidemage.ui.kit.fonts import load_fonts
from conftest import build_window, qapp as qapp  # noqa: F401


@pytest.fixture(autouse=True)
def _registry(fake_routes):
    return fake_routes


@pytest.fixture
def window(qapp, monkeypatch):
    assert load_fonts()
    window = build_window(monkeypatch)
    window.resize(1700, 800)
    window.show()
    window.state.set_mode("source")
    qapp.processEvents()
    return window


def texts(combo: QComboBox):
    return [combo.itemText(i) for i in range(combo.count())]


def test_a_fourth_route_is_in_the_switch_setup_and_pickers(window, qapp, monkeypatch):
    routes.register(FakeRoute(id="fake", service="Fake AI"))
    ctx = window.project
    ai_profile.set_cloud_conn(ctx, "fake")
    window.state.set_ai_route(CLOUD)
    qapp.processEvents()
    assert window.state.ai_route == "fake" and "Cloud · Fake AI" in window.ai_switch.toolTip()
    window.ai_switch.caret.click()
    setup = window.ai_route.setup
    assert setup.conn is not None and set(setup.conn._buttons) == {"fake_cloud", "fake"}
    assert setup.heads[CLOUD].text() == "Cloud · Fake AI"
    cell = setup.cells[(CLOUD, TRANSLATION)]
    assert texts(cell) == ["FAKE-1", "FAKE-2"] and cell.currentData() == "fake-1"
    combo = QComboBox()
    assert ai_models.fill_model_combo(ctx, combo, TRANSLATION, "(none)")
    assert texts(combo) == ["FAKE-1", "FAKE-2"]
    assert ai_profile.resolve(ctx, CHAT).name == "Cloud · Fake AI"


def test_a_side_with_no_route_is_a_disabled_half_with_install_a_plugin(window, qapp, monkeypatch):
    for route in routes.on_side(False):
        routes._routes.pop(route.id)
    window.assistant.refresh_models()
    window.ai_switch.refresh()
    cloud = window.ai_switch.segments.buttons()[1]
    assert not cloud.isEnabled() and window.ai_switch.segments.buttons()[0].isEnabled()
    assert not window.ai_switch.install.isHidden() and window.ai_switch.install.text() == "Install a plugin…"
    window.ai_route.request(CLOUD)                         # nothing to move to
    assert window.state.ai_mode == LOCAL
    assert not window.commands["ai:cloud"].enabled(window) and window.commands["ai:local"].enabled(window)
    opened = []

    class Sheet:
        loaded, after = False, None

        def __init__(self, parent, tab, focus=None):
            opened.append(tab)

        def exec(self):
            return 0

    monkeypatch.setattr("slidemage.ui.workspace.window.SettingsSheet", Sheet)
    window.ai_switch.install.click()
    assert opened == [PLUGINS]                                                    # Settings → Extensions


def test_a_policy_on_an_empty_side_does_not_switch_routes(window):
    for route in routes.on_side(True):
        routes._routes.pop(route.id)
    ai_profile.set_policy(window.project, LOCAL)
    ai_profile._modes.clear()
    assert ai_profile.mode(window.project) == LOCAL and ai_profile.active_route(window.project) == ""


def test_with_no_route_the_ai_ui_hides(window, qapp):
    assert window.assistant.isVisible() and window.commands["ai:setup"].visible(window)
    routes.clear()
    ai_profile._modes.clear()
    window.refresh_ai_models()
    qapp.processEvents()
    assert window.assistant.isHidden() and not window.assistant.available
    for command in window.commands:
        if command.id.startswith(("ai:", "task:", "selection:")) or command.id in ("slide:readable", "slide:translate"):
            assert not command.visible(window), command.id
    assert ai_profile.active_route(window.project) == "" and ai_profile.cloud_conn(window.project) == "claude_code"
    assert window.commands["images"].visible(window)
    ai_menu = next(m for m in window.menuBar().findChildren(QMenu) if m.objectName() == "menu:ai")
    assert not ai_menu.menuAction().isVisible()
    ai_menu.aboutToShow.emit()
    assert not [a for a in ai_menu.actions() if not a.isSeparator()]            # the AI menu has nothing to show


def test_route_owned_surface_is_shown_and_new_conversation_resets_it(window, fake_routes, qapp):
    from fake_chat import FakeChatSurface

    fake_routes.cloud.surface_factory = FakeChatSurface
    window.assistant.refresh_models()
    surface = window.assistant.surface_for(fake_routes.cloud.id)
    surface.replies.append("A scripted answer")
    window.state.set_ai_route(CLOUD)
    qapp.processEvents()
    assert window.assistant._stack.currentWidget() is surface
    surface.composer.setText("Hello")
    surface.send()
    assert surface.turns == ["Hello"] and surface.answer.text() == "A scripted answer"
    window.assistant.new_conversation()
    assert surface.turns == [] and surface.answer.text() == "" and surface.restarts == [("", False)]


def test_scripted_task_runner_receives_and_validates_the_captured_slide(window, fake_routes):
    import threading

    from fake_chat import FakeTaskRunner
    from slidemage.ai import tasks
    from slidemage.ai.task_result import DONE

    captured = "\\begin{standardframe}{Old}\\n\\end{standardframe}"
    runner = FakeTaskRunner(window.project, {"title": "New"})
    fake_routes.local.runner = runner
    route = ai_profile.resolve(window.project, ai_profile.FIXES)
    from slidemage.ui.workspace.task_bubbles import _runner_of

    outcome = _runner_of(window.project, route)(tasks.TITLE, captured, "Change title", threading.Event(), None)
    assert outcome.status == DONE and "{New}" in outcome.text
    assert runner.calls[0][:3] == (tasks.TITLE, captured, "Change title")
