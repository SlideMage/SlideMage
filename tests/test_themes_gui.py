# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings → Extensions with theme packages (themes.py): the Themes list with Remove, and Install from file… taking a
.smtheme (its theme.toml shown first, a .sha256 beside it checked)."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QMessageBox, QWidget

from conftest import qapp as qapp
from slidemage import themes
from slidemage.plugins import installer, session
from slidemage.ui.dialogs import settings_plugins
from slidemage.ui.dialogs.settings_plugins import PluginsTab
from slidemage.ui.kit.theme import ThemeManager

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import make_theme_package  # noqa: E402


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
    folder = tmp_path / "src" / "sample-theme"
    shutil.copytree(REPO / "tests" / "fixtures" / "theme_package" / "sample-theme", folder)
    return make_theme_package.pack(folder, tmp_path / "dist")


def answer(monkeypatch, yes):
    asked = []

    def question(parent, title, text, *a, **k):
        asked.append(text)
        return QMessageBox.StandardButton.Yes if yes else QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    return asked


def test_no_theme_says_how_to_get_one(tab):
    assert tab.theme_rows == {}


def test_install_from_file_takes_a_theme_after_showing_its_manifest(tab, package, monkeypatch):
    asked = answer(monkeypatch, False)
    assert tab.install_from_file(package) is False
    assert themes.installed() == [] and "Sample Theme 1.0.0" in asked[0] and "Template key: sample-theme" in asked[0]
    asked = answer(monkeypatch, True)
    assert tab.install_from_file(package) is True
    assert list(tab.theme_rows) == ["sample-theme"] and "is installed" in tab.status.text()
    assert not installer.pending_restart()          # a theme needs no restart
    tab.install_from_file(package)
    assert "replaces the installed version 1.0.0" in asked[-1]


def test_a_theme_that_does_not_match_its_sha256_file_is_not_even_offered(tab, package, monkeypatch):
    asked = answer(monkeypatch, True)
    Path(str(package) + ".sha256").write_text(f"{'1' * 64}  {package.name}\n")
    assert tab.install_from_file(package) is False
    assert asked == [] and "does not match" in tab.status.text() and themes.installed() == []


def test_a_broken_theme_is_a_caption(tab, tmp_path):
    bad = tmp_path / "bad.smtheme"
    bad.write_bytes(b"no zip")
    assert tab.install_from_file(bad) is False
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


def test_add_from_file_offers_themes_only(tab, monkeypatch):
    seen = {}

    def dialog(parent, title, folder, filters):
        seen["filters"] = filters
        return "", ""

    monkeypatch.setattr(settings_plugins.QFileDialog, "getOpenFileName", staticmethod(dialog))
    tab.theme_file_button.click()
    assert seen["filters"] == settings_plugins.THEME_FILES
