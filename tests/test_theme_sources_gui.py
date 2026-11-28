# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Installing and updating GitHub themes from Settings and at startup."""
from __future__ import annotations

import shutil
import threading
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QMessageBox

from conftest import answer, qapp as qapp, wait_until
from slidemage import theme_sources, themes, updater
from slidemage.ui.dialogs import settings_plugins
from slidemage.ui.workspace import maintenance
from slidemage.ui.dialogs.settings_plugins import PluginsTab
from test_theme_sources import ASSET, GH, build, github as github
from test_themes_gui import FakeApp, idle, isolated as isolated


@pytest.fixture
def installed_theme(github):
    github.release("1.0.0")
    theme_sources.install(theme_sources.newest_eligible(GH)[0])


@pytest.fixture
def update(github, installed_theme, tmp_path):
    github.release("1.1.0", build(tmp_path, "1.1.0"))


@pytest.fixture
def tab(qapp, tmp_path):
    app = FakeApp(tmp_path)
    app.installed_keys = []
    app.theme_installed = app.installed_keys.append
    return PluginsTab(app)


def choose(monkeypatch, choice):
    offered = []
    monkeypatch.setattr(settings_plugins, "ask_theme_update", lambda parent, offer: offered.append(offer) or choice)
    monkeypatch.setattr(maintenance, "ask_theme_update", lambda parent, offer: offered.append(offer) or choice)
    return offered


def test_add_theme_from_github_installs_the_newest_eligible_release_after_asking(tab, github, monkeypatch):
    github.release("1.0.0")
    asked = answer(monkeypatch, False)
    tab.add_theme_from_github("https://github.com/" + GH)
    idle(tab)
    assert themes.installed() == [] and f"from {GH}" in asked[0] and "Sample Theme 1.0.0" in asked[0]
    asked = answer(monkeypatch, True)
    tab.add_theme_from_github(GH)
    idle(tab)
    assert len(asked) == 2 and "automatically" in asked[1] and "the theme Sample Theme" in asked[1]
    assert [t.key for t in themes.installed()] == ["sample-theme"] and tab.app.installed_keys == ["sample-theme"]
    row = tab.theme_rows["sample-theme"]
    assert GH in row.source_label.text() and row.update_button is not None and row.check_error_label is None
    assert theme_sources.read_source("sample-theme").auto_update and row.auto_check.isChecked()
    row.auto_check.setChecked(False)
    assert not theme_sources.read_source("sample-theme").auto_update


def test_a_wrong_name_or_a_refusal_is_a_caption(tab, github):
    tab.add_theme_from_github("not a repository")
    assert "owner/name" in tab.status.text() and tab._job is None
    github.error = 404
    tab.add_theme_from_github(GH)
    idle(tab)
    assert "No published release found" in tab.status.text() and tab.status.property("tone") == "error"


def test_a_repository_without_an_eligible_release_says_why(tab, github, tmp_path):
    github.release("1.0.0", build(tmp_path, "1.0.0", requires=">=1.99"))
    tab.add_theme_from_github(GH)
    idle(tab)
    assert "no release SlideMage can install" in tab.status.text() and "needs SlideMage >=1.99" in tab.status.text()


def test_a_file_installed_theme_has_no_update_button(tab):
    themes.install_file(ASSET)
    tab.refresh()
    row = tab.theme_rows["sample-theme"]
    assert row.update_button is None and row.auto_check is None


def test_manual_check_reports_failure_and_can_skip_or_install_an_update(
    tab, github, installed_theme, tmp_path, monkeypatch,
):
    tab.refresh()

    def check():
        tab.theme_rows["sample-theme"].update_button.click()
        idle(tab)

    github.error = 403
    check()
    label = tab.theme_rows["sample-theme"].check_error_label
    assert label is not None and "Contents: Read-only" in label.text() and "keeps working" in label.text()
    github.error = None
    check()
    assert "up to date" in tab.status.text()
    github.release("1.1.0", build(tmp_path, "1.1.0"))
    offered = choose(monkeypatch, "skip")
    check()
    assert offered[0].fetched.release.version == "1.1.0" and themes.installed()[0].manifest.version == "1.0.0"
    assert theme_sources.read_source("sample-theme").skipped_version == "1.1.0"
    choose(monkeypatch, "install")
    check()
    assert themes.installed()[0].manifest.version == "1.1.0" and tab.app.installed_keys == ["sample-theme"]


def test_the_offer_shows_the_notes_and_a_new_major_version(qapp, github, tmp_path, monkeypatch):
    github.release("2.0.0", build(tmp_path, "2.0.0"), body="New colors.")
    fetched = theme_sources.newest_eligible(GH)[0]
    offer = theme_sources.Offer("sample-theme", "Sample Theme", "1.4.0", fetched)

    def exec_(box):
        assert "2.0.0 is available (you have 1.4.0)" in box.text()
        assert "New colors." in box.informativeText() and "new major version" in box.informativeText()
        assert [b.text() for b in box.buttons()] == ["Install now", "Not now", "Skip this version"]
        box.buttons()[-1].click()
        return 0

    monkeypatch.setattr(QMessageBox, "exec", exec_)
    assert settings_plugins.ask_theme_update(None, offer) == "skip"
    fetched.discard()


@pytest.fixture
def window(qapp):
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
    assert scheduled == []
    github.release("1.0.0")
    theme_sources.install(theme_sources.newest_eligible(GH)[0])
    updater.set_update_mode("off")
    maintenance.schedule_theme_update_check(SimpleNamespace())
    assert scheduled == []
    for mode in ("ask", "auto"):
        updater.set_update_mode(mode)
        maintenance.schedule_theme_update_check(SimpleNamespace())
    assert len(scheduled) == 2


def test_startup_offers_the_update_then_installs_on_a_worker(window, update, monkeypatch):
    updater.set_update_mode("auto")
    offered = choose(monkeypatch, "later")
    maintenance.on_theme_updates_done(window, theme_sources.check_updates())
    assert len(offered) == 1 and themes.installed()[0].manifest.version == "1.0.0" and window.installed == []
    threads, install = [], theme_sources.install
    monkeypatch.setattr(theme_sources, "install",
                        lambda fetched: threads.append(threading.current_thread()) or install(fetched))
    choose(monkeypatch, "install")
    maintenance.on_theme_updates_done(window, theme_sources.check_updates())
    wait_until(lambda: window.installed)
    assert themes.installed()[0].manifest.version == "1.1.0" and window.installed == ["sample-theme"]
    assert threads and threads[0] is not threading.main_thread()


def test_off_while_checking_offers_nothing_and_a_failure_is_only_logged(window, github, update, monkeypatch):
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


def test_an_install_re_renders_only_when_the_open_deck_uses_the_key():
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


def test_a_theme_that_updates_automatically_is_installed_without_asking(window, update, monkeypatch):
    theme_sources.set_auto_update("sample-theme", True)
    updater.set_update_mode("ask")
    offered = choose(monkeypatch, "later")
    maintenance.on_theme_updates_done(window, theme_sources.check_updates())
    wait_until(lambda: window.installed)
    assert offered == [] and themes.installed()[0].manifest.version == "1.1.0" and window.installed == ["sample-theme"]
    assert any("updated to 1.1.0" in text for text in window.toast.shown)
    assert theme_sources.read_source("sample-theme").auto_update


def test_help_check_for_updates_reports_status_and_offers_an_update_even_when_off(
    window, github, installed_theme, tmp_path, monkeypatch,
):
    updater.set_update_mode("off")
    offered = choose(monkeypatch, "later")
    maintenance.on_theme_updates_done(window, theme_sources.check_updates(), manual=True)
    assert offered == [] and any("up to date" in text for text in window.toast.shown)
    github.release("1.1.0", build(tmp_path, "1.1.0"))
    maintenance.on_theme_updates_done(window, theme_sources.check_updates(), manual=True)
    assert len(offered) == 1 and themes.installed()[0].manifest.version == "1.0.0"


def test_revert_to_online_installs_the_release_again_and_trashes_the_projects_copy(tab, github, monkeypatch, tmp_path):
    github.release("1.0.0", ASSET.read_bytes())
    answer(monkeypatch, True)
    tab.add_theme_from_github(GH)
    idle(tab)
    folder = next(f for f in themes.installed_dirs() if f.name == "sample-theme")
    template = folder / themes.template_file("sample-theme")
    online = template.read_bytes()
    template.write_text("edited in the installed folder", encoding="utf-8")
    copy = themes.copy_to_project("sample-theme", tab.app.project.root)
    copy.write_text("edited in the project", encoding="utf-8")
    trashed = []
    monkeypatch.setattr(settings_plugins.deck_snapshot, "move_to_trash",
                        lambda path: trashed.append(path.name) or (shutil.rmtree(path) if path.is_dir() else path.unlink()) or True)
    row = tab.theme_rows["sample-theme"]
    assert row.revert_button is not None
    asked = answer(monkeypatch, False)
    row.revert_button.click()
    assert template.read_text(encoding="utf-8") == "edited in the installed folder" and copy.exists()   # asked, declined
    assert themes.template_file("sample-theme") in asked[0]
    answer(monkeypatch, True)
    row.revert_button.click()
    idle(tab)
    assert template.read_bytes() == online and not copy.exists()
    assert themes.template_file("sample-theme") in trashed and "back to the release" in tab.status.text()
    assert tab.app.installed_keys == ["sample-theme", "sample-theme"]


def test_a_file_installed_theme_has_no_revert_button(tab):
    themes.install_file(ASSET)
    tab.refresh()
    assert tab.theme_rows["sample-theme"].revert_button is None
