# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Install and remove plugins from a zip archive. No Qt, standard library only.

A plugin runs in-process with the user's rights, so nothing here is trusted. What is checked, and why:

- The SHA-256, when the caller has one (the catalogue pins a hash per release): a download that differs from what
  the catalogue promised is refused before anything is written.
- Every zip member: no absolute paths, drive letters, "..", backslashes (zip-slip), no symlinks, no compiled files
  (.pyc .pyo .so .pyd .dll .dylib .exe: they cannot be reviewed, and in the frozen build they cannot load anyway),
  and caps on member count and sizes (zip bombs). Nothing is extracted until all members pass.
- The unpacked plugin.toml (manifest rules), the package folder named after the id, the api_version this
  SlideMage supports and requires_slidemage against the running version.

The archive is unpacked into plugins/.staging/ and checked before publication. Updates and removals are staged
in plugins/.pending/<id>/ until cleanup() at the next start, before loading any plugin. The running plugin
keeps its original import and resource paths. Failed publication restores the previous pending operation.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import stat
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from http.client import HTTPException
from pathlib import Path, PurePosixPath

from ..plugin_api import SUPPORTED_API_VERSIONS
from ..version import VERSION_NUMBER
from .loader import plugins_dir
from .manifest import MANIFEST_NAME, Manifest, ManifestError, matches, package_name, read_manifest, valid_id

log = logging.getLogger(__name__)

FORBIDDEN_SUFFIXES = frozenset({".pyc", ".pyo", ".so", ".pyd", ".dll", ".dylib", ".exe"})
MAX_MEMBERS = 2000
MAX_TOTAL_BYTES = 50 * 1024 * 1024
MAX_MEMBER_BYTES = 20 * 1024 * 1024

MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
USER_AGENT = "SlideMage-updater"

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_changed: set[str] = set()


class InstallError(Exception):
    """Installing or removing failed; the message is written for the user."""


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_sha256_file(path: Path) -> str | None:
    """The hash in a `sha256sum`-style file ("<64 hex>  <name>"), lowercase; None if missing or malformed."""
    try:
        words = Path(path).read_text(encoding="utf-8").split()
    except (OSError, UnicodeDecodeError):
        return None
    if not words:
        return None
    word = words[0].lower()
    return word if _SHA_RE.match(word) else None


def download(url: str, dest: Path, *, expected_size: int | None = None, timeout: float = 30,
             max_bytes: int = MAX_DOWNLOAD_BYTES) -> None:
    """Stream `url` (http or https only: urlopen would also read file: addresses) into `dest`. Stops at `max_bytes`
    and, with `expected_size`, refuses a download of another size: the catalogue states each release's size. Raises
    InstallError; `dest` is deleted on any failure. Blocking: call it from a worker thread."""
    if not re.match(r"^https?://", url):
        raise InstallError("The download address is not an http(s) address.")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    done = 0
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, open(dest, "wb") as out:
            declared = int(response.headers.get("Content-Length") or 0)
            if declared > max_bytes:
                raise InstallError("The download is too large.")
            while chunk := response.read(256 * 1024):
                done += len(chunk)
                if done > max_bytes:
                    raise InstallError("The download is too large.")
                out.write(chunk)
        if expected_size is not None and done != expected_size:
            raise InstallError("The download is not the size the plugin list promised; nothing was installed.")
    except InstallError:
        dest.unlink(missing_ok=True)
        raise
    except (urllib.error.URLError, HTTPException, OSError, ValueError) as e:
        dest.unlink(missing_ok=True)
        raise InstallError(f"The download failed: {e}") from None


def peek(archive: Path) -> Manifest:
    """The checked manifest of `archive`, read without unpacking anything else (the Extensions tab shows it before
    it asks whether to install a file that is not from the catalogue). Raises InstallError."""
    try:
        with zipfile.ZipFile(archive) as zf:
            info = next((i for i in zf.infolist() if i.filename == MANIFEST_NAME), None)
            if info is None:
                raise InstallError(f"The archive has no {MANIFEST_NAME} at its top level.")
            if info.file_size > MAX_MANIFEST_BYTES:
                raise InstallError(f"The {MANIFEST_NAME} is too large.")
            data = zf.read(info)
    except zipfile.BadZipFile:
        raise InstallError("The file is not a valid zip archive.") from None
    except OSError as e:
        raise InstallError(f"The archive cannot be read: {e}") from None
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / MANIFEST_NAME).write_bytes(data)
        try:
            return read_manifest(Path(tmp))
        except ManifestError as e:
            raise InstallError(f"The plugin's {MANIFEST_NAME} is not valid: {e}") from None


def mark_changed(plugin_id: str) -> None:
    """Record that a plugin was installed, removed, enabled or disabled in this session."""
    _changed.add(plugin_id)


def changed_ids() -> frozenset[str]:
    return frozenset(_changed)


def pending_restart() -> bool:
    return bool(_changed)


def _check_member(info: zipfile.ZipInfo) -> None:
    name = info.filename
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or name.startswith("/")
        or re.match(r"^[A-Za-z]:", name)
        or ".." in path.parts
        or "\x00" in name
    ):
        raise InstallError(f"The archive contains an unsafe path: {name!r}.")
    if stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK:
        raise InstallError(f"The archive contains a symbolic link: {name!r}.")
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise InstallError(f"The archive contains a compiled file, which is not allowed: {name!r}.")
    if info.file_size > MAX_MEMBER_BYTES:
        raise InstallError(f"The archive contains a file that is too large: {name!r}.")


def extract(zf: zipfile.ZipFile, target: Path, manifest_name: str = MANIFEST_NAME) -> None:
    """Check every member of `zf` (the rules above) and unpack it into `target`; `manifest_name` must be at the top
    level (plugin.toml, or a theme package's theme.toml: themes.py). Raises InstallError."""
    infos = zf.infolist()
    if len(infos) > MAX_MEMBERS:
        raise InstallError(f"The archive has too many files ({len(infos)}, at most {MAX_MEMBERS}).")
    total = 0
    for info in infos:
        _check_member(info)
        total += info.file_size
    if total > MAX_TOTAL_BYTES:
        raise InstallError("The archive is too large when unpacked.")
    if manifest_name not in {i.filename for i in infos}:
        raise InstallError(f"The archive has no {manifest_name} at its top level.")
    root = target.resolve()
    for info in infos:
        dest = (target / info.filename).resolve()
        if dest != root and root not in dest.parents:
            raise InstallError(f"The archive contains an unsafe path: {info.filename!r}.")
        if info.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with zf.open(info) as src, open(dest, "wb") as out:
            for chunk in iter(lambda: src.read(1 << 16), b""):
                written += len(chunk)
                if written > MAX_MEMBER_BYTES:
                    raise InstallError(f"The archive contains a file that is too large: {info.filename!r}.")
                out.write(chunk)


def _check_plugin(folder: Path, app_version: str) -> Manifest:
    try:
        manifest = read_manifest(folder)
    except ManifestError as e:
        raise InstallError(f"The plugin's {MANIFEST_NAME} is not valid: {e}") from None
    if not (folder / package_name(manifest.id) / "__init__.py").is_file():
        raise InstallError(f"The plugin has no package folder {package_name(manifest.id)}/ with an __init__.py.")
    if manifest.api_version not in SUPPORTED_API_VERSIONS:
        raise InstallError(
            f"The plugin uses plugin interface {manifest.api_version}, which this SlideMage does not support."
        )
    try:
        ok = matches(manifest.requires_slidemage, app_version)
    except ValueError as e:
        raise InstallError(f"Cannot compare SlideMage versions: {e}") from None
    if not ok:
        raise InstallError(f"The plugin needs SlideMage {manifest.requires_slidemage}; this is {app_version}.")
    return manifest


def _old_target(plugin_id: str) -> Path:
    return plugins_dir() / ".old" / f"{plugin_id}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def install(archive: Path, *, expected_sha256: str | None = None, app_version: str = VERSION_NUMBER) -> Manifest:
    """Check and install a new plugin, or stage an update for the next start. Raises InstallError."""
    archive = Path(archive)
    if expected_sha256 is not None:
        try:
            actual = sha256_of(archive)
        except OSError as e:
            raise InstallError(f"The archive cannot be read: {e}") from None
        if actual != expected_sha256.strip().lower():
            raise InstallError("The download does not match its checksum (SHA-256); nothing was installed.")
    staging = plugins_dir() / ".staging" / uuid.uuid4().hex
    old: Path | None = None
    final: Path | None = None
    try:
        try:
            staging.mkdir(parents=True)
            with zipfile.ZipFile(archive) as zf:
                extract(zf, staging)
        except zipfile.BadZipFile:
            raise InstallError("The file is not a valid zip archive.") from None
        except OSError as e:
            raise InstallError(f"The archive could not be unpacked: {e}") from None
        manifest = _check_plugin(staging, app_version)
        installed = plugins_dir() / manifest.id
        final = plugins_dir() / ".pending" / manifest.id if installed.exists() else installed
        try:
            final.parent.mkdir(parents=True, exist_ok=True)
            if final.exists():
                old = _old_target(manifest.id)
                old.parent.mkdir(parents=True, exist_ok=True)
                os.replace(final, old)
            os.replace(staging, final)
        except OSError as e:
            if old is not None and old.exists() and not final.exists():
                try:
                    os.replace(old, final)
                except OSError:
                    log.exception("Could not restore %s", final)
            raise InstallError(f"The plugin could not be put in place: {e}") from None
        mark_changed(manifest.id)
        return manifest
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        try:
            (plugins_dir() / ".staging").rmdir()
        except OSError:
            pass


def _pending(plugin_id: str) -> Path:
    return plugins_dir() / ".pending" / plugin_id


def row_state(plugin_id: str, current: tuple[str, str, str]) -> tuple[str, str, str]:
    """The Extensions tab reflects a queued operation while the live folder stays intact."""
    pending = _pending(plugin_id)
    if (pending / ".remove").is_file():
        return "Removed after a restart", "info", ""
    if (pending / MANIFEST_NAME).is_file():
        return "Installed; it starts after a restart", "info", ""
    return current


def remove(plugin_id: str) -> None:
    """Stage removal for the next start, preserving every live import and resource path."""
    folder = plugins_dir() / plugin_id
    if not valid_id(plugin_id) or not folder.is_dir():
        raise InstallError(f"The plugin {plugin_id!r} is not installed.")
    staging = plugins_dir() / ".staging" / uuid.uuid4().hex
    target = _pending(plugin_id)
    old = None
    try:
        staging.mkdir(parents=True)
        (staging / ".remove").touch()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            old = _old_target(plugin_id)
            old.parent.mkdir(parents=True, exist_ok=True)
            os.replace(target, old)
        os.replace(staging, target)
    except OSError as e:
        if old is not None and old.exists() and not target.exists():
            os.replace(old, target)
        raise InstallError(f"The plugin could not be removed: {e}") from None
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    mark_changed(plugin_id)


def apply_pending() -> bool:
    """Apply queued changes before loading plugins at startup. Keep failed changes for another start."""
    pending = plugins_dir() / ".pending"
    if not pending.is_dir():
        return True
    ok = True
    for staged in sorted(pending.iterdir()):
        old = None
        final = plugins_dir() / staged.name
        try:
            if not valid_id(staged.name):
                raise InstallError("The pending plugin has an invalid or reserved id.")
            removing = (staged / ".remove").is_file()
            if not removing:
                manifest = _check_plugin(staged, VERSION_NUMBER)
                if manifest.id != staged.name:
                    raise InstallError("The pending plugin id does not match its folder.")
            if final.exists():
                old = _old_target(staged.name)
                old.parent.mkdir(parents=True, exist_ok=True)
                os.replace(final, old)
            if removing:
                shutil.rmtree(staged)
            else:
                os.replace(staged, final)
        except Exception:
            ok = False
            log.exception("Could not apply pending plugin change %s", staged.name)
            if old is not None and old.exists() and not final.exists():
                try:
                    os.replace(old, final)
                except OSError:
                    log.exception("Could not restore %s", final)
    try:
        pending.rmdir()
    except OSError:
        pass
    return ok


def cleanup() -> None:
    """Delete leftovers of earlier installs (.staging/, .old/). Never raises."""
    try:
        if not apply_pending():
            return   # retain backups if restoring a failed change also failed
        base = plugins_dir()
        for name in (".staging", ".old"):
            path = base / name
            if path.exists():
                shutil.rmtree(path, onerror=lambda _f, p, _e: log.warning("Could not delete %s", p))
    except Exception:
        log.exception("Plugin cleanup failed")
