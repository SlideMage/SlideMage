# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""TeX packages installed from (private) GitHub repositories and their updates.

Use the GitHub token updater.py keeps (Settings → General, $SLIDEMAGE_GITHUB_TOKEN wins).
* Read /repos/{owner}/{name}/releases, never /releases/latest: GitHub can mark a broken or withdrawn release
  "Latest". A release is eligible when published (not draft or pre-release), carrying <key>-<version> plus the
  kind's suffix and .sha256, with the version its tag without "v". The download must match that hash; its manifest
  must name that version and key, and accept this SlideMage. Try the newest version first, passing over failures.
* Download through API asset URLs with Accept: application/octet-stream (updater._request); a private repository
  needs these URLs and GitHub redirects to the file.
* source.json in the installed folder records repository, version, release id, installation time, last check and
  skipped version. Installing from a file replaces the folder and loses its source, so it is never updated.
* SourceError explains no access, token refusal or no network, with the permissions a fine-grained token needs.
  A failed check never touches the installed package.
No Qt, standard library only; blocking: call network functions from a worker thread.
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

from . import diagnostics, packages, updater
from .plugins import installer
from .plugins.manifest import parse_version
from .version import VERSION_NUMBER

# Both kinds already use this network diagnostic area; keep existing log filtering useful.
log = logging.getLogger("slidemage.theme_sources")

API = "https://api.github.com"
SOURCE_FILE = "source.json"
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
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
    manifest: packages.PackageManifest

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
    """A newer eligible release of an installed GitHub package."""
    key: str
    name: str
    installed_version: str
    fetched: Fetched
    passed_over: list[str] = field(default_factory=list)

    @property
    def major(self) -> bool:
        """A higher major version: the package's own breaking change."""
        try:
            return self.fetched.release.number[0] > parse_version(self.installed_version)[0]
        except ValueError:
            return False


def asset_pattern(kind: packages.PackageKind) -> re.Pattern:
    return re.compile(r"^(?P<key>[a-z][a-z0-9-]{1,31})-(?P<version>\d+\.\d+\.\d+)" + re.escape(kind.suffix) + "$")


def _logger(kind: packages.PackageKind) -> logging.Logger:
    return logging.getLogger(f"slidemage.{kind.manifest_name.removesuffix('.toml')}_sources")


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

def source_path(kind: packages.PackageKind, key: str) -> Path:
    return kind.folder() / key / SOURCE_FILE


def read_source(kind: packages.PackageKind, key: str) -> Source | None:
    """Where the installed package came from, or None (installed from a file, or source.json unreadable)."""
    try:
        data = json.loads(source_path(kind, key).read_text(encoding="utf-8"))
        known = {f.name for f in fields(Source)}
        source = Source(**{k: v for k, v in data.items() if k in known})
        parse_repository(source.repository)
        return source
    except (OSError, ValueError, TypeError, SourceError):
        return None


def write_source(kind: packages.PackageKind, key: str, source: Source) -> None:
    path = source_path(kind, key)
    path.write_text(json.dumps(asdict(source), indent=2) + "\n", encoding="utf-8")


def record_check(kind: packages.PackageKind, key: str, error: str = "") -> None:
    """Note the check's time and, if it failed, why (Settings shows it). Never raises."""
    source = read_source(kind, key)
    if source is None:
        return
    source.checked_at, source.check_error = _now(), error
    try:
        write_source(kind, key, source)
    except OSError:
        _logger(kind).exception("could not write %s", source_path(kind, key))


def skip_version(kind: packages.PackageKind, key: str, version: str) -> None:
    """"Skip this version": not offered again; a later one is."""
    source = read_source(kind, key)
    if source is not None:
        source.skipped_version = version
        write_source(kind, key, source)


def github_packages(kind: packages.PackageKind) -> list[tuple[packages.InstalledPackage, Source]]:
    """The installed, usable packages that came from a GitHub repository."""
    found = []
    for item in packages.installed(kind):
        source = read_source(kind, item.key) if item.manifest is not None and not item.problem else None
        if source is not None:
            found.append((item, source))
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
        request = updater._request(url, "application/vnd.github+json")
        with diagnostics.timed(log, "GET", url=url) as info, urllib.request.urlopen(request, timeout=timeout) as response:
            info["status"] = getattr(response, "status", None)
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
        request = updater._request(url, "application/octet-stream")
        with diagnostics.timed(log, "download", url=url), urllib.request.urlopen(request, timeout=timeout) as response, \
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


def _candidate(kind: packages.PackageKind, item: dict, repo: str, key: str | None,
               asset_re: re.Pattern | None = None) -> ThemeRelease | None:
    """A published release carrying this kind's package (or `asset_re`) and its .sha256."""
    if not isinstance(item, dict) or item.get("draft") or item.get("prerelease"):
        return None
    tag = str(item.get("tag_name") or "")
    version = tag.removeprefix("v")
    assets = {a.get("name"): a for a in item.get("assets") or [] if isinstance(a, dict)}
    asset_re = asset_re if asset_re is not None else asset_pattern(kind)
    for name, asset in assets.items():
        match = asset_re.match(name or "")
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


def list_releases(kind: packages.PackageKind, repo: str, key: str | None = None, timeout: float = 10,
                  asset_re: re.Pattern | None = None) -> list[ThemeRelease]:
    """The repository's releases that may be eligible (published, with the two files), newest version first."""
    data = _get_json(f"{API}/repos/{repo}/releases?per_page=100", repo, timeout)
    if not isinstance(data, list):
        raise SourceError("GitHub sent an unexpected answer for the release list.")
    found = [r for r in (_candidate(kind, item, repo, key, asset_re) for item in data) if r is not None]
    return sorted(found, key=lambda r: r.number, reverse=True)


def fetch(kind: packages.PackageKind, release: ThemeRelease, app_version: str = VERSION_NUMBER,
          timeout: float = 30) -> Fetched:
    """Download `release` and run the eligibility checks that need its files. Raises NotEligible or SourceError."""
    folder = Path(tempfile.mkdtemp(prefix=f"slidemage-{kind.manifest_name.removesuffix('.toml')}-"))
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
            manifest = packages.peek(kind, archive)
            if manifest.version != release.version:
                raise NotEligible(f"its {kind.manifest_name} says version {manifest.version}, the tag {release.tag}")
            if manifest.id != release.key:
                raise NotEligible(f"its {kind.manifest_name} names the key {manifest.id!r}, the file {release.key!r}")
            kind.check_manifest(manifest, app_version)
        except kind.error as e:
            raise NotEligible(str(e)) from None
        return Fetched(release, archive, expected, manifest)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise


def newest_eligible(kind: packages.PackageKind, repo: str, *, key: str | None = None, newer_than: str | None = None,
                    app_version: str = VERSION_NUMBER, timeout: float = 30) -> tuple[Fetched | None, list[str]]:
    """The newest eligible release (downloaded and checked), newer than `newer_than` if given, and why the newer ones
    were passed over ("v1.2.0: ..."). Raises SourceError when the repository cannot be read."""
    floor = parse_version(newer_than) if newer_than else None
    passed: list[str] = []
    for release in list_releases(kind, repo, key, timeout=min(timeout, 10)):
        if floor is not None and release.number <= floor:
            break
        try:
            return fetch(kind, release, app_version, timeout), passed
        except NotEligible as e:
            passed.append(f"{release.tag}: {e}")
    return None, passed


def install(kind: packages.PackageKind, fetched: Fetched) -> packages.PackageManifest:
    """Install a fetched release and record where it came from; the download is deleted. Raises the kind's error."""
    try:
        manifest = packages.install_file(kind, fetched.archive, expected_sha256=fetched.sha256)
        release = fetched.release
        try:
            write_source(kind, manifest.id, Source(release.repository, manifest.version, release.release_id, _now()))
        except OSError as e:
            raise kind.error(f"The {kind.name} is installed, but where it came from could not be saved, so it will "
                             f"not be updated: {e}") from None
        return manifest
    finally:
        fetched.discard()


def check_updates(kind: packages.PackageKind, app_version: str = VERSION_NUMBER) -> tuple[list[Offer], dict[str, str]]:
    """Check each GitHub package for updates on a worker thread. Return checked downloads (excluding skipped
    versions) and errors per key; record each check's outcome in source.json."""
    offers: list[Offer] = []
    errors: dict[str, str] = {}
    for item, source in github_packages(kind):
        have = item.manifest.version
        try:
            fetched, passed = newest_eligible(kind, source.repository, key=item.key, newer_than=have,
                                              app_version=app_version)
        except SourceError as e:
            errors[item.key] = str(e)
            record_check(kind, item.key, str(e))
            continue
        except Exception as e:          # one package failing must not stop the others
            _logger(kind).exception("%s update check of %s failed", kind.manifest_name.removesuffix(".toml"), item.key)
            errors[item.key] = str(e)
            record_check(kind, item.key, str(e))
            continue
        record_check(kind, item.key, "")
        if fetched is None:
            continue
        if source.skipped_version and source.skipped_version == fetched.release.version:
            fetched.discard()
            continue
        offers.append(Offer(item.key, item.manifest.name, have, fetched, passed))
    return offers, errors
