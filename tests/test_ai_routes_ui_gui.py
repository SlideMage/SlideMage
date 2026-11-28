# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Workspace controls and task dispatch for plugin-provided AI routes."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QMenu

from slidemage.ai import ai_profile, routes
from slidemage.ai.ai_profile import CLOUD, LOCAL, TRANSLATION
from fake_routes import FakeRoute
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


def test_a_new_route_is_selectable_in_the_switch_and_setup(window, qapp):
    routes.register(FakeRoute(id="fake", service="Fake AI"))
    ctx = window.project
    ai_profile.set_cloud_conn(ctx, "fake")
    window.state.set_ai_route(CLOUD)
    qapp.processEvents()
    assert window.state.ai_route == "fake"
    window.ai_switch.caret.click()
    setup = window.ai_route.setup
    assert setup.conn is not None and set(setup.conn._buttons) == {"fake_cloud", "fake"}
    cell = setup.cells[(CLOUD, TRANSLATION)]
    assert [cell.itemData(i) for i in range(cell.count())] == ["fake-1", "fake-2"]
    assert cell.currentData() == "fake-1"


def test_a_side_with_no_route_is_a_disabled_half_with_install_a_plugin(window, qapp, monkeypatch):
    for route in routes.on_side(False):
        routes._routes.pop(route.id)
    window.assistant.refresh_models()
    window.ai_switch.refresh()
    cloud = window.ai_switch.segments.buttons()[1]
    assert not cloud.isEnabled() and window.ai_switch.segments.buttons()[0].isEnabled()
    assert not window.ai_switch.install.isHidden()
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


def test_with_no_route_the_ai_ui_hides(window, qapp):
    assert window.assistant.isVisible() and window.commands["ai:setup"].visible(window)
    routes.clear()
    ai_profile._modes.clear()
    window.refresh_ai_models()
    qapp.processEvents()
    assert window.assistant.isHidden() and not window.assistant.available
    assert all(not command.visible(window) for command in window.commands
               if command.id.startswith(("ai:", "task:", "selection:", "slide:readable", "slide:translate")))
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
