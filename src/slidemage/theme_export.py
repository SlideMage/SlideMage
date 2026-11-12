# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Export a theme as a .smtheme package (docs/plans/theme-editor.md, section 3.5 and stage C4; docs/THEME_PACKAGE.md).

* pack(folder, out_dir): a theme folder that has its theme.toml (a theme's source folder) becomes its release asset
  <key>-<version>.smtheme and its .sha256; what tools/make_theme_package.py does (the tool calls this).
* export(home, key, info, out_dir): a personal theme, which is only a template file in the project (and its scheme
  folder and layout profile), gets the files a package needs written from `info` (theme.toml, README.md,
  CHANGELOG.md, LICENSE) in a staging folder, and is packed from there. Nothing is written into the project.
* defaults(home, key): what the export dialog starts from.

The package is checked with the rules "Install from file…" applies (themes.check_folder), so what this writes
installs. No Qt.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import themes
from .theme_file import ThemeFile
from .version import VERSION_NUMBER

FIXED_DATE = (2026, 1, 1, 0, 0, 0)
DEFAULT_LICENSE = "LPPL-1.3c-or-later"
_SPDX_LINE = re.compile(r"^%\s*SPDX-License-Identifier:\s*(\S+)", re.M)


def pack(folder: Path, out_dir: Path, app_version: str = VERSION_NUMBER) -> Path:
    """Check `folder` and write its .smtheme and .sha256 into `out_dir`; the .smtheme's path. Files are stored in name
    order with a fixed date, so the same folder gives the same bytes. Raises ThemeError."""
    folder = Path(folder)
    if not folder.is_dir():
        raise themes.ThemeError(f"{folder} is not a folder.")
    manifest = themes.check_folder(folder, app_version, skip_hidden=True)
    out_dir = Path(out_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        asset = out_dir / themes.package_name(manifest)
        files = [name for name in themes.folder_names(folder, skip_hidden=True) if not name.endswith("/")]
        with zipfile.ZipFile(asset, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name in sorted(files, key=lambda n: (n != themes.MANIFEST_NAME, n)):     # theme.toml first
                info = zipfile.ZipInfo(name, date_time=FIXED_DATE)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                zf.writestr(info, (folder / name).read_bytes())
        digest = hashlib.sha256(asset.read_bytes()).hexdigest()
        Path(str(asset) + ".sha256").write_text(f"{digest}  {asset.name}\n", encoding="utf-8", newline="\n")
    except OSError as exc:
        raise themes.ThemeError(f"Could not write the package into {out_dir}: {exc}") from None
    return asset


@dataclass(frozen=True)
class ExportInfo:
    """What a package says about itself (theme.toml); the template gives the key and the layout profile."""
    name: str
    version: str = "1.0.0"
    summary: str = ""
    author: str = ""
    homepage: str = ""
    license: str = DEFAULT_LICENSE


def _template(home: Path, key: str) -> Path:
    return home / themes.template_file(key)


def layout_of(text: str) -> str:
    """The layout profile the theme text picks (\\SMLayoutProfile), fira when it sets none."""
    return (ThemeFile(text).value("SMLayoutProfile") or "fira").strip()


def defaults(home: Path, key: str) -> ExportInfo:
    """The dialog's first values: the name of the template's name line, the licence of its SPDX line."""
    try:
        text = _template(home, key).read_bytes().decode("utf-8", errors="replace")
    except OSError:
        text = ""
    name = (ThemeFile(text).value("header:name") or key).strip()[:40]
    spdx = _SPDX_LINE.search(text)
    license_id = spdx.group(1).replace("LPPL-1.3c+", DEFAULT_LICENSE) if spdx else DEFAULT_LICENSE
    return ExportInfo(name=name, summary=f"The {name} theme for SlideMage."[:120], license=license_id)


def manifest_text(key: str, info: ExportInfo, layout: str, app_version: str = VERSION_NUMBER) -> str:
    """theme.toml for `key` from `info`; this SlideMage is the oldest the package says it works with."""
    def line(field: str, value: str) -> str:
        return f"{field} = {json.dumps(value.strip(), ensure_ascii=False)}"     # a JSON string is a TOML basic string
    return "\n".join([
        line("id", key), line("name", info.name), line("version", info.version),
        line("requires_slidemage", ">=" + app_version.lstrip("v")), line("summary", info.summary),
        line("author", info.author), line("homepage", info.homepage), line("license", info.license),
        line("layout", layout)]) + "\n"


def check_info(key: str, info: ExportInfo, layout: str = "fira") -> str:
    """"" when `info` makes a valid theme.toml for `key`, else what is wrong (the first problem, in words)."""
    for attr, label in (("name", "a name"), ("version", "a version"), ("summary", "a summary"),
                        ("author", "an author"), ("homepage", "a homepage (an http or https address)"),
                        ("license", "a license")):
        if not getattr(info, attr).strip():
            return f"A package needs {label}."
    try:
        manifest = themes.parse_manifest(manifest_text(key, info, layout))
        themes.check_manifest(manifest)
    except themes.ThemeError as exc:
        return str(exc).removeprefix(f"{themes.MANIFEST_NAME}: ")
    return ""


def stage(home: Path, key: str, info: ExportInfo, staging: Path) -> Path:
    """Write the package's folder into `staging`: the template, its scheme folder and own layout profile from `home`,
    and theme.toml, README.md, CHANGELOG.md and LICENSE from `info`. Returns `staging`. Raises ThemeError."""
    template = _template(home, key)
    if not template.is_file():
        raise themes.ThemeError(f"{template} was not found.")
    try:
        text = template.read_bytes().decode("utf-8", errors="replace")
        layout = layout_of(text)
        staging.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(template, staging / template.name)
        schemes = home / "schemes" / themes.scheme_dir(key)
        if schemes.is_dir():
            shutil.copytree(schemes, staging / "schemes" / themes.scheme_dir(key))
        own = f"{themes.LAYOUT_PREFIX}{layout}.tex"
        if layout not in themes.BUNDLED_PROFILES and (home / own).is_file():
            shutil.copyfile(home / own, staging / own)
        name = info.name.strip()
        files = {
            themes.MANIFEST_NAME: manifest_text(key, info, layout),
            "README.md": f"# {name}\n\n{info.summary.strip()}\n\nA theme for SlideMage. Install it with Settings → "
                         f"Extensions → \"Add from file…\", then choose the template \"{key}\" in a deck's settings.\n",
            "CHANGELOG.md": f"# Changelog\n\n## {info.version.strip()}\n\n- Exported from SlideMage "
                            f"{VERSION_NUMBER}.\n",
            "LICENSE": f"{name}, by {info.author.strip()}.\n\nThis theme (its template file and the files in its "
                       f"scheme folder) is distributed under the licence {info.license.strip()}.\n",
        }
        for file_name, content in files.items():
            (staging / file_name).write_text(content, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise themes.ThemeError(f"Could not put the package together: {exc}") from None
    return staging


def export(home: Path, key: str, info: ExportInfo, out_dir: Path) -> Path:
    """The personal theme `key` of the folder `home` as <key>-<version>.smtheme in `out_dir` (with its .sha256); the
    package's path. Raises ThemeError with the rule that is broken (a key SlideMage ships, a missing field, a logo
    the scheme folder does not hold is not checked: the template may name a file on the TeX search path)."""
    with tempfile.TemporaryDirectory(prefix="slidemage-theme-export-") as tmp:
        return pack(stage(home, key, info, Path(tmp) / key), out_dir)
