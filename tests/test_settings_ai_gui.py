# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The AI tab of the Settings sheet (step 3c): the built-in sections, a plugin's section, no routes, no tab, and
the old Cloud, Ollama and Prompts tabs as sections of it."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QLabel

from conftest import qapp as qapp  # noqa: F401
from slidemage.ai import routes
from slidemage.plugins import session
from slidemage.plugins.registry import Registrar
from slidemage.ui.dialogs.settings import AI, GENERAL, OLLAMA, PLUGINS, PROMPTS, PROJECT
from test_settings_gui import open_sheet, tab_names
from fake_routes import FakeRoute


@pytest.fixture(autouse=True)
def _fresh_routes(fake_routes):
    return fake_routes


def fake_plugin(registrar_calls):
    registrar = Registrar(SimpleNamespace(id="fake", name="Fake plugin"))
    with registrar.activation():
        registrar_calls(registrar)
    return SimpleNamespace(id="fake", manifest=SimpleNamespace(name="Fake plugin"), contributions=registrar.contributions)


def test_the_ai_tab_has_the_policy_the_models_the_prompts_and_a_section_per_service(qapp):
    sheet = open_sheet(qapp, tab=AI)
    assert tab_names(sheet) == ["General", "AI", "Presentation", "Project", "About", "Plugins"]
    assert list(sheet.ai.sections) == ["prompts"]
    assert sheet.ai.policy.current() in ("local", "cloud")
    assert not sheet.ai.cloud_route_field.isVisibleTo(sheet.ai)
    assert sheet.ai.models.heads["local"].text() == "Local · Fake local"
    assert sheet.ai.sections["prompts"].isAncestorOf(sheet.prompts)


def test_changing_the_cloud_route_changes_the_cloud_column_of_the_models(qapp):
    route = FakeRoute(id="second_cloud", service="Second cloud")
    routes.register(route)
    sheet = open_sheet(qapp, tab=AI)
    sheet.ai.cloud_route.changed.emit("second_cloud")
    assert sheet.ai.models.heads["cloud"].text() == "Cloud · Second cloud"
    sheet.ai.cloud_route.changed.emit("fake_cloud")
    assert sheet.ai.models.heads["cloud"].text() == "Cloud · Fake cloud"


def test_a_plugins_section_follows_the_built_in_ones(qapp, monkeypatch):
    plugin = fake_plugin(lambda host: host.add_settings_section("ai", "Fake AI", lambda: QLabel("fake section body")))
    monkeypatch.setattr(session, "active", lambda: [plugin])
    sheet = open_sheet(qapp, tab=AI)
    assert list(sheet.ai.sections) == ["prompts", "Fake AI"]
    assert any(l.text() == "fake section body" for l in sheet.ai.sections["Fake AI"].findChildren(QLabel))


def test_a_plugin_section_that_raises_is_said_in_its_section(qapp, monkeypatch):
    def boom():
        raise RuntimeError("no luck")
    plugin = fake_plugin(lambda host: host.add_settings_section("ai", "Broken", boom))
    monkeypatch.setattr(session, "active", lambda: [plugin])
    sheet = open_sheet(qapp, tab=AI)
    assert any("no luck" in l.text() for l in sheet.ai.sections["Broken"].findChildren(QLabel))


def test_a_plugins_route_with_a_section_gets_a_section_titled_by_its_service(qapp):
    route = FakeRoute(id="acme.cloud")
    route.service = "Acme"
    route.settings_section = lambda: lambda: QLabel("acme settings")
    routes.register(route)
    sheet = open_sheet(qapp, tab=AI)
    assert "Acme" in sheet.ai.sections


def test_a_route_may_share_a_service_and_so_a_section(qapp, fake_routes):
    fake_routes.local.settings_section = lambda: lambda: QLabel("first local part")
    route = FakeRoute(is_local=True, id="acme.local")
    route.service = "Fake local"
    route.settings_section = lambda: lambda: QLabel("second local part")
    routes.register(route)
    sheet = open_sheet(qapp, tab=AI)
    assert list(sheet.ai.sections).count("Fake local") == 1
    labels = [l.text() for l in sheet.ai.sections["Fake local"].findChildren(QLabel)]
    assert "first local part" in labels and "second local part" in labels


def test_without_ai_routes_there_is_no_ai_tab(qapp):
    routes.clear()
    sheet = open_sheet(qapp, tab=PLUGINS)
    assert tab_names(sheet) == ["General", "Presentation", "Project", "About", "Plugins"]
    assert sheet.ai is None and sheet.prompts is None
    assert sheet.current_tab() == PLUGINS and sheet._tabs.tabText(sheet._tabs.currentIndex()) == "Plugins"
    sheet.set_current_tab(PROJECT)
    assert sheet._tabs.tabText(sheet._tabs.currentIndex()) == "Project"
    sheet.close()


@pytest.mark.parametrize("alias, section", [(PROMPTS, "prompts")])
def test_the_old_tabs_open_the_ai_tab_at_their_section(qapp, alias, section):
    sheet = open_sheet(qapp, tab=alias)
    assert sheet.current_tab() == AI and sheet.scrolled_to == section
    sheet.resize(760, 300)
    sheet.show()
    qapp.processEvents()
    qapp.processEvents()
    assert sheet._ai_area.verticalScrollBar().value() > 0 or section == "prompts"
    sheet.close()


def test_an_alias_without_the_ai_tab_opens_general(qapp):
    routes.clear()
    sheet = open_sheet(qapp, tab=OLLAMA)
    assert sheet.current_tab() == GENERAL
    sheet.close()


def test_a_settings_section_is_only_allowed_for_the_ai_page_and_while_activating():
    registrar = Registrar(SimpleNamespace(id="fake", name="Fake"))
    with pytest.raises(RuntimeError):
        registrar.add_settings_section("ai", "x", lambda: None)
    with registrar.activation():
        with pytest.raises(ValueError):
            registrar.add_settings_section("general", "x", lambda: None)
        registrar.add_settings_section("ai", "x", lambda: None)
    assert [s.title for s in registrar.contributions.settings_sections] == ["x"]


def test_model_grid_uses_registered_route_choices(qapp):
    routes.clear()
    route = FakeRoute(is_local=True, id="ollama")
    choices = ["plugin-model"]
    route.model_choices = lambda ctx, task: list(choices)
    routes.register(route)
    sheet = open_sheet(qapp, tab=AI)
    combo = sheet.ai.models.cells[("local", "chat")]
    assert combo.findData("plugin-model") >= 0
    choices[:] = ["new-model"]
    sheet.ai.models.refresh()
    assert combo.findData("plugin-model") == -1
    assert combo.findData("new-model") >= 0
    sheet.close()


def test_route_notification_refreshes_grid_and_picker(qapp, monkeypatch):
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QComboBox
    from slidemage.ai import ai_profile
    from slidemage.ui.ai_models import fill_model_combo
    from slidemage.ui.dialogs.settings_ai import AiPage
    from test_settings_gui import FakeApp

    class Notifier(QObject):
        model_choices_changed = Signal(str)
    routes.clear()
    route = FakeRoute(is_local=True, id="ollama")
    choices = ["first"]
    route.model_choices = lambda ctx, task: list(choices)
    routes.register(route)
    app = FakeApp()
    notifier = Notifier()
    app.model_choices_changed = notifier.model_choices_changed
    page = AiPage(app)
    combo = QComboBox()
    app.model_choices_changed.connect(lambda _: fill_model_combo(app.project, combo, ai_profile.CHAT, "none"))
    fill_model_combo(app.project, combo, ai_profile.CHAT, "none")
    assert combo.findData("first") >= 0
    choices[:] = ["second"]
    app.model_choices_changed.emit("ollama")
    assert combo.findData("second") >= 0 and combo.findData("first") == -1
    assert page.models.cells[("local", "chat")].findData("second") >= 0
    page.close()
