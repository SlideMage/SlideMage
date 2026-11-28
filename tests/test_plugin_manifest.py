# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""plugin.toml rules and version comparison."""
from __future__ import annotations

import pytest

from slidemage.plugins.manifest import RESERVED_IDS, ManifestError, matches, parse_version, read_manifest

GOOD = {
    "id": '"my-plugin"', "name": '"My plugin"', "version": '"1.2.3"', "api_version": "1",
    "requires_slidemage": '">=9.0, <10"', "summary": '"Does things."', "author": '"Me"',
    "homepage": '"https://example.org"', "license": '"MIT"', "needs": '["a"]', "network": "[]",
}


def write(tmp_path, **changes):
    fields = {**GOOD, **changes}
    (tmp_path / "plugin.toml").write_text(
        "".join(f"{k} = {v}\n" for k, v in fields.items() if v is not None), encoding="utf-8")
    return tmp_path


def test_good_manifest(tmp_path):
    m = read_manifest(write(tmp_path))
    assert (m.id, m.api_version, m.needs, m.network) == ("my-plugin", 1, ("a",), ())
    optional = read_manifest(write(tmp_path, needs=None, network=None))
    assert optional.needs == () and optional.network == ()


@pytest.mark.parametrize("changes, word", [
    ({"id": '"1ab"'}, "id"), ({"id": '"a' + "b" * 32 + '"'}, "id"),
    ({"id": None}, "id"),
    ({"name": '""'}, "name"), ({"name": '"' + "x" * 41 + '"'}, "name"),
    ({"version": '"1.2"'}, "version"),
    ({"api_version": "0"}, "api_version"), ({"api_version": "true"}, "api_version"),
    ({"api_version": None}, "api_version"),
    ({"requires_slidemage": '"9.0"'}, "requires_slidemage"),
    ({"requires_slidemage": '">=9.0 <10"'}, "requires_slidemage"),
    ({"summary": '""'}, "summary"), ({"summary": '"' + "x" * 121 + '"'}, "summary"),
    ({"author": '""'}, "author"), ({"license": '"  "'}, "license"),
    ({"homepage": '"ftp://example.org"'}, "homepage"), ({"homepage": '"example.org"'}, "homepage"),
    ({"needs": '"text"'}, "needs"), ({"needs": '[1]'}, "needs"), ({"network": '[""]'}, "network"),
    ({"network": '["' + "x" * 121 + '"]'}, "network"),
])
def test_rules(tmp_path, changes, word):
    with pytest.raises(ManifestError, match=word):
        read_manifest(write(tmp_path, **changes))


def test_missing_and_broken_file(tmp_path):
    with pytest.raises(ManifestError, match="plugin.toml"):
        read_manifest(tmp_path)
    (tmp_path / "plugin.toml").write_text("id = = 1", encoding="utf-8")
    with pytest.raises(ManifestError, match="TOML"):
        read_manifest(tmp_path)


@pytest.mark.parametrize("text, expected", [
    ("v8.64.0", (8, 64, 0)), ("8.64", (8, 64, 0)), ("9", (9, 0, 0)),
])
def test_parse_version(text, expected):
    assert parse_version(text) == expected


def test_parse_version_rejects():
    with pytest.raises(ValueError):
        parse_version("eight")


@pytest.mark.parametrize("requirement, version, expected", [
    (">=9.0, <10", "v9.3.1", True), (">=9.0, <10", "v10.0.0", False), (">=9.0, <10", "v8.64.0", False),
    (">9.0", "9.0.0", False), ("<=9", "9.0.0", True), ("==9.3", "9.3.0", True),
    ("==9.3", "9.3.1", False), (">= 8.0 , < 9", "v8.64.0", True),
])
def test_matches(requirement, version, expected):
    assert matches(requirement, version) is expected


def test_matches_rejects_malformed():
    with pytest.raises(ValueError):
        matches("newer", "9.0")


@pytest.mark.parametrize("plugin_id", sorted(RESERVED_IDS))
def test_host_storage_ids_are_refused(tmp_path, plugin_id):
    with pytest.raises(ManifestError, match="id"):
        read_manifest(write(tmp_path, id=f'"{plugin_id}"'))
