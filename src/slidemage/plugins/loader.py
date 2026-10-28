# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Find the plugins on this computer, check them, import them and call their activate().

A plugin is a folder with a plugin.toml and a package named after its id (hyphens as underscores). It comes from
config_dir()/plugins/<id>/ (installed) or from a folder on SLIDEMAGE_PLUGIN_PATH (a development checkout, which
wins over an installed plugin with the same id). The package is imported under its own top-level name straight
from its folder, not through sys.path, so a plugin can never shadow the standard library, SlideMage or another
plugin: such a name refuses that plugin instead.

A plugin that fails anywhere (manifest, import, activate) is reported with its reason or traceback and left out
for this session; the app starts regardless.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .. import project
from ..plugin_api import SUPPORTED_API_VERSIONS
from ..version import VERSION_NUMBER
from .manifest import MANIFEST_NAME, Manifest, ManifestError, matches, package_name, read_manifest
from .registry import Contributions, Registrar

PATH_ENV = "SLIDEMAGE_PLUGIN_PATH"

State = Literal["loaded", "disabled", "failed", "incompatible"]


@dataclass(frozen=True)
class Found:
    """A plugin folder discovered on disk. manifest is None when plugin.toml is bad (error says why)."""

    folder: Path
    source: Literal["installed", "dev"]
    manifest: Manifest | None
    error: str = ""
    note: str = ""      # e.g. that this folder replaces an installed copy

    @property
    def id(self) -> str:
        return self.manifest.id if self.manifest else self.folder.name


@dataclass
class LoadedPlugin:
    folder: Path
    source: Literal["installed", "dev"]
    id: str
    manifest: Manifest | None
    state: State
    reason: str = ""            # why it is not loaded, or the traceback of a failure
    note: str = ""
    contributions: Contributions = field(default_factory=Contributions)


def plugins_dir() -> Path:
    return project.config_dir() / "plugins"


def _state_file() -> Path:
    return plugins_dir() / "state.json"


def _disabled_ids() -> set[str]:
    try:
        data = json.loads(_state_file().read_text(encoding="utf-8"))
        return {i for i in data.get("disabled", []) if isinstance(i, str)}
    except (OSError, ValueError, AttributeError):
        return set()


def is_enabled(plugin_id: str) -> bool:
    return plugin_id not in _disabled_ids()


def set_enabled(plugin_id: str, enabled: bool) -> None:
    """Remember the choice (takes effect at the next start). Written atomically: a crash keeps the old file."""
    disabled = _disabled_ids()
    disabled.discard(plugin_id) if enabled else disabled.add(plugin_id)
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"disabled": sorted(disabled)}, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _inspect(folder: Path, source: Literal["installed", "dev"]) -> Found:
    try:
        return Found(folder, source, read_manifest(folder))
    except ManifestError as e:
        return Found(folder, source, None, error=str(e))


def discover(installed_dir: Path | None = None, extra: list[Path] | None = None) -> list[Found]:
    """The plugin folders: installed ones, then SLIDEMAGE_PLUGIN_PATH (or `extra`) ones, sorted by id."""
    installed_dir = plugins_dir() if installed_dir is None else installed_dir
    if extra is None:
        extra = [Path(p) for p in os.environ.get(PATH_ENV, "").split(os.pathsep) if p]
    found: dict[str, Found] = {}
    if installed_dir.is_dir():
        for folder in sorted(installed_dir.iterdir()):
            if folder.name.startswith(".") or not (folder / MANIFEST_NAME).is_file():
                continue
            item = _inspect(folder, "installed")
            found[item.id] = item
    for folder in extra:
        if not (folder / MANIFEST_NAME).is_file():
            continue
        item = _inspect(folder, "dev")
        old = found.get(item.id)
        if old is not None and old.source == "installed":
            item = Found(item.folder, "dev", item.manifest, item.error,
                         note=f"replaces the installed copy in {old.folder}")
        found[item.id] = item
    return sorted(found.values(), key=lambda f: f.id)


def _inside(path: str | os.PathLike, folder: Path) -> bool:
    try:
        Path(path).resolve().relative_to(folder.resolve())
        return True
    except ValueError:
        return False


def _name_taken(name: str, folder: Path) -> bool:
    if name in sys.modules:
        return True
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError):
        return False
    if spec is None:
        return False
    locations = list(spec.submodule_search_locations or [])
    if spec.origin:
        locations.append(spec.origin)
    return not (locations and all(_inside(p, folder) for p in locations))


def _discard_module(name: str) -> None:
    for key in [k for k in sys.modules if k == name or k.startswith(name + ".")]:
        del sys.modules[key]


def _load_one(found: Found, make_host: Callable[[Manifest], Registrar], app_version: str) -> LoadedPlugin:
    plugin = LoadedPlugin(found.folder, found.source, found.id, found.manifest, "failed", note=found.note)
    manifest = found.manifest
    if manifest is None:
        plugin.reason = found.error
        return plugin
    if not is_enabled(manifest.id):
        plugin.state = "disabled"
        return plugin
    if manifest.api_version not in SUPPORTED_API_VERSIONS:
        plugin.state = "incompatible"
        plugin.reason = f"written for plugin API {manifest.api_version}"
        return plugin
    if not matches(manifest.requires_slidemage, app_version):
        plugin.state = "incompatible"
        plugin.reason = f"needs SlideMage {manifest.requires_slidemage}"
        return plugin

    name = package_name(manifest.id)
    init = found.folder / name / "__init__.py"
    if not init.is_file():
        plugin.reason = f"the package folder {name}/ with an __init__.py is missing"
        return plugin
    if _name_taken(name, found.folder):
        plugin.reason = f"the name {name} is taken by another module; a plugin cannot use it"
        return plugin

    try:
        spec = importlib.util.spec_from_file_location(
            name, init, submodule_search_locations=[str(found.folder / name)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        host = make_host(manifest)
        with host.activation():
            module.activate(host)
        from ..ai import routes
        registered = {route.id for route in routes.all()}
        for route in host.contributions.ai_routes:
            if route.id in registered:
                raise ValueError(f"AI route {route.id!r} is already registered")
            registered.add(route.id)
        for route in host.contributions.ai_routes:
            routes.register(route)
    except BaseException:       # a plugin's SystemExit must not end the app either
        _discard_module(name)
        plugin.reason = traceback.format_exc()
        return plugin
    plugin.state = "loaded"
    plugin.contributions = host.contributions
    return plugin


def load_all(make_host: Callable[[Manifest], Registrar], app_version: str = VERSION_NUMBER) -> list[LoadedPlugin]:
    """Load every discovered plugin; make_host(manifest) builds the host that plugin's activate() gets."""
    return [_load_one(f, make_host, app_version) for f in discover()]
