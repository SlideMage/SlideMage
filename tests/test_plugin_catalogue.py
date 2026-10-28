# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The plugin catalogue: parsing the website's index (schema 1), best_release, and fetch with its cache."""
from __future__ import annotations

import copy
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from slidemage.plugin_api import SUPPORTED_API_VERSIONS
from slidemage.plugins import catalogue, loader
from slidemage.plugins.catalogue import (
    CATALOGUE_ENV,
    CATALOGUE_URL,
    CatalogueError,
    CatalogueTooNew,
    best_release,
    parse,
)
from slidemage.version import VERSION_NUMBER

FIXTURES = Path(__file__).parent / "fixtures" / "catalogue"
SCHEMA_FILE = FIXTURES / "plugins-index.schema.json"
HELLO_SHA = "a72af2022f7b2a5b161964d6e55376815e76be50c8645e2d02ee2dc7358c00f9"


def _raw(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _json(name: str) -> dict:
    return json.loads(_raw(name).decode("utf-8"))


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(loader.project, "config_dir", lambda: tmp_path / "config")
    monkeypatch.delenv(CATALOGUE_ENV, raising=False)
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    yield


@pytest.fixture
def server():
    """A local HTTP server; `state["body"]` and `state["status"]` say what it answers to any GET."""
    state = {"body": b"", "status": 200}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(state["body"])))
            self.end_headers()
            self.wfile.write(state["body"])

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, f"http://127.0.0.1:{httpd.server_port}/plugins/index.json"
    finally:
        httpd.shutdown()
        httpd.server_close()


def _cache_path() -> Path:
    return loader.plugins_dir() / catalogue.CACHE_NAME


# --- parsing -----------------------------------------------------------------------------------------------


def test_index_test_parses():
    cat = parse(_json("index-test.json"))
    assert cat.generated == "2026-10-27T11:45:44Z"
    assert cat.plugins_page == "https://slidemage.org/plugins/"
    assert [p.id for p in cat.plugins] == ["hello"]
    hello = cat.plugins[0]
    assert hello.name == "Hello" and hello.recommended is False
    assert hello.icon == "https://slidemage.org/plugins/hello/icon.svg"
    assert hello.needs == () and hello.network == ()
    assert len(hello.releases) == 1
    release = hello.releases[0]
    assert release.version == "0.1.0"
    assert release.sha256 == HELLO_SHA
    assert release.size == 12357
    assert release.api_version == 1 and release.requires_slidemage == ">=9.0"
    assert release.published == "2026-10-26"


def test_multi_unknown_fields_ignored():
    cat = parse(_json("index-multi.json"))
    assert [p.id for p in cat.plugins] == ["multi-release", "extra-tools"]
    assert not hasattr(cat, "themes")
    assert not hasattr(cat.plugins[0], "color")
    assert cat.plugins[1].recommended is True
    assert [r.version for r in cat.plugins[0].releases] == ["2.0.0", "1.5.0", "1.0.0"]


def test_multi_best_release_oldest_for_v9_with_api_1():
    plugin = parse(_json("index-multi.json")).plugins[0]
    release = best_release(plugin, "v9.0.0", {1})
    assert release is not None and release.version == "1.0.0"


def test_multi_best_release_api_2_when_supported():
    plugin = parse(_json("index-multi.json")).plugins[0]
    release = best_release(plugin, "v9.0.0", {1, 2})
    assert release is not None and release.version == "1.5.0"


def test_multi_best_release_newest_when_app_is_99():
    plugin = parse(_json("index-multi.json")).plugins[0]
    release = best_release(plugin, "v99.0.0", {1})
    assert release is not None and release.version == "2.0.0"


def test_multi_best_release_none_when_nothing_fits():
    plugin = parse(_json("index-multi.json")).plugins[0]
    assert best_release(plugin, "v8.64.0", {1, 2}) is None


def test_best_release_defaults_to_this_app():
    plugin = parse(_json("index-test.json")).plugins[0]
    # hello 0.1.0 needs SlideMage >=9.0, and this build is older, so nothing fits by default
    assert best_release(plugin) is None
    assert best_release(plugin, "v9.0.0") is not None
    assert best_release(plugin) == best_release(plugin, VERSION_NUMBER, SUPPORTED_API_VERSIONS)


def test_schema_two_is_too_new():
    data = _json("index-test.json")
    data["schema"] = 2
    with pytest.raises(CatalogueTooNew, match="Update SlideMage to see plugins."):
        parse(data)


def test_missing_schema_is_an_error_not_too_new():
    data = _json("index-test.json")
    del data["schema"]
    with pytest.raises(CatalogueError) as info:
        parse(data)
    assert not isinstance(info.value, CatalogueTooNew)


def test_broken_plugin_entry_is_skipped():
    data = _json("index-multi.json")
    broken = copy.deepcopy(data["plugins"][1])
    broken["id"] = "broken-one"
    broken["releases"][0]["sha256"] = "ABC"  # not 64 lowercase hex
    data["plugins"].append(broken)
    cat = parse(data)
    assert [p.id for p in cat.plugins] == ["multi-release", "extra-tools"]


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p.update(homepage="http://slidemage.org/plugins/hello/"),
        lambda p: p["releases"][0].update(url="http://github.com/x/y/releases/download/v1/a.smplugin"),
        lambda p: p["releases"][0].update(notes_url="http://example.org/notes"),
        lambda p: p.update(icon="http://slidemage.org/icon.svg"),
        lambda p: p["releases"][0].update(size=0),
        lambda p: p["releases"][0].update(api_version=True),
        lambda p: p["releases"][0].update(requires_slidemage="9.0"),
        lambda p: p["releases"][0].update(version="0.1"),
        lambda p: p.update(releases=[]),
        lambda p: p.update(recommended="yes"),
        lambda p: p.update(id="Hello"),
    ],
)
def test_entry_failing_one_check_is_skipped(change):
    data = _json("index-test.json")
    good = copy.deepcopy(data["plugins"][0])
    good["id"] = "other-one"
    data["plugins"].append(good)
    change(data["plugins"][0])
    cat = parse(data)
    assert [p.id for p in cat.plugins] == ["other-one"]


def test_non_https_plugins_page_refused():
    data = _json("index-test.json")
    data["plugins_page"] = "http://slidemage.org/plugins/"
    with pytest.raises(CatalogueError):
        parse(data)


def test_top_level_not_an_object_refused():
    with pytest.raises(CatalogueError):
        parse([])  # type: ignore[arg-type]


@pytest.mark.parametrize("name", ["index-test.json", "index-multi.json"])
def test_fixtures_validate_against_schema(name):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    jsonschema.validate(_json(name), schema, format_checker=jsonschema.FormatChecker())


# --- URL and fetch ----------------------------------------------------------------------------------------


def test_catalogue_url_default_and_override(monkeypatch):
    assert catalogue.catalogue_url() == CATALOGUE_URL == "https://slidemage.org/plugins/index.json"
    monkeypatch.setenv(CATALOGUE_ENV, "  http://127.0.0.1:9/index.json ")
    assert catalogue.catalogue_url() == "http://127.0.0.1:9/index.json"


def test_fetch_uses_override_and_writes_cache(server, monkeypatch):
    state, url = server
    state["body"] = _raw("index-test.json")
    monkeypatch.setenv(CATALOGUE_ENV, url)
    cat = catalogue.fetch(timeout=5)
    assert [p.id for p in cat.plugins] == ["hello"]
    assert _cache_path().read_bytes() == state["body"]
    assert catalogue.cached() == cat
    assert not list(_cache_path().parent.glob(".catalogue.json.*"))  # no temporary file left behind


def test_cached_none_without_cache():
    assert catalogue.cached() is None


def test_cached_none_for_unreadable_cache():
    _cache_path().parent.mkdir(parents=True)
    _cache_path().write_text("{not json", encoding="utf-8")
    assert catalogue.cached() is None


def test_network_failure_raises_and_keeps_cache(server, monkeypatch):
    state, url = server
    state["body"] = _raw("index-test.json")
    monkeypatch.setenv(CATALOGUE_ENV, url)
    catalogue.fetch(timeout=5)
    before = _cache_path().read_bytes()

    monkeypatch.setenv(CATALOGUE_ENV, "http://127.0.0.1:1/index.json")  # nothing listens here
    with pytest.raises(CatalogueError):
        catalogue.fetch(timeout=2)
    assert _cache_path().read_bytes() == before
    assert catalogue.cached() is not None


def test_http_error_raises_and_writes_no_cache(server, monkeypatch):
    state, url = server
    state["status"] = 500
    state["body"] = b"oops"
    monkeypatch.setenv(CATALOGUE_ENV, url)
    with pytest.raises(CatalogueError):
        catalogue.fetch(timeout=5)
    assert not _cache_path().exists()


def test_bad_json_raises_and_writes_no_cache(server, monkeypatch):
    state, url = server
    state["body"] = b"<html>not json</html>"
    monkeypatch.setenv(CATALOGUE_ENV, url)
    with pytest.raises(CatalogueError):
        catalogue.fetch(timeout=5)
    assert not _cache_path().exists()


def test_too_new_propagates_and_is_not_cached(server, monkeypatch):
    state, url = server
    data = _json("index-test.json")
    data["schema"] = 2
    state["body"] = json.dumps(data).encode("utf-8")
    monkeypatch.setenv(CATALOGUE_ENV, url)
    with pytest.raises(CatalogueTooNew):
        catalogue.fetch(timeout=5)
    assert not _cache_path().exists()


def test_too_new_keeps_older_cache(server, monkeypatch):
    state, url = server
    state["body"] = _raw("index-test.json")
    monkeypatch.setenv(CATALOGUE_ENV, url)
    catalogue.fetch(timeout=5)
    before = _cache_path().read_bytes()
    data = _json("index-test.json")
    data["schema"] = 2
    state["body"] = json.dumps(data).encode("utf-8")
    with pytest.raises(CatalogueTooNew):
        catalogue.fetch(timeout=5)
    assert _cache_path().read_bytes() == before


@pytest.mark.parametrize("plugin_id", ["settings", "secrets", "pending", "staging", "old", "state", "catalogue"])
def test_host_storage_ids_are_left_out(plugin_id):
    data = _json("index-test.json")
    data["plugins"][0]["id"] = plugin_id
    assert parse(data).plugins == []


def test_legacy_cache_is_migrated_once():
    base = loader.plugins_dir()
    base.mkdir(parents=True)
    (base / "catalogue.json").write_bytes(_raw("index-test.json"))
    assert catalogue.cached().plugins[0].id == "hello"
    assert (base / catalogue.CACHE_NAME).is_file()
    assert not (base / "catalogue.json").exists()
