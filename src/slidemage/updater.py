# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Info -> "Check for updates…": compare this build's VERSION_NUMBER with
the newest GitHub release, and install that release's zip over the
running PyInstaller build.

Only a frozen build can update itself -- a source checkout is updated
with git, and replacing its files with a release binary would be wrong.

Every release has two builds per platform, and an installation updates itself with the one it is:
the single file (SlideMage.exe: unpacks itself at every start, so it starts slowly) and the folder
(SlideMage.exe next to its _internal folder: starts quickly). install_flavour() tells which one is running.

The running single file can't be overwritten in place on Windows, but it can
be renamed, so installing moves it aside as "<name>.old" first and drops
the new one in under the original name; the next start removes the
leftover (remove_leftover_binary()). Linux takes the same path.

A running folder can't be replaced while it runs (its DLLs are loaded), so the update is unpacked next to
it ("<folder>.update", stage_folder_update()) and a small helper script, started detached
(spawn_folder_swap()), waits until this process has ended, swaps the two folders (the old one becomes
"<folder>.old", removed by the next start: remove_leftover_folder()) and, when the user chose to restart,
starts the new SlideMage.

SlideMage Presenter (docs/plans/presenter-app.md, v0.13.6) is a third flavour: always a folder build, with its own
assets (PRESENTER_ASSETS, SlideMagePresenter-<os>.zip) attached to the same releases, but only to those that
change it. It updates with the same stage_folder_update() and spawn_folder_swap(). On macOS it is an unsigned
.app and does not replace itself: can_self_update() is False there and it shows the release page instead.

Nothing is installed unless download() has checked the zip: its length, the SHA-256 GitHub reports for the asset
and the signature in "<zip>.sig" against the keys built into the app (release_signing.py, ed25519.py).
install_zip() is all or nothing: it undoes its swaps when one fails.

v4.1.0 (direct instruction): an update mode per user and machine --
"off" (never check on start), "ask" (default: check on start and ask) or
"auto" (check on start and install) -- stored next to the token in
config_dir(), never in the project. A release that breaks with the past
is always asked about, even in "auto" mode: see plan_update(). A release
is breaking when its notes contain a paragraph starting "BREAKING:" (or a
"## Breaking changes" section) -- CHANGELOG.md's history entry supplies
them, packaging/release_notes.py enforces the marker for a major bump --
or when its major version number is higher than the running one.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import diagnostics, fileio, release_signing, tls_trust
from .project import MARKER, config_dir
from .version import base_version, is_beta, release_key

REPO = "SlideMage/SlideMage"
RELEASES_URL = f"https://api.github.com/repos/{REPO}/releases"
# SlideMage's releases are public. The token is for themes from private repositories (package_sources.py);
# _open_own() drops it for SlideMage's own releases once GitHub refuses it.
# The environment variable wins over the token saved in Settings, which
# lives in the per-user config folder -- never the project's .slidemage/,
# which travels with the (often cloud-synced) project folder.
TOKEN_ENV_VAR = "SLIDEMAGE_GITHUB_TOKEN"
_log = logging.getLogger("slidemage.update")
TOKEN_FILENAME = "github_token"
# release.yml's asset names and the binary each one contains.
ASSETS = {
    "win32": ("SlideMage-windows.zip", "SlideMage.exe"),
    "linux": ("SlideMage-linux.zip", "SlideMage"),
}
# The folder build: a zip of one folder (SlideMage.exe or SlideMage, and _internal/).
FOLDER_ASSETS = {
    "win32": ("SlideMage-windows-folder.zip", "SlideMage.exe"),
    "linux": ("SlideMage-linux-folder.zip", "SlideMage"),
}
# SlideMage Presenter: a zip of one folder (SlideMagePresenter(.exe) and _internal/); on macOS a zip of the .app.
PRESENTER_ASSETS = {
    "win32": ("SlideMagePresenter-windows.zip", "SlideMagePresenter.exe"),
    "linux": ("SlideMagePresenter-linux.zip", "SlideMagePresenter"),
    "darwin": ("SlideMagePresenter-macos.zip", "SlideMage Presenter.app"),
}
PRESENTER_NAME = "SlideMagePresenter"
PRESENTER_APP = "SlideMage Presenter.app"
SINGLE, FOLDER, PRESENTER = "single", "folder", "presenter"
OLD_SUFFIX = ".old"
UPDATE_SUFFIX = ".update"
FLAVOUR_ENV_VAR = "SLIDEMAGE_FLAVOUR"      # tests and support: "single", "folder" or "presenter" instead of detecting it

UPDATE_MODE_OFF = "off"
UPDATE_MODE_ASK = "ask"
UPDATE_MODE_AUTO = "auto"
UPDATE_MODES = (UPDATE_MODE_OFF, UPDATE_MODE_ASK, UPDATE_MODE_AUTO)
DEFAULT_UPDATE_MODE = UPDATE_MODE_ASK
UPDATE_MODE_FILENAME = "update_mode"
# "yes" in this file of the config folder: beta versions (GitHub pre-releases, version.BETA_SUFFIX) are offered
# too. Missing or anything else: only releases. Settings -> General, "Offer beta versions".
BETA_UPDATES_FILENAME = "beta_updates"

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
    asset_name: str = ""       # the zip's file name on the release page
    asset_digest: Optional[str] = None   # "sha256:<64 hex>" as GitHub reports it for the zip; None = missing or malformed
    signature_url: Optional[str] = None  # API url of "<zip name>.sig" (release_signing), if attached


@dataclass
class UpdatePlan:
    """What plan_update() found for the running version."""
    latest: Optional[Release]  # newest release newer than the running one; None = up to date
    breaking: list[Release]    # releases in (running, latest] that break with the past
    safe: Optional[Release]    # newest newer release before the first breaking one, if any


def parse_version(tag: str) -> Optional[tuple[int, ...]]:
    """(0, 11, 2) for "v0.11.2" or "0.11.2"; None for anything else. A beta reads as the release it belongs to
    ("v1.1.0-beta.2" is (1, 1, 0)); is_newer() and plan_update() order betas with version.release_key."""
    parts = base_version(tag).lstrip("vV").split(".")
    if not parts or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


# v1.0.0 is the stable continuation of the 0.x line, not a break with it: going from 0.x to exactly 1.0.0 (or a
# beta of it) does not count as a major step by its number (raises_major). A BREAKING: paragraph still marks one.
FIRST_STABLE = (1, 0, 0)


def raises_major(new: tuple[int, ...], current: tuple[int, ...]) -> bool:
    """Whether `new` has a higher major version than `current` (major_key), not counting 0.x -> 1.0.0."""
    if current[:1] == (0,) and new[:3] == FIRST_STABLE and not any(new[3:]):
        return False
    return major_key(new) > major_key(current)


def major_key(number: tuple[int, ...]) -> tuple[int, ...]:
    """What a "major" bump compares: the first part, or in 0.x the second (the old majors became the minors)."""
    return number[:2] if number[:1] == (0,) else number[:1]


def is_newer(latest_tag: str, current_tag: str) -> bool:
    """Whether `latest_tag` comes after `current_tag`, betas included: v1.1.0-beta.1 < v1.1.0-beta.2 < v1.1.0."""
    latest, current = release_key(latest_tag), release_key(current_tag)
    return latest is not None and current is not None and latest > current


def is_presenter() -> bool:
    """True when the running program is SlideMage Presenter: its executable is SlideMagePresenter(.exe), or it sits
    inside SlideMage Presenter.app."""
    executable = Path(sys.executable)
    return executable.stem == PRESENTER_NAME or any(part.name == PRESENTER_APP for part in executable.parents)


def can_self_update() -> bool:
    """A frozen Windows or Linux build can replace itself. The macOS Presenter (an unsigned .app, the only macOS
    build) cannot: it is not in ASSETS, so this stays False there."""
    return getattr(sys, "frozen", False) and sys.platform in ASSETS


def install_flavour() -> str:
    """FOLDER when SlideMage runs from a folder build (PyInstaller's onedir: the libraries sit in _internal/ next to
    the executable), else SINGLE; PRESENTER for SlideMage Presenter, which is always a folder build."""
    forced = os.environ.get(FLAVOUR_ENV_VAR)
    if forced in (SINGLE, FOLDER, PRESENTER):
        return forced
    if is_presenter():
        return PRESENTER
    internal = getattr(sys, "_MEIPASS", None)
    if internal and getattr(sys, "frozen", False) and Path(internal).resolve() == (Path(sys.executable).parent / "_internal").resolve():
        return FOLDER
    return SINGLE


def asset_names(flavour: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
    """(zip name, binary name) of this platform's release asset for `flavour` (the running one by default)."""
    flavour = flavour or install_flavour()
    table = PRESENTER_ASSETS if flavour == PRESENTER else FOLDER_ASSETS if flavour == FOLDER else ASSETS
    return table.get(sys.platform, (None, None))


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


def _beta_updates_file() -> Path:
    return config_dir() / BETA_UPDATES_FILENAME


def get_beta_updates() -> bool:
    """Whether beta versions are offered (Settings -> General). Off unless the user switched it on."""
    try:
        return _beta_updates_file().read_text(encoding="utf-8").strip() == "yes"
    except OSError:
        return False


def set_beta_updates(on: bool) -> None:
    path = _beta_updates_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(("yes" if on else "no") + "\n", encoding="utf-8")


def offered(release_tag: str, prerelease: bool, *, betas: bool) -> bool:
    """Whether a published release may be offered: a release always; a beta (a GitHub pre-release, or a tag with the
    beta suffix) only with `betas`. A pre-release whose tag is not a beta's is never offered."""
    if prerelease or is_beta(release_tag):
        return betas and is_beta(release_tag)
    return True


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
    return new is not None and current is not None and raises_major(new, current)


def plan_update(releases: list[Release], current_tag: str, *, need_asset: bool = False) -> UpdatePlan:
    """Decide what to offer. Every release between the running version and
    the newest one counts: skipping over a breaking release to a later,
    unmarked one still breaks with the past.

    `need_asset` (a copy that installs updates itself): a release without
    this installation's file is not offered yet. GitHub lists a release as
    soon as its first file is attached, and the builds of the platforms
    finish minutes apart; offered then, the download failed with "has no
    download for this platform". The next check finds it."""
    newer = sorted(
        (r for r in releases if is_newer(r.tag, current_tag)),
        key=lambda r: release_key(r.tag),
    )
    if need_asset:
        while newer and newer[-1].asset_url is None:
            newer.pop()            # an older one without the file still counts as one passed over
    if not newer:
        return UpdatePlan(latest=None, breaking=[], safe=None)
    breaking = [r for r in newer if is_breaking(r, current_tag)]
    safe = None
    for release in newer:
        if release in breaking:
            break
        safe = release
    return UpdatePlan(latest=newer[-1], breaking=breaking, safe=safe)


def _token_file() -> Path:
    return config_dir() / TOKEN_FILENAME


def saved_token() -> str:
    try:
        return _token_file().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def save_token(token: str) -> None:
    """Save `token` readable only by this user; an empty one removes it."""
    global _token_refused
    _token_refused = False
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


def _request(url: str, accept: str, *, token: bool = True) -> urllib.request.Request:
    headers = {"Accept": accept, "User-Agent": "SlideMage-updater"}
    value = active_token() if token else ""
    if value:
        headers["Authorization"] = f"Bearer {value}"
    return urllib.request.Request(url, headers=headers)


# SlideMage's own releases are public: the token is for themes from private repositories (package_sources.py). Once
# GitHub refuses it here (expired, revoked, not approved), this run asks for SlideMage's releases without it, so a
# bad token never blocks the app's update. Saving a token in Settings clears the flag.
_token_refused = False


def _open_own(url: str, accept: str, timeout: float):
    """urlopen() for SlideMage's own releases: with the token, and without it again when GitHub refuses it."""
    global _token_refused
    with_token = bool(active_token()) and not _token_refused
    try:
        return urllib.request.urlopen(_request(url, accept, token=with_token), timeout=timeout)
    except urllib.error.HTTPError as exc:
        if not with_token or exc.code not in (401, 403):
            raise
        _log.warning("GitHub refused the saved token (%s %s) for %s; asking without it. Themes from private "
                     "repositories need a new one under Settings → General.", exc.code, exc.reason, REPO)
        _token_refused = True
        return urllib.request.urlopen(_request(url, accept, token=False), timeout=timeout)


def _get_json(url: str, timeout: float):
    try:
        with diagnostics.timed(_log, "GET", url=url) as info, _open_own(
            url, "application/vnd.github+json", timeout,
        ) as response:
            info["status"] = getattr(response, "status", None)
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError(f"No published release found for {REPO}.") from exc
        raise UpdateError(f"GitHub answered {exc.code} {exc.reason}.") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise UpdateError(tls_trust.certificate_message(exc, url) or f"Couldn't reach GitHub: {exc}") from exc


_DIGEST_RE = re.compile(r"sha256:[0-9a-fA-F]{64}")


def _valid_digest(value) -> Optional[str]:
    """`value` as "sha256:<64 lowercase hex>" when it has that form, else None (a malformed digest counts as missing)."""
    return value.lower() if isinstance(value, str) and _DIGEST_RE.fullmatch(value) else None


def _release_from(data: dict, flavour: Optional[str] = None) -> Release:
    asset_name = asset_names(flavour)[0]
    assets = [a for a in data.get("assets", []) if isinstance(a, dict)]
    asset = next((a for a in assets if a.get("name") == asset_name), None)
    signature = next((a for a in assets if asset_name and a.get("name") == asset_name + release_signing.SIGNATURE_SUFFIX), None)
    return Release(
        tag=data.get("tag_name", ""),
        page_url=data.get("html_url", f"https://github.com/{REPO}/releases"),
        asset_url=asset["url"] if asset else None,
        asset_size=asset.get("size", 0) if asset else 0,
        body=data.get("body") or "",
        asset_name=(asset_name or "") if asset else "",
        asset_digest=_valid_digest(asset.get("digest")) if asset else None,
        signature_url=signature.get("url") if signature else None,
    )


def fetch_releases(limit: int = 30, timeout: float = 10, flavour: Optional[str] = None,
                   betas: Optional[bool] = None) -> list[Release]:
    """The newest `limit` published releases (drafts skipped; betas only with `betas`, by default the setting
    get_beta_updates()), in GitHub's order -- plan_update() sorts them itself.
    `flavour` picks the asset each Release carries (PRESENTER from a source checkout)."""
    betas = get_beta_updates() if betas is None else betas
    data = _get_json(f"{RELEASES_URL}?per_page={limit}", timeout)
    if not isinstance(data, list):
        raise UpdateError("GitHub sent an unexpected answer for the release list.")
    return [
        _release_from(item, flavour) for item in data
        if isinstance(item, dict) and not item.get("draft")
        and offered(str(item.get("tag_name", "")), bool(item.get("prerelease")), betas=betas)
    ]


def _refusal(release: Release, what: str) -> UpdateError:
    return UpdateError(f"{what} Nothing was installed. You can download SlideMage {release.tag} from {release.page_url} instead.")


def _fetch_signature(release: Release, timeout: float) -> str:
    """The text of the release's ".sig" asset (a few dozen bytes)."""
    if release.signature_url is None:
        raise _refusal(release, f"Release {release.tag} has no signature for this download, so it can't be checked.")
    try:
        with _open_own(release.signature_url, "application/octet-stream", timeout) as response:
            return response.read(4096).decode("ascii", "replace")
    except urllib.error.HTTPError as exc:
        raise UpdateError(f"Download failed: {exc.code} {exc.reason}.") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise UpdateError(tls_trust.certificate_message(exc, release.signature_url) or f"Download failed: {exc}") from exc


def download(
    release: Release, dest: Path, progress: Callable[[int, int], bool], timeout: float = 30,
) -> None:
    """Stream the release zip into `dest` and check it: complete (the length GitHub announced), the SHA-256 GitHub
    reports for the asset, and the release's signature against the keys built into the app
    (release_signing). A release without a valid digest or without a valid signature is refused, and a file that
    fails any check is deleted. `progress(done, total)` is called after every chunk; returning False cancels
    (UpdateError)."""
    if release.asset_url is None:
        raise UpdateError(f"Release {release.tag} has no download for this platform.")
    expected = _valid_digest(release.asset_digest)
    if expected is None:
        raise _refusal(release, f"GitHub gave no checksum for release {release.tag}'s download, so it can't be checked.")
    if not release_signing.parse_keys(release_signing.TRUSTED_PUBLIC_KEYS):
        raise _refusal(release, "This SlideMage has no release signing key built in, so a download can't be checked.")
    signature = _fetch_signature(release, timeout)
    digest = hashlib.sha256()
    done = 0
    total = 0
    try:
        with diagnostics.timed(_log, "download", url=release.asset_url), _open_own(
            release.asset_url, "application/octet-stream", timeout,
        ) as response, open(dest, "wb") as out:
            total = int(response.headers.get("Content-Length") or release.asset_size or 0)
            while chunk := response.read(256 * 1024):
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if not progress(done, total):
                    raise UpdateError("Download canceled.")
        announced = [n for n in (total, release.asset_size) if n]
        if any(done < n for n in announced):
            raise _refusal(release, f"The download ended early ({done} of {max(announced)} bytes).")
        actual = "sha256:" + digest.hexdigest()
        if actual != expected:
            _log.warning("download of %s: SHA-256 %s, expected %s", release.tag, actual, expected)
            raise _refusal(release, "The download does not match the release (SHA-256).")
        try:
            release_signing.verify_release(release.asset_name, digest.hexdigest(), signature)
        except release_signing.SignatureError as exc:
            _log.warning("download of %s: signature check failed: %s", release.tag, exc)
            raise _refusal(release, f"The release signature is not valid ({exc}).") from exc
        _log.info("download of %s verified: %s, signature ok", release.tag, actual)
    except urllib.error.HTTPError as exc:
        dest.unlink(missing_ok=True)
        raise UpdateError(f"Download failed: {exc.code} {exc.reason}.") from exc
    except (urllib.error.URLError, OSError) as exc:
        dest.unlink(missing_ok=True)
        raise UpdateError(tls_trust.certificate_message(exc, release.asset_url) or f"Download failed: {exc}") from exc
    except UpdateError:
        dest.unlink(missing_ok=True)
        raise


def install_zip(zip_path: Path, executable: Path, binary_name: str) -> None:
    """Unpack every file in `zip_path` next to `executable`, replacing what's there. The zip's `binary_name` entry
    replaces `executable` itself, whatever the running binary has been renamed to.

    All or nothing: every replaced file is first moved aside as "<name>.old", and when any swap fails all of them
    are put back. After success only the executable's ".old" stays (on Windows the running file cannot be deleted;
    remove_leftover_binary() removes it at the next start)."""
    target_dir = executable.parent
    try:
        with zipfile.ZipFile(zip_path) as archive, tempfile.TemporaryDirectory(
            dir=target_dir, prefix=".slidemage-update-",
        ) as staging:
            members = [m for m in archive.infolist() if not m.is_dir()]
            # Flat install: only the file name counts, never a path inside the zip (so nothing can land outside
            # target_dir) -- which is why two members with the same name would overwrite each other.
            names = [Path(m.filename).name for m in members]
            if binary_name not in names:
                raise UpdateError(f"The release zip doesn't contain {binary_name}.")
            duplicates = sorted({n for n in names if names.count(n) > 1})
            if duplicates:
                raise UpdateError(f"The release zip has several files named {', '.join(duplicates)}.")
            staged: list[tuple[Path, Path]] = []
            for member, name in zip(members, names):
                source = Path(staging) / name
                with archive.open(member) as src, open(source, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                target = executable if name == binary_name else target_dir / name
                if target == executable and os.name != "nt":
                    source.chmod(0o755)
                staged.append((source, target))
            swapped: list[tuple[Path, Optional[Path]]] = []      # (target, its ".old", or None when it was new)
            try:
                for source, target in staged:
                    old: Optional[Path] = None
                    if target.exists():
                        old = target.with_name(target.name + OLD_SUFFIX)
                        old.unlink(missing_ok=True)
                        fileio.replace_with_retry(target, old)
                    swapped.append((target, old))
                    fileio.replace_with_retry(source, target)
            except OSError as exc:
                problems = _undo_swaps(swapped)
                raise UpdateError(
                    f"Couldn't install the update: {exc}. "
                    + ("The previous version could not be fully restored: " + "; ".join(problems) if problems
                       else "The previous version is intact.")
                ) from exc
            for target, old in swapped:
                if old is not None and target != executable:
                    old.unlink(missing_ok=True)
    except (zipfile.BadZipFile, OSError) as exc:
        raise UpdateError(f"Couldn't install the update: {exc}") from exc


def _undo_swaps(swapped: list[tuple[Path, Optional[Path]]]) -> list[str]:
    """Put every swapped file back (newest first); what could not be restored is returned as text."""
    problems = []
    for target, old in reversed(swapped):
        try:
            target.unlink(missing_ok=True)
            if old is not None:
                fileio.replace_with_retry(old, target)
        except OSError as exc:
            problems.append(f"{target.name}: {exc}")
    return problems


def remove_leftover_binary(executable: Path) -> None:
    """Delete the "<name>.old" a previous update left behind."""
    try:
        executable.with_name(executable.name + OLD_SUFFIX).unlink(missing_ok=True)
    except OSError:
        pass  # still locked, e.g. the old process hasn't exited yet


# -- the folder build ---------------------------------------------------------------------------------------


def _sibling(folder: Path, suffix: str) -> Path:
    return folder.with_name(folder.name + suffix)


def projects_in(folder: Path) -> list[Path]:
    """The SlideMage projects (folders with slide_ids.csv) in or below `folder`. A folder build's own `_internal`
    is skipped: it holds the bundled example project."""
    found = []
    for root, dirs, files in os.walk(folder):
        if MARKER in files:
            found.append(Path(root))
            dirs.clear()
        elif "_internal" in dirs:
            dirs.remove("_internal")
    return sorted(found)


def stage_folder_update(zip_path: Path, install_dir: Path, binary_name: str) -> Path:
    """Unpack the folder zip into "<install_dir>.update" and return it. The zip holds one folder (or its content
    directly); a path that would leave the staging folder is refused. Nothing in `install_dir` is touched.

    Refused while a project lies in `install_dir` or in the "<install_dir>.old" an earlier update left: the swap
    moves the one and deletes the other (issue #85)."""
    held = projects_in(install_dir) + projects_in(_sibling(install_dir, OLD_SUFFIX))
    if held:
        listed = "\n".join(f"  {path}" for path in held)
        raise UpdateError(f"These projects lie inside the program folder {install_dir} or the folder an earlier "
                          f"update left next to it:\n{listed}\n\nAn update replaces those folders. Move the "
                          "projects somewhere else, open them from there, then update again.")
    staging = _sibling(install_dir, UPDATE_SUFFIX)
    try:
        shutil.rmtree(staging, ignore_errors=True)
        with zipfile.ZipFile(zip_path) as archive:
            members = [m for m in archive.infolist() if not m.is_dir()]
            parts = [Path(m.filename).parts for m in members]
            if not parts or any(len(p) < 1 or ".." in p or Path(m.filename).is_absolute() for p, m in zip(parts, members)):
                raise UpdateError("The release zip is empty or has unsafe paths.")
            strip = 1 if all(len(p) > 1 and p[0] == parts[0][0] for p in parts) else 0
            if not any(len(p) == 1 + strip and p[-1] == binary_name for p in parts):
                raise UpdateError(f"The release zip doesn't contain {binary_name}.")
            for member, p in zip(members, parts):
                target = staging.joinpath(*p[strip:])
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                mode = (member.external_attr >> 16) & 0o777
                if os.name != "nt" and mode:
                    target.chmod(mode)
        if os.name != "nt":
            (staging / binary_name).chmod(0o755)
    except (zipfile.BadZipFile, OSError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError(f"Couldn't install the update: {exc}") from exc
    except UpdateError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return staging


def swap_script(install_dir: Path, staging: Path, binary_name: str, pid: int, relaunch: list[str] | None,
                windows: Optional[bool] = None) -> tuple[str, str]:
    """(file name, text) of the helper that waits for process `pid` to end, swaps `staging` into `install_dir`
    (the old folder is kept as "<install_dir>.old") and, when `relaunch` is given, starts the new binary with those
    arguments. If the swap fails the old folder is put back and started instead."""
    windows = os.name == "nt" if windows is None else windows
    old = _sibling(install_dir, OLD_SUFFIX)
    if windows:
        quote = lambda path: f'"{path}"'
        args = " ".join(f'"{a}"' for a in relaunch or [])
        # Started from its own folder, as Explorer starts it: the next update's helper must not inherit it.
        start = (f'cd /d {quote(install_dir)}\r\nstart "" {quote(install_dir / binary_name)} {args}\r\n'
                 if relaunch is not None else "")
        text = (
            "@echo off\r\n"
            f":wait\r\ntasklist /FI \"PID eq {pid}\" 2>NUL | find \"{pid}\" >NUL\r\n"
            "if not errorlevel 1 (\r\n  ping -n 2 127.0.0.1 >NUL\r\n  goto wait\r\n)\r\n"
            f"set tries=0\r\n:swap\r\nif exist {quote(old)} rmdir /s /q {quote(old)}\r\n"
            f"move {quote(install_dir)} {quote(old)} >NUL 2>&1\r\n"
            # No ( ) block here: cmd expands %tries% in a block once, when it reads it, so the limit never applied.
            "if not errorlevel 1 goto moved\r\n"
            "set /a tries+=1\r\nif %tries% GEQ 20 goto launch\r\nping -n 3 127.0.0.1 >NUL\r\ngoto swap\r\n"
            ":moved\r\n"
            f"move {quote(staging)} {quote(install_dir)} >NUL 2>&1\r\n"
            f"if errorlevel 1 move {quote(old)} {quote(install_dir)} >NUL 2>&1\r\n"
            f":launch\r\n{start}"
            "(goto) 2>NUL & del \"%~f0\"\r\n"
        )
        return "slidemage-swap.cmd", text
    q = lambda path: "'" + str(path).replace("'", "'\\''") + "'"
    start = f"{q(install_dir / binary_name)} {' '.join(q(a) for a in relaunch)} >/dev/null 2>&1 &\n" if relaunch is not None else ""
    text = (
        "#!/bin/sh\n"
        f"while kill -0 {pid} 2>/dev/null; do sleep 1; done\n"
        f"rm -rf {q(old)}\n"
        f"if mv {q(install_dir)} {q(old)}; then\n"
        f"  mv {q(staging)} {q(install_dir)} || mv {q(old)} {q(install_dir)}\n"
        "fi\n"
        f"{start}"
        "rm -f \"$0\"\n"
    )
    return "slidemage-swap.sh", text


def spawn_folder_swap(install_dir: Path, staging: Path, binary_name: str, relaunch: list[str] | None = None) -> None:
    """Start the detached helper (swap_script) that puts the staged update in place once this process has ended and
    then starts it again with `relaunch` (None: no restart, the new version is there at the next start)."""
    name, text = swap_script(install_dir, staging, binary_name, os.getpid(), relaunch)
    script = Path(tempfile.mkdtemp(prefix="slidemage-swap-")) / name
    try:
        script.write_text(text, encoding="utf-8", newline="")
        start_helper(script)
    except OSError as exc:
        raise UpdateError(f"Couldn't start the update helper: {exc}") from exc


def start_helper(script: Path) -> subprocess.Popen:
    """Start the swap helper `script` so that it outlives this process.

    On Windows it gets a console of its own that is never shown, and NUL as its input and output. A detached cmd
    (DETACHED_PROCESS, no console) with the windowed app's missing handles ended at once with exit code 1, before
    it swapped anything, and each console program it ran (tasklist, ping) flashed a window of its own.

    It runs in the script's own folder. Started from Explorer, the app's working folder is the installation, and a
    helper that inherited it could never move that folder (v8.39.2 to v8.51.0: every try failed and the old version
    started again)."""
    env = {**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"}
    quiet = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, env=env,
                 cwd=str(script.parent))
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        return subprocess.Popen(["cmd", "/c", str(script)], creationflags=flags, **quiet)
    script.chmod(0o755)
    return subprocess.Popen(["/bin/sh", str(script)], start_new_session=True, **quiet)


# The uninstall entry SlideMage-Setup.exe writes (packaging/slidemage.iss, AppId; Inno Setup appends "_is1").
SETUP_UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{6F2B8C41-3D7A-4E59-9B1C-5A0E7D2F4C83}_is1"


def sync_setup_version(install_dir: Path, version: str) -> bool:
    """Windows, a folder installed by SlideMage-Setup.exe: write `version` (VERSION_NUMBER, without its "v") as the
    version "Installed apps" shows, which the setup wrote for the version it installed and a self-update would
    otherwise leave behind. Only for the entry whose InstallLocation is `install_dir`. True when it was changed."""
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, SETUP_UNINSTALL_KEY, 0,
                            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as key:
            location, _kind = winreg.QueryValueEx(key, "InstallLocation")
            if Path(str(location)).resolve() != Path(install_dir).resolve():
                return False
            shown = version.removeprefix("v")
            try:
                current, _kind = winreg.QueryValueEx(key, "DisplayVersion")
            except OSError:
                current = None
            if current == shown:
                return False
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, shown)
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "SlideMage")
            return True
    except OSError:
        return False


def remove_leftover_folder(install_dir: Path) -> list[Path]:
    """Delete the "<folder>.old" a previous folder update left behind, unless it holds projects (an update by a
    SlideMage without the check in stage_folder_update moved them there, issue #85): then it is kept, and the
    projects are returned so the user can be told where they are."""
    old = _sibling(install_dir, OLD_SUFFIX)
    held = projects_in(old)
    if held:
        _log.warning("Kept %s: it holds the projects %s", old, ", ".join(map(str, held)))
    else:
        shutil.rmtree(old, ignore_errors=True)
    return held
