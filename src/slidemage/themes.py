# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Theme packages (docs/THEME_PACKAGE.md): a template packaged on its own, installed in config_dir()/themes/<key>/.

A catalogue "theme" is what the framework calls a template (SlideMage_template_<key>.tex, its schemes/scheme_<key>/
folder and at most its own layout profile file), never the beamer theme beamerthemeSlideMage.sty, which is
framework. A theme runs no Python, so its manifest theme.toml has no api_version, needs or network.

* Discovery: installed_dirs() are the theme folders on this computer; compiler.build_env puts them on TEXINPUTS
  (texinputs()) for every compile and preview, after the project root and the framework, so a project's own copy
  of the same key wins, then the installed theme, and the bundled templates never lose to a theme (a theme cannot
  take a bundled key). slide_snapshot lists their templates beside the project's and the framework's.
* Checks: check_folder() is what install_file() and tools/make_theme_package.py run: a valid theme.toml, its
  requires_slidemage met, the template file there, nothing but the package's own files (no TeX code besides the
  template and its layout profile, which would be found on TEXINPUTS ahead of the TeX distribution), and a key that
  does not shadow a bundled template. The archive members pass the plugin installer's zip checks first.
* Install and remove take effect at once: nothing of a theme stays loaded between compiles.

No Qt, standard library only.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import tomllib
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from . import project
from .plugins import installer
from .plugins.manifest import REQUIRES_RE, VERSION_RE, ManifestError, _text, matches
from .version import VERSION_NUMBER

log = logging.getLogger(__name__)

MANIFEST_NAME = "theme.toml"
PACKAGE_SUFFIX = ".smtheme"
TEMPLATE_PREFIX = "SlideMage_template_"
LAYOUT_PREFIX = "SlideMage_layout_"
KEY_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
LAYOUT_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
# The files a package holds besides its template, scheme folder and layout profile.
REQUIRED_FILES = ("README.md", "CHANGELOG.md", "LICENSE")
OPTIONAL_FILES = ("preview.png",)
OPTIONAL_DIRS = ("LICENSES",)       # REUSE-style licence texts
# TeX finds these on TEXINPUTS; only the template and the layout profile may be one.
TEX_CODE_SUFFIXES = frozenset({".tex", ".sty", ".cls", ".lua", ".def", ".cfg", ".fd", ".clo", ".ltx", ".dtx", ".ins"})
BUNDLED_PROFILES = ("fira", "lmsans")


class ThemeError(Exception):
    """A theme package or folder breaks a rule, or installing/removing failed; the message is for the user."""


@dataclass(frozen=True)
class ThemeManifest:
    id: str
    name: str
    version: str
    requires_slidemage: str
    summary: str
    author: str
    homepage: str
    license: str
    layout: str

    @property
    def template_file(self) -> str:
        return template_file(self.id)

    @property
    def scheme_dir(self) -> str:
        return scheme_dir(self.id)


@dataclass(frozen=True)
class InstalledTheme:
    key: str
    folder: Path
    manifest: ThemeManifest | None      # None: theme.toml unreadable (the folder is still listed, to be removed)
    problem: str = ""


def template_file(key: str) -> str:
    return f"{TEMPLATE_PREFIX}{key}.tex"


def scheme_dir(key: str) -> str:
    """The scheme folder's name: schemes/scheme_<key> with the key's hyphens as underscores (scheme_uni_graz)."""
    return f"scheme_{key.replace('-', '_')}"


def themes_dir() -> Path:
    return project.config_dir() / "themes"


def bundled_keys() -> frozenset[str]:
    """The keys of the templates SlideMage itself ships (latex/), which a theme may not take."""
    keys = {"slidemage"}
    latex = project.template_dir("latex")
    if latex is not None:
        keys |= {path.stem[len(TEMPLATE_PREFIX):] for path in latex.glob(f"{TEMPLATE_PREFIX}*.tex")}
    return frozenset(keys)


# -- theme.toml

def parse_manifest(text: str) -> ThemeManifest:
    """The checked theme.toml text. Raises ThemeError."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ThemeError(f"{MANIFEST_NAME} is not valid TOML: {e}") from None
    try:
        key = _text(data, "id", 1)
        if not KEY_RE.match(key):
            raise ManifestError("id (the template key) must be 2 to 32 characters: a lowercase letter, then "
                                "lowercase letters, digits, -")
        version = _text(data, "version", 1)
        if not VERSION_RE.match(version):
            raise ManifestError("version must look like 1.2.3")
        requires = _text(data, "requires_slidemage", 1)
        if not REQUIRES_RE.match(requires):
            raise ManifestError('requires_slidemage must look like ">=10.16" or ">=10.16, <11"')
        homepage = _text(data, "homepage", 1)
        if not re.match(r"^https?://\S+$", homepage):
            raise ManifestError("homepage must be an http(s) address")
        layout = _text(data, "layout", 1)
        if not LAYOUT_RE.match(layout):
            raise ManifestError("layout must be a layout profile name: lowercase letters, digits, -")
        for unwanted in ("api_version", "needs", "network"):
            if unwanted in data:
                raise ManifestError(f"{unwanted} belongs to plugin.toml; a theme runs no Python")
        return ThemeManifest(
            id=key, name=_text(data, "name", 1, 40), version=version, requires_slidemage=requires,
            summary=_text(data, "summary", 1, 120), author=_text(data, "author", 1), homepage=homepage,
            license=_text(data, "license", 1), layout=layout)
    except ManifestError as e:
        raise ThemeError(f"{MANIFEST_NAME}: {e}") from None


def read_manifest(folder: Path) -> ThemeManifest:
    path = Path(folder) / MANIFEST_NAME
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ThemeError(f"There is no {MANIFEST_NAME} in {folder}.") from None
    except (OSError, UnicodeDecodeError) as e:
        raise ThemeError(f"{MANIFEST_NAME} cannot be read: {e}") from None
    return parse_manifest(text)


# -- the package rules

def check_names(names: list[str], manifest: ThemeManifest) -> None:
    """The package's file names (POSIX, relative to its top, folders ending in /) hold the template and the required
    files and nothing that is not the theme's own. Raises ThemeError."""
    files = {n for n in names if not n.endswith("/")}
    own_layout = f"{LAYOUT_PREFIX}{manifest.layout}.tex"
    allowed_top = {MANIFEST_NAME, manifest.template_file, own_layout, *REQUIRED_FILES, *OPTIONAL_FILES}
    for name in names:
        path = PurePosixPath(name.rstrip("/"))
        if not name or name.startswith("/") or "\\" in name or ".." in path.parts or re.match(r"^[A-Za-z]:", name):
            raise ThemeError(f"The theme contains a path outside the package: {name!r}.")
        top = path.parts[0]
        if len(path.parts) == 1 and not name.endswith("/"):
            if top not in allowed_top:
                raise ThemeError(f"The theme contains a file that is not part of a theme package: {name!r}.")
            continue
        if top == "schemes":
            if len(path.parts) >= 2 and path.parts[1] != manifest.scheme_dir:
                raise ThemeError(f"The theme's scheme folder must be schemes/{manifest.scheme_dir}/, "
                                 f"not {'/'.join(path.parts[:2])}/.")
            if path.suffix.lower() in TEX_CODE_SUFFIXES and not name.endswith("/"):
                raise ThemeError(f"The theme contains TeX code besides its template and layout profile: {name!r}.")
        elif top not in OPTIONAL_DIRS:
            raise ThemeError(f"The theme contains a folder that is not part of a theme package: {top}/.")
        elif path.suffix.lower() in TEX_CODE_SUFFIXES and not name.endswith("/"):
            raise ThemeError(f"The theme contains TeX code besides its template and layout profile: {name!r}.")
        if path.suffix.lower() in installer.FORBIDDEN_SUFFIXES:
            raise ThemeError(f"The theme contains a compiled file, which is not allowed: {name!r}.")
    for required in (manifest.template_file, *REQUIRED_FILES):
        if required not in files:
            raise ThemeError(f"The theme has no {required}.")
    if manifest.layout not in BUNDLED_PROFILES and own_layout not in files:
        raise ThemeError(f"The theme names the layout profile {manifest.layout!r}, which is neither SlideMage's "
                         f"({', '.join(BUNDLED_PROFILES)}) nor its own {own_layout}.")


def check_manifest(manifest: ThemeManifest, app_version: str = VERSION_NUMBER) -> None:
    """The rules that depend on this SlideMage: requires_slidemage, and a key no bundled template has."""
    if manifest.id in bundled_keys():
        raise ThemeError(f"The theme's key {manifest.id!r} is the key of a template SlideMage ships; "
                         "a theme cannot replace it.")
    try:
        ok = matches(manifest.requires_slidemage, app_version)
    except ValueError as e:
        raise ThemeError(f"Cannot compare SlideMage versions: {e}") from None
    if not ok:
        raise ThemeError(f"The theme needs SlideMage {manifest.requires_slidemage}; this is {app_version}.")


def folder_names(folder: Path, skip_hidden: bool = False) -> list[str]:
    """The names check_names() takes, for the files under `folder`. `skip_hidden` leaves out what starts with a dot
    (.git/, .github/, .gitignore of a theme's repository: tools/make_theme_package.py does not pack them)."""
    names = []
    for path in sorted(Path(folder).rglob("*")):
        rel = path.relative_to(folder).as_posix()
        if skip_hidden and any(part.startswith(".") for part in PurePosixPath(rel).parts):
            continue
        if path.is_symlink():
            raise ThemeError(f"The theme contains a symbolic link: {rel!r}.")
        names.append(rel + "/" if path.is_dir() else rel)
    return names


def check_folder(folder: Path, app_version: str = VERSION_NUMBER, skip_hidden: bool = False) -> ThemeManifest:
    """Every package rule for the unpacked theme in `folder`. Raises ThemeError."""
    manifest = read_manifest(folder)
    check_names(folder_names(folder, skip_hidden), manifest)
    check_manifest(manifest, app_version)
    return manifest


def package_name(manifest: ThemeManifest) -> str:
    return f"{manifest.id}-{manifest.version}{PACKAGE_SUFFIX}"


def peek(archive: Path) -> ThemeManifest:
    """The checked theme.toml of a .smtheme, read without unpacking it. Raises ThemeError."""
    try:
        with zipfile.ZipFile(archive) as zf:
            info = next((i for i in zf.infolist() if i.filename == MANIFEST_NAME), None)
            if info is None:
                raise ThemeError(f"The archive has no {MANIFEST_NAME} at its top level.")
            if info.file_size > installer.MAX_MANIFEST_BYTES:
                raise ThemeError(f"The {MANIFEST_NAME} is too large.")
            data = zf.read(info)
    except zipfile.BadZipFile:
        raise ThemeError("The file is not a valid zip archive.") from None
    except OSError as e:
        raise ThemeError(f"The archive cannot be read: {e}") from None
    try:
        return parse_manifest(data.decode("utf-8"))
    except UnicodeDecodeError:
        raise ThemeError(f"{MANIFEST_NAME} is not UTF-8 text.") from None


# -- installed themes

def installed() -> list[InstalledTheme]:
    """Every theme folder in themes_dir(), by key; one with a broken theme.toml has its problem set."""
    base = themes_dir()
    try:
        folders = sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        return []
    themes = []
    for folder in folders:
        try:
            manifest = read_manifest(folder)
        except ThemeError as e:
            themes.append(InstalledTheme(folder.name, folder, None, str(e)))
            continue
        problem = "" if manifest.id == folder.name else f"its {MANIFEST_NAME} names the key {manifest.id!r}"
        themes.append(InstalledTheme(folder.name, folder, manifest, problem))
    return themes


def installed_dirs() -> list[Path]:
    """The installed theme folders TeX searches: those holding their own key's template file. Cheap (one directory
    listing and a stat per theme): every compile and preview asks."""
    base = themes_dir()
    try:
        folders = sorted(p for p in base.iterdir() if not p.name.startswith(".") and KEY_RE.match(p.name))
    except OSError:
        return []
    return [folder for folder in folders if (folder / template_file(folder.name)).is_file()]


def texinputs(env: dict | None = None) -> str | None:
    """The TEXINPUTS a compile gets: the installed theme folders, then what `env` had (or nothing: the trailing
    separator keeps the TeX distribution's own search path). None when no theme is installed, so the
    environment stays as it was. The project's .latexmkrc puts the project root and the framework in front."""
    dirs = installed_dirs()
    if not dirs:
        return None
    rest = (env or {}).get("TEXINPUTS", "")
    return os.pathsep.join([*(str(d) for d in dirs), rest])


def theme_of(path: Path) -> Path | None:
    """The installed theme folder `path` lies in, or None."""
    try:
        resolved = Path(path).resolve()
    except OSError:
        return None
    for folder in installed_dirs():
        root = folder.resolve()
        if resolved == root or root in resolved.parents:
            return folder
    return None


# -- install and remove

def install_file(archive: Path, *, expected_sha256: str | None = None,
                 app_version: str = VERSION_NUMBER) -> ThemeManifest:
    """Check the .smtheme `archive` and install it unpacked in themes_dir()/<key>/, replacing an installed version of
    the same key. Raises ThemeError; nothing is changed then."""
    archive = Path(archive)
    if expected_sha256 is not None:
        try:
            actual = installer.sha256_of(archive)
        except OSError as e:
            raise ThemeError(f"The archive cannot be read: {e}") from None
        if actual != expected_sha256.strip().lower():
            raise ThemeError("The theme does not match its checksum (SHA-256); nothing was installed.")
    base = themes_dir()
    staging = base / ".staging" / uuid.uuid4().hex
    old: Path | None = None
    try:
        try:
            staging.mkdir(parents=True)
            with zipfile.ZipFile(archive) as zf:
                installer.extract(zf, staging, MANIFEST_NAME)
        except installer.InstallError as e:
            raise ThemeError(str(e)) from None
        except zipfile.BadZipFile:
            raise ThemeError("The file is not a valid zip archive.") from None
        except OSError as e:
            raise ThemeError(f"The archive could not be unpacked: {e}") from None
        manifest = check_folder(staging, app_version)
        final = base / manifest.id
        try:
            if final.exists():
                old = base / ".old" / f"{manifest.id}-{uuid.uuid4().hex[:8]}"
                old.parent.mkdir(parents=True, exist_ok=True)
                os.replace(final, old)
            os.replace(staging, final)
        except OSError as e:
            if old is not None and old.exists() and not final.exists():
                try:
                    os.replace(old, final)
                except OSError:
                    log.exception("Could not restore %s", final)
            raise ThemeError(f"The theme could not be put in place (is a compile using it?): {e}") from None
        return manifest
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        cleanup()


def remove(key: str) -> None:
    """Delete the installed theme `key`. Raises ThemeError."""
    folder = themes_dir() / key
    if not KEY_RE.match(key) or not folder.is_dir():
        raise ThemeError(f"The theme {key!r} is not installed.")
    old = themes_dir() / ".old" / f"{key}-{uuid.uuid4().hex[:8]}"
    try:
        old.parent.mkdir(parents=True, exist_ok=True)
        os.replace(folder, old)
    except OSError as e:
        raise ThemeError(f"The theme could not be removed (is a compile using it?): {e}") from None
    cleanup()


def cleanup() -> None:
    """Delete leftovers of earlier installs (.staging/, .old/). Never raises."""
    for name in (".staging", ".old"):
        path = themes_dir() / name
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
