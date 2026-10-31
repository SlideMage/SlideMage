# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""A plugin's plugin.toml: read it, check every field, and compare versions.

The rules are the ones the plugin website's catalogue uses (PLUGINS_PLAN 2.9), so a plugin that passes here
passes there. A bad manifest raises ManifestError with a sentence the Plugins tab can show as it is.
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from ..version import to_zero_x

MANIFEST_NAME = "plugin.toml"

ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
# Host storage names, including legacy names and the ID-shaped forms of metadata files.
RESERVED_IDS = frozenset({
    "settings", "secrets", "pending", "staging", "old", "state", "catalogue",
    "last-update-check", "offer-seen", "migrations-seen", "last_update_check", "offer_seen",
    "migrations_seen.json", "state.json", "catalogue.json",
})
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_COMPARISON = r"(>=|<=|==|<|>)\s*\d+(\.\d+){0,2}"
REQUIRES_RE = re.compile(rf"^{_COMPARISON}(\s*,\s*{_COMPARISON})*$")
_COMPARISON_PARTS_RE = re.compile(r"(>=|<=|==|<|>)\s*(\d+(?:\.\d+){0,2})")


class ManifestError(Exception):
    """plugin.toml is missing, unreadable or breaks a rule; the message says which, for the user."""


@dataclass(frozen=True)
class Manifest:
    id: str
    name: str
    version: str
    api_version: int
    requires_slidemage: str
    summary: str
    author: str
    homepage: str
    license: str
    needs: tuple[str, ...] = field(default_factory=tuple)
    network: tuple[str, ...] = field(default_factory=tuple)


def package_name(plugin_id: str) -> str:
    """The top-level Python package of a plugin: its id with "-" as "_" (a hyphen can't be imported)."""
    return plugin_id.replace("-", "_")


def valid_id(plugin_id: str) -> bool:
    """An ID must fit both the public syntax and the host's on-disk namespace."""
    return ID_RE.fullmatch(plugin_id) is not None and plugin_id not in RESERVED_IDS


def parse_version(text: str) -> tuple[int, int, int]:
    """"v8.64.0", "8.64" or "9" as (8, 64, 0); a missing part is 0. ValueError for anything else."""
    m = re.fullmatch(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", text.strip())
    if not m:
        raise ValueError(f"not a version: {text!r}")
    major, minor, patch = (int(g) if g else 0 for g in m.groups())
    return major, minor, patch


def parse_app_version(text: str) -> tuple[int, ...]:
    """SlideMage's own version ("v0.11.0", or "v0.10.19.0" from the history) as numbers; an old-scheme one
    ("v10.19.0", ">=10.17" in a requirement) reads as 0.<old>. ValueError for anything else."""
    m = re.fullmatch(r"v?(\d+(?:\.\d+){0,3})", text.strip())
    if not m:
        raise ValueError(f"not a version: {text!r}")
    parts = tuple(int(g) for g in m.group(1).split("."))
    parts = to_zero_x(parts + (0,) * (3 - len(parts)))
    return parts + (0,) * (4 - len(parts))


def matches(requirement: str, version: str) -> bool:
    """Whether `version` satisfies every comparison of `requirement` (">=9.0, <10"). ValueError if malformed."""
    if not REQUIRES_RE.match(requirement.strip()):
        raise ValueError(f"not a version requirement: {requirement!r}")
    have = parse_app_version(version)
    for op, number in _COMPARISON_PARTS_RE.findall(requirement):
        want = parse_app_version(number)
        ok = {">=": have >= want, "<=": have <= want, "==": have == want, "<": have < want, ">": have > want}[op]
        if not ok:
            return False
    return True


def _text(data: dict, key: str, low: int, high: int | None = None) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ManifestError(f"{key} is missing or not text")
    value = value.strip()
    if len(value) < low or (high is not None and len(value) > high):
        span = f"{low} to {high}" if high else f"at least {low}"
        raise ManifestError(f"{key} must be {span} characters")
    return value


def _lines(data: dict, key: str) -> tuple[str, ...]:
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) and 1 <= len(v.strip()) <= 120 for v in value):
        raise ManifestError(f"{key} must be a list of lines of 1 to 120 characters")
    return tuple(v.strip() for v in value)


def read_manifest(folder: Path) -> Manifest:
    """The checked plugin.toml in `folder`. Raises ManifestError."""
    path = Path(folder) / MANIFEST_NAME
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ManifestError(f"no {MANIFEST_NAME} in {folder}") from None
    except (OSError, UnicodeDecodeError) as e:
        raise ManifestError(f"{MANIFEST_NAME} cannot be read: {e}") from None
    except tomllib.TOMLDecodeError as e:
        raise ManifestError(f"{MANIFEST_NAME} is not valid TOML: {e}") from None

    plugin_id = _text(data, "id", 1)
    if not ID_RE.match(plugin_id):
        raise ManifestError("id must be 2 to 32 characters: a lowercase letter, then lowercase letters, digits, -")
    if plugin_id in RESERVED_IDS:
        raise ManifestError(f"id {plugin_id!r} is reserved for SlideMage's own storage")
    version = _text(data, "version", 1)
    if not VERSION_RE.match(version):
        raise ManifestError("version must look like 1.2.3")
    api_version = data.get("api_version")
    if isinstance(api_version, bool) or not isinstance(api_version, int) or api_version < 1:
        raise ManifestError("api_version must be a whole number, 1 or more")
    requires = _text(data, "requires_slidemage", 1)
    if not REQUIRES_RE.match(requires):
        raise ManifestError('requires_slidemage must look like ">=0.9" or ">=0.9, <0.12"')
    homepage = _text(data, "homepage", 1)
    if not re.match(r"^https?://\S+$", homepage):
        raise ManifestError("homepage must be an http(s) address")
    return Manifest(
        id=plugin_id,
        name=_text(data, "name", 1, 40),
        version=version,
        api_version=api_version,
        requires_slidemage=requires,
        summary=_text(data, "summary", 1, 120),
        author=_text(data, "author", 1),
        homepage=homepage,
        license=_text(data, "license", 1),
        needs=_lines(data, "needs"),
        network=_lines(data, "network"),
    )
