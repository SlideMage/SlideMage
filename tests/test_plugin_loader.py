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


def test_hello_loads(monkeypatch):
    use_dev(monkeypatch, "hello")
    p = load()["hello"]
    assert p.state == "loaded" and p.source == "dev"
    assert [c.id for c in p.contributions.commands] == ["hello.say"]
    assert p.contributions.menu_entries == [("deck", "hello.say")]


def test_installed_and_dev_override(tmp_path, monkeypatch):
    installed = tmp_path / "config" / "plugins"
    shutil.copytree(FIXTURES / "hello", installed / "hello")
    (installed / ".staging").mkdir()
    shutil.copytree(FIXTURES / "hello", installed / ".staging" / "x")    # hidden folders are skipped
    assert [f.source for f in loader.discover()] == ["installed"]
    use_dev(monkeypatch, "hello")
    (found,) = loader.discover()
    assert found.source == "dev" and "replaces the installed copy" in found.note
    assert load()["hello"].note == found.note


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


def test_bad_manifest(monkeypatch):
    use_dev(monkeypatch, "bad-manifest")
    p = load()["bad-manifest"]
    assert p.state == "failed" and "version" in p.reason and p.manifest is None


def test_raising_activate_is_cleaned_up(monkeypatch):
    use_dev(monkeypatch, "raises", "hello")
    plugins = load()
    assert plugins["raises"].state == "failed" and "boom" in plugins["raises"].reason
    assert plugins["raises"].contributions.commands == []
    assert "raises" not in sys.modules
    assert plugins["hello"].state == "loaded"       # the others still load


def test_future_api(monkeypatch):
    use_dev(monkeypatch, "future-api")
    p = load()["future-api"]
    assert p.state == "incompatible" and p.reason == "written for plugin API 2"
    assert "future_api" not in sys.modules


def test_needs_newer(monkeypatch):
    use_dev(monkeypatch, "needs-newer")
    p = load()["needs-newer"]
    assert p.state == "incompatible" and p.reason == "needs SlideMage >=99"


def test_name_clash_with_stdlib(monkeypatch):
    use_dev(monkeypatch, "clash")
    p = load()["json"]
    assert p.state == "failed" and "json is taken" in p.reason
    import json as stdlib_json
    assert sys.modules["json"] is stdlib_json and hasattr(stdlib_json, "dumps")


def test_missing_package(tmp_path, monkeypatch):
    shutil.copytree(FIXTURES / "hello", tmp_path / "h")
    shutil.rmtree(tmp_path / "h" / "hello")
    monkeypatch.setenv(loader.PATH_ENV, str(tmp_path / "h"))
    p = load()["hello"]
    assert p.state == "failed" and "hello/" in p.reason


def test_relative_import(monkeypatch):
    use_dev(monkeypatch, "relative")
    p = load()["relative"]
    assert p.state == "loaded" and p.contributions.commands[0].title == "From a submodule"
    assert "relative.helper" in sys.modules


def test_late_add_is_refused(monkeypatch):
    use_dev(monkeypatch, "late-add")
    assert load()["late-add"].state == "loaded"
    host = sys.modules["late_add"].KEPT[0]
    with pytest.raises(RuntimeError):
        host.add_command("late-add.x", "X", lambda deck: None)


def test_order_by_id(monkeypatch):
    use_dev(monkeypatch, "relative", "hello", "raises")
    assert [p.id for p in loader.load_all(Registrar, "v8.64.0")] == ["hello", "raises", "relative"]


def test_unloaded_name_may_load_twice(monkeypatch):
    use_dev(monkeypatch, "hello")
    assert load()["hello"].state == "loaded"
    # a second load in the same process finds the name in sys.modules and refuses, as for any clash
    assert load()["hello"].state == "failed"


def test_legacy_state_is_migrated_once():
    base = loader.plugins_dir()
    base.mkdir(parents=True)
    (base / "state.json").write_text('{"disabled": ["hello"]}')
    assert not loader.is_enabled("hello")
    assert (base / ".state.json").is_file()
    assert not (base / "state.json").exists()
    loader.set_enabled("hello", True)
    assert loader.is_enabled("hello")


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
