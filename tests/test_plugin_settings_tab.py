# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings → Plugins (step 7): the rows and states of installed plugins, the enable switch and the restart banner,
Remove, Install from file (confirmation, checksum file), the catalogue's Available list with Install (download +
hash), Check for plugins (too new, offline), and Help → Plugins… opening the tab. Nothing leaves the machine: the
download function is replaced and the catalogue comes from a local server."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QMessageBox, QWidget

from conftest import build_window, command_context, filled_menu, make_project, qapp as qapp, wait_until
from slidemage.plugins import catalogue, installer, loader, session
from slidemage.plugins.registry import Registrar
from slidemage.project import ProjectContext
from test_settings_gui import fakes as fakes, open_sheet
from slidemage.ui.dialogs import settings_plugins
from slidemage.ui.dialogs.settings import PLUGINS
from slidemage.ui.dialogs.settings_plugins import PluginsTab
from slidemage.ui.kit.theme import ThemeManager

FIXTURES = Path(__file__).parent / "fixtures" / "plugins"
PACKAGES = ("hello", "raises", "future_api", "needs_newer")
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


def load_dev(monkeypatch, *names):
    monkeypatch.setenv(loader.PATH_ENV, __import__("os").pathsep.join(str(FIXTURES / n) for n in names))
    session.set_loaded(loader.load_all(Registrar, "v8.64.0"))


def zip_plugin(tmp_path, name="hello", version=None, toml_extra="", out=None):
    """A .smplugin of the fixture plugin `name` (a version and extra manifest text can be changed)."""
    src = FIXTURES / name
    out = out or tmp_path / f"{name}.smplugin"
    with zipfile.ZipFile(out, "w") as zf:
        for path in sorted(src.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                data = path.read_bytes()
                if path.name == "plugin.toml":
                    text = data.decode()
                    if version:
                        text = text.replace('version = "0.1.0"', f'version = "{version}"')
                    data = (text + toml_extra).encode()
                zf.writestr(str(path.relative_to(src)), data)
    return out


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


def answer(monkeypatch, yes):
    asked = []

    def question(parent, title, text, *a, **k):
        asked.append(text)
        return QMessageBox.StandardButton.Yes if yes else QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    return asked


def idle(tab):
    wait_until(lambda: tab._job is None)


def chip_texts(tab):
    return {pid: r.state_chip.text() for pid, r in tab.rows.items()}


def all_text(widget):
    from PySide6.QtWidgets import QLabel
    return "\n".join(label.text() for label in widget.findChildren(QLabel))


# -- installed rows

def test_rows_show_every_state(app, monkeypatch):
    loader.set_enabled("future-api", False)
    load_dev(monkeypatch, "hello", "raises", "future-api", "needs-newer", "bad-manifest")
    tab = PluginsTab(app)
    states = chip_texts(tab)
    assert states["hello"] == "Loaded"
    assert states["raises"] == "Failed to load"
    assert states["future-api"] == "Disabled"
    assert states["needs-newer"].startswith("Needs SlideMage")
    assert states["bad-manifest"] == "Failed to load"
    row = tab.rows["hello"]
    assert row.title_label.text() == "hello fixture  0.1.0"
    text = all_text(row)
    assert "development copy" in text and "Fixture plugin hello." in text and "Contacts nothing on the network" in text
    assert row.remove_button is None and row.details_button is None       # a development copy cannot be removed
    assert row.enable_check.isChecked() and not tab.rows["future-api"].enable_check.isChecked()
    assert tab.rows["raises"].details_button is not None
    assert not tab.banner.isVisibleTo(tab)


def test_details_shows_the_traceback(app, monkeypatch):
    load_dev(monkeypatch, "raises")
    shown = []
    monkeypatch.setattr(settings_plugins.TextSheet, "exec", lambda self: shown.append(self.view.toPlainText()))
    tab = PluginsTab(app)
    tab.rows["raises"].details_button.click()
    assert "Traceback" in shown[0]


def test_incompatible_api_row_names_the_reason(app, monkeypatch):
    load_dev(monkeypatch, "future-api")
    assert chip_texts(PluginsTab(app))["future-api"].startswith("Written for plugin API")


def test_network_and_needs_lines(app, tmp_path, monkeypatch):
    text = (FIXTURES / "hello" / "plugin.toml").read_text().replace(
        "needs = []", 'needs = ["Ollama"]').replace("network = []", 'network = ["api.example.org"]')
    folder = loader.plugins_dir() / "hello"
    shutil.copytree(FIXTURES / "hello", folder)
    (folder / "plugin.toml").write_text(text)
    session.set_loaded(loader.load_all(Registrar, "v8.64.0"))
    row = PluginsTab(app).rows["hello"]
    assert "Needs: Ollama" in all_text(row) and "Contacts: api.example.org" in all_text(row)
    assert row.remove_button is not None and "installed" in all_text(row)


def test_empty_tab_renders(app):
    tab = PluginsTab(app)
    assert tab.rows == {} and tab.available == {}
    assert "No plugins are installed." in all_text(tab)
    assert "has not been loaded" in tab.available_note.text()
    assert not tab.banner.isVisibleTo(tab)


# -- enable, remove

def test_enable_switch_writes_state_and_shows_banner(app, monkeypatch):
    load_dev(monkeypatch, "hello")
    tab = PluginsTab(app)
    tab.show()
    tab.rows["hello"].enable_check.setChecked(False)
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


def test_remove_confirms_and_removes(app, tmp_path, monkeypatch):
    installer.install(zip_plugin(tmp_path))
    installer._changed.clear()
    session.set_loaded(loader.load_all(Registrar, "v8.64.0"))
    tab = PluginsTab(app)
    answer(monkeypatch, False)
    tab.rows["hello"].remove_button.click()
    assert (loader.plugins_dir() / "hello").is_dir() and not installer.pending_restart()
    asked = answer(monkeypatch, True)
    tab.rows["hello"].remove_button.click()
    assert "Remove hello fixture" in asked[0]
    assert (loader.plugins_dir() / "hello").is_dir()
    assert installer.pending_restart()
    assert tab.rows["hello"].state_chip.text() == "Removed after a restart"
    assert "removed" in tab.status.text()


# -- install from file

def test_install_from_file_confirms_with_the_manifest(app, tmp_path, monkeypatch):
    text = (FIXTURES / "hello" / "plugin.toml").read_text().replace("network = []", 'network = ["api.example.org"]')
    archive = tmp_path / "net.smplugin"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("plugin.toml", text)
        zf.writestr("hello/__init__.py", (FIXTURES / "hello" / "hello" / "__init__.py").read_text())
    tab = PluginsTab(app)
    asked = answer(monkeypatch, False)
    assert tab.install_from_file(archive) is False
    assert not (loader.plugins_dir() / "hello").exists() and not installer.pending_restart()
    assert "not from the SlideMage plugin list. It runs with your rights." in asked[0]
    assert "hello fixture 0.1.0" in asked[0] and "api.example.org" in asked[0]
    answer(monkeypatch, True)
    assert tab.install_from_file(archive) is True
    assert (loader.plugins_dir() / "hello" / "plugin.toml").is_file()
    assert tab.banner.isVisibleTo(tab) and "hello" in tab.rows
    assert "starts after a restart" in tab.rows["hello"].state_chip.text()


def test_install_from_file_checks_a_sha256_file(app, tmp_path, monkeypatch):
    archive = zip_plugin(tmp_path)
    tab = PluginsTab(app)
    asked = answer(monkeypatch, True)
    Path(str(archive) + ".sha256").write_text(f"{'1' * 64}  hello.smplugin\n")
    assert tab.install_from_file(archive) is False
    assert asked == [] and "does not match" in tab.status.text()          # not even asked
    assert tab.status.property("tone") == "error" and not (loader.plugins_dir() / "hello").exists()
    Path(str(archive) + ".sha256").write_text("garbage")
    assert tab.install_from_file(archive) is False and "SHA-256" in tab.status.text()
    Path(str(archive) + ".sha256").write_text(f"{sha(archive)}  hello.smplugin\n")
    assert tab.install_from_file(archive) is True


def test_install_from_file_bad_archive_is_a_caption(app, tmp_path):
    bad = tmp_path / "bad.smplugin"
    bad.write_bytes(b"not a zip")
    tab = PluginsTab(app)
    assert tab.install_from_file(bad) is False
    assert "not a valid zip" in tab.status.text()


def test_file_dialog_installs_the_chosen_file(app, tmp_path, monkeypatch):
    archive = zip_plugin(tmp_path)
    monkeypatch.setattr(settings_plugins.QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(archive), "")))
    answer(monkeypatch, True)
    tab = PluginsTab(app)
    tab.file_button.click()
    assert (loader.plugins_dir() / "hello").is_dir()


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


def _zip(tmp_path, files):
    out = tmp_path / "z.zip"
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
    with pytest.raises(installer.InstallError, match="http"):
        installer.download(tmp_path.as_uri(), dest)


# -- the catalogue

def test_available_list_from_the_cache(app, tmp_path, monkeypatch):
    load_dev(monkeypatch, "hello")
    write_cache(entry("hello"), entry("zeta", "Zeta"), entry("alpha", "Alpha", recommended=True, network=("x.org",)),
                entry("future", "Future", requires=">=99"))
    tab = PluginsTab(app)
    assert list(tab.available) == ["alpha", "future", "zeta"]           # hello is installed; recommended first, then by name
    assert "Recommended" in all_text(tab.available["alpha"]) and "Contacts: x.org" in all_text(tab.available["alpha"])
    assert tab.available["alpha"].install_button.isEnabled()
    assert not tab.available["future"].install_button.isEnabled()
    assert tab.catalogue.plugins_page == "https://example.org/all/"


def test_install_downloads_and_verifies_the_hash(app, tmp_path, monkeypatch):
    archive = zip_plugin(tmp_path)
    write_cache(entry("hello", "Hello", sha256=sha(archive), size=archive.stat().st_size))
    calls = fake_download(monkeypatch, archive)
    tab = PluginsTab(app)
    tab.available["hello"].install_button.click()
    assert not tab.check_button.isEnabled()                   # busy
    idle(tab)
    assert calls == [("https://example.org/hello-0.1.0.smplugin", archive.stat().st_size)]
    assert (loader.plugins_dir() / "hello" / "plugin.toml").is_file()
    assert "hello" in tab.rows and "hello" not in tab.available
    assert installer.pending_restart() and tab.check_button.isEnabled()


def test_install_with_a_wrong_hash_installs_nothing(app, tmp_path, monkeypatch):
    archive = zip_plugin(tmp_path)
    write_cache(entry("hello", sha256="2" * 64))
    fake_download(monkeypatch, archive)
    tab = PluginsTab(app)
    tab.available["hello"].install_button.click()
    idle(tab)
    assert "checksum" in tab.status.text() and tab.status.property("tone") == "error"
    assert not (loader.plugins_dir() / "hello").exists() and not installer.pending_restart()
    assert "hello" in tab.available


def test_install_download_failure_is_a_caption(app, monkeypatch):
    write_cache(entry("hello"))

    def boom(*a, **k):
        raise installer.InstallError("The download failed: offline")

    monkeypatch.setattr(installer, "download", boom)
    tab = PluginsTab(app)
    tab.available["hello"].install_button.click()
    idle(tab)
    assert "offline" in tab.status.text() and not installer.pending_restart()


def test_update_button_for_a_newer_release(app, tmp_path, monkeypatch):
    installer.install(zip_plugin(tmp_path))
    installer._changed.clear()
    session.set_loaded(loader.load_all(Registrar, "v8.64.0"))
    new = zip_plugin(tmp_path, version="0.2.0", out=tmp_path / "new.smplugin")
    write_cache(entry("hello", version="0.2.0", sha256=sha(new), size=new.stat().st_size))
    fake_download(monkeypatch, new)
    tab = PluginsTab(app)
    button = tab.rows["hello"].update_button
    assert button is not None and "0.2.0" in button.text()
    button.click()
    idle(tab)
    assert 'version = "0.1.0"' in (loader.plugins_dir() / "hello" / "plugin.toml").read_text()
    assert 'version = "0.2.0"' in (loader.plugins_dir() / ".pending" / "hello" / "plugin.toml").read_text()
    assert "starts after a restart" in tab.rows["hello"].state_chip.text()
    assert tab.rows["hello"].update_button is None            # changed this session: restart first
    write_cache(entry("hello", version="0.1.0"))
    installer._changed.clear()
    assert PluginsTab(app).rows["hello"].update_button is None        # not newer


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


def test_check_for_plugins_fills_the_list(app, server):
    server.body = json.dumps(catalogue_json(entry("hello"))).encode()
    tab = PluginsTab(app)
    tab.check_button.click()
    idle(tab)
    assert list(tab.available) == ["hello"] and "up to date" in tab.status.text()
    assert (loader.plugins_dir() / catalogue.CACHE_NAME).is_file()


def test_check_for_plugins_too_new(app, server):
    write_cache(entry("hello"))
    server.body = json.dumps(catalogue_json(schema=2)).encode()
    tab = PluginsTab(app)
    tab.check_button.click()
    idle(tab)
    assert tab.status.text() == "Update SlideMage to see plugins."
    assert list(tab.available) == ["hello"]                     # the cached list stays


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


# -- in the sheet and the menu

def test_the_tab_is_in_the_sheet_before_the_plugins_own(qapp, fakes):  # noqa: F811
    sheet = open_sheet(qapp, tab=PLUGINS)
    names = [sheet._tabs.tabText(i) for i in range(sheet._tabs.count())]
    assert names[PLUGINS] == "Plugins" and names[-1] == "Plugins"
    assert sheet._tabs.currentIndex() == PLUGINS


def test_help_plugins_opens_the_tab(qapp, monkeypatch, tmp_path):
    help_menu = filled_menu(command_context(), "Help")
    assert [a.objectName() for a in help_menu.actions() if not a.isSeparator()][-3:] == [
        "check_updates", "plugins", "project_compat"]
    window = build_window(monkeypatch, ProjectContext.at(make_project(monkeypatch, tmp_path / "proj2")))
    opened = []
    monkeypatch.setattr(type(window), "open_settings", lambda self, tab=0, **k: opened.append(tab))
    window.commands.run("plugins", window)
    assert opened == [PLUGINS]
    window.deleteLater()
