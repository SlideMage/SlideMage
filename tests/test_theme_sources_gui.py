# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Themes from GitHub in the window (theme_sources.py): Settings → Extensions → Themes' "Add from GitHub…", a
theme row's source, failure and "Check for update", and the start-up check (maintenance): under the update
setting, offered with the release notes (Install now / Not now / Skip this version), never installed silently,
and the previews of decks using the key re-rendered after an install. The fake GitHub API is test_theme_sources'."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QMessageBox

from conftest import qapp as qapp, wait_until
from slidemage import theme_sources, themes, updater
from slidemage.ui.dialogs import settings_plugins
from slidemage.ui.workspace import maintenance
from test_theme_sources import ASSET, GH, build, github as github  # noqa: F401
from test_themes_gui import FakeApp, answer, isolated as isolated  # noqa: F401
from slidemage.ui.dialogs.settings_plugins import PluginsTab


@pytest.fixture
def tab(qapp, tmp_path):
    app = FakeApp(tmp_path)
    app.installed_keys = []
    app.theme_installed = app.installed_keys.append
    return PluginsTab(app)


def idle(tab):
    wait_until(lambda: tab._job is None)


def choose(monkeypatch, choice):
    offered = []
    monkeypatch.setattr(settings_plugins, "ask_theme_update", lambda parent, offer: offered.append(offer) or choice)
    monkeypatch.setattr(maintenance, "ask_theme_update", lambda parent, offer: offered.append(offer) or choice)
    return offered


def test_add_theme_from_github_installs_the_newest_eligible_release_after_asking(tab, github, monkeypatch):
    github.release("1.0.0", ASSET.read_bytes())
    asked = answer(monkeypatch, False)
    tab.add_theme_from_github("https://github.com/" + GH)
    idle(tab)
    assert themes.installed() == [] and f"from {GH}" in asked[0] and "Sample Theme 1.0.0" in asked[0]
    answer(monkeypatch, True)
    tab.add_theme_from_github(GH)
    idle(tab)
    assert [t.key for t in themes.installed()] == ["sample-theme"] and tab.app.installed_keys == ["sample-theme"]
    row = tab.theme_rows["sample-theme"]
    assert GH in row.source_label.text() and row.update_button is not None and row.check_error_label is None
    assert f"installed from {GH}" in tab.status.text()


def test_a_wrong_name_or_a_refusal_is_a_caption(tab, github):
    tab.add_theme_from_github("not a repository")
    assert "owner/name" in tab.status.text() and tab._job is None
    github.error = 404
    tab.add_theme_from_github(GH)
    idle(tab)
    assert "No published release found" in tab.status.text() and tab.status.property("tone") == "error"


def test_a_repository_without_an_eligible_release_says_why(tab, github, tmp_path):
    github.release("1.0.0", build(tmp_path, "1.0.0", requires=">=99"))
    tab.add_theme_from_github(GH)
    idle(tab)
    assert "no release SlideMage can install" in tab.status.text() and "needs SlideMage >=99" in tab.status.text()


def test_a_file_installed_theme_has_no_update_button(tab):
    themes.install_file(ASSET)
    tab.refresh()
    assert tab.theme_rows["sample-theme"].update_button is None


def test_check_for_update_offers_and_skip_is_remembered(tab, github, tmp_path, monkeypatch):
    github.release("1.0.0", ASSET.read_bytes())
    theme_sources.install(theme_sources.newest_eligible(GH)[0])
    tab.refresh()
    tab.theme_rows["sample-theme"].update_button.click()
    idle(tab)
    assert "up to date" in tab.status.text()
    github.release("1.1.0", build(tmp_path, "1.1.0"))
    offered = choose(monkeypatch, "skip")
    tab.theme_rows["sample-theme"].update_button.click()
    idle(tab)
    assert offered[0].fetched.release.version == "1.1.0" and themes.installed()[0].manifest.version == "1.0.0"
    assert theme_sources.read_source("sample-theme").skipped_version == "1.1.0"
    choose(monkeypatch, "install")
    tab.theme_rows["sample-theme"].update_button.click()
    idle(tab)
    assert themes.installed()[0].manifest.version == "1.1.0" and tab.app.installed_keys == ["sample-theme"]


def test_the_row_says_why_the_last_check_failed(tab, github):
    github.release("1.0.0", ASSET.read_bytes())
    theme_sources.install(theme_sources.newest_eligible(GH)[0])
    github.error = 403
    tab.refresh()
    tab.theme_rows["sample-theme"].update_button.click()
    idle(tab)
    label = tab.theme_rows["sample-theme"].check_error_label
    assert label is not None and "Contents: Read-only" in label.text() and "keeps working" in label.text()


def test_the_offer_shows_the_notes_and_a_new_major_version(qapp, github, tmp_path, monkeypatch):
    github.release("2.0.0", build(tmp_path, "2.0.0"), body="New colours.")
    fetched = theme_sources.newest_eligible(GH)[0]
    offer = theme_sources.Offer("sample-theme", "Sample Theme", "1.4.0", fetched)
    seen = {}

    def exec_(box):
        seen["text"], seen["info"] = box.text(), box.informativeText()
        seen["buttons"] = [b.text() for b in box.buttons()]
        box.buttons()[-1].click()
        return 0

    monkeypatch.setattr(QMessageBox, "exec", exec_)
    assert settings_plugins.ask_theme_update(None, offer) == "skip"
    assert "2.0.0 is available (you have 1.4.0)" in seen["text"]
    assert "New colours." in seen["info"] and "new major version" in seen["info"]
    assert seen["buttons"] == ["Install now", "Not now", "Skip this version"]
    fetched.discard()


# -- the start-up check

@pytest.fixture
def window(tmp_path):
    fake = SimpleNamespace(logged=[], installed=[], toast=SimpleNamespace(shown=[]))
    fake.log = fake.logged.append
    fake.theme_installed = fake.installed.append
    fake.toast.show_message = lambda text, *a, **k: fake.toast.shown.append(text)
    fake.theme_updates_done = SimpleNamespace(emit=lambda result: fake.results.append(result))
    fake.results = []
    return fake


def test_schedule_follows_the_update_setting_and_needs_a_github_theme(github, monkeypatch):
    scheduled = []
    monkeypatch.setattr(maintenance.QTimer, "singleShot", lambda *a: scheduled.append(a))
    updater.set_update_mode("ask")
    maintenance.schedule_theme_update_check(SimpleNamespace())
    assert scheduled == []                          # no theme from GitHub
    github.release("1.0.0", ASSET.read_bytes())
    theme_sources.install(theme_sources.newest_eligible(GH)[0])
    updater.set_update_mode("off")
    maintenance.schedule_theme_update_check(SimpleNamespace())
    assert scheduled == []
    for mode in ("ask", "auto"):
        updater.set_update_mode(mode)
        maintenance.schedule_theme_update_check(SimpleNamespace())
    assert len(scheduled) == 2


@pytest.mark.parametrize("mode", ["ask", "auto"])
def test_an_update_is_offered_never_installed_silently(window, github, tmp_path, monkeypatch, mode):
    github.release("1.0.0", ASSET.read_bytes())
    theme_sources.install(theme_sources.newest_eligible(GH)[0])
    github.release("1.1.0", build(tmp_path, "1.1.0"))
    updater.set_update_mode(mode)
    offered = choose(monkeypatch, "later")
    maintenance.on_theme_updates_done(window, theme_sources.check_updates())
    assert len(offered) == 1 and themes.installed()[0].manifest.version == "1.0.0" and window.installed == []
    assert any("not installed for now" in line for line in window.logged)
    choose(monkeypatch, "install")
    maintenance.on_theme_updates_done(window, theme_sources.check_updates())
    assert themes.installed()[0].manifest.version == "1.1.0" and window.installed == ["sample-theme"]


def test_off_while_checking_offers_nothing_and_a_failure_is_only_logged(window, github, tmp_path, monkeypatch):
    github.release("1.0.0", ASSET.read_bytes())
    theme_sources.install(theme_sources.newest_eligible(GH)[0])
    github.release("1.1.0", build(tmp_path, "1.1.0"))
    offered = choose(monkeypatch, "install")
    result = theme_sources.check_updates()
    updater.set_update_mode("off")
    maintenance.on_theme_updates_done(window, result)
    maintenance.theme_update_check(window)
    assert offered == [] and window.results == [] and themes.installed()[0].manifest.version == "1.0.0"
    updater.set_update_mode("ask")
    github.offline = True
    maintenance.on_theme_updates_done(window, theme_sources.check_updates())
    assert offered == [] and any("Couldn't reach GitHub" in line for line in window.logged) and window.toast.shown == []


def test_an_install_re_renders_only_when_the_open_deck_uses_the_key(monkeypatch):
    calls = []
    renderer = SimpleNamespace(replan=lambda: calls.append("replan"))
    preview = SimpleNamespace(render_after_save=lambda: calls.append("render"))
    deck = SimpleNamespace(preamble_text="\\input{SlideMage_template_other}\n")
    window = SimpleNamespace(background=SimpleNamespace(renderer=renderer), centre=SimpleNamespace(preview=preview),
                             state=SimpleNamespace(deck=deck))
    maintenance.on_theme_installed(window, "sample-theme")
    assert calls == ["replan"]
    deck.preamble_text = "\\input{SlideMage_template_sample-theme}\n"
    maintenance.on_theme_installed(window, "sample-theme")
    assert calls == ["replan", "replan", "render"]
