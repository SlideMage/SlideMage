"""The update check on start (v4.1.0): modes, the four answers to the
"Update available" question, and breaking releases asked about even in
"auto" mode. Uses SlideMageWindow's methods on a stand-in object, so no
dialog is ever shown."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from slidemage import qt_gui, updater


def _release(tag, body=""):
    return updater.Release(tag, f"https://example.invalid/{tag}", "asset", 1, body)


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "config_dir", lambda: tmp_path / "cfg")
    monkeypatch.setattr(qt_gui.version_mod, "VERSION_NUMBER", "v4.1.0")
    fake = SimpleNamespace(installed=[], logged=[], asked=[])
    fake.log = fake.logged.append
    fake._download_and_install_update = lambda release: fake.installed.append(release.tag)
    fake._ask_update_choice = lambda release: fake.asked.append(("choice", release.tag)) or fake.choice
    fake._ask_breaking_update = lambda plan: fake.asked.append(("breaking", plan.latest.tag)) or fake.breaking_choice
    fake._confirm_safe_update = lambda release: fake.asked.append(("safe", release.tag)) or fake.confirm_safe
    for name in ("_offer_update", "_apply_update_choice", "_on_startup_update_check_done"):
        setattr(fake, name, getattr(qt_gui.SlideMageWindow, name).__get__(fake))
    return fake


@pytest.mark.parametrize("choice, installed, mode", [
    ("install", ["v4.2.0"], "ask"),
    ("later", [], "ask"),
    ("auto", ["v4.2.0"], "auto"),
    ("off", [], "off"),
])
def test_ask_mode_choices(window, choice, installed, mode):
    window.choice = choice
    window._on_startup_update_check_done(updater.plan_update([_release("v4.2.0")], "v4.1.0"))
    assert window.asked == [("choice", "v4.2.0")]
    assert window.installed == installed
    assert updater.get_update_mode() == mode


def test_auto_mode_installs_without_asking(window):
    updater.set_update_mode("auto")
    window._on_startup_update_check_done(updater.plan_update([_release("v4.2.0")], "v4.1.0"))
    assert window.asked == []
    assert window.installed == ["v4.2.0"]


def test_errors_and_up_to_date_only_log(window):
    window._on_startup_update_check_done(updater.UpdateError("offline"))
    window._on_startup_update_check_done(updater.plan_update([_release("v4.1.0")], "v4.1.0"))
    assert window.asked == [] and window.installed == []
    assert window.logged == ["Update check failed: offline", "SlideMage v4.1.0 is up to date."]


RELEASES = [_release("v5.0.0", "BREAKING: new project format."), _release("v4.3.0")]


@pytest.mark.parametrize("mode", ["ask", "auto"])
def test_breaking_update_is_always_asked(window, mode):
    updater.set_update_mode(mode)
    window.breaking_choice = "later"
    window._on_startup_update_check_done(updater.plan_update(RELEASES, "v4.1.0"))
    assert window.asked == [("breaking", "v5.0.0")]
    assert window.installed == []


def test_breaking_update_install_anyway(window):
    window.breaking_choice = "install"
    window._on_startup_update_check_done(updater.plan_update(RELEASES, "v4.1.0"))
    assert window.installed == ["v5.0.0"]


def test_staying_on_the_major_version_installs_the_safe_release(window):
    window.breaking_choice = "stay"
    updater.set_update_mode("auto")
    window._on_startup_update_check_done(updater.plan_update(RELEASES, "v4.1.0"))
    assert window.installed == ["v4.3.0"]
    assert ("safe", "v4.3.0") not in window.asked  # auto: no second question

    window.installed.clear()
    updater.set_update_mode("ask")
    window.confirm_safe = False
    window._on_startup_update_check_done(updater.plan_update(RELEASES, "v4.1.0"))
    assert ("safe", "v4.3.0") in window.asked
    assert window.installed == []


def test_no_startup_check_for_a_source_checkout(monkeypatch):
    scheduled = []
    monkeypatch.setattr(qt_gui.updater, "can_self_update", lambda: False)
    monkeypatch.setattr(qt_gui.QTimer, "singleShot", lambda *a: scheduled.append(a))
    qt_gui.SlideMageWindow.schedule_startup_update_check(SimpleNamespace())
    assert scheduled == []
