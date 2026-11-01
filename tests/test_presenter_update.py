# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""SlideMage Presenter's release assets and update notice (docs/plans/presenter-app.md, step 4): the updater's
Presenter flavour, when the Presenter looks for a release, the notice in the start window and its button, and the
macOS keep-awake backend. The layout store and the update-mode file are isolated by conftest."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from slidemage import updater
from slidemage.presentation import keep_awake, presenter_update
from slidemage.ui.presentation import presenter_window
from slidemage.ui.presentation.presenter_window import PresenterStartWindow

NEWER = "v99.0.0"


def release(tag=NEWER, asset="https://api.example/asset"):
    return updater.Release(tag=tag, page_url=f"https://example.org/releases/{tag}", asset_url=asset, asset_size=10)


# -- updater.py: the Presenter flavour -----------------------------------------------------------

@pytest.mark.parametrize("platform, expected", [
    ("win32", ("SlideMagePresenter-windows.zip", "SlideMagePresenter.exe")),
    ("linux", ("SlideMagePresenter-linux.zip", "SlideMagePresenter")),
    ("darwin", ("SlideMagePresenter-macos.zip", "SlideMage Presenter.app")),
])
def test_presenter_asset_names(monkeypatch, platform, expected):
    monkeypatch.setattr(sys, "platform", platform)
    assert updater.asset_names(updater.PRESENTER) == expected


@pytest.mark.parametrize("executable, expected", [
    ("C:/Apps/SlideMagePresenter/SlideMagePresenter.exe", True),
    ("/opt/SlideMagePresenter/SlideMagePresenter", True),
    ("/Applications/SlideMage Presenter.app/Contents/MacOS/anything", True),
    ("C:/Apps/SlideMage/SlideMage.exe", False),
    ("/usr/bin/python3", False),
])
def test_the_running_program_is_the_presenter_by_its_executable(monkeypatch, executable, expected):
    monkeypatch.delenv(updater.FLAVOUR_ENV_VAR, raising=False)
    monkeypatch.setattr(sys, "executable", executable)
    assert updater.is_presenter() is expected
    monkeypatch.setattr(sys, "platform", "win32")
    assert (updater.asset_names()[0] == "SlideMagePresenter-windows.zip") is expected


def test_slidemage_itself_keeps_its_assets(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", "C:/Apps/SlideMage/SlideMage.exe")
    monkeypatch.setenv(updater.FLAVOUR_ENV_VAR, "folder")
    assert updater.asset_names() == ("SlideMage-windows-folder.zip", "SlideMage.exe")
    monkeypatch.setenv(updater.FLAVOUR_ENV_VAR, "single")
    assert updater.asset_names() == ("SlideMage-windows.zip", "SlideMage.exe")


def test_a_release_is_read_for_the_presenters_asset(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    data = {"tag_name": NEWER, "assets": [{"name": "SlideMage-linux.zip", "url": "slidemage-url", "size": 1},
                                          {"name": "SlideMagePresenter-linux.zip", "url": "presenter-url", "size": 2}]}
    assert updater._release_from(data, updater.PRESENTER).asset_url == "presenter-url"
    assert updater._release_from({"tag_name": NEWER, "assets": [data["assets"][0]]}, updater.PRESENTER).asset_url is None


def test_a_release_without_the_presenter_asset_is_not_offered():
    plan = updater.plan_update([release("v99.0.0", asset=None), release("v98.0.0")], "v0.13.5", need_asset=True)
    assert plan.latest.tag == "v98.0.0"
    assert updater.plan_update([release("v99.0.0", asset=None)], "v0.13.5", need_asset=True).latest is None


@pytest.mark.parametrize("platform, expected", [("win32", True), ("linux", True), ("darwin", False)])
def test_only_windows_and_linux_builds_replace_themselves(monkeypatch, platform, expected):
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert updater.can_self_update() is expected


def test_the_updater_stays_light():
    script = ("import sys, slidemage.updater\n"
              "print(sorted(m for m in sys.modules if m.split('.')[0] in ('PySide6', 'lxml')))")
    env = {**os.environ, "PYTHONPATH": str(Path(updater.__file__).resolve().parents[1])}
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60, env=env)
    assert done.returncode == 0 and done.stdout.strip() == "[]", done.stderr[-500:] or done.stdout


# -- presenter_update.py: when to look -----------------------------------------------------------

def test_the_update_mode_off_never_checks():
    updater.set_update_mode(updater.UPDATE_MODE_OFF)
    assert not presenter_update.check_allowed()
    for mode in (updater.UPDATE_MODE_ASK, updater.UPDATE_MODE_AUTO):
        updater.set_update_mode(mode)
        assert presenter_update.check_allowed()


def test_find_update_asks_for_the_presenter_asset(monkeypatch):
    asked = []
    monkeypatch.setattr(updater, "fetch_releases", lambda **kw: asked.append(kw) or [release("v98.0.0"), release()])
    found = presenter_update.find_update("v0.13.5")
    assert found.tag == NEWER and asked == [{"flavour": updater.PRESENTER}]
    assert presenter_update.find_update("v99.0.0") is None


# -- the start window ---------------------------------------------------------------------------

@pytest.fixture
def window(qapp, monkeypatch):
    """A start window whose background work runs on the spot, and whose fetch is counted."""
    monkeypatch.setattr(presenter_window, "run_in_background", lambda work: work())
    fetched = []
    releases = {"value": [release()]}

    def fetch(**kw):
        fetched.append(kw)
        return releases["value"]

    monkeypatch.setattr(updater, "fetch_releases", fetch)
    win = PresenterStartWindow()
    win.fetched, win.releases = fetched, releases
    return win


def test_the_notice_is_hidden_until_an_update_is_found(window):
    assert window.update_bar.isHidden()


def test_a_newer_release_with_a_presenter_asset_shows_the_notice(window, monkeypatch):
    monkeypatch.setattr(updater, "can_self_update", lambda: True)
    window.start_update_check()
    assert window.fetched == [{"flavour": updater.PRESENTER}]
    assert not window.update_bar.isHidden()
    assert window.update_label.text() == f"SlideMage Presenter {NEWER} is available."
    assert window.update_button.text() == "Update and restart"


def test_a_release_without_the_asset_shows_nothing(window):
    window.releases["value"] = [release(asset=None)]
    window.start_update_check()
    assert len(window.fetched) == 1 and window.update_bar.isHidden() and window.update_release is None


def test_an_older_release_shows_nothing(window):
    window.releases["value"] = [release("v0.0.1")]
    window.start_update_check()
    assert window.update_bar.isHidden()


def test_mode_off_never_asks_github(window):
    updater.set_update_mode(updater.UPDATE_MODE_OFF)
    window.start_update_check()
    assert window.fetched == [] and window.update_bar.isHidden()


def test_it_looks_at_every_start(window):
    """Once a day hid a new release for up to 24 hours after the last look."""
    window.start_update_check()
    window.start_update_check()
    assert len(window.fetched) == 2



def test_a_network_error_is_silent(window, monkeypatch):
    def fail(**_kw):
        raise updater.UpdateError("offline")

    monkeypatch.setattr(updater, "fetch_releases", fail)
    window.start_update_check()
    assert window.update_bar.isHidden()


def test_the_button_installs_on_windows_and_linux(window, monkeypatch, tmp_path):
    for platform, binary in (("win32", "SlideMagePresenter.exe"), ("linux", "SlideMagePresenter")):
        monkeypatch.setattr(sys, "platform", platform)
        monkeypatch.setattr(updater, "can_self_update", lambda: True)
        calls = []
        staging = tmp_path / "SlideMagePresenter.update"
        monkeypatch.setattr(updater, "download",
                            lambda rel, dest, progress: calls.append(("download", rel.tag, progress(5, 10))))
        monkeypatch.setattr(updater, "stage_folder_update",
                            lambda zip_path, folder, name: calls.append(("stage", folder, name)) or staging)
        monkeypatch.setattr(updater, "spawn_folder_swap",
                            lambda folder, stage, name, relaunch=None: calls.append(("swap", folder, stage, name, relaunch)))
        quits = []
        monkeypatch.setattr(presenter_window, "QApplication", SimpleNamespace(quit=lambda: quits.append(True)))
        window.show_update(release())
        assert window.update_button.text() == "Update and restart"
        window.update_button.click()
        folder = Path(sys.executable).parent
        assert calls == [("download", NEWER, True), ("stage", folder, binary), ("swap", folder, staging, binary, [])]
        assert quits == [True]
        window.updating = False


def test_the_button_shows_progress_and_a_failure(window, monkeypatch):
    monkeypatch.setattr(updater, "can_self_update", lambda: True)
    monkeypatch.setattr(sys, "platform", "linux")
    window.show_update(release())
    window.updating = True
    window.show_progress(5, 10)
    assert "50 %" in window.update_label.text()
    window.updating = False

    def fail(*_args, **_kw):
        raise updater.UpdateError("Download failed: 404")

    monkeypatch.setattr(updater, "download", fail)
    window.update_button.click()
    assert "Download failed: 404" in window.update_label.text()
    assert window.update_button.isEnabled() and window.update_button.text() == "Try again" and not window.updating


def test_no_update_during_a_talk(window, monkeypatch):
    monkeypatch.setattr(updater, "can_self_update", lambda: True)
    called = []
    monkeypatch.setattr(updater, "download", lambda *a, **k: called.append(a))
    window.show_update(release())
    window.presenting = True
    window.update_button.click()
    assert called == [] and not window.updating


def test_an_update_installed_during_a_talk_quits_when_the_talk_has_ended(window, monkeypatch):
    quits = []
    monkeypatch.setattr(presenter_window, "QApplication", SimpleNamespace(quit=lambda: quits.append(True)))
    monkeypatch.setattr(presenter_window.standalone, "present_pdf_file", lambda path: window.finish_update() or True)
    window.present(Path("talk.pdf"))
    assert quits == [True] and window.isHidden()


def test_macos_and_a_source_checkout_open_the_release_page(window, monkeypatch):
    opened = []
    monkeypatch.setattr(presenter_window.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or True)
    monkeypatch.setattr(updater, "download", lambda *a, **k: pytest.fail("must not download"))
    for platform in ("darwin", "linux"):
        monkeypatch.setattr(sys, "platform", platform)      # not frozen: the first is the Mac's case, the second a checkout
        window.show_update(release())
        assert window.update_button.text() == "Download…"
        window.update_button.click()
    assert opened == [f"https://example.org/releases/{NEWER}"] * 2
    assert not window.updating


# -- keep_awake.py: macOS ---------------------------------------------------------------------

class FakeProcess:
    def __init__(self, command):
        self.command, self.terminated = command, 0

    def terminate(self):
        self.terminated += 1


def test_the_mac_backend_runs_caffeinate_for_this_process_and_ends_it(monkeypatch):
    started = []
    monkeypatch.setattr(keep_awake.subprocess, "Popen",
                        lambda command, **kw: started.append(FakeProcess(command)) or started[-1])
    backend = keep_awake._Mac()
    backend.start()
    assert started[0].command == ["caffeinate", "-d", "-i", "-w", str(os.getpid())]
    backend.stop()
    backend.stop()
    assert started[0].terminated == 1
    monkeypatch.setattr(sys, "platform", "darwin")
    assert isinstance(keep_awake.default_backend(), keep_awake._Mac)


def test_a_missing_caffeinate_never_fails_the_show(monkeypatch):
    def missing(*_a, **_k):
        raise FileNotFoundError("caffeinate")

    monkeypatch.setattr(keep_awake.subprocess, "Popen", missing)
    awake = keep_awake.KeepAwake(keep_awake._Mac())
    awake.start()
    assert not awake.active
    awake.stop()
