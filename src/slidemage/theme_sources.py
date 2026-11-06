# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Theme GitHub sources. Public compatibility API for package_sources.py's shared release mechanism."""
from __future__ import annotations

import logging
from functools import partial

from . import themes, package_sources
from .package_sources import (
    API as API, Fetched as Fetched, HTTPException as HTTPException, MAX_SHA_BYTES as MAX_SHA_BYTES,
    NotEligible as NotEligible, Offer as Offer, Path as Path, REPOSITORY_RE as REPOSITORY_RE,
    SOURCE_FILE as SOURCE_FILE, Source as Source, SourceError as SourceError, TOKEN_PERMISSION as TOKEN_PERMISSION,
    ThemeRelease as ThemeRelease, VERSION_NUMBER as VERSION_NUMBER, _download as _download, _explain as _explain,
    _get_json as _get_json, _now as _now, asdict as asdict, dataclass as dataclass, datetime as datetime,
    diagnostics as diagnostics, field as field, fields as fields, installer as installer, json as json,
    parse_repository as parse_repository, parse_version as parse_version, re as re, shutil as shutil,
    tempfile as tempfile, timezone as timezone, updater as updater, urllib as urllib)

log = logging.getLogger(__name__)
ASSET_RE = package_sources.asset_pattern(themes.KIND)

source_path = partial(package_sources.source_path, themes.KIND)
read_source = partial(package_sources.read_source, themes.KIND)
write_source = partial(package_sources.write_source, themes.KIND)
record_check = partial(package_sources.record_check, themes.KIND)
skip_version = partial(package_sources.skip_version, themes.KIND)
github_themes = partial(package_sources.github_packages, themes.KIND)
_candidate = partial(package_sources._candidate, themes.KIND)
list_releases = partial(package_sources.list_releases, themes.KIND)
fetch = partial(package_sources.fetch, themes.KIND)
newest_eligible = partial(package_sources.newest_eligible, themes.KIND)
install = partial(package_sources.install, themes.KIND)
check_updates = partial(package_sources.check_updates, themes.KIND)
