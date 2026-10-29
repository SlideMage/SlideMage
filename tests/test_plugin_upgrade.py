# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""plugins/upgrade.py: which built-in features this machine and project use (so an update that removes one can
preselect its plugin), the preselection, and the first-start flag."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from slidemage import app_settings, deck_scan
from slidemage.ai import ai_profile
from slidemage.plugins import catalogue, loader, upgrade
from slidemage.project import ProjectContext


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(loader.project, "config_dir", lambda: tmp_path / "config")
    monkeypatch.setattr(deck_scan, "scan_decks", lambda ctx: [])


@pytest.fixture
def ctx(tmp_path):
    return ProjectContext.at(tmp_path / "project")


def test_nothing_used_by_default(ctx):
    assert upgrade.used_features(ctx) == {}


def test_an_api_key_means_claude(ctx, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    used = upgrade.used_features(ctx)
    assert list(used) == ["claude"] and "API key" in used["claude"]


@pytest.mark.parametrize("settings", [
    {ai_profile.CONNECTION_KEY: "claude_code"},
    {ai_profile.CONNECTION_KEY: "api"},
    {ai_profile.MODELS_KEY: {"claude_code": {"chat": "haiku:medium"}}},
    {ai_profile.MODELS_KEY: {"api": {"translation": "claude-sonnet-5-5"}}},
])
def test_a_cloud_route_in_the_ai_settings_means_claude(ctx, settings):
    for key, value in settings.items():
        app_settings.set(ctx, key, value)
    assert list(upgrade.used_features(ctx)) == ["claude"]


def test_empty_or_unknown_ai_settings_do_not(ctx):
    app_settings.set(ctx, ai_profile.CONNECTION_KEY, "something-else")
    app_settings.set(ctx, ai_profile.MODELS_KEY, {"claude_code": {"chat": ""}, "api": "broken"})
    assert upgrade.used_features(ctx) == {}


def test_ollama_models_or_host_mean_ollama(ctx):
    app_settings.set(ctx, ai_profile.MODELS_KEY, {"local": {"chat": "gemma3:12b"}})
    assert list(upgrade.used_features(ctx)) == ["ollama"]
    app_settings.set(ctx, ai_profile.MODELS_KEY, {})
    assert upgrade.used_features(ctx) == {}
    app_settings.set(ctx, app_settings.OLLAMA_HOST_SETTING_KEY, "http://box:11434")
    assert list(upgrade.used_features(ctx)) == ["ollama"]


def test_both_ai_features_are_found_together(ctx):
    app_settings.set(ctx, ai_profile.MODELS_KEY, {"local": {"chat": "x"}, "api": {"chat": "y"}})
    assert set(upgrade.used_features(ctx)) == {"claude", "ollama"}


def test_a_deck_with_a_course_link_means_campusonline(ctx, monkeypatch):
    def deck(link):
        return SimpleNamespace(text="\\documentclass{beamer}\n" + (f"%% SlideMage course URL: {link}\n" if link else "")
                               + "\\begin{document}\n")

    decks = [deck(None), deck("https://campus.example/course/1")]
    monkeypatch.setattr(deck_scan, "scan_decks", lambda c: decks)
    used = upgrade.used_features(ctx)
    assert list(used) == ["campusonline"] and "course link" in used["campusonline"]
    decks.append(deck("https://campus.example/course/2"))
    assert "2 decks" in upgrade.used_features(ctx)["campusonline"]
    monkeypatch.setattr(deck_scan, "scan_decks", lambda c: [deck(None)])
    assert upgrade.used_features(ctx) == {}


def entries(*ids):
    return [catalogue.parse({"schema": 1, "generated": "x", "plugins_page": "https://e.org/", "plugins": [
        {"id": i, "name": i, "summary": "s", "homepage": "https://e.org/", "source": "https://e.org/",
         "icon": None, "license": "MIT", "maintainer": "m", "recommended": False, "needs": [], "network": [],
         "releases": [{"version": "1.0.0", "api_version": 1, "requires_slidemage": ">=8.0", "url": "https://e.org/x",
                       "sha256": "0" * 64, "size": 1, "published": "2026-10-26"}]}]}).plugins[0] for i in ids]


def test_preselect_picks_the_catalogue_plugins_in_use():
    plugins = entries("claude", "ollama", "campusonline", "other")
    assert upgrade.preselect(plugins, {"claude": "why", "campusonline": "why", "gone": "why"}) == {
        "claude", "campusonline"}
    assert upgrade.preselect(plugins, {}) == set()


def test_a_course_link_in_the_body_or_empty_does_not_count():
    assert upgrade.has_course_link("%% SlideMage course URL: https://x.org/c\n\\begin{document}\n")
    assert not upgrade.has_course_link("\\begin{document}\n%% SlideMage course URL: https://x.org/c\n")
    assert not upgrade.has_course_link("%% SlideMage course URL:   \n\\begin{document}\n")


def test_each_removed_feature_is_migrated_in_the_release_that_removed_it():
    assert upgrade.MIGRATIONS == [upgrade.Migration("campusonline", "v9.0.0"), upgrade.Migration("claude", "v9.1.0"),
                                  upgrade.Migration("ollama", "v9.1.0")]


def test_linked_deck_is_due_even_after_onboarding_was_dismissed(ctx, monkeypatch):
    monkeypatch.setattr(deck_scan, "scan_decks", lambda c: [SimpleNamespace(
        text="%% SlideMage course URL: https://campus.example/c/1\n\\begin{document}\n")])
    upgrade.mark_offer_seen()
    assert upgrade.migrations_due(ctx) == {"campusonline": "A deck of this project has a CAMPUSonline course link"}
    upgrade.mark_migrations_seen(["campusonline"])
    assert upgrade.migrations_due(ctx) == {}


def test_migrations_due(ctx, monkeypatch):
    monkeypatch.setattr(upgrade, "MIGRATIONS", [upgrade.Migration("campusonline", "v8.70.0"),
                                                upgrade.Migration("claude", "v9.0.0")])
    monkeypatch.setattr(upgrade, "used_features", lambda c: {"campusonline": "why", "claude": "why2"})
    assert upgrade.migrations_due(ctx, "v8.70.0") == {"campusonline": "why"}       # claude: release is newer
    assert upgrade.migrations_due(ctx, "v9.1.0") == {"campusonline": "why", "claude": "why2"}
    upgrade.mark_migrations_seen(["campusonline"])
    assert upgrade.migrations_seen() == {"campusonline"}
    assert upgrade.migrations_due(ctx, "v9.1.0") == {"claude": "why2"}
    assert not upgrade.offer_seen()                      # onboarding is a separate flag
    monkeypatch.setattr(upgrade, "used_features", lambda c: {})
    assert upgrade.migrations_due(ctx, "v9.1.0") == {}


def test_a_migrated_plugin_that_is_installed_is_not_due(ctx, monkeypatch):
    monkeypatch.setattr(upgrade, "MIGRATIONS", [upgrade.Migration("campusonline", "v8.0.0")])
    monkeypatch.setattr(upgrade, "used_features", lambda c: {"campusonline": "why"})
    monkeypatch.setattr(upgrade, "discover", lambda: [SimpleNamespace(id="campusonline")])
    assert upgrade.migrations_due(ctx) == {}


def test_the_offer_flag():
    assert not upgrade.offer_seen()
    upgrade.mark_offer_seen()
    assert upgrade.offer_seen() and (loader.plugins_dir() / "offer_seen").is_file()


def test_the_course_link_hint_shows_once_per_project_until_dismissed(ctx, monkeypatch):
    from slidemage.ui.workspace import maintenance

    monkeypatch.setattr(deck_scan, "scan_decks", lambda c: [SimpleNamespace(
        text="%% SlideMage course URL: https://campus.example/c/1\n\\begin{document}\n")])
    shown = []
    window = SimpleNamespace(project=ctx, toast=SimpleNamespace(
        show_message=lambda text, actions=(), **kw: shown.append((text, [key for key, _ in actions]))))
    monkeypatch.setattr(maintenance.plugin_session, "loaded", lambda: [])
    maintenance.show_course_hint(window)
    assert len(shown) == 1 and "CampusOnline course links" in shown[0][0]
    assert shown[0][1] == [maintenance.OPEN_PLUGINS, maintenance.COURSE_HINT_DISMISS]
    maintenance.on_plugin_toast_action(window, maintenance.COURSE_HINT_DISMISS)
    maintenance.show_course_hint(window)
    assert len(shown) == 1                                       # dismissed for this project
    app_settings.set(ctx, maintenance.COURSE_HINT_DISMISSED_KEY, False)
    monkeypatch.setattr(maintenance.plugin_session, "loaded",
                        lambda: [SimpleNamespace(id="campusonline")])
    maintenance.show_course_hint(window)
    assert len(shown) == 1                                       # the plugin is loaded
    monkeypatch.setattr(maintenance.plugin_session, "loaded", lambda: [])
    monkeypatch.setattr(deck_scan, "scan_decks", lambda c: [SimpleNamespace(text="\\begin{document}\n")])
    maintenance.show_course_hint(window)
    assert len(shown) == 1                                       # no course links


def test_installed_but_inactive_plugin_can_schedule_the_hint(monkeypatch):
    from slidemage.ui.workspace import maintenance

    scheduled = []
    monkeypatch.setattr(upgrade, "discover", lambda: [SimpleNamespace(id="campusonline")])
    monkeypatch.setattr(maintenance.QTimer, "singleShot", lambda delay, callback: scheduled.append(callback))
    maintenance.schedule_course_hint(SimpleNamespace())
    assert len(scheduled) == 1
