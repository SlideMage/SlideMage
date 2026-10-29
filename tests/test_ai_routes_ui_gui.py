# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The AI UI over the route registry (plugins step 3b): a route nobody hard-coded shows up in the switch, AI setup and
the pickers; a side with no route is a disabled half of the switch; with no route at all the AI UI is gone."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QComboBox, QMenu

from slidemage.ai import ai_profile, routes
from slidemage.ai.ai_profile import CHAT, CLOUD, LOCAL, TRANSLATION
from slidemage.ai.providers import InstalledModel, OllamaProvider
from slidemage.ui import ai_models
from slidemage.ui.dialogs.settings import PLUGINS
from slidemage.ui.kit.fonts import load_fonts
from conftest import build_window, qapp as qapp  # noqa: F401

INSTALLED = [InstalledModel("chat-model", 1, "", ("tools",))]


class FakeRoute:
    """A fourth route, as a plugin would register it."""
    id, service, is_local = "fake", "Fake AI", False
    tasks = frozenset(ai_profile.TASKS)
    def settings_section(self):
        return None

    def __init__(self, is_local: bool = False, id: str = "fake") -> None:
        self.is_local, self.id = is_local, id

    def problem(self, ctx, route) -> str:
        return ""

    def model_choices(self, ctx, task) -> list[str]:
        return ["fake-1", "fake-2"]

    def default_choice(self, task) -> str:
        return "fake-1"

    def choice_label(self, choice) -> str:
        return choice.upper()

    def split_choice(self, choice):
        return choice, None

    def valid_choice(self, ctx, choice):
        return choice in ("fake-1", "fake-2")

    def work_label(self, route):
        return route.model

    def provider(self, ctx, route):
        return None

    draft_backend = translation_backend = slide_translator = provider

    def task_runner(self, ctx, route):
        return None

    def chat_surface(self, *args, **kwargs):
        return None


@pytest.fixture(autouse=True)
def _registry():
    yield
    routes.clear()
    routes.register_builtin_routes()


@pytest.fixture
def window(qapp, monkeypatch):
    assert load_fonts()
    monkeypatch.setattr(OllamaProvider, "installed", lambda self, **_: list(INSTALLED))
    window = build_window(monkeypatch)
    window.resize(1700, 800)
    window.show()
    window.state.set_mode("source")
    qapp.processEvents()
    return window


def texts(combo: QComboBox):
    return [combo.itemText(i) for i in range(combo.count())]


def test_a_fourth_route_is_in_the_switch_setup_and_pickers(window, qapp, monkeypatch):
    routes.register(FakeRoute())
    ctx = window.project
    ai_profile.set_cloud_conn(ctx, "fake")
    window.state.set_ai_route(CLOUD)
    qapp.processEvents()
    assert window.state.ai_route == "fake" and "Cloud · Fake AI" in window.ai_switch.toolTip()
    window.ai_switch.caret.click()
    setup = window.ai_route.setup
    assert setup.conn is not None and set(setup.conn._buttons) == {"claude_code", "anthropic_api", "fake"}
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
    assert opened == [PLUGINS]                                                    # Settings → Plugins


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
    window.assistant.refresh_models()
    qapp.processEvents()
    assert window.assistant.isHidden() and not window.assistant.available
    for command in window.commands:
        if command.id.startswith(("ai:", "task:", "selection:")) or command.id in ("slide:readable", "images"):
            assert not command.visible(window), command.id
    assert ai_profile.active_route(window.project) == "" and ai_profile.cloud_conn(window.project) == "claude_code"
    ai_menu = next(m for m in window.menuBar().findChildren(QMenu) if m.objectName() == "menu:ai")
    ai_menu.aboutToShow.emit()
    assert not [a for a in ai_menu.actions() if not a.isSeparator()]            # the AI menu has nothing to show
