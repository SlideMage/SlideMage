# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Themes installed from a (private) GitHub repository, and their updates (docs/THEME_PACKAGE.md, "From GitHub").

A theme carrying an institution's logo is never in the catalogue: SlideMage installs it straight from its repository,
with the GitHub token updater.py keeps (Settings → General, $SLIDEMAGE_GITHUB_TOKEN wins), and offers its updates.

* Releases: /repos/{owner}/{name}/releases, never /releases/latest (GitHub can mark a broken or withdrawn release
  "Latest"). A release is **eligible** when it is published (not a draft, not a pre-release), carries
  <key>-<version>.smtheme and its .sha256 with <version> its tag without the "v", the download matches the hash,
  its theme.toml has that version (and, for an update, the installed key), and its requires_slidemage accepts this
  SlideMage. The newest eligible one wins; one that fails a check is passed over for the next older one.
* Downloads: the API asset URL with Accept: application/octet-stream (updater._request), which a private
  repository needs; GitHub answers with a redirect to the file.
* Where it came from: config_dir()/themes/<key>/source.json (repository, version, release id, installed at, and the
  last check's time and failure, a version the user skipped). A theme installed from a file has none (the package
  cannot hold one, and installing replaces the folder), so it is never updated.
* Failures are SourceError, worded like the updater's: 404 = no access or no release, 401/403 = token refused,
  with the permission a fine-grained token needs. They never touch the installed theme.

No Qt, standard library only; blocking: call the network functions from a worker thread.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import tempfile
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from http.client import HTTPException
from pathlib import Path

from . import themes, updater
from .plugins import installer
from .plugins.manifest import parse_version
from .version import VERSION_NUMBER

log = logging.getLogger(__name__)

API = "https://api.github.com"
SOURCE_FILE = "source.json"
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
ASSET_RE = re.compile(r"^(?P<key>[a-z][a-z0-9-]{1,31})-(?P<version>\d+\.\d+\.\d+)\.smtheme$")
MAX_SHA_BYTES = 4096
TOKEN_PERMISSION = ("a fine-grained token needs the repository's owner ({owner}) as its resource owner, {repo} among "
                    "its repositories, and Repository permissions → Contents: Read-only")


class SourceError(Exception):
    """The repository could not be read (no access, token refused, no network); the message is for the user."""


class NotEligible(Exception):
    """One release fails a check; the next older one is tried."""


@dataclass(frozen=True)
class ThemeRelease:
    repository: str
    tag: str
    version: str
    release_id: int
    key: str
    body: str               # the release notes (Markdown)
    page_url: str
    asset_name: str
    asset_url: str          # API urls: a private repository's files are read through the API
    asset_size: int
    sha_url: str

    @property
    def number(self) -> tuple[int, int, int]:
        return parse_version(self.version)


@dataclass
class Fetched:
    """A downloaded, checked release, waiting in a folder of its own to be installed (or discarded)."""
    release: ThemeRelease
    archive: Path
    sha256: str
    manifest: themes.ThemeManifest

    def discard(self) -> None:
        shutil.rmtree(self.archive.parent, ignore_errors=True)


@dataclass
class Source:
    repository: str
    version: str
    release_id: int
    installed_at: str
    checked_at: str = ""
    check_error: str = ""   # why the last update check failed ("" = it worked)
    skipped_version: str = ""


@dataclass
class Offer:
    """A newer eligible release of an installed GitHub theme."""
    key: str
    name: str
    installed_version: str
    fetched: Fetched
    passed_over: list[str] = field(default_factory=list)

    @property
    def major(self) -> bool:
        """A higher major version: the theme's own breaking change."""
        try:
            return self.fetched.release.number[0] > parse_version(self.installed_version)[0]
        except ValueError:
            return False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_repository(text: str) -> str:
    """"owner/name" from what the user typed: owner/name, or a github.com address of it. Raises SourceError."""
    value = text.strip()
    value = re.sub(r"^(?:https?://)?(?:www\.)?github\.com/", "", value)
    value = value.removesuffix("/").removesuffix(".git")
    if not REPOSITORY_RE.match(value):
        raise SourceError(f"{text.strip()!r} is not a GitHub repository: type owner/name, "
                          "for example SlideMage/slidemage-theme-uni-graz.")
    return value


# -- source.json

def source_path(key: str) -> Path:
    return themes.themes_dir() / key / SOURCE_FILE


def read_source(key: str) -> Source | None:
    """Where the installed theme `key` came from, or None (installed from a file, or source.json unreadable)."""
    try:
        data = json.loads(source_path(key).read_text(encoding="utf-8"))
        known = {f.name for f in fields(Source)}
        source = Source(**{k: v for k, v in data.items() if k in known})
        parse_repository(source.repository)
        return source
    except (OSError, ValueError, TypeError, SourceError):
        return None


def write_source(key: str, source: Source) -> None:
    path = source_path(key)
    path.write_text(json.dumps(asdict(source), indent=2) + "\n", encoding="utf-8")


def record_check(key: str, error: str = "") -> None:
    """Note the update check's time and, if it failed, why (Settings → Themes shows it). Never raises."""
    source = read_source(key)
    if source is None:
        return
    source.checked_at, source.check_error = _now(), error
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


def github_themes() -> list[tuple[themes.InstalledTheme, Source]]:
    """The installed, usable themes that came from a GitHub repository."""
    found = []
    for theme in themes.installed():
        source = read_source(theme.key) if theme.manifest is not None and not theme.problem else None
        if source is not None:
            found.append((theme, source))
    return found


# -- GitHub

def _explain(exc: urllib.error.HTTPError, repo: str) -> SourceError:
    owner = repo.split("/")[0]
    if exc.code == 404:
        hint = ("add a GitHub token that can read it under Settings → General "
                f"(or set {updater.TOKEN_ENV_VAR})" if not updater.active_token() else
                "check that your token can read it: " + TOKEN_PERMISSION.format(owner=owner, repo=repo))
        return SourceError(f"No published release found for {repo}, or no access to it. If the repository is "
                           f"private, {hint}.")
    if exc.code in (401, 403) and updater.active_token():
        return SourceError(f"GitHub refused the saved token ({exc.code} {exc.reason}). It may have expired, lack "
                           f"read access to {repo}, or wait for the organization's approval -- "
                           + TOKEN_PERMISSION.format(owner=owner, repo=repo) + ".")
    if exc.code in (401, 403):
        return SourceError(f"GitHub refused the request ({exc.code} {exc.reason}). Add a GitHub token under "
                           f"Settings → General (or set {updater.TOKEN_ENV_VAR}).")
    return SourceError(f"GitHub answered {exc.code} {exc.reason}.")


def _get_json(url: str, repo: str, timeout: float):
    try:
        with urllib.request.urlopen(updater._request(url, "application/vnd.github+json"), timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise _explain(exc, repo) from exc
    except (urllib.error.URLError, HTTPException, OSError, ValueError) as exc:
        raise SourceError(f"Couldn't reach GitHub: {exc}") from exc


def _download(url: str, dest: Path, repo: str, max_bytes: int, timeout: float) -> None:
    """Stream the API asset `url` into `dest` (Accept: application/octet-stream). Raises SourceError, or NotEligible
    for a file larger than `max_bytes`."""
    done = 0
    try:
        with urllib.request.urlopen(updater._request(url, "application/octet-stream"), timeout=timeout) as response, \
                open(dest, "wb") as out:
            while chunk := response.read(256 * 1024):
                done += len(chunk)
                if done > max_bytes:
                    raise NotEligible("its file is too large")
                out.write(chunk)
    except urllib.error.HTTPError as exc:
        raise _explain(exc, repo) from exc
    except (urllib.error.URLError, HTTPException, OSError) as exc:
        raise SourceError(f"Download failed: {exc}") from exc


def _candidate(item: dict, repo: str, key: str | None) -> ThemeRelease | None:
    """The release `item` of the list, when it is published and carries <key>-<version>.smtheme and its .sha256."""
    if not isinstance(item, dict) or item.get("draft") or item.get("prerelease"):
        return None
    tag = str(item.get("tag_name") or "")
    version = tag.removeprefix("v")
    assets = {a.get("name"): a for a in item.get("assets") or [] if isinstance(a, dict)}
    for name, asset in assets.items():
        match = ASSET_RE.match(name or "")
        if not match or match["version"] != version or (key is not None and match["key"] != key):
            continue
        sha = assets.get(name + ".sha256")
        if sha is None or not asset.get("url") or not sha.get("url"):
            continue
        return ThemeRelease(
            repository=repo, tag=tag, version=version, release_id=int(item.get("id") or 0), key=match["key"],
            body=item.get("body") or "", page_url=item.get("html_url") or f"https://github.com/{repo}/releases",
            asset_name=name, asset_url=asset["url"], asset_size=int(asset.get("size") or 0), sha_url=sha["url"])
    return None


def list_releases(repo: str, key: str | None = None, timeout: float = 10) -> list[ThemeRelease]:
    """The repository's releases that may be eligible (published, with the two files), newest version first."""
    data = _get_json(f"{API}/repos/{repo}/releases?per_page=100", repo, timeout)
    if not isinstance(data, list):
        raise SourceError("GitHub sent an unexpected answer for the release list.")
    found = [r for r in (_candidate(item, repo, key) for item in data) if r is not None]
    return sorted(found, key=lambda r: r.number, reverse=True)


def fetch(release: ThemeRelease, app_version: str = VERSION_NUMBER, timeout: float = 30) -> Fetched:
    """Download `release` and run the eligibility checks that need its files. Raises NotEligible or SourceError."""
    folder = Path(tempfile.mkdtemp(prefix="slidemage-theme-"))
    try:
        sha_file = folder / (release.asset_name + ".sha256")
        _download(release.sha_url, sha_file, release.repository, MAX_SHA_BYTES, timeout)
        expected = installer.read_sha256_file(sha_file)
        if expected is None:
            raise NotEligible(f"{sha_file.name} holds no SHA-256 checksum")
        archive = folder / release.asset_name
        _download(release.asset_url, archive, release.repository, installer.MAX_DOWNLOAD_BYTES, timeout)
        if installer.sha256_of(archive) != expected:
            raise NotEligible(f"{release.asset_name} does not match its .sha256")
        try:
            manifest = themes.peek(archive)
            if manifest.version != release.version:
                raise NotEligible(f"its theme.toml says version {manifest.version}, the tag {release.tag}")
            if manifest.id != release.key:
                raise NotEligible(f"its theme.toml names the key {manifest.id!r}, the file {release.key!r}")
            themes.check_manifest(manifest, app_version)
        except themes.ThemeError as e:
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


def install(fetched: Fetched) -> themes.ThemeManifest:
    """Install a fetched release and record where it came from; the download is deleted. Raises ThemeError."""
    try:
        manifest = themes.install_file(fetched.archive, expected_sha256=fetched.sha256)
        release = fetched.release
        try:
            write_source(manifest.id, Source(release.repository, manifest.version, release.release_id, _now()))
        except OSError as e:
            raise themes.ThemeError(f"The theme is installed, but where it came from could not be saved, so it will "
                                    f"not be updated: {e}") from None
        return manifest
    finally:
        fetched.discard()


def check_updates(app_version: str = VERSION_NUMBER) -> tuple[list[Offer], dict[str, str]]:
    """Look for a newer eligible release of each GitHub theme (a worker thread's job). The offers (downloaded,
    checked, not installed; a skipped version is not offered) and, per key, why a check failed. Each check's outcome
    is recorded in the theme's source.json."""
    offers: list[Offer] = []
    errors: dict[str, str] = {}
    for theme, source in github_themes():
        have = theme.manifest.version
        try:
            fetched, passed = newest_eligible(source.repository, key=theme.key, newer_than=have,
                                              app_version=app_version)
        except SourceError as e:
            errors[theme.key] = str(e)
            record_check(theme.key, str(e))
            continue
        except Exception as e:          # one theme failing must not stop the others
            log.exception("theme update check of %s failed", theme.key)
            errors[theme.key] = str(e)
            record_check(theme.key, str(e))
            continue
        record_check(theme.key, "")
        if fetched is None:
            continue
        if source.skipped_version and source.skipped_version == fetched.release.version:
            fetched.discard()
            continue
        offers.append(Offer(theme.key, theme.manifest.name, have, fetched, passed))
    return offers, errors
