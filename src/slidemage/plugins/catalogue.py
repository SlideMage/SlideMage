# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The plugin catalogue: the list of plugins SlideMage offers, fetched from the plugin website, checked and cached.

The catalogue is the only source of plugins for the app. It is never GitHub's "latest release" of a plugin: the
website lists the releases, and each release carries its URL and sha256, which the installer checks. The URL is
fixed in the app (CATALOGUE_URL); the environment variable SLIDEMAGE_PLUGIN_CATALOGUE exists for development and
tests only.

The format is schema 1 of the website (PLUGINS_PLAN 2.9 and website section 5). Fields the app does not know are
ignored, so the website can add fields without an update; a newer schema number raises CatalogueTooNew, because
an older app cannot tell what the new fields mean. A plugin entry that breaks one of the checks is left out of the
list, the rest of the catalogue still works. The last good copy is kept in plugins_dir()/.catalogue.json, so the
Extensions tab can show something offline.

No Qt here: plain functions, so the Extensions tab can run fetch() on a worker thread.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.client import HTTPException

from ..fileio import atomic_write
from ..plugin_api import SUPPORTED_API_VERSIONS
from ..version import VERSION_NUMBER
from .loader import plugins_dir
from .manifest import REQUIRES_RE, VERSION_RE, matches, valid_id
from .storage import private_file

CATALOGUE_URL = "https://slidemage.org/plugins/index.json"
CATALOGUE_ENV = "SLIDEMAGE_PLUGIN_CATALOGUE"
CACHE_NAME = ".catalogue.json"
SCHEMA = 1
MAX_BYTES = 2 * 1024 * 1024
USER_AGENT = "SlideMage-updater"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HTTPS_RE = re.compile(r"^https://\S+$")


class CatalogueError(Exception):
    """The catalogue could not be fetched or read; the message is a sentence the Extensions tab can show."""


class CatalogueTooNew(CatalogueError):
    """The catalogue is a schema this version of SlideMage does not read."""

    def __init__(self) -> None:
        super().__init__("Update SlideMage to see plugins.")


@dataclass(frozen=True)
class Release:
    version: str
    api_version: int
    requires_slidemage: str
    url: str
    sha256: str
    size: int
    published: str
    notes_url: str = ""


@dataclass(frozen=True)
class CataloguePlugin:
    id: str
    name: str
    summary: str
    homepage: str
    source: str
    icon: str | None
    license: str
    maintainer: str
    recommended: bool
    needs: tuple[str, ...]
    network: tuple[str, ...]
    releases: tuple[Release, ...]


@dataclass(frozen=True)
class Catalogue:
    generated: str
    plugins_page: str
    plugins: list[CataloguePlugin]


class _Bad(Exception):
    """One plugin entry breaks a rule; the entry is skipped."""


def catalogue_url() -> str:
    return os.environ.get(CATALOGUE_ENV, "").strip() or CATALOGUE_URL


def _text(data: dict, key: str, low: int = 1, high: int | None = None) -> str:
    value = data.get(key)
    if not isinstance(value, str) or len(value.strip()) < low or (high and len(value) > high):
        raise _Bad(key)
    return value


def _https(data: dict, key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not _HTTPS_RE.match(value):
        raise _Bad(key)
    return value


def _lines(data: dict, key: str) -> tuple[str, ...]:
    value = data.get(key)
    if not isinstance(value, list) or not all(isinstance(v, str) and 1 <= len(v) <= 120 for v in value):
        raise _Bad(key)
    return tuple(value)


def _whole(data: dict, key: str, low: int) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < low:
        raise _Bad(key)
    return value


def _release(data: dict) -> Release:
    version = data.get("version")
    if not isinstance(version, str) or not VERSION_RE.match(version):
        raise _Bad("version")
    requires = _text(data, "requires_slidemage")
    if not REQUIRES_RE.match(requires):
        raise _Bad("requires_slidemage")
    sha = data.get("sha256")
    if not isinstance(sha, str) or not _SHA256_RE.match(sha):
        raise _Bad("sha256")
    published = _text(data, "published")
    if not _DATE_RE.match(published):
        raise _Bad("published")
    notes_url = _https(data, "notes_url") if "notes_url" in data else ""
    return Release(
        version=version,
        api_version=_whole(data, "api_version", 1),
        requires_slidemage=requires,
        url=_https(data, "url"),
        sha256=sha,
        size=_whole(data, "size", 1),
        published=published,
        notes_url=notes_url,
    )


def _plugin(data: dict) -> CataloguePlugin:
    plugin_id = data.get("id")
    if not isinstance(plugin_id, str) or not valid_id(plugin_id):
        raise _Bad("id")
    recommended = data.get("recommended")
    if not isinstance(recommended, bool):
        raise _Bad("recommended")
    releases = data.get("releases")
    if not isinstance(releases, list) or not releases:
        raise _Bad("releases")
    if not all(isinstance(r, dict) for r in releases):
        raise _Bad("releases")
    icon = _https(data, "icon") if data.get("icon") is not None else None
    return CataloguePlugin(
        id=plugin_id,
        name=_text(data, "name", 1, 40),
        summary=_text(data, "summary", 1, 120),
        homepage=_https(data, "homepage"),
        source=_https(data, "source"),
        icon=icon,
        license=_text(data, "license"),
        maintainer=_text(data, "maintainer"),
        recommended=recommended,
        needs=_lines(data, "needs"),
        network=_lines(data, "network"),
        releases=tuple(_release(r) for r in releases),
    )


def parse(data: dict) -> Catalogue:
    """The catalogue in `data` (the decoded JSON), checked. Raises CatalogueTooNew for a schema other than 1,
    CatalogueError when the top level is broken. A plugin entry that fails a check is left out."""
    if not isinstance(data, dict):
        raise CatalogueError("The plugin catalogue is not a JSON object.")
    schema = data.get("schema")
    if isinstance(schema, bool) or not isinstance(schema, int):
        raise CatalogueError("The plugin catalogue has no schema number.")
    if schema != SCHEMA:
        raise CatalogueTooNew()
    try:
        generated = _text(data, "generated")
        plugins_page = _https(data, "plugins_page")
    except _Bad as e:
        raise CatalogueError(f"The plugin catalogue has a bad {e}.") from None
    entries = data.get("plugins")
    if not isinstance(entries, list):
        raise CatalogueError("The plugin catalogue has no plugin list.")
    plugins: list[CataloguePlugin] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            plugins.append(_plugin(entry))
        except _Bad:
            continue
    return Catalogue(generated=generated, plugins_page=plugins_page, plugins=plugins)


def _cache_file():
    return private_file(plugins_dir(), CACHE_NAME.removeprefix("."))


def fetch(timeout: float = 10) -> Catalogue:
    """Download the catalogue, check it and keep the raw JSON as the cache. Raises CatalogueError when the
    network or the JSON fails (the cache is then untouched), CatalogueTooNew for a newer schema (not cached)."""
    request = urllib.request.Request(
        catalogue_url(), headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_BYTES + 1)
    except (urllib.error.URLError, HTTPException, OSError, ValueError) as e:
        raise CatalogueError(f"Could not load the plugin list: {e}") from None
    if len(raw) > MAX_BYTES:
        raise CatalogueError("The plugin list is too large.")
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError:  # includes UnicodeDecodeError
        raise CatalogueError("The plugin list is not valid JSON.") from None
    catalogue = parse(data)
    try:
        atomic_write(_cache_file(), raw)
    except OSError:
        pass  # the cache is a convenience; the list in hand is still good
    return catalogue


def cached() -> Catalogue | None:
    """The last good copy from fetch(), or None when there is none or it no longer reads."""
    try:
        return parse(json.loads(_cache_file().read_text(encoding="utf-8")))
    except (OSError, ValueError, CatalogueError):
        return None


def best_release(
    plugin: CataloguePlugin,
    app_version: str = VERSION_NUMBER,
    api_versions: frozenset[int] | set[int] = SUPPORTED_API_VERSIONS,
) -> Release | None:
    """The newest release of `plugin` that this app can run: its api_version is in `api_versions` and its
    requires_slidemage matches `app_version`. Releases are tried in the order the catalogue gives them (newest
    first). None when no release fits."""
    for release in plugin.releases:
        if release.api_version not in api_versions:
            continue
        try:
            if matches(release.requires_slidemage, app_version):
                return release
        except ValueError:
            continue
    return None
