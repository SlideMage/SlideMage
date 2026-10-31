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


@dataclass(frozen=True)
class InstalledCitation:
    key: str
    folder: Path
    manifest: CitationManifest | None   # None: citation.toml unreadable (the folder is still listed, to be removed)
    problem: str = ""


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


def read_manifest(folder: Path) -> CitationManifest:
    path = Path(folder) / MANIFEST_NAME
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise CitationError(f"There is no {MANIFEST_NAME} in {folder}.") from None
    except (OSError, UnicodeDecodeError) as e:
        raise CitationError(f"{MANIFEST_NAME} cannot be read: {e}") from None
    return parse_manifest(text)


# -- the package rules

def _is_extra(name: str, key: str) -> bool:
    path = PurePosixPath(name)
    return (path.name.startswith(f"{FORMAT_PREFIX}{key}_") and path.suffix.lower() in EXTRA_SUFFIXES
            and path.stem != f"{FORMAT_PREFIX}{key}_")


def check_names(names: list[str], manifest: CitationManifest) -> None:
    """The package's file names (POSIX, relative to its top, folders ending in /) hold the format file and the
    required files and nothing that is not the package's own. Raises CitationError."""
    files = {n for n in names if not n.endswith("/")}
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


def folder_names(folder: Path, skip_hidden: bool = False) -> list[str]:
    """The names check_names() takes, for the files under `folder`. `skip_hidden` leaves out what starts with a dot
    (.git/, .github/, .gitignore of a package's repository: tools/make_citation_package.py does not pack them)."""
    names = []
    for path in sorted(Path(folder).rglob("*")):
        rel = path.relative_to(folder).as_posix()
        if skip_hidden and any(part.startswith(".") for part in PurePosixPath(rel).parts):
            continue
        if path.is_symlink():
            raise CitationError(f"The package contains a symbolic link: {rel!r}.")
        names.append(rel + "/" if path.is_dir() else rel)
    return names


def check_folder(folder: Path, app_version: str = VERSION_NUMBER, skip_hidden: bool = False) -> CitationManifest:
    """Every package rule for the unpacked package in `folder`. Raises CitationError."""
    manifest = read_manifest(folder)
    check_names(folder_names(folder, skip_hidden), manifest)
    check_manifest(manifest, app_version)
    return manifest


def package_name(manifest: CitationManifest) -> str:
    return f"{manifest.id}-{manifest.version}{PACKAGE_SUFFIX}"


def peek(archive: Path) -> CitationManifest:
    """The checked citation.toml of a .smcite, read without unpacking it. Raises CitationError."""
    try:
        with zipfile.ZipFile(archive) as zf:
            info = next((i for i in zf.infolist() if i.filename == MANIFEST_NAME), None)
            if info is None:
                raise CitationError(f"The archive has no {MANIFEST_NAME} at its top level.")
            if info.file_size > installer.MAX_MANIFEST_BYTES:
                raise CitationError(f"The {MANIFEST_NAME} is too large.")
            data = zf.read(info)
    except zipfile.BadZipFile:
        raise CitationError("The file is not a valid zip archive.") from None
    except OSError as e:
        raise CitationError(f"The archive cannot be read: {e}") from None
    try:
        return parse_manifest(data.decode("utf-8"))
    except UnicodeDecodeError:
        raise CitationError(f"{MANIFEST_NAME} is not UTF-8 text.") from None


# -- installed formats

def installed() -> list[InstalledCitation]:
    """Every folder in citations_dir(), by key; one with a broken citation.toml has its problem set."""
    base = citations_dir()
    try:
        folders = sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        return []
    found = []
    for folder in folders:
        try:
            manifest = read_manifest(folder)
        except CitationError as e:
            found.append(InstalledCitation(folder.name, folder, None, str(e)))
            continue
        problem = "" if manifest.id == folder.name else f"its {MANIFEST_NAME} names the key {manifest.id!r}"
        found.append(InstalledCitation(folder.name, folder, manifest, problem))
    return found


def citation_dirs() -> list[Path]:
    """The installed format folders TeX searches: those holding their own key's format file. Cheap (one directory
    listing and a stat per package): every compile and preview asks."""
    base = citations_dir()
    try:
        folders = sorted(p for p in base.iterdir() if not p.name.startswith(".") and KEY_RE.match(p.name))
    except OSError:
        return []
    return [folder for folder in folders if (folder / format_file(folder.name)).is_file()]


def texinputs(env: dict | None = None) -> str | None:
    """The TEXINPUTS a compile gets: the installed format folders, then what `env` had (or nothing: the trailing
    separator keeps the TeX distribution's own search path). None when no package is installed, so the environment
    stays as it was. The project's .latexmkrc puts the project root and the framework in front."""
    dirs = citation_dirs()
    if not dirs:
        return None
    rest = (env or {}).get("TEXINPUTS", "")
    return os.pathsep.join([*(str(d) for d in dirs), rest])


def citation_of(path: Path) -> Path | None:
    """The installed citation folder `path` lies in, or None."""
    try:
        resolved = Path(path).resolve()
    except OSError:
        return None
    for folder in citation_dirs():
        root = folder.resolve()
        if resolved == root or root in resolved.parents:
            return folder
    return None


# -- install and remove

def install_file(archive: Path, *, expected_sha256: str | None = None,
                 app_version: str = VERSION_NUMBER) -> CitationManifest:
    """Check the .smcite `archive` and install it unpacked in citations_dir()/<key>/, replacing an installed version
    of the same key. Raises CitationError; nothing is changed then."""
    archive = Path(archive)
    if expected_sha256 is not None:
        try:
            actual = installer.sha256_of(archive)
        except OSError as e:
            raise CitationError(f"The archive cannot be read: {e}") from None
        if actual != expected_sha256.strip().lower():
            raise CitationError("The package does not match its checksum (SHA-256); nothing was installed.")
    base = citations_dir()
    staging = base / ".staging" / uuid.uuid4().hex
    old: Path | None = None
    try:
        try:
            staging.mkdir(parents=True)
            with zipfile.ZipFile(archive) as zf:
                installer.extract(zf, staging, MANIFEST_NAME)
        except installer.InstallError as e:
            raise CitationError(str(e)) from None
        except zipfile.BadZipFile:
            raise CitationError("The file is not a valid zip archive.") from None
        except OSError as e:
            raise CitationError(f"The archive could not be unpacked: {e}") from None
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
            raise CitationError(f"The citation format could not be put in place (is a compile using it?): {e}"
                                ) from None
        return manifest
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        cleanup()


def remove(key: str) -> None:
    """Delete the installed citation format `key`. Raises CitationError."""
    folder = citations_dir() / key
    if not KEY_RE.match(key) or not folder.is_dir():
        raise CitationError(f"The citation format {key!r} is not installed.")
    old = citations_dir() / ".old" / f"{key}-{uuid.uuid4().hex[:8]}"
    try:
        old.parent.mkdir(parents=True, exist_ok=True)
        os.replace(folder, old)
    except OSError as e:
        raise CitationError(f"The citation format could not be removed (is a compile using it?): {e}") from None
    cleanup()


def cleanup() -> None:
    """Delete leftovers of earlier installs (.staging/, .old/). Never raises."""
    for name in (".staging", ".old"):
        path = citations_dir() / name
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
