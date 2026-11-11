# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Installed TeX packages: shared discovery, validation and stage-and-swap installation.

Themes and citation formats keep their own manifest and file rules. PackageKind supplies those rules and the
nouns in existing messages, so both public modules can delegate here without changing what callers or users see.
No Qt, standard library only.
"""
from __future__ import annotations

import os
import re
import shutil
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from .plugins import installer
from .version import VERSION_NUMBER


class PackageManifest(Protocol):
    id: str
    name: str
    version: str
    requires_slidemage: str
    summary: str
    author: str
    homepage: str
    license: str


@dataclass(frozen=True)
class PackageKind:
    name: str                         # theme / citation format (install/remove messages)
    folder: Callable[[], Path]
    manifest_name: str
    suffix: str
    error: type[Exception]
    parse_manifest: Callable[[str], PackageManifest]
    check_names: Callable[[list[str], PackageManifest], None]
    check_manifest: Callable[[PackageManifest, str], None]
    key_re: re.Pattern
    tex_file: Callable[[str], str]
    contents_name: str                # theme / package (file and checksum messages)
    # A rule on the files' contents that a newer SlideMage made (folder, key) -> problem, "" when fine: a package that
    # breaks it is not installed, not put on TeX's path and shown as needing an update.
    check_contents: Callable[[Path, str], str] | None = None


@dataclass(frozen=True)
class InstalledPackage:
    key: str
    folder: Path
    manifest: PackageManifest | None  # unreadable manifests stay listed, so the folder can still be removed
    problem: str = ""
    needs_update: bool = False        # the problem is one a newer version of the package fixes (check_contents)


def read_manifest(kind: PackageKind, folder: Path) -> PackageManifest:
    """Read the manifest with this kind's error type and rules."""
    path = Path(folder) / kind.manifest_name
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise kind.error(f"There is no {kind.manifest_name} in {folder}.") from None
    except (OSError, UnicodeDecodeError) as e:
        raise kind.error(f"{kind.manifest_name} cannot be read: {e}") from None
    return kind.parse_manifest(text)


def folder_names(kind: PackageKind, folder: Path, skip_hidden: bool = False) -> list[str]:
    """The POSIX names check_names() takes, with folders ending in /. `skip_hidden` leaves out repository
    metadata (.git/, .github/, .gitignore), which the package tools do not pack."""
    names = []
    for path in sorted(Path(folder).rglob("*")):
        rel = path.relative_to(folder).as_posix()
        if skip_hidden and any(part.startswith(".") for part in PurePosixPath(rel).parts):
            continue
        if path.is_symlink():
            raise kind.error(f"The {kind.contents_name} contains a symbolic link: {rel!r}.")
        names.append(rel + "/" if path.is_dir() else rel)
    return names


def check_folder(kind: PackageKind, folder: Path, app_version: str = VERSION_NUMBER,
                 skip_hidden: bool = False) -> PackageManifest:
    """Check all rules for an unpacked package; return its manifest."""
    manifest = read_manifest(kind, folder)
    kind.check_names(folder_names(kind, folder, skip_hidden), manifest)
    kind.check_manifest(manifest, app_version)
    if kind.check_contents is not None:
        problem = kind.check_contents(folder, manifest.id)
        if problem:
            raise kind.error(problem)
    return manifest


def package_name(kind: PackageKind, manifest: PackageManifest) -> str:
    return f"{manifest.id}-{manifest.version}{kind.suffix}"


def peek(kind: PackageKind, archive: Path) -> PackageManifest:
    """Read the checked manifest of an archive without unpacking it."""
    try:
        with zipfile.ZipFile(archive) as zf:
            info = next((i for i in zf.infolist() if i.filename == kind.manifest_name), None)
            if info is None:
                raise kind.error(f"The archive has no {kind.manifest_name} at its top level.")
            if info.file_size > installer.MAX_MANIFEST_BYTES:
                raise kind.error(f"The {kind.manifest_name} is too large.")
            data = zf.read(info)
    except zipfile.BadZipFile:
        raise kind.error("The file is not a valid zip archive.") from None
    except OSError as e:
        raise kind.error(f"The archive cannot be read: {e}") from None
    try:
        return kind.parse_manifest(data.decode("utf-8"))
    except UnicodeDecodeError:
        raise kind.error(f"{kind.manifest_name} is not UTF-8 text.") from None


def installed(kind: PackageKind) -> list[InstalledPackage]:
    """Every visible package folder by key, including broken manifests with their problem set."""
    base = kind.folder()
    try:
        folders = sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        return []
    found = []
    for folder in folders:
        try:
            manifest = read_manifest(kind, folder)
        except kind.error as e:
            found.append(InstalledPackage(folder.name, folder, None, str(e)))
            continue
        problem = "" if manifest.id == folder.name else f"its {kind.manifest_name} names the key {manifest.id!r}"
        outdated = "" if problem or kind.check_contents is None else kind.check_contents(folder, folder.name)
        found.append(InstalledPackage(folder.name, folder, manifest, problem or outdated, bool(outdated)))
    return found


def installed_dirs(kind: PackageKind) -> list[Path]:
    """The folders TeX searches: those holding their own key's TeX file. Cheap (one directory listing and a
    stat per package): every compile and preview asks."""
    base = kind.folder()
    try:
        folders = sorted(p for p in base.iterdir() if not p.name.startswith(".") and kind.key_re.match(p.name))
    except OSError:
        return []
    return [folder for folder in folders if (folder / kind.tex_file(folder.name)).is_file()
            and (kind.check_contents is None or not kind.check_contents(folder, folder.name))]


def texinputs(kind: PackageKind, env: dict | None = None) -> str | None:
    """Installed folders followed by the existing TEXINPUTS. The trailing separator keeps the TeX distribution's
    search path. None when no package is installed, so the environment stays as it was; the project's .latexmkrc
    puts the project root and framework in front."""
    dirs = installed_dirs(kind)
    if not dirs:
        return None
    rest = (env or {}).get("TEXINPUTS", "")
    return os.pathsep.join([*(str(d) for d in dirs), rest])


def owner_of(kind: PackageKind, path: Path) -> Path | None:
    """The installed package folder `path` lies in, or None."""
    try:
        resolved = Path(path).resolve()
    except OSError:
        return None
    for folder in installed_dirs(kind):
        root = folder.resolve()
        if resolved == root or root in resolved.parents:
            return folder
    return None


def install_file(kind: PackageKind, archive: Path, *, expected_sha256: str | None = None,
                 app_version: str = VERSION_NUMBER) -> PackageManifest:
    """Check and install an archive, replacing the same key. A failed swap restores the previous folder;
    validation failures leave the installed package untouched."""
    archive = Path(archive)
    if expected_sha256 is not None:
        try:
            actual = installer.sha256_of(archive)
        except OSError as e:
            raise kind.error(f"The archive cannot be read: {e}") from None
        if actual != expected_sha256.strip().lower():
            raise kind.error(f"The {kind.contents_name} does not match its checksum (SHA-256); nothing was installed.")
    base = kind.folder()
    staging = base / ".staging" / uuid.uuid4().hex
    try:
        try:
            staging.mkdir(parents=True)
            with zipfile.ZipFile(archive) as zf:
                installer.extract(zf, staging, kind.manifest_name)
        except installer.InstallError as e:
            raise kind.error(str(e)) from None
        except zipfile.BadZipFile:
            raise kind.error("The file is not a valid zip archive.") from None
        except OSError as e:
            raise kind.error(f"The archive could not be unpacked: {e}") from None
        manifest = check_folder(kind, staging, app_version)
        final = base / manifest.id
        try:
            old_dir = base / ".old" / f"{manifest.id}-{uuid.uuid4().hex[:8]}"
            installer.swap_into_place(staging, final, old_dir)
        except OSError as e:
            raise kind.error(f"The {kind.name} could not be put in place (is a compile using it?): {e}") from None
        return manifest
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        cleanup(kind)


def remove(kind: PackageKind, key: str) -> None:
    """Remove an installed package by key, with this kind's error messages."""
    folder = kind.folder() / key
    if not kind.key_re.match(key) or not folder.is_dir():
        raise kind.error(f"The {kind.name} {key!r} is not installed.")
    old = kind.folder() / ".old" / f"{key}-{uuid.uuid4().hex[:8]}"
    try:
        old.parent.mkdir(parents=True, exist_ok=True)
        os.replace(folder, old)
    except OSError as e:
        raise kind.error(f"The {kind.name} could not be removed (is a compile using it?): {e}") from None
    cleanup(kind)


def cleanup(kind: PackageKind) -> None:
    """Delete leftovers of earlier installs (.staging/, .old/). Never raises."""
    for name in (".staging", ".old"):
        path = kind.folder() / name
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
