# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""A theme's source folder (docs/plans/theme-editor.md, section 3.6, route B): where the author of an installed theme
keeps its source, usually the theme's repository. Set per theme key on this computer (layout_settings), so that the
theme form edits the source there and not a copy in the project (route A) or the installed files (route C, never
offered: an update overwrites them).

* folder(key) / set_folder(key, folder): the setting. check(key, folder) says why a folder cannot be one.
* place(path, root): where a theme file lives, for the line at the top of the theme tab that says where an edit is
  written: the project, a source folder, the installed themes, or elsewhere.
* home(path, root): the folder a theme file's own files (logos, its layout profile) are looked up and written in.

No Qt.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import themes
from .ui import layout_settings

SETTING_KEY = "theme_source_folders"        # {theme key: folder}


def _same(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def folders() -> dict[str, str]:
    stored = layout_settings.get(SETTING_KEY, {})
    return {str(k): str(v) for k, v in stored.items()} if isinstance(stored, dict) else {}


def folder(key: str) -> Optional[Path]:
    """The source folder set for the theme `key`, None when none is set."""
    value = folders().get(key)
    return Path(value) if value else None


def set_folder(key: str, folder: Optional[Path]) -> None:
    """Remember `folder` as the source folder of `key`; None forgets it. Raises ThemeError for a folder check() refuses."""
    stored = folders()
    if folder is None:
        stored.pop(key, None)
    else:
        problem = check(key, folder)
        if problem:
            raise themes.ThemeError(problem)
        stored[key] = str(folder)
    layout_settings.set(SETTING_KEY, stored)


def template(key: str) -> Optional[Path]:
    """The theme's template file in its source folder, None when no folder is set or the file is gone."""
    base = folder(key)
    path = base / themes.template_file(key) if base is not None else None
    return path if path is not None and path.is_file() else None


def check(key: str, folder: Path) -> str:
    """"" when `folder` can be the source folder of the theme `key`, else why not."""
    if not folder.is_dir():
        return f"{folder} is not a folder."
    if any(_same(folder, installed) for installed in themes.installed_dirs()) or _same(folder.parent, themes.themes_dir()):
        return ("This is the installed theme itself: an update replaces what is in it. Pick the folder the theme's "
                "source is kept in (its repository).")
    if not (folder / themes.template_file(key)).is_file():
        return f"The folder has no {themes.template_file(key)}."
    if (folder / themes.MANIFEST_NAME).is_file():
        try:
            manifest = themes.read_manifest(folder)
        except themes.ThemeError as exc:
            return f"Its {themes.MANIFEST_NAME} cannot be read: {exc}"
        if manifest.id != key:
            return f"Its {themes.MANIFEST_NAME} is of the theme {manifest.id!r}, not {key!r}."
    return ""


def version(folder: Path) -> str:
    """The version the folder's theme.toml gives, "" when there is none to read."""
    try:
        return themes.read_manifest(folder).version
    except (themes.ThemeError, OSError):
        return ""


@dataclass(frozen=True)
class Place:
    kind: str       # project | source | installed | other
    line: str       # where an edit is written, for the theme tab
    warning: bool = False


def place(path: Path, root: Path) -> Place:
    """Where the theme file `path` lives, seen from the project at `root`."""
    key = path.stem[len(themes.TEMPLATE_PREFIX):]
    parent = path.parent
    installed = next((theme for theme in themes.installed() if theme.key == key), None)
    installed_version = installed.manifest.version if installed is not None and installed.manifest else ""
    if _same(parent, root):
        if installed is None:
            return Place("project", "")     # a personal theme of the project: the plain case, no line
        return Place("project", f"Your project's copy of {key}. This project's decks use it instead of the installed "
                                f"theme{' ' + installed_version if installed_version else ''}.")
    if installed is not None and _same(parent, installed.folder):
        return Place("installed", f"The installed copy of {key}: the next update of the theme replaces what you change "
                                  "here. Use \"Copy to my project and edit\" or the theme's source folder instead.", True)
    source = folder(key)
    if source is not None and _same(parent, source):
        here = version(parent)
        versions = ", ".join(part for part in (f"version {here} here" if here else "",
                                               f"{installed_version} installed" if installed_version else "") if part)
        same = bool(here) and here == installed_version
        return Place("source", f"The source folder of {key}: {parent}" + (f" ({versions})" if versions else "") + ". "
                     "Decks keep using the installed theme until you release this one and update"
                     + (f"; raise the version in {themes.MANIFEST_NAME} for the release." if same else "."))
    return Place("other", f"A theme file outside the project: {parent}. This project's decks do not use it.")


def home(path: Path, root: Path) -> Path:
    """The folder a theme file's logos and layout profile belong to: the file's own folder (the project for a
    personal theme, the source folder for one edited there)."""
    return root if _same(path.parent, root) else path.parent
