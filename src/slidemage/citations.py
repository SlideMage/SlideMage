# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Citation format packages (docs/CITATION_PACKAGE.md): a citation format packaged on its own, installed in
config_dir()/citations/<key>/. The third category beside plugins and themes (themes.py, which this mirrors).

A citation format is the file SlideMage_citation_<key>.tex: it redefines \\SMBiblatexOptions and
\\SMBibliographyStyle (the house format, latex/SlideMage_citation_default.tex, is the model). The catalog's
\\SMCitationFormat names the one a template or deck uses; the base and \\SMUseBibliography load that file. A
package runs no Python, so its manifest citation.toml has no api_version, needs or network.

* Discovery: citation_dirs() are the installed format folders on this computer; texinputs() puts them on TEXINPUTS
  (compiler.build_env) after the project root and the framework, so a project's own copy of a format file wins,
  then the installed package, and the bundled format (default) never loses to a package (a package cannot take a
  bundled key).
* Checks: check_folder() is what install_file() and tools/make_citation_package.py run: a valid citation.toml,
  its requires_slidemage met, the format file there, nothing but the package's own files (TeX code only as
  SlideMage_citation_<key>.tex and extra files named SlideMage_citation_<key>_*, which cannot shadow biblatex's own
  style files), and a key that does not shadow a bundled format. The archive members pass the plugin installer's
  zip checks first.
* Install and remove take effect at once: nothing of a package stays loaded between compiles.

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

MANIFEST_NAME = "citation.toml"
PACKAGE_SUFFIX = ".smcite"
FORMAT_PREFIX = "SlideMage_citation_"
KEY_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
REQUIRED_FILES = ("README.md", "CHANGELOG.md", "LICENSE")
OPTIONAL_FILES = ("preview.png",)
OPTIONAL_DIRS = ("LICENSES",)       # REUSE-style licence texts
# Extra TeX files of a format (biblatex style files it loads): named after the format, never a stock style's name.
EXTRA_SUFFIXES = frozenset({".tex", ".bbx", ".cbx", ".dbx", ".lbx"})
TEX_CODE_SUFFIXES = frozenset({".tex", ".sty", ".cls", ".lua", ".def", ".cfg", ".fd", ".clo", ".ltx", ".dtx", ".ins",
                               ".bbx", ".cbx", ".dbx", ".lbx", ".bst"})


class CitationError(Exception):
    """A citation package or folder breaks a rule, or installing/removing failed; the message is for the user."""


@dataclass(frozen=True)
class CitationManifest:
    id: str
    name: str
    version: str
    requires_slidemage: str
    summary: str
    author: str
    homepage: str
    license: str

    @property
    def format_file(self) -> str:
        return format_file(self.id)


def format_file(key: str) -> str:
    return f"{FORMAT_PREFIX}{key}.tex"


def citations_dir() -> Path:
    return project.config_dir() / "citations"


def bundled_keys() -> frozenset[str]:
    """The keys of the citation formats SlideMage itself ships (latex/), which a package may not take."""
    keys = {"default"}
    latex = project.template_dir("latex")
    if latex is not None:
        keys |= {path.stem[len(FORMAT_PREFIX):] for path in latex.glob(f"{FORMAT_PREFIX}*.tex")}
    return frozenset(keys)


# -- citation.toml

def parse_manifest(text: str) -> CitationManifest:
    """The checked citation.toml text. Raises CitationError."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise CitationError(f"{MANIFEST_NAME} is not valid TOML: {e}") from None
    try:
        key = _text(data, "id", 1)
        if not KEY_RE.match(key):
            raise ManifestError("id (the citation format's key) must be 2 to 32 characters: a lowercase letter, "
                                "then lowercase letters, digits, -")
        version = _text(data, "version", 1)
        if not VERSION_RE.match(version):
            raise ManifestError("version must look like 1.2.3")
        requires = _text(data, "requires_slidemage", 1)
        if not REQUIRES_RE.match(requires):
            raise ManifestError('requires_slidemage must look like ">=0.13.0" or ">=0.13.0, <0.15"')
        homepage = _text(data, "homepage", 1)
        if not re.match(r"^https?://\S+$", homepage):
            raise ManifestError("homepage must be an http(s) address")
        for unwanted in ("api_version", "needs", "network", "layout"):
            if unwanted in data:
                raise ManifestError(f"{unwanted} does not belong in a citation package "
                                    "(it runs no Python and has no layout)")
        return CitationManifest(
            id=key, name=_text(data, "name", 1, 40), version=version, requires_slidemage=requires,
            summary=_text(data, "summary", 1, 120), author=_text(data, "author", 1), homepage=homepage,
            license=_text(data, "license", 1))
    except ManifestError as e:
        raise CitationError(f"{MANIFEST_NAME}: {e}") from None


# -- the package rules

def _is_extra(name: str, key: str) -> bool:
    path = PurePosixPath(name)
    return (path.name.startswith(f"{FORMAT_PREFIX}{key}_") and path.suffix.lower() in EXTRA_SUFFIXES
            and path.stem != f"{FORMAT_PREFIX}{key}_")


def check_names(names: list[str], manifest: CitationManifest) -> None:
    """The package's file names (POSIX, relative to its top, folders ending in /) hold the format file and the
    required files and nothing that is not the package's own. Raises CitationError."""
    files = {n for n in names if not n.endswith("/")}
    latex = project.template_dir("latex")
    shipped = ({p.name for p in latex.iterdir() if p.is_file()} - set(REQUIRED_FILES)
               if latex is not None else set())
    for name in sorted(files):
        if name in shipped or (name == format_file("default")):
            # Installed packages are on TEXINPUTS ahead of the framework: such a file would replace SlideMage's own.
            raise CitationError(f"The package contains a file named like one of SlideMage's own framework files, "
                                f"which it would replace for every deck: {name!r}.")
    allowed_top = {MANIFEST_NAME, manifest.format_file, *REQUIRED_FILES, *OPTIONAL_FILES}
    for name in names:
        path = PurePosixPath(name.rstrip("/"))
        if not name or name.startswith("/") or "\\" in name or ".." in path.parts or re.match(r"^[A-Za-z]:", name):
            raise CitationError(f"The package contains a path outside the package: {name!r}.")
        top = path.parts[0]
        if len(path.parts) == 1 and not name.endswith("/"):
            if top not in allowed_top and not _is_extra(top, manifest.id):
                raise CitationError(f"The package contains a file that is not part of a citation package "
                                    f"(extra TeX files are named {FORMAT_PREFIX}{manifest.id}_<name>): {name!r}.")
            continue
        if top not in OPTIONAL_DIRS:
            raise CitationError(f"The package contains a folder that is not part of a citation package: {top}/.")
        if path.suffix.lower() in TEX_CODE_SUFFIXES and not name.endswith("/"):
            raise CitationError(f"The package contains TeX code outside its format files: {name!r}.")
        if path.suffix.lower() in installer.FORBIDDEN_SUFFIXES:
            raise CitationError(f"The package contains a compiled file, which is not allowed: {name!r}.")
    for required in (manifest.format_file, *REQUIRED_FILES):
        if required not in files:
            raise CitationError(f"The package has no {required}.")
    for name in files:
        if PurePosixPath(name).suffix.lower() in installer.FORBIDDEN_SUFFIXES:
            raise CitationError(f"The package contains a compiled file, which is not allowed: {name!r}.")


def check_manifest(manifest: CitationManifest, app_version: str = VERSION_NUMBER) -> None:
    """The rules that depend on this SlideMage: requires_slidemage, and a key no bundled format has."""
    if manifest.id in bundled_keys():
        raise CitationError(f"The citation format's key {manifest.id!r} is the key of a format SlideMage ships; "
                            "a package cannot replace it.")
    try:
        ok = matches(manifest.requires_slidemage, app_version)
    except ValueError as e:
        raise CitationError(f"Cannot compare SlideMage versions: {e}") from None
    if not ok:
        raise CitationError(f"The citation format needs SlideMage {manifest.requires_slidemage}; "
                            f"this is {app_version}.")


# Keep the public package API here; callers and package tools need no knowledge of the shared store.
KIND = packages.PackageKind(
    name="citation format", folder=lambda: citations_dir(), manifest_name=MANIFEST_NAME, suffix=PACKAGE_SUFFIX,
    error=CitationError, parse_manifest=lambda text: parse_manifest(text),
    check_names=lambda names, manifest: check_names(names, manifest),
    check_manifest=lambda manifest, app_version: check_manifest(manifest, app_version),
    key_re=KEY_RE, tex_file=format_file, contents_name="package")

InstalledCitation = packages.InstalledPackage
read_manifest = partial(packages.read_manifest, KIND)
folder_names = partial(packages.folder_names, KIND)
check_folder = partial(packages.check_folder, KIND)
package_name = partial(packages.package_name, KIND)
peek = partial(packages.peek, KIND)
installed = partial(packages.installed, KIND)
citation_dirs = partial(packages.installed_dirs, KIND)
texinputs = partial(packages.texinputs, KIND)
citation_of = partial(packages.owner_of, KIND)
install_file = partial(packages.install_file, KIND)
remove = partial(packages.remove, KIND)
cleanup = partial(packages.cleanup, KIND)
