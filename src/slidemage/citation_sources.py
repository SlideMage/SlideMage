# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Citation format GitHub sources. Public compatibility API for package_sources.py's shared release mechanism."""
from __future__ import annotations

import logging
from functools import partial

from . import citations, package_sources
from . import theme_sources as theme_sources
from .package_sources import (
    API as API, Fetched as Fetched, MAX_SHA_BYTES as MAX_SHA_BYTES, NotEligible as NotEligible, Offer as Offer,
    Path as Path, REPOSITORY_RE as REPOSITORY_RE, SOURCE_FILE as SOURCE_FILE, Source as Source,
    SourceError as SourceError, TOKEN_PERMISSION as TOKEN_PERMISSION, ThemeRelease as ThemeRelease,
    VERSION_NUMBER as VERSION_NUMBER, _download as _download, _explain as _explain, _get_json as _get_json,
    _now as _now, asdict as asdict, fields as fields, installer as installer, json as json,
    parse_repository as parse_repository, parse_version as parse_version, re as re, shutil as shutil,
    tempfile as tempfile, urllib as urllib)

log = logging.getLogger(__name__)
ASSET_RE = package_sources.asset_pattern(citations.KIND)

__all__ = ["SourceError", "NotEligible", "Offer", "Fetched", "Source", "parse_repository"]

source_path = partial(package_sources.source_path, citations.KIND)
read_source = partial(package_sources.read_source, citations.KIND)
write_source = partial(package_sources.write_source, citations.KIND)
record_check = partial(package_sources.record_check, citations.KIND)
skip_version = partial(package_sources.skip_version, citations.KIND)
github_citations = partial(package_sources.github_packages, citations.KIND)
_candidate = partial(package_sources._candidate, citations.KIND)
list_releases = partial(package_sources.list_releases, citations.KIND)
fetch = partial(package_sources.fetch, citations.KIND)
newest_eligible = partial(package_sources.newest_eligible, citations.KIND)
install = partial(package_sources.install, citations.KIND)
check_updates = partial(package_sources.check_updates, citations.KIND)
