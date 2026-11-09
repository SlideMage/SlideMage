# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
r"""The colours a deck's theme gives the c_* names: what the toolbar's Color menu shows, read from the same
SlideMage_template_<key>.tex (and the files it \inputs, SlideMage_setup.tex first) that the render loads, so a swatch
is the colour the slide gets. Only plain \definecolor lines with a HTML, RGB, rgb or gray value and \lorlet lines
that copy another name are read; a name a theme defines otherwise keeps latex_edit's fallback swatch."""
from __future__ import annotations

import re
from pathlib import Path

from . import latex_edit, slide_templates

_DEFINE_RE = re.compile(r"\\definecolor\{(c_[a-z]+_[a-z]+)\}\{(HTML|RGB|rgb|gray)\}\{([^}]*)\}")
_LET_RE = re.compile(r"\\colorlet\{(c_[a-z]+_[a-z]+)\}\{(c_[a-z]+_[a-z]+)\}\s*$")
_INPUT_RE = re.compile(r"\\input\{([A-Za-z0-9_.-]+)\}")
_CATEGORIES = {"custom": 0, "primary": 1, "secondary": 2, "tertiary": 3}


def _hex(model: str, value: str) -> str | None:
    try:
        if model == "HTML":
            return "#" + value.strip().lower() if re.fullmatch(r"[0-9A-Fa-f]{6}", value.strip()) else None
        parts = [float(p) for p in value.split(",")]
        if model == "gray" and len(parts) == 1:
            parts = parts * 3
        if len(parts) != 3:
            return None
        scale = 255 if model == "RGB" else 1
        return "#" + "".join(f"{round(min(max(p / scale, 0), 1) * 255):02x}" for p in parts)
    except ValueError:
        return None


def _read(name: str, root: Path, colors: dict[str, str], seen: set[Path]) -> None:
    for folder in slide_templates.template_dirs(root):
        path = folder / (name if name.endswith(".tex") else name + ".tex")
        if path.is_file():
            break
    else:
        return
    if path in seen:
        return
    seen.add(path)
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        code = re.split(r"(?<!\\)%", line, maxsplit=1)[0]
        for found in _INPUT_RE.finditer(code):
            _read(found.group(1), root, colors, seen)
        for found in _DEFINE_RE.finditer(code):
            value = _hex(found.group(2), found.group(3))
            if value:
                colors[found.group(1)] = value
        let = _LET_RE.search(code.strip())
        if let and let.group(2) in colors:
            colors[let.group(1)] = colors[let.group(2)]


def theme_colors(template: str, root: Path) -> dict[str, str]:
    """{c_* name: "#rrggbb"} the template `template` gives, for the project at `root`."""
    colors: dict[str, str] = {}
    _read(f"{slide_templates.TEMPLATE_PREFIX}{template}", root, colors, set())
    return colors


def swatches(template: str, root: Path) -> dict[str, str]:
    """The Color menu's names in menu order and their swatches under `template`: its own colours over latex_edit's
    fallback ones."""
    merged = {**latex_edit.TEXTCOLOR_SWATCHES, **theme_colors(template, root)}
    return {name: merged[name] for name in sorted(
        (n for n in merged if n.split("_")[1] in _CATEGORIES), key=lambda n: (_CATEGORIES[n.split("_")[1]], n))}
