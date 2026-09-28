"""Info -> "Check for updates…": compare this build's VERSION_NUMBER with
the newest GitHub release, and install that release's zip over the
running PyInstaller binary.

Only a frozen build can update itself -- a source checkout is updated
with git, and replacing its files with a release binary would be wrong.

The running binary can't be overwritten in place on Windows, but it can
be renamed, so installing moves it aside as "<name>.old" first and drops
the new one in under the original name; the next start removes the
leftover (remove_leftover_binary()). Linux takes the same path.

v4.1.0 (direct instruction): an update mode per user and machine --
"off" (never check on start), "ask" (default: check on start and ask) or
"auto" (check on start and install) -- stored next to the token in
config_dir(), never in the project. A release that breaks with the past
is always asked about, even in "auto" mode: see plan_update(). A release
is breaking when its notes contain a paragraph starting "BREAKING:" (or a
"## Breaking changes" section) -- version.py's history entry supplies
them, packaging/release_notes.py enforces the marker for a major bump --
or when its major version number is higher than the running one.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .project import config_dir

REPO = "stpalan/SlideMage"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://api.github.com/repos/{REPO}/releases"
# A private repo's releases are only visible with a token that can read it.
# The environment variable wins over the token saved in Preferences, which
# lives in the per-user config folder -- never the project's .slidemage/,
# which travels with the (often cloud-synced) project folder.
TOKEN_ENV_VAR = "SLIDEMAGE_GITHUB_TOKEN"
TOKEN_FILENAME = "github_token"
# release.yml's asset names and the binary each one contains.
ASSETS = {
    "win32": ("SlideMage-windows.zip", "SlideMage.exe"),
    "linux": ("SlideMage-linux.zip", "SlideMage"),
}
OLD_SUFFIX = ".old"

UPDATE_MODE_OFF = "off"
UPDATE_MODE_ASK = "ask"
UPDATE_MODE_AUTO = "auto"
UPDATE_MODES = (UPDATE_MODE_OFF, UPDATE_MODE_ASK, UPDATE_MODE_AUTO)
DEFAULT_UPDATE_MODE = UPDATE_MODE_ASK
UPDATE_MODE_FILENAME = "update_mode"

BREAKING_PREFIX = "BREAKING:"
BREAKING_HEADING = "## breaking changes"


class UpdateError(RuntimeError):
    pass


@dataclass
class Release:
    tag: str
    page_url: str
    asset_url: Optional[str]   # API url of this platform's zip, if attached
    asset_size: int
    body: str = ""             # the release notes (Markdown)


@dataclass
class UpdatePlan:
    """What plan_update() found for the running version."""
    latest: Optional[Release]  # newest release newer than the running one; None = up to date
    breaking: list[Release]    # releases in (running, latest] that break with the past
    safe: Optional[Release]    # newest newer release before the first breaking one, if any


def parse_version(tag: str) -> Optional[tuple[int, ...]]:
    """(3, 29, 5) for "v3.29.5" or "3.29.5"; None for anything else."""
    parts = tag.strip().lstrip("vV").split(".")
    if not parts or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def is_newer(latest_tag: str, current_tag: str) -> bool:
    latest, current = parse_version(latest_tag), parse_version(current_tag)
    return latest is not None and current is not None and latest > current


def can_self_update() -> bool:
    return getattr(sys, "frozen", False) and sys.platform in ASSETS


def _update_mode_file() -> Path:
    return config_dir() / UPDATE_MODE_FILENAME


def get_update_mode() -> str:
    """"off", "ask" or "auto"; a missing or unknown value means "ask"."""
    try:
        mode = _update_mode_file().read_text(encoding="utf-8").strip()
    except OSError:
        return DEFAULT_UPDATE_MODE
    return mode if mode in UPDATE_MODES else DEFAULT_UPDATE_MODE


def set_update_mode(mode: str) -> None:
    if mode not in UPDATE_MODES:
        raise ValueError(f"Unknown update mode {mode!r}")
    path = _update_mode_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(mode + "\n", encoding="utf-8")


def breaking_notes(release: Release) -> list[str]:
    """The paragraphs of `release`'s notes that describe a break with the
    past: each paragraph starting "BREAKING:", and everything under a
    "## Breaking changes" heading up to the next heading."""
    notes: list[str] = []
    paragraph: list[str] = []
    in_section = False

    def flush() -> None:
        text = "\n".join(paragraph).strip()
        if text and (in_section or text.startswith(BREAKING_PREFIX)):
            notes.append(text)
        paragraph.clear()

    for line in release.body.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            flush()
            in_section = stripped.lower().startswith(BREAKING_HEADING)
            continue
        if not stripped:
            flush()
            continue
        if stripped.startswith(BREAKING_PREFIX):
            flush()
        paragraph.append(line.rstrip())
    flush()
    return notes


def is_breaking(release: Release, current_tag: str) -> bool:
    """True if `release` is marked as breaking, or if its major version
    number is higher than `current_tag`'s."""
    if breaking_notes(release):
        return True
    if any(line.strip().lower().startswith(BREAKING_HEADING)
           for line in release.body.splitlines()):
        return True
    new, current = parse_version(release.tag), parse_version(current_tag)
    return new is not None and current is not None and new[0] > current[0]


def plan_update(releases: list[Release], current_tag: str) -> UpdatePlan:
    """Decide what to offer. Every release between the running version and
    the newest one counts: skipping over a breaking release to a later,
    unmarked one still breaks with the past."""
    newer = sorted(
        (r for r in releases if is_newer(r.tag, current_tag)),
        key=lambda r: parse_version(r.tag),
    )
    if not newer:
        return UpdatePlan(latest=None, breaking=[], safe=None)
    breaking = [r for r in newer if is_breaking(r, current_tag)]
    safe = None
    for release in newer:
        if release in breaking:
            break
        safe = release
    return UpdatePlan(latest=newer[-1], breaking=breaking, safe=safe)


def newest_non_breaking(releases: list[Release], current_tag: str) -> Optional[Release]:
    return plan_update(releases, current_tag).safe


def _token_file() -> Path:
    return config_dir() / TOKEN_FILENAME


def saved_token() -> str:
    try:
        return _token_file().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def save_token(token: str) -> None:
    """Save `token` readable only by this user; an empty one removes it."""
    path = _token_file()
    token = token.strip()
    if not token:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(token + "\n")
    if os.name != "nt":
        path.chmod(0o600)  # an older file may have been created looser


def active_token() -> str:
    return os.environ.get(TOKEN_ENV_VAR, "").strip() or saved_token()


def _request(url: str, accept: str) -> urllib.request.Request:
    headers = {"Accept": accept, "User-Agent": "SlideMage-updater"}
    token = active_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers)


def _get_json(url: str, timeout: float):
    try:
        with urllib.request.urlopen(
            _request(url, "application/vnd.github+json"), timeout=timeout,
        ) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError(
                f"No published release found for {REPO}. If the repository is "
                "private, add a GitHub token that can read it under "
                f"Preferences → General (or set {TOKEN_ENV_VAR})."
            ) from exc
        if exc.code in (401, 403) and active_token():
            raise UpdateError(
                f"GitHub refused the saved token ({exc.code} {exc.reason}). It may have "
                f"expired, or lack read access to {REPO}'s releases -- a fine-grained "
                "token needs Repository permissions → Contents: Read-only."
            ) from exc
        raise UpdateError(f"GitHub answered {exc.code} {exc.reason}.") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise UpdateError(f"Couldn't reach GitHub: {exc}") from exc


def _release_from(data: dict) -> Release:
    asset_name = ASSETS.get(sys.platform, (None, None))[0]
    asset = next((a for a in data.get("assets", []) if a.get("name") == asset_name), None)
    return Release(
        tag=data.get("tag_name", ""),
        page_url=data.get("html_url", f"https://github.com/{REPO}/releases"),
        asset_url=asset["url"] if asset else None,
        asset_size=asset.get("size", 0) if asset else 0,
        body=data.get("body") or "",
    )


def fetch_latest_release(timeout: float = 10) -> Release:
    return _release_from(_get_json(LATEST_RELEASE_URL, timeout))


def fetch_releases(limit: int = 30, timeout: float = 10) -> list[Release]:
    """The newest `limit` published releases (drafts and prereleases
    skipped), in GitHub's order -- plan_update() sorts them itself."""
    data = _get_json(f"{RELEASES_URL}?per_page={limit}", timeout)
    if not isinstance(data, list):
        raise UpdateError("GitHub sent an unexpected answer for the release list.")
    return [
        _release_from(item) for item in data
        if isinstance(item, dict) and not item.get("draft") and not item.get("prerelease")
    ]


def download(
    release: Release, dest: Path, progress: Callable[[int, int], bool], timeout: float = 30,
) -> None:
    """Stream the release zip into `dest`. `progress(done, total)` is
    called after every chunk; returning False cancels (UpdateError)."""
    if release.asset_url is None:
        raise UpdateError(f"Release {release.tag} has no download for this platform.")
    try:
        with urllib.request.urlopen(
            _request(release.asset_url, "application/octet-stream"), timeout=timeout,
        ) as response, open(dest, "wb") as out:
            total = int(response.headers.get("Content-Length") or release.asset_size or 0)
            done = 0
            while chunk := response.read(256 * 1024):
                out.write(chunk)
                done += len(chunk)
                if not progress(done, total):
                    raise UpdateError("Download cancelled.")
    except urllib.error.HTTPError as exc:
        raise UpdateError(f"Download failed: {exc.code} {exc.reason}.") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise UpdateError(f"Download failed: {exc}") from exc


def install_zip(zip_path: Path, executable: Path, binary_name: str) -> None:
    """Unpack every file in `zip_path` next to `executable`, replacing
    what's there. The zip's `binary_name` entry replaces `executable`
    itself, whatever the running binary has been renamed to."""
    target_dir = executable.parent
    try:
        with zipfile.ZipFile(zip_path) as archive, tempfile.TemporaryDirectory(
            dir=target_dir, prefix=".slidemage-update-",
        ) as staging:
            members = [m for m in archive.infolist() if not m.is_dir()]
            if not any(Path(m.filename).name == binary_name for m in members):
                raise UpdateError(f"The release zip doesn't contain {binary_name}.")
            staged: list[tuple[Path, Path]] = []
            for member in members:
                # Flat install: only the file name counts, never a path
                # inside the zip (so nothing can land outside target_dir).
                name = Path(member.filename).name
                source = Path(staging) / name
                with archive.open(member) as src, open(source, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                target = executable if name == binary_name else target_dir / name
                if target == executable and os.name != "nt":
                    source.chmod(0o755)
                staged.append((source, target))
            for source, target in staged:
                if target == executable and target.exists():
                    old = target.with_name(target.name + OLD_SUFFIX)
                    old.unlink(missing_ok=True)
                    os.replace(target, old)
                os.replace(source, target)
    except (zipfile.BadZipFile, OSError) as exc:
        raise UpdateError(f"Couldn't install the update: {exc}") from exc


def remove_leftover_binary(executable: Path) -> None:
    """Delete the "<name>.old" a previous update left behind."""
    try:
        executable.with_name(executable.name + OLD_SUFFIX).unlink(missing_ok=True)
    except OSError:
        pass  # still locked, e.g. the old process hasn't exited yet
