# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Discovery, state file and loading of plugins, with the fixture plugins in tests/fixtures/plugins."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from slidemage.plugins import loader
from slidemage.plugins.registry import Registrar

FIXTURES = Path(__file__).parent / "fixtures" / "plugins"
PACKAGES = ("hello", "raises", "future_api", "needs_newer", "relative", "late_add", "bad_manifest")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(loader.project, "config_dir", lambda: tmp_path / "config")
    monkeypatch.delenv(loader.PATH_ENV, raising=False)
    yield
    for name in PACKAGES:
        for key in [k for k in sys.modules if k == name or k.startswith(name + ".")]:
            del sys.modules[key]


def use_dev(monkeypatch, *names):
    monkeypatch.setenv(loader.PATH_ENV, __import__("os").pathsep.join(str(FIXTURES / n) for n in names))


def load(version="v8.64.0"):
    return {p.id: p for p in loader.load_all(Registrar, version)}


def test_installed_and_dev_override(tmp_path, monkeypatch):
    installed = tmp_path / "config" / "plugins"
    shutil.copytree(FIXTURES / "hello", installed / "hello")
    (installed / ".staging").mkdir()
    shutil.copytree(FIXTURES / "hello", installed / ".staging" / "x")    # hidden folders are skipped
    assert [f.source for f in loader.discover()] == ["installed"]
    use_dev(monkeypatch, "hello")
    (found,) = loader.discover()
    assert found.source == "dev" and "replaces the installed copy" in found.note
    plugin = load()["hello"]
    assert (plugin.state, plugin.source, plugin.note) == ("loaded", "dev", found.note)
    assert [c.id for c in plugin.contributions.commands] == ["hello.say"]
    assert plugin.contributions.menu_entries == [("deck", "hello.say")]


def test_folders_without_manifest_are_ignored(tmp_path, monkeypatch):
    (tmp_path / "empty").mkdir()
    monkeypatch.setenv(loader.PATH_ENV, str(tmp_path / "empty"))
    assert loader.discover() == []


def test_disabled(monkeypatch):
    use_dev(monkeypatch, "hello")
    assert loader.is_enabled("hello")
    loader.set_enabled("hello", False)
    assert not loader.is_enabled("hello")
    assert json.loads((loader.plugins_dir() / ".state.json").read_text()) == {"disabled": ["hello"]}
    assert load()["hello"].state == "disabled"
    loader.set_enabled("hello", True)
    assert load()["hello"].state == "loaded"


def test_invalid_plugins_do_not_stop_other_plugins_loading(monkeypatch):
    use_dev(monkeypatch, "relative", "raises", "future-api", "bad-manifest", "needs-newer")
    plugins = load()
    assert list(plugins) == ["bad-manifest", "future-api", "needs-newer", "raises", "relative"]
    bad, api, newer, broken, relative = plugins.values()
    assert bad.state == "failed" and bad.manifest is None and "version" in bad.reason
    assert api.state == "incompatible" and "API 2" in api.reason and "future_api" not in sys.modules
    assert newer.state == "incompatible" and ">=99" in newer.reason
    assert broken.state == "failed" and "boom" in broken.reason and not broken.contributions.commands
    assert "raises" not in sys.modules
    assert relative.state == "loaded" and relative.contributions.commands[0].title == "From a submodule"


def test_name_clash_with_stdlib(monkeypatch):
    use_dev(monkeypatch, "clash")
    p = load()["json"]
    assert p.state == "failed" and "json is taken" in p.reason
    assert sys.modules["json"] is json and hasattr(json, "dumps")


def test_missing_package(tmp_path, monkeypatch):
    shutil.copytree(FIXTURES / "hello", tmp_path / "h")
    shutil.rmtree(tmp_path / "h" / "hello")
    monkeypatch.setenv(loader.PATH_ENV, str(tmp_path / "h"))
    p = load()["hello"]
    assert p.state == "failed" and "hello/" in p.reason


def test_late_add_is_refused(monkeypatch):
    use_dev(monkeypatch, "late-add")
    assert load()["late-add"].state == "loaded"
    host = sys.modules["late_add"].KEPT[0]
    with pytest.raises(RuntimeError):
        host.add_command("late-add.x", "X", lambda deck: None)


def test_an_already_loaded_package_name_is_refused(monkeypatch):
    use_dev(monkeypatch, "hello")
    assert load()["hello"].state == "loaded"
    # a second load in the same process finds the name in sys.modules and refuses, as for any clash
    assert load()["hello"].state == "failed"


def test_ai_routes_are_registered_after_activation_and_duplicates_fail_atomically(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from slidemage.ai import routes

    monkeypatch.setattr(routes, '_routes', dict(routes._routes))
    folder = tmp_path / 'plugin'
    shutil.copytree(FIXTURES / 'hello', folder)
    source = folder / 'hello' / '__init__.py'
    monkeypatch.setenv(loader.PATH_ENV, str(folder))
    source.write_text('from types import SimpleNamespace\n'
                      'def activate(host):\n'
                      '    host.add_ai_route(SimpleNamespace(id="plugin_route"))\n')
    plugin = load()['hello']
    assert plugin.state == 'loaded'
    assert routes.get('plugin_route') is plugin.contributions.ai_routes[0]
    del sys.modules['hello']
    routes.register(SimpleNamespace(id='occupied'))
    source.write_text('from types import SimpleNamespace\n'
                      'def activate(host):\n'
                      '    host.add_ai_route(SimpleNamespace(id="another_route"))\n'
                      '    host.add_ai_route(SimpleNamespace(id="occupied"))\n')
    plugin = load()['hello']
    assert plugin.state == 'failed' and 'occupied' in plugin.reason
    assert routes.get('another_route') is None
    registrar = Registrar(SimpleNamespace(id='hello'))
    with pytest.raises(RuntimeError):
        registrar.add_ai_route(SimpleNamespace(id='late'))

def test_reserved_installed_folder_is_refused_even_with_another_manifest_id():
    folder = loader.plugins_dir() / "settings"
    shutil.copytree(FIXTURES / "hello", folder)
    found, = loader.discover()
    assert found.manifest is None and "reserved" in found.error
    assert load()["settings"].state == "failed"


@pytest.mark.parametrize("source", ["installed", "dev"])
def test_reserved_manifest_id_is_refused(tmp_path, monkeypatch, source):
    folder = loader.plugins_dir() / "settings" if source == "installed" else tmp_path / "checkout"
    shutil.copytree(FIXTURES / "hello", folder)
    path = folder / "plugin.toml"
    path.write_text(path.read_text().replace('id = "hello"', 'id = "settings"'))
    if source == "dev":
        monkeypatch.setenv(loader.PATH_ENV, str(folder))
    found, = loader.discover()
    assert found.manifest is None and "reserved" in found.error
