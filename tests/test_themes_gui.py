# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Theme package installation and removal from Settings."""
from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QWidget

from conftest import answer, pause, qapp as qapp, wait_until
from slidemage import themes
from slidemage.plugins import installer, session
from slidemage.ui.dialogs import settings_plugins
from slidemage.ui.dialogs.settings_plugins import PluginsTab
from slidemage.ui.kit.theme import ThemeManager

from test_theme_sources import ASSET


@pytest.fixture(autouse=True)
def isolated():
    installer._changed.clear()
    session.set_loaded([])
    yield
    installer._changed.clear()


class FakeApp(QWidget):
    def __init__(self, root):
        super().__init__()
        self.project = SimpleNamespace(root=root)
        self.theme = ThemeManager()


@pytest.fixture
def tab(qapp, tmp_path):
    return PluginsTab(FakeApp(tmp_path))


@pytest.fixture
def package(tmp_path):
    path = tmp_path / ASSET.name
    path.write_bytes(ASSET.read_bytes())
    digest = ASSET.with_suffix(".smtheme.sha256")
    path.with_suffix(".smtheme.sha256").write_bytes(digest.read_bytes())
    return path


def idle(tab):
    wait_until(lambda: tab._job is None)


def test_install_from_file_confirms_the_manifest_and_unpacks_on_a_worker(tab, package, monkeypatch):
    assert tab.theme_rows == {}

    def dialog(parent, title, folder, filters):
        assert filters == settings_plugins.THEME_FILES
        return str(package), filters

    monkeypatch.setattr(settings_plugins.QFileDialog, "getOpenFileName", staticmethod(dialog))
    asked = answer(monkeypatch, False)
    tab.theme_file_button.click()
    assert themes.installed() == [] and "Sample Theme 1.0.0" in asked[0] and "Template key: sample-theme" in asked[0]
    gate, threads, real = threading.Event(), [], themes.install_file

    def unpack(*args, **kwargs):
        threads.append(threading.current_thread())
        gate.wait(5)
        return real(*args, **kwargs)

    monkeypatch.setattr(themes, "install_file", unpack)
    asked = answer(monkeypatch, True)
    tab.theme_file_button.click()
    pause(tab.busy.SHOW_AFTER_MS + 100)
    assert tab.busy.isVisibleTo(tab) and not tab.theme_file_button.isEnabled()
    gate.set()
    idle(tab)
    assert threads and threads[0] is not threading.main_thread() and list(tab.theme_rows) == ["sample-theme"]
    assert "is installed" in tab.status.text()
    wait_until(lambda: not tab.busy.isVisibleTo(tab))
    assert not installer.pending_restart()
    tab.install_from_file(package)
    idle(tab)
    assert "replaces the installed version 1.0.0" in asked[-1]


def test_a_theme_that_does_not_match_its_sha256_file_is_not_even_offered(tab, package, monkeypatch):
    asked = answer(monkeypatch, True)
    Path(str(package) + ".sha256").write_text(f"{'1' * 64}  {package.name}\n")
    tab.install_from_file(package)
    assert asked == [] and "does not match" in tab.status.text() and themes.installed() == []


def test_a_broken_theme_is_a_caption(tab, tmp_path):
    bad = tmp_path / "bad.smtheme"
    bad.write_bytes(b"no zip")
    tab.install_from_file(bad)
    assert "not a valid zip" in tab.status.text() and tab.status.property("tone") == "error"


def test_remove_asks_and_removes(tab, package, monkeypatch):
    themes.install_file(package)
    tab.refresh()
    answer(monkeypatch, False)
    tab.theme_rows["sample-theme"].remove_button.click()
    assert [t.key for t in themes.installed()] == ["sample-theme"]
    answer(monkeypatch, True)
    tab.theme_rows["sample-theme"].remove_button.click()
    assert themes.installed() == [] and tab.theme_rows == {} and "removed" in tab.status.text()
