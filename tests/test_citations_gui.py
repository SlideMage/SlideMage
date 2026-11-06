# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings → Extensions with citation format packages (citations.py): the Citation formats list with Remove, and
Install from file… taking a .smcite (its citation.toml shown first, a .sha256 beside it checked)."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QMessageBox, QWidget

from conftest import qapp as qapp
from slidemage import citations
from slidemage.plugins import installer, session
from slidemage.ui.dialogs.settings_plugins import PluginsTab
from slidemage.ui.kit.theme import ThemeManager

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import make_citation_package  # noqa: E402


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
        self.installed_keys: list[str] = []

    def citation_installed(self, key: str) -> None:
        self.installed_keys.append(key)


@pytest.fixture
def tab(qapp, tmp_path):
    return PluginsTab(FakeApp(tmp_path))


@pytest.fixture
def package(tmp_path):
    folder = tmp_path / "src" / "sample-format"
    shutil.copytree(REPO / "tests" / "fixtures" / "citation_package" / "sample-format", folder)
    return make_citation_package.pack(folder, tmp_path / "dist")


def answer(monkeypatch, yes):
    asked = []

    def question(parent, title, text, *a, **k):
        asked.append(text)
        return QMessageBox.StandardButton.Yes if yes else QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    return asked


def test_no_format_is_a_caption_and_the_github_button_is_there(tab):
    assert tab.citation_rows == {} and tab.citation_github_button.text() == "Add from GitHub…"


def test_install_from_file_takes_a_package_after_showing_its_manifest(tab, package, monkeypatch):
    asked = answer(monkeypatch, False)
    assert tab.install_from_file(package) is False
    assert citations.installed() == [] and "Sample Format 1.0.0" in asked[0] and "Key: sample" in asked[0]
    asked = answer(monkeypatch, True)
    assert tab.install_from_file(package) is True
    assert list(tab.citation_rows) == ["sample"] and "is installed" in tab.status.text()
    assert "SMCitationFormat" in tab.status.text() and not installer.pending_restart()
    tab.install_from_file(package)
    assert "replaces the installed version 1.0.0" in asked[-1]


def test_a_failing_checksum_installs_nothing(tab, package, monkeypatch):
    Path(str(package) + ".sha256").write_text("0" * 64 + f"  {package.name}\n", encoding="utf-8")
    answer(monkeypatch, True)
    assert tab.install_from_file(package) is False
    assert citations.installed() == [] and "does not match" in tab.status.text()


def test_the_row_says_where_it_came_from_and_remove_deletes_it(tab, package, monkeypatch):
    answer(monkeypatch, True)
    tab.install_from_file(package)
    row = tab.citation_rows["sample"]
    assert row.update_button is None and row.source_label is None       # from a file: never updated
    tab.remove_citation("sample", "Sample Format")
    assert citations.installed() == [] and tab.citation_rows == {}


# --- the catalogue's citation formats ------------------------------------------------------------------------------


def _catalogue_entry(package, **changes):
    import hashlib
    raw = package.read_bytes()
    release = {"version": "1.0.0", "requires_slidemage": ">=0.13.0", "sha256": hashlib.sha256(raw).hexdigest(),
               "url": "https://example.org/sample-1.0.0.smcite", "size": len(raw), "published": "2026-11-06"}
    entry = {"id": "sample", "name": "Sample Format", "summary": "A sample.", "homepage": "https://example.org/s/",
             "source": "https://example.org/src", "license": "LPPL-1.3c-or-later", "maintainer": "M",
             "recommended": False, "releases": [{**release, **changes}]}
    return entry


def _with_catalogue(tab, entries):
    from slidemage.plugins.catalogue import parse
    tab.catalogue = parse({"schema": 1, "generated": "2026-11-06T00:00:00Z", "plugins_page": "https://x.org/",
                           "plugins": [], "citations": entries})
    tab.refresh()


def _run_now(tab, monkeypatch):
    """Run the tab's background jobs on the spot."""
    def start(work, done, message):
        try:
            result, error = work(), None
        except Exception as exc:  # noqa: BLE001
            result, error = None, exc
        done(result, error)
    monkeypatch.setattr(tab, "_start", start)


def test_the_catalogues_formats_are_listed_until_installed(tab, package, monkeypatch):
    assert tab.available_citations == {} and "not been loaded" in tab.citation_available_note.text()
    _with_catalogue(tab, [_catalogue_entry(package)])
    assert list(tab.available_citations) == ["sample"] and tab.available_citations["sample"].installable
    monkeypatch.setattr(installer, "download", lambda url, dest, **kw: shutil.copy(package, dest))
    _run_now(tab, monkeypatch)
    tab.available_citations["sample"].install_button.click()
    assert list(tab.citation_rows) == ["sample"] and tab.available_citations == {}
    assert "is installed" in tab.status.text() and tab.app.installed_keys == ["sample"]
    assert "installed" in tab.citation_available_note.text()


def test_a_download_that_does_not_match_the_catalogues_hash_installs_nothing(tab, package, monkeypatch):
    _with_catalogue(tab, [_catalogue_entry(package, sha256="0" * 64)])
    monkeypatch.setattr(installer, "download", lambda url, dest, **kw: shutil.copy(package, dest))
    _run_now(tab, monkeypatch)
    tab.available_citations["sample"].install_button.click()
    assert citations.installed() == [] and "does not match" in tab.status.text()
    assert list(tab.available_citations) == ["sample"]


def test_a_format_no_release_of_which_fits_cannot_be_installed_and_the_house_format_is_not_offered(tab, package):
    _with_catalogue(tab, [_catalogue_entry(package, requires_slidemage=">=99.0.0"),
                          {**_catalogue_entry(package), "id": "default"}])
    assert list(tab.available_citations) == ["sample"] and not tab.available_citations["sample"].installable
