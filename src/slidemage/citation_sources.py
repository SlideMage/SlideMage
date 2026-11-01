# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Citation formats installed from a (private) GitHub repository, and their updates (docs/CITATION_PACKAGE.md,
"From GitHub"): theme_sources.py's mechanism for the third category.

The GitHub plumbing (release list, downloads, error sentences, token, source.json's shape, Offer, Fetched) is
theme_sources'; what differs is the asset (<key>-<version>.smcite), the manifest (citation.toml), the folder
(config_dir()/citations/<key>/) and the install. The release rules are the themes': a published release that carries
<key>-<version>.smcite and its .sha256 with <version> its tag without the "v", a download that matches the hash, a
citation.toml with that version (and, for an update, the installed key) that this SlideMage accepts; the newest
eligible one wins, one that fails a check is passed over for the next older one. A format installed from a file has
no source.json and is never updated.

No Qt, standard library only; blocking: call the network functions from a worker thread.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import tempfile
from dataclasses import asdict, fields
from pathlib import Path

from . import citations, theme_sources
from .plugins import installer
from .plugins.manifest import parse_version
from .theme_sources import (Fetched, NotEligible, Offer, Source, SourceError, ThemeRelease, parse_repository)
from .version import VERSION_NUMBER

log = logging.getLogger(__name__)

ASSET_RE = re.compile(r"^(?P<key>[a-z][a-z0-9-]{1,31})-(?P<version>\d+\.\d+\.\d+)\.smcite$")
SOURCE_FILE = theme_sources.SOURCE_FILE

__all__ = ["SourceError", "NotEligible", "Offer", "Fetched", "Source", "parse_repository"]


# -- source.json

def source_path(key: str) -> Path:
    return citations.citations_dir() / key / SOURCE_FILE


def read_source(key: str) -> Source | None:
    """Where the installed citation format `key` came from, or None (installed from a file, or unreadable)."""
    try:
        data = json.loads(source_path(key).read_text(encoding="utf-8"))
        known = {f.name for f in fields(Source)}
        source = Source(**{k: v for k, v in data.items() if k in known})
        parse_repository(source.repository)
        return source
    except (OSError, ValueError, TypeError, SourceError):
        return None


def write_source(key: str, source: Source) -> None:
    source_path(key).write_text(json.dumps(asdict(source), indent=2) + "\n", encoding="utf-8")


def record_check(key: str, error: str = "") -> None:
    """Note the update check's time and, if it failed, why (Settings shows it). Never raises."""
    source = read_source(key)
    if source is None:
        return
    source.checked_at, source.check_error = theme_sources._now(), error
    try:
        write_source(key, source)
    except OSError:
        log.exception("could not write %s", source_path(key))


def skip_version(key: str, version: str) -> None:
    """"Skip this version": not offered again; a later one is."""
    source = read_source(key)
    if source is not None:
        source.skipped_version = version
        write_source(key, source)


def github_citations() -> list[tuple[citations.InstalledCitation, Source]]:
    """The installed, usable citation formats that came from a GitHub repository."""
    found = []
    for item in citations.installed():
        source = read_source(item.key) if item.manifest is not None and not item.problem else None
        if source is not None:
            found.append((item, source))
    return found


# -- GitHub

def list_releases(repo: str, key: str | None = None, timeout: float = 10) -> list[ThemeRelease]:
    return theme_sources.list_releases(repo, key, timeout=timeout, asset_re=ASSET_RE)


def fetch(release: ThemeRelease, app_version: str = VERSION_NUMBER, timeout: float = 30) -> Fetched:
    """Download `release` and run the eligibility checks that need its files. Raises NotEligible or SourceError."""
    folder = Path(tempfile.mkdtemp(prefix="slidemage-citation-"))
    try:
        sha_file = folder / (release.asset_name + ".sha256")
        theme_sources._download(release.sha_url, sha_file, release.repository, theme_sources.MAX_SHA_BYTES, timeout)
        expected = installer.read_sha256_file(sha_file)
        if expected is None:
            raise NotEligible(f"{sha_file.name} holds no SHA-256 checksum")
        archive = folder / release.asset_name
        theme_sources._download(release.asset_url, archive, release.repository, installer.MAX_DOWNLOAD_BYTES, timeout)
        if installer.sha256_of(archive) != expected:
            raise NotEligible(f"{release.asset_name} does not match its .sha256")
        try:
            manifest = citations.peek(archive)
            if manifest.version != release.version:
                raise NotEligible(f"its citation.toml says version {manifest.version}, the tag {release.tag}")
            if manifest.id != release.key:
                raise NotEligible(f"its citation.toml names the key {manifest.id!r}, the file {release.key!r}")
            citations.check_manifest(manifest, app_version)
        except citations.CitationError as e:
            raise NotEligible(str(e)) from None
        return Fetched(release, archive, expected, manifest)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise


def newest_eligible(repo: str, *, key: str | None = None, newer_than: str | None = None,
                    app_version: str = VERSION_NUMBER, timeout: float = 30) -> tuple[Fetched | None, list[str]]:
    """The newest eligible release (downloaded and checked), newer than `newer_than` if given, and why the newer ones
    were passed over ("v1.2.0: ..."). Raises SourceError when the repository cannot be read."""
    floor = parse_version(newer_than) if newer_than else None
    passed: list[str] = []
    for release in list_releases(repo, key, timeout=min(timeout, 10)):
        if floor is not None and release.number <= floor:
            break
        try:
            return fetch(release, app_version, timeout), passed
        except NotEligible as e:
            passed.append(f"{release.tag}: {e}")
    return None, passed


def install(fetched: Fetched) -> citations.CitationManifest:
    """Install a fetched release and record where it came from; the download is deleted. Raises CitationError."""
    try:
        manifest = citations.install_file(fetched.archive, expected_sha256=fetched.sha256)
        release = fetched.release
        try:
            write_source(manifest.id, Source(release.repository, manifest.version, release.release_id,
                                             theme_sources._now()))
        except OSError as e:
            raise citations.CitationError(f"The citation format is installed, but where it came from could not be "
                                          f"saved, so it will not be updated: {e}") from None
        return manifest
    finally:
        fetched.discard()


def check_updates(app_version: str = VERSION_NUMBER) -> tuple[list[Offer], dict[str, str]]:
    """Look for a newer eligible release of each GitHub citation format (a worker thread's job). The offers
    (downloaded, checked, not installed; a skipped version is not offered) and, per key, why a check failed. Each
    check's outcome is recorded in the format's source.json."""
    offers: list[Offer] = []
    errors: dict[str, str] = {}
    for item, source in github_citations():
        have = item.manifest.version
        try:
            fetched, passed = newest_eligible(source.repository, key=item.key, newer_than=have,
                                              app_version=app_version)
        except Exception as e:          # one format failing must not stop the others
            if not isinstance(e, SourceError):
                log.exception("citation update check of %s failed", item.key)
            errors[item.key] = str(e)
            record_check(item.key, str(e))
            continue
        record_check(item.key, "")
        if fetched is None:
            continue
        if source.skipped_version and source.skipped_version == fetched.release.version:
            fetched.discard()
            continue
        offers.append(Offer(item.key, item.manifest.name, have, fetched, passed))
    return offers, errors
