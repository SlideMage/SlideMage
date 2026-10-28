# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which installed plugins have a newer release, and when the app last asked. No Qt.

The check runs with the app's own startup update check and follows its mode (off / ask / auto); this module is the
pure part: the comparison, the withdrawn test and the once-a-day timestamp in plugins/.last_update_check.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Iterable

from ..version import VERSION_NUMBER
from .catalogue import Catalogue, CataloguePlugin, Release, best_release
from .loader import LoadedPlugin, plugins_dir
from .manifest import parse_version
from .storage import private_file

log = logging.getLogger(__name__)

CHECK_FILE = ".last_update_check"
CHECK_INTERVAL_S = 24 * 3600


def _version(text: str) -> tuple[int, int, int] | None:
    try:
        return parse_version(text)
    except ValueError:
        return None


def installed_plugins(loaded: Iterable[LoadedPlugin]) -> list[LoadedPlugin]:
    """The plugins installed through SlideMage with a readable manifest; a development copy is the developer's."""
    return [p for p in loaded if p.source == "installed" and p.manifest is not None]


def available_updates(loaded: Iterable[LoadedPlugin], catalogue: Catalogue,
                      app_version: str = VERSION_NUMBER) -> list[tuple[str, str, Release]]:
    """(id, installed version, release) for each installed plugin whose newest release this SlideMage can run is
    newer than the installed one."""
    entries = {entry.id: entry for entry in catalogue.plugins}
    found: list[tuple[str, str, Release]] = []
    for plugin in installed_plugins(loaded):
        entry = entries.get(plugin.id)
        release = best_release(entry, app_version) if entry else None
        have, offered = _version(plugin.manifest.version), _version(release.version) if release else None
        if release is not None and have is not None and offered is not None and offered > have:
            found.append((plugin.id, plugin.manifest.version, release))
    return found


def is_withdrawn(plugin: LoadedPlugin, entry: CataloguePlugin | None) -> bool:
    """The catalogue knows the plugin but no longer lists the installed version (it was pulled, say for a flaw)."""
    if entry is None or plugin.source != "installed" or plugin.manifest is None:
        return False
    have = _version(plugin.manifest.version)
    return all(_version(release.version) != have for release in entry.releases)


# -- once a day ------------------------------------------------------------------------------------

def check_due(now: float | None = None) -> bool:
    """Whether a day has passed since the last successful check (or there was none, or its stamp is unreadable
    or lies in the future)."""
    now = time.time() if now is None else now
    try:
        stamp = float(private_file(plugins_dir(), CHECK_FILE.removeprefix(".")).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return True
    return stamp > now or now - stamp >= CHECK_INTERVAL_S


def mark_checked(now: float | None = None) -> None:
    try:
        folder = plugins_dir()
        folder.mkdir(parents=True, exist_ok=True)
        private_file(folder, CHECK_FILE.removeprefix(".")).write_text(
            f"{int(time.time() if now is None else now)}\n", encoding="utf-8")
    except OSError:
        log.exception("could not write %s", CHECK_FILE)
