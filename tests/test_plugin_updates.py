# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Plugin updates: the pure comparison, the once-a-day stamp, the startup check in off / ask / auto mode on a
stand-in window (the catalogue and the download replaced), and the Plugins tab's withdrawn row."""
from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from conftest import qapp as qapp
from slidemage import updater
from slidemage.plugins import catalogue, installer, loader, session, updates
from slidemage.plugins.loader import LoadedPlugin
from slidemage.plugins.manifest import Manifest
from slidemage.plugins.registry import Registrar
from slidemage.ui.dialogs import settings_plugins
from slidemage.ui.dialogs.settings_plugins import PluginsTab
from slidemage.ui.workspace import maintenance
from test_plugin_settings_tab import (all_text, catalogue_json, entry, isolated as isolated, write_cache, zip_plugin)
from test_plugin_settings_tab import app as app  # noqa: F401


def manifest(plugin_id="hello", version="0.1.0"):
    return Manifest(plugin_id, plugin_id.title(), version, 1, ">=0.8.0", "s", "a", "https://e.org/", "MIT")


def plugin(plugin_id="hello", version="0.1.0", source="installed", state="loaded"):
    return LoadedPlugin(Path("/x") / plugin_id, source, plugin_id, manifest(plugin_id, version), state)


def parsed(*entries):
    return catalogue.parse(catalogue_json(*entries))


# -- the comparison

def test_only_installed_plugins_with_a_newer_fitting_release():
    hello = entry("hello", version="0.11.0", requires=">=99")
    hello["releases"].append(entry("hello", version="0.10.0")["releases"][0])
    cat = parsed(hello, entry("same", version="1.0.0"), entry("older", version="0.9.0"),
                 entry("dev", version="9.0.0"), entry("future", version="2.0.0", requires=">=99"),
                 entry("notinstalled", version="3.0.0"))
    loaded = [plugin("hello", "0.9.0"), plugin("same", "1.0.0"), plugin("older", "1.0.0"),
              plugin("dev", "0.1.0", source="dev"), plugin("future", "1.0.0"), plugin("unlisted", "1.0.0")]
    found = updates.available_updates(loaded, cat, "v0.8.64.0")
    assert [(i, v, r.version) for i, v, r in found] == [("hello", "0.9.0", "0.10.0")]


# -- the startup check

class Toast:
    def __init__(self):
        self.shown = []

    def show_message(self, text, actions=(), **kw):
        self.shown.append((text, list(actions)))


@pytest.fixture
def window(monkeypatch, qapp):
    fake = SimpleNamespace(logged=[], toast=Toast(), opened=0, threads=[], asked=[], answer="later")
    fake.log = fake.logged.append
    fake.open_plugins = lambda: setattr(fake, "opened", fake.opened + 1)
    fake.plugin_updates_done = SimpleNamespace(emit=lambda result: fake.threads.append(result))
    session.set_loaded([plugin("hello", "0.1.0")])

    def ask(parent, name, have, release):
        fake.asked.append((name, have, release.version))
        return fake.answer

    monkeypatch.setattr(maintenance, "ask_plugin_update", ask)
    return fake


@pytest.fixture
def work_calls(monkeypatch):
    calls = {"fetch": 0, "installed": []}
    cat = parsed(entry("hello", "Hello", version="0.2.0"))

    def fetch(timeout=10):
        calls["fetch"] += 1
        return cat

    monkeypatch.setattr(catalogue, "fetch", fetch)
    monkeypatch.setattr(maintenance, "download_release", lambda release: Path("/nowhere"))
    monkeypatch.setattr(maintenance, "install_downloaded",
                        lambda folder, release: calls["installed"].append(release.version) or manifest("hello", release.version))
    return calls


def deliver(window, mode):
    updater.set_update_mode(mode)
    result = maintenance.plugin_update_work(mode)
    maintenance.on_plugin_updates_done(window, result)
    return result


def wait_for_thread(window, count=1):
    end = time.monotonic() + 5
    while len(window.threads) < count and time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)
    return len(window.threads) >= count


def test_ask_mode_offers_and_keeps_each_update_pending(window, work_calls, monkeypatch):
    session.set_loaded([plugin("hello", "0.1.0"), plugin("other", "0.3.0")])
    monkeypatch.setattr(catalogue, "fetch", lambda timeout=10: parsed(
        entry("hello", "Hello", version="0.2.0"), entry("other", "Other", version="0.4.0")))
    deliver(window, "ask")
    assert window.asked == [("Hello", "0.1.0", "0.2.0"), ("Other", "0.3.0", "0.4.0")]
    assert work_calls["installed"] == [] and window.toast.shown == []
    assert {key: update[2].version for key, update in window.plugin_updates_pending.items()} == {
        "hello": "0.2.0", "other": "0.4.0"}


def test_install_now_installs_on_a_thread_and_says_so(window, work_calls):
    window.answer = "install"
    deliver(window, "ask")
    assert wait_for_thread(window)
    assert work_calls["installed"] == ["0.2.0"] and "hello" not in window.plugin_updates_pending
    maintenance.on_plugin_updates_done(window, window.threads[0])
    assert window.toast.shown[-1][0] == "Plugin updates installed: Hello 0.2.0. They take effect after a restart."


def test_skip_this_version_is_not_offered_again_but_a_later_one_is(window, work_calls, monkeypatch):
    window.answer = "skip"
    deliver(window, "ask")
    assert updates.skipped_version("hello") == "0.2.0" and "hello" not in window.plugin_updates_pending
    window.asked.clear()
    deliver(window, "ask")
    assert window.asked == []
    monkeypatch.setattr(catalogue, "fetch", lambda timeout=10: parsed(entry("hello", "Hello", version="0.3.0")))
    deliver(window, "ask")
    assert window.asked == [("Hello", "0.1.0", "0.3.0")]


def test_auto_mode_installs_and_says_so(window, work_calls):
    deliver(window, "auto")
    assert work_calls["installed"] == ["0.2.0"] and window.asked == []
    assert window.toast.shown == [("Plugin updates installed: Hello 0.2.0. They take effect after a restart.", [])]


def test_a_plugins_own_choice_wins_over_the_apps_update_mode(window, work_calls):
    updates.set_auto_update("hello", True)
    deliver(window, "ask")                                                # ask mode, but the plugin updates itself
    assert work_calls["installed"] == ["0.2.0"] and window.asked == []
    work_calls["installed"].clear()
    updates.set_auto_update("hello", False)
    deliver(window, "auto")                                               # auto mode, but the plugin asks
    assert work_calls["installed"] == [] and window.asked == [("Hello", "0.1.0", "0.2.0")]
    updates.forget_choices("hello")
    assert updates.auto_choice("hello") is None


def test_auto_mode_offers_a_failed_install_by_hand(window, work_calls, monkeypatch):
    def boom(folder, release):
        raise installer.InstallError("checksum")

    monkeypatch.setattr(maintenance, "install_downloaded", boom)
    deliver(window, "auto")
    assert any("checksum" in line for line in window.logged)
    assert window.asked == [("Hello", "0.1.0", "0.2.0")]


def test_off_mode_checks_nothing(window, work_calls):
    updater.set_update_mode("off")
    maintenance.plugin_update_check(window)
    assert work_calls["fetch"] == 0 and window.threads == []
    deliver(window, "off")                  # switched off while the check ran
    assert window.toast.shown == [] and window.asked == []


def test_schedule_follows_the_mode(monkeypatch):
    scheduled = []
    monkeypatch.setattr(maintenance.QTimer, "singleShot", lambda *a: scheduled.append(a))
    updater.set_update_mode("off")
    maintenance.schedule_plugin_update_check(SimpleNamespace())
    assert scheduled == []
    for mode in ("ask", "auto"):
        updater.set_update_mode(mode)
        maintenance.schedule_plugin_update_check(SimpleNamespace())
    assert len(scheduled) == 2


def test_the_check_runs_on_a_thread_once_a_day(window, work_calls):
    updater.set_update_mode("ask")
    maintenance.plugin_update_check(window)
    assert wait_for_thread(window)
    assert work_calls["fetch"] == 1
    maintenance.on_plugin_updates_done(window, window.threads[0])          # a success stamps the day
    maintenance.plugin_update_check(window)
    time.sleep(0.1)
    QApplication.processEvents()
    assert work_calls["fetch"] == 1 and len(window.threads) == 1
    stamp = loader.plugins_dir() / updates.CHECK_FILE
    stamp.write_text(str(time.time() + 3600))
    assert updates.check_due()
    stamp.write_text("garbage")
    assert updates.check_due()
    stamp.write_text(str(time.time() - 2 * 86400))
    maintenance.plugin_update_check(window)
    assert wait_for_thread(window, count=2)
    assert work_calls["fetch"] == 2


def test_no_installed_plugin_means_no_network(window, work_calls):
    session.set_loaded([plugin("dev", "1.0.0", source="dev")])
    updater.set_update_mode("ask")
    maintenance.plugin_update_check(window)
    assert work_calls["fetch"] == 0


def test_a_failed_check_is_only_logged_and_tried_again(window, monkeypatch):
    def offline(timeout=10):
        raise catalogue.CatalogueError("Could not load the plugin list: offline")

    monkeypatch.setattr(catalogue, "fetch", offline)
    deliver(window, "ask")
    assert window.toast.shown == [] and "offline" in window.logged[0]
    assert updates.check_due()                     # not stamped: the next start asks again


def test_nothing_new_shows_nothing_but_stamps(window, work_calls, monkeypatch):
    monkeypatch.setattr(catalogue, "fetch", lambda timeout=10: parsed(entry("hello", version="0.1.0")))
    deliver(window, "ask")
    assert window.toast.shown == [] and not updates.check_due()


# -- the withdrawn row

def test_the_tab_flags_a_withdrawn_version(app, tmp_path):    # noqa: F811
    installer.install(zip_plugin(tmp_path))
    installer._changed.clear()
    session.set_loaded(loader.load_all(Registrar, "v0.8.64.0"))
    write_cache(entry("hello", version="0.2.0", requires=">=99"))
    tab = PluginsTab(app)
    row = tab.rows["hello"]
    assert row.withdrawn_label is not None
    assert settings_plugins.WITHDRAWN_NOTE in all_text(row)
    write_cache(entry("hello", version="0.1.0"))
    assert PluginsTab(app).rows["hello"].withdrawn_label is None
    (loader.plugins_dir() / catalogue.CACHE_NAME).unlink()
    assert PluginsTab(app).rows["hello"].withdrawn_label is None            # no list: nothing known


def test_help_check_for_updates_offers_a_plugin_update_even_when_updates_are_off(window, work_calls):
    updater.set_update_mode("off")
    maintenance.on_plugin_updates_done(window, maintenance.plugin_update_work("ask"), manual=True)
    assert window.asked == [("Hello", "0.1.0", "0.2.0")] and work_calls["installed"] == []


def test_help_check_for_updates_says_when_the_plugins_are_up_to_date(window, work_calls, monkeypatch):
    monkeypatch.setattr(catalogue, "fetch", lambda timeout=10: parsed(entry("hello", "Hello", version="0.1.0")))
    maintenance.on_plugin_updates_done(window, maintenance.plugin_update_work("ask"), manual=True)
    assert window.asked == [] and any("up to date" in text for text, _ in window.toast.shown)
