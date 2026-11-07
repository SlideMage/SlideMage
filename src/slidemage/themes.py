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
import re
import tomllib
from dataclasses import dataclass
from functools import partial
from pathlib import Path, PurePosixPath

from . import packages, project
from .packages import os as os, shutil as shutil, uuid as uuid, zipfile as zipfile
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
BUNDLED_PROFILES = ("fira", "lmsans", "lmroman")


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
            raise ManifestError('requires_slidemage must look like ">=0.10.16" or ">=0.10.16, <0.12"')
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


# -- the package rules

def check_names(names: list[str], manifest: ThemeManifest) -> None:
    """The package's file names (POSIX, relative to its top, folders ending in /) hold the template and the required
    files and nothing that is not the theme's own. Raises ThemeError."""
    files = {n for n in names if not n.endswith("/")}
    own_layout = f"{LAYOUT_PREFIX}{manifest.layout}.tex"
    if manifest.layout in BUNDLED_PROFILES and own_layout in files:
        # An installed theme is on TEXINPUTS ahead of the framework: its copy would replace the bundled profile
        # for every deck using it, not just the theme's own template.
        raise ThemeError(f"The theme ships its own copy of SlideMage's layout profile {manifest.layout} "
                         f"({own_layout}); a theme may ship a layout profile only under a name of its own.")
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


# Keep the public package API here; callers and package tools need no knowledge of the shared store.
KIND = packages.PackageKind(
    name="theme", folder=lambda: themes_dir(), manifest_name=MANIFEST_NAME, suffix=PACKAGE_SUFFIX,
    error=ThemeError, parse_manifest=lambda text: parse_manifest(text),
    check_names=lambda names, manifest: check_names(names, manifest),
    check_manifest=lambda manifest, app_version: check_manifest(manifest, app_version),
    key_re=KEY_RE, tex_file=template_file, contents_name="theme")

InstalledTheme = packages.InstalledPackage
read_manifest = partial(packages.read_manifest, KIND)
folder_names = partial(packages.folder_names, KIND)
check_folder = partial(packages.check_folder, KIND)
package_name = partial(packages.package_name, KIND)
peek = partial(packages.peek, KIND)
installed = partial(packages.installed, KIND)
installed_dirs = partial(packages.installed_dirs, KIND)
texinputs = partial(packages.texinputs, KIND)
theme_of = partial(packages.owner_of, KIND)
install_file = partial(packages.install_file, KIND)
remove = partial(packages.remove, KIND)
cleanup = partial(packages.cleanup, KIND)
