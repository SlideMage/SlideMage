# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Plugin management and navigation in Settings → Extensions."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QLabel, QScrollArea, QWidget

from conftest import answer, build_window, make_project, qapp as qapp, wait_until
from slidemage.plugins import catalogue, installer, loader, session, updates
from slidemage.plugins.registry import Registrar
from slidemage.project import ProjectContext
from slidemage.ui.dialogs import settings_plugins
from slidemage.ui.dialogs.settings import PLUGIN_LIST, PLUGINS, SettingsSheet
from slidemage.ui.dialogs.settings_plugins import PluginsTab
from slidemage.ui.kit import kit_qss as q
from slidemage.ui.kit.theme import ThemeManager

FIXTURES = Path(__file__).parent / "fixtures" / "plugins"
PACKAGES = ("hello", "raises")
HELLO_SHA = "0" * 64


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(loader.project, "config_dir", lambda: tmp_path / "config")
    monkeypatch.delenv(loader.PATH_ENV, raising=False)
    monkeypatch.delenv(catalogue.CATALOGUE_ENV, raising=False)
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    installer._changed.clear()
    session.set_loaded([])
    yield
    installer._changed.clear()
    session.set_loaded([])
    for name in PACKAGES:
        for key in [k for k in sys.modules if k == name or k.startswith(name + ".")]:
            del sys.modules[key]


@pytest.fixture(autouse=True)
def auto_answers(monkeypatch):
    asked = SimpleNamespace(what=[], yes=False)

    def ask(parent, what):
        asked.what.append(what)
        return asked.yes

    monkeypatch.setattr(settings_plugins, "ask_auto_update", ask)
    return asked


class FakeApp(QWidget):
    def __init__(self, root):
        super().__init__()
        self.project = SimpleNamespace(root=root)
        self.theme = ThemeManager()
        self.relaunched = []

    def relaunch_with_project(self, root):
        self.relaunched.append(root)


@pytest.fixture
def app(qapp, tmp_path):
    return FakeApp(tmp_path)


def load_plugins():
    session.set_loaded(loader.load_all(Registrar, "v8.64.0"))


def load_dev(monkeypatch, *names):
    monkeypatch.setenv(loader.PATH_ENV, os.pathsep.join(str(FIXTURES / n) for n in names))
    load_plugins()


def zip_plugin(tmp_path, *, version="0.1.0", network="", needs=""):
    src = FIXTURES / "hello"
    manifest = (src / "plugin.toml").read_text(encoding="utf-8")
    for key, previous, value in (
        ("version", '"0.1.0"', f'"{version}"'),
        ("network", "[]", f"[{network}]"),
        ("needs", "[]", f"[{needs}]"),
    ):
        manifest = manifest.replace(f"{key} = {previous}", f"{key} = {value}")
    return _zip(tmp_path, {
        "plugin.toml": manifest, "hello/__init__.py": (src / "hello" / "__init__.py").read_bytes(),
    }, name=f"hello-{version}.smplugin")

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def catalogue_json(*plugins, schema=1):
    return {"schema": schema, "generated": "2026-10-27T11:45:44Z", "plugins_page": "https://example.org/all/",
            "plugins": list(plugins)}


def entry(plugin_id="hello", name="Hello", version="0.1.0", sha256=HELLO_SHA, size=100, recommended=False,
          network=(), requires=">=8.0"):
    return {
        "id": plugin_id, "name": name, "summary": f"{name} does things.", "homepage": "https://example.org/",
        "source": "https://example.org/src", "icon": None, "license": "GPL-3.0-or-later", "maintainer": "Test",
        "recommended": recommended, "needs": ["Ollama"], "network": list(network),
        "releases": [{"version": version, "api_version": 1, "requires_slidemage": requires,
                      "url": f"https://example.org/{plugin_id}-{version}.smplugin", "sha256": sha256,
                      "size": size, "published": "2026-10-26"}]}


def write_cache(*plugins):
    path = loader.plugins_dir() / catalogue.CACHE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalogue_json(*plugins)), encoding="utf-8")


def fake_download(monkeypatch, source):
    """installer.download that copies `source` instead of using the network."""
    calls = []

    def download(url, dest, *, expected_size=None, **_):
        calls.append((url, expected_size))
        shutil.copy(source, dest)

    monkeypatch.setattr(installer, "download", download)
    return calls


def idle(tab):
    wait_until(lambda: tab._job is None)


def all_text(widget):
    return "\n".join(label.text() for label in widget.findChildren(QLabel))


# -- installed rows


def test_failure_details_and_incompatible_api_reason(app, monkeypatch):
    load_dev(monkeypatch, "raises", "future-api")
    shown = []
    monkeypatch.setattr(settings_plugins.TextSheet, "exec", lambda self: shown.append(self.view.toPlainText()))
    tab = PluginsTab(app)
    assert tab.rows["future-api"].state_chip.text().startswith("Written for plugin API")
    failed = tab.rows["raises"]
    assert failed.state_chip.text() == "Failed to load"
    failed.details_button.click()
    assert "Traceback" in shown[0]

# -- enable, remove

def test_enable_switch_writes_state_and_shows_banner(app, monkeypatch):
    load_dev(monkeypatch, "hello")
    tab = PluginsTab(app)
    tab.show()
    row = tab.rows["hello"]
    assert row.remove_button is None
    row.enable_check.setChecked(False)
    assert not loader.is_enabled("hello")
    assert installer.pending_restart() and installer.changed_ids() == {"hello"}
    assert tab.banner.isVisible()
    tab.rows["hello"].enable_check.setChecked(True)
    assert loader.is_enabled("hello")


def test_restart_now_leaves_the_sheet_then_relaunches(app, tmp_path):
    left = []
    tab = PluginsTab(app, left.append)
    tab.restart_now()
    assert app.relaunched == [] and len(left) == 1
    left[0]()
    assert app.relaunched == [tmp_path]
    PluginsTab(app).restart_now()               # without a sheet around it: at once
    assert app.relaunched == [tmp_path, tmp_path]


def test_remove_respects_confirmation_and_forgets_update_choices(app, tmp_path, monkeypatch):
    installer.install(zip_plugin(tmp_path))
    installer._changed.clear()
    load_plugins()
    updates.set_auto_update("hello", True)
    updates.skip_version("hello", "9.9.9")
    tab = PluginsTab(app)
    row = tab.rows["hello"]
    title_line = row.title_label.parentWidget()
    assert all(control.parentWidget() is title_line for control in (row.remove_button, row.enable_check, row.state_chip))
    installed = loader.plugins_dir() / "hello"

    answer(monkeypatch, False)
    row.remove_button.click()
    assert installed.is_dir() and not installer.pending_restart()
    assert updates.auto_choice("hello") is True and updates.skipped_version("hello") == "9.9.9"

    asked = answer(monkeypatch, True)
    row.remove_button.click()
    assert "Remove hello fixture" in asked[0] and installed.is_dir()
    assert installer.pending_restart()
    assert tab.rows["hello"].state_chip.text() == "Removed after a restart"
    assert updates.auto_choice("hello") is None and updates.skipped_version("hello") == ""

# -- install from file

def test_file_install_requires_a_valid_archive_checksum_and_confirmation(app, tmp_path, monkeypatch):
    tab = PluginsTab(app)
    bad = tmp_path / "bad.smplugin"
    bad.write_bytes(b"not a zip")
    tab.install_from_file(bad)
    assert "not a valid zip" in tab.status.text()

    archive = zip_plugin(tmp_path, network='"api.example.org"', needs='"Ollama"')
    monkeypatch.setattr(settings_plugins.QFileDialog, "getOpenFileName", lambda *a, **kw: (str(archive), ""))
    installed = loader.plugins_dir() / "hello" / "plugin.toml"
    sidecar = archive.with_suffix(".smplugin.sha256")
    asked = answer(monkeypatch, False)
    for text, message in ((f"{'1' * 64}  {archive.name}\n", "does not match"), ("garbage", "SHA-256")):
        sidecar.write_text(text)
        tab.file_button.click()
        assert not asked and tab._job is None and not installed.exists()
        assert message in tab.status.text() and tab.status.property("tone") == "error"

    sidecar.write_text(f"{sha(archive)}  {archive.name}\n")
    tab.file_button.click()
    assert tab._job is None and not installed.exists() and not installer.pending_restart()
    assert "not from the SlideMage plugin list. It runs with your rights." in asked[0]
    assert "hello fixture 0.1.0" in asked[0] and "api.example.org" in asked[0]

    answer(monkeypatch, True)
    tab.file_button.click()
    idle(tab)
    assert installed.is_file() and tab.banner.isVisibleTo(tab)
    row = tab.rows["hello"]
    assert "starts after a restart" in row.state_chip.text()
    assert row.remove_button.parentWidget() is row.title_label.parentWidget()
    assert row.state_chip.parentWidget() is not row.title_label.parentWidget()
    assert "Needs: Ollama" in all_text(row) and "Contacts: api.example.org" in all_text(row)

# -- peek and download (installer)

def test_peek_reads_the_manifest_only(tmp_path):
    assert installer.peek(zip_plugin(tmp_path)).id == "hello"
    with pytest.raises(installer.InstallError, match="plugin.toml"):
        installer.peek(_zip(tmp_path, {"x.txt": "1"}))
    with pytest.raises(installer.InstallError, match="not valid"):
        installer.peek(_zip(tmp_path, {"plugin.toml": 'id = "x"'}))
    with pytest.raises(installer.InstallError, match="valid zip"):
        (tmp_path / "n.zip").write_bytes(b"x")
        installer.peek(tmp_path / "n.zip")
    assert not (loader.plugins_dir() / "hello").exists()


def _zip(tmp_path, files, name="z.zip"):
    out = tmp_path / name
    with zipfile.ZipFile(out, "w") as zf:
        for n, d in files.items():
            zf.writestr(n, d)
    return out


@pytest.fixture
def file_server(tmp_path):
    state = {"body": b"", "status": 200}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(state["status"])
            self.send_header("Content-Length", str(len(state["body"])))
            self.end_headers()
            self.wfile.write(state["body"])

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield state, f"http://127.0.0.1:{httpd.server_port}/p.smplugin"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_download_checks_size_and_cap(tmp_path, file_server):
    state, url = file_server
    state["body"] = b"x" * 1000
    dest = tmp_path / "d.bin"
    installer.download(url, dest, expected_size=1000)
    assert dest.stat().st_size == 1000
    for kwargs, message in (({"expected_size": 999}, "size"), ({"max_bytes": 10}, "too large")):
        with pytest.raises(installer.InstallError, match=message):
            installer.download(url, dest, **kwargs)
        assert not dest.exists()
    state["status"] = 404
    with pytest.raises(installer.InstallError, match="failed"):
        installer.download(url, dest)
    assert not dest.exists()
    with pytest.raises(installer.InstallError, match="http"):
        installer.download(tmp_path.as_uri(), dest)


# -- the catalogue

def test_available_list_from_the_cache(app, monkeypatch):
    load_dev(monkeypatch, "hello")
    write_cache(entry("hello"), entry("zeta", "Zeta"), entry("alpha", "Alpha", recommended=True, network=("x.org",)),
                entry("future", "Future", requires=">=1.99"))
    tab = PluginsTab(app)
    assert list(tab.available) == ["alpha", "future", "zeta"]           # hello is installed; recommended first, then by name
    assert "Recommended" in all_text(tab.available["alpha"]) and "Contacts: x.org" in all_text(tab.available["alpha"])
    assert tab.available["alpha"].install_button.isEnabled()
    assert not tab.available["future"].install_button.isEnabled()
    assert tab.catalogue.plugins_page == "https://example.org/all/"


def test_catalogue_install_checks_download_and_hash_and_asks_about_updates(app, tmp_path, monkeypatch, auto_answers):
    archive = zip_plugin(tmp_path)
    installed = loader.plugins_dir() / "hello" / "plugin.toml"
    write_cache(entry("hello", sha256="2" * 64))
    tab = PluginsTab(app)
    monkeypatch.setattr(installer, "download", Mock(side_effect=installer.InstallError("offline")))
    tab.available["hello"].install_button.click()
    idle(tab)
    assert "offline" in tab.status.text() and not installer.pending_restart()

    calls = fake_download(monkeypatch, archive)
    tab.available["hello"].install_button.click()
    idle(tab)
    assert "checksum" in tab.status.text() and tab.status.property("tone") == "error"
    assert not installed.exists() and not installer.pending_restart() and "hello" in tab.available

    write_cache(entry("hello", sha256=sha(archive), size=archive.stat().st_size))
    tab = PluginsTab(app)
    auto_answers.yes = True
    calls.clear()
    tab.available["hello"].install_button.click()
    assert not tab.check_button.isEnabled()
    idle(tab)
    assert calls == [("https://example.org/hello-0.1.0.smplugin", archive.stat().st_size)]
    assert installed.is_file() and "hello" in tab.rows and "hello" not in tab.available
    assert installer.pending_restart() and tab.check_button.isEnabled()
    assert auto_answers.what == ["the plugin hello fixture"] and updates.auto_choice("hello") is True

    installer._changed.clear()
    load_plugins()
    row = PluginsTab(app).rows["hello"]
    assert row.auto_check.isChecked()
    row.auto_check.setChecked(False)
    assert updates.auto_choice("hello") is False


class CatalogueServer:
    def __init__(self):
        self.body, self.status = b"", 200
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(outer.status)
                self.send_header("Content-Length", str(len(outer.body)))
                self.end_headers()
                self.wfile.write(outer.body)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/index.json"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server(monkeypatch):
    s = CatalogueServer()
    monkeypatch.setenv(catalogue.CATALOGUE_ENV, s.url)
    yield s
    s.close()


def test_check_refreshes_the_list_and_preserves_it_when_too_new(app, server):
    tab = PluginsTab(app)
    assert not tab.available
    server.body = json.dumps(catalogue_json(entry("hello"))).encode()
    tab.check_button.click()
    idle(tab)
    assert list(tab.available) == ["hello"] and "up to date" in tab.status.text()
    assert (loader.plugins_dir() / catalogue.CACHE_NAME).is_file()

    server.body = json.dumps(catalogue_json(schema=2)).encode()
    tab.check_button.click()
    idle(tab)
    assert tab.status.text() == "Update SlideMage to see plugins." and list(tab.available) == ["hello"]


def test_check_for_plugins_offline_keeps_the_cache(app, monkeypatch):
    write_cache(entry("hello"))
    monkeypatch.setenv(catalogue.CATALOGUE_ENV, "http://127.0.0.1:9/index.json")
    tab = PluginsTab(app)
    tab.check_button.click()
    idle(tab)
    assert "Could not load the plugin list" in tab.status.text() and "last list is shown" in tab.status.text()
    assert tab.status.property("tone") == "error" and list(tab.available) == ["hello"]


def test_plugins_page_link(app, monkeypatch):
    opened = []
    monkeypatch.setattr(settings_plugins.QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toString())))
    tab = PluginsTab(app)
    tab.page_button.click()
    write_cache(entry("hello"))
    tab = PluginsTab(app)
    tab.page_button.click()
    assert opened == ["https://slidemage.org/plugins/", "https://example.org/all/"]


# -- the tab's order and density


def test_extensions_sections_are_ordered_and_pick_their_own_file_kinds(app, monkeypatch):
    dialog = Mock(return_value=("", ""))
    monkeypatch.setattr(settings_plugins.QFileDialog, "getOpenFileName", dialog)
    tab = PluginsTab(app)
    tab.show()
    headings = [label for label in tab.findChildren(QLabel) if label.objectName() == q.SHEET_SECTION]
    headings.sort(key=lambda label: label.mapTo(tab, label.rect().topLeft()).y())
    assert [label.text() for label in headings] == ["Themes", "Citation formats", "Plugins"]
    for button in (tab.theme_file_button, tab.citation_file_button, tab.file_button):
        button.click()
    assert [call.args[3] for call in dialog.call_args_list] == [
        "SlideMage themes (*.smtheme)", "SlideMage citation formats (*.smcite)", "SlideMage plugins (*.smplugin)",
    ]

def test_a_status_scrolls_up_to_where_it_is_shown(app, qapp):
    tab = PluginsTab(app)
    area = QScrollArea()
    area.setWidget(tab)
    area.resize(700, 120)
    area.show()
    qapp.processEvents()
    assert not tab.status.isVisibleTo(tab)
    area.verticalScrollBar().setValue(area.verticalScrollBar().maximum())
    assert area.verticalScrollBar().value() > 0
    tab._say("Done.")
    assert area.verticalScrollBar().value() == 0 and tab.status.isVisibleTo(tab)
    tab._say("")
    assert not tab.status.isVisibleTo(tab)
    area.close()


def test_opening_for_a_plugin_scrolls_to_the_plugins(app, qapp):
    app.project = ProjectContext.at(app.project.root)
    app.set_dark_mode = app.set_autosave = app.set_tab_width_chars = app.set_hover_help = lambda *args: None
    sheet = SettingsSheet(app, tab=PLUGINS, focus=PLUGIN_LIST)
    assert sheet.current_tab() == PLUGINS
    assert sheet._tabs.tabText(sheet._tabs.count() - 1) == "Extensions"
    sheet._plugins_area.setFixedHeight(120)
    sheet.show()
    qapp.processEvents()
    wait_until(lambda: sheet._plugins_area.verticalScrollBar().value() > 0)
    bar = sheet._plugins_area.verticalScrollBar()
    assert bar.value() == min(sheet.plugins.plugins_heading.y(), bar.maximum())
    sheet.close()


def test_help_opens_the_top_and_a_plugin_request_the_plugins(qapp, monkeypatch, tmp_path):
    window = build_window(monkeypatch, ProjectContext.at(make_project(monkeypatch, tmp_path / "proj")))
    opened = Mock()
    monkeypatch.setattr(window, "open_settings", opened)
    assert window.commands.run("plugins", window)
    opened.assert_called_once_with(PLUGINS)
    opened.reset_mock()
    window.open_plugins()
    opened.assert_called_once_with(PLUGINS, focus=PLUGIN_LIST)

# -- updating without asking


def test_update_stages_the_new_release_without_asking_again(app, tmp_path, monkeypatch, auto_answers):
    installer.install(zip_plugin(tmp_path))
    installer._changed.clear()
    load_plugins()
    write_cache(entry("hello", version="0.1.0"))
    assert PluginsTab(app).rows["hello"].update_button is None
    new = zip_plugin(tmp_path, version="0.2.0")
    write_cache(entry("hello", version="0.2.0", sha256=sha(new), size=new.stat().st_size))
    fake_download(monkeypatch, new)
    tab = PluginsTab(app)
    tab.rows["hello"].update_button.click()
    idle(tab)
    base = loader.plugins_dir()
    assert 'version = "0.1.0"' in (base / "hello" / "plugin.toml").read_text()
    assert 'version = "0.2.0"' in (base / ".pending" / "hello" / "plugin.toml").read_text()
    assert "starts after a restart" in tab.rows["hello"].state_chip.text()
    assert tab.rows["hello"].update_button is None and not auto_answers.what
