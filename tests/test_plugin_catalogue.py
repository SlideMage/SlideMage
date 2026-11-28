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


def test_plugin_release_lookup_respects_app_and_api_compatibility():
    cat = parse(_json("index-multi.json"))
    plugin, extra = cat.plugins
    assert (plugin.id, extra.id, extra.recommended) == ("multi-release", "extra-tools", True)
    assert not hasattr(cat, "themes") and not hasattr(plugin, "color")
    for app, apis, version in (
        ("v0.9.0.0", {1}, "1.0.0"),
        ("v0.9.0.0", {1, 2}, "1.5.0"),
        ("v99.0.0", {1}, "2.0.0"),
        ("v0.8.64.0", {1, 2}, None),
    ):
        release = best_release(plugin, app, apis)
        assert (release.version if release else None) == version, (app, apis)
    assert best_release(plugin) == best_release(plugin, VERSION_NUMBER, SUPPORTED_API_VERSIONS)


def test_invalid_plugin_entries_are_skipped_without_hiding_good_entries():
    data = _json("index-test.json")
    hello = data["plugins"][0]
    for i, change in enumerate((
        lambda p: p.update(homepage="http://slidemage.org/plugins/hello/"),
        lambda p: p["releases"][0].update(url="http://github.com/x/y/releases/download/v1/a.smplugin"),
        lambda p: p["releases"][0].update(notes_url="http://example.org/notes"),
        lambda p: p.update(icon="http://slidemage.org/icon.svg"),
        lambda p: p["releases"][0].update(size=0),
        lambda p: p["releases"][0].update(api_version=True),
        lambda p: p["releases"][0].update(requires_slidemage="9.0"),
        lambda p: p["releases"][0].update(version="0.1"),
        lambda p: p["releases"][0].update(sha256="ABC"),
        lambda p: p.update(releases=[]),
        lambda p: p.update(recommended="yes"),
        lambda p: p.update(id="Hello"),
    )):
        broken = {**copy.deepcopy(hello), "id": f"bad-{i}"}
        change(broken)
        data["plugins"].append(broken)
    assert [p.id for p in parse(data).plugins] == ["hello"]


def test_host_storage_ids_are_left_out():
    data = _json("index-test.json")
    hello = data["plugins"][0]
    reserved = ["settings", "secrets", "pending", "staging", "old", "state", "catalogue"]
    data["plugins"].extend({**hello, "id": plugin_id} for plugin_id in reserved)
    assert [p.id for p in parse(data).plugins] == ["hello"]


def test_invalid_catalogue_headers_are_rejected():
    data = _json("index-test.json")
    with pytest.raises(CatalogueError, match="bad plugins_page"):
        parse({**data, "plugins_page": "http://slidemage.org/plugins/"})
    with pytest.raises(CatalogueError, match="not a JSON object"):
        parse([])  # type: ignore[arg-type]
    del data["schema"]
    with pytest.raises(CatalogueError, match="no schema number") as error:
        parse(data)
    assert not isinstance(error.value, CatalogueTooNew)


@pytest.mark.parametrize("name", ["index-test.json", "index-multi.json"])
def test_fixtures_validate_against_schema(name):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    jsonschema.validate(_json(name), schema, format_checker=jsonschema.FormatChecker())


def test_fetch_rejects_invalid_responses_without_writing_cache(server, monkeypatch):
    state, url = server
    monkeypatch.setenv(CATALOGUE_ENV, url)
    path = _cache_path()

    state.update(status=500, body=b"oops")
    with pytest.raises(CatalogueError, match="Could not load the plugin list"):
        catalogue.fetch(timeout=5)
    assert not path.exists()

    state.update(status=200, body=b"<html>not json</html>")
    with pytest.raises(CatalogueError, match="not valid JSON"):
        catalogue.fetch(timeout=5)
    assert not path.exists()

    state["body"] = json.dumps({**_json("index-test.json"), "schema": 2}).encode()
    with pytest.raises(CatalogueTooNew):
        catalogue.fetch(timeout=5)
    assert not path.exists()


def test_fetch_uses_override_and_preserves_cache_on_errors(server, monkeypatch):
    state, url = server
    assert catalogue.catalogue_url() == CATALOGUE_URL == "https://slidemage.org/plugins/index.json"
    monkeypatch.setenv(CATALOGUE_ENV, f"  {url} ")
    assert catalogue.catalogue_url() == url
    path = _cache_path()
    assert catalogue.cached() is None

    raw = state["body"] = _raw("index-test.json")
    cat = catalogue.fetch(timeout=5)
    (hello,) = cat.plugins
    release = best_release(hello)
    assert hello.id == "hello" and cat.citations == []
    assert (release.version, release.size, release.sha256) == ("0.1.0", 12357, HELLO_SHA)
    assert path.read_bytes() == raw and catalogue.cached() == cat
    assert not list(path.parent.glob(f".{path.name}.*.tmp"))

    state["body"] = json.dumps({**_json("index-test.json"), "schema": 2}).encode()
    with pytest.raises(CatalogueTooNew, match="Update SlideMage to see plugins"):
        catalogue.fetch(timeout=5)
    assert path.read_bytes() == raw

    monkeypatch.setenv(CATALOGUE_ENV, "http://127.0.0.1:1/index.json")
    with pytest.raises(CatalogueError, match="Could not load the plugin list"):
        catalogue.fetch(timeout=2)
    assert path.read_bytes() == raw and catalogue.cached() == cat

    path.write_bytes(b"{not json")
    assert catalogue.cached() is None


def _citation_entry(**changes) -> dict:
    entry = {"id": "apa", "name": "APA 7", "summary": "A format.", "homepage": "https://slidemage.org/citations/apa/",
             "source": "https://github.com/SlideMage/slidemage-citation-apa", "license": "LPPL-1.3c-or-later",
             "maintainer": "Stefan Palan", "recommended": False,
             "preview": "https://slidemage.org/citations/apa/preview.png",
             "releases": [{"version": "1.0.0", "requires_slidemage": ">=0.13.0", "sha256": "a" * 64,
                           "url": "https://github.com/SlideMage/slidemage-citation-apa/releases/download/v1.0.0/"
                                  "apa-1.0.0.smcite", "size": 70195, "published": "2026-11-06"}]}
    entry.update(changes)
    return entry


def test_citation_formats_are_read_and_incompatible_releases_are_skipped():
    data = _json("index-test.json")
    entry = _citation_entry()
    (older,) = entry["releases"]
    newer = {**older, "version": "2.0.0", "requires_slidemage": ">=99.0.0"}
    entry["releases"] = [newer, older]
    data["citations"] = [entry, _citation_entry(id="Bad"), _citation_entry(id="empty", releases=[]),
                         _citation_entry(id="chicago", preview=None, name="Chicago"), "nope",
                         _citation_entry(id="http", homepage="http://x")]
    found = parse(data).citations
    assert [c.id for c in found] == ["apa", "chicago"]
    apa, chicago = found
    assert apa.name == "APA 7" and apa.preview.endswith("preview.png") and chicago.preview is None
    release = catalogue.best_citation_release(apa, "v0.14.20")
    assert (release.version, release.size, release.sha256) == ("1.0.0", 70195, "a" * 64)
    assert not hasattr(release, "api_version")
    assert catalogue.best_citation_release(apa, "v100.0.0").version == "2.0.0"
    assert catalogue.best_citation_release(apa, "v0.12.0") is None
    data["citations"] = "not a list"
    assert parse(data).citations == []
