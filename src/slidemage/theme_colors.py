# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
r"""The colours a deck's theme gives the c_* names: what the toolbar's Color menu shows, read from the same
SlideMage_template_<key>.tex (and the files it \inputs, SlideMage_setup.tex first) that the render loads, so a swatch
is the colour the slide gets. Only plain \definecolor lines with a HTML, RGB, rgb or gray value and \colorlet lines
of a colour expression (`name`, `name!60`, `name!60!other`) are read; a name a theme defines otherwise keeps
latex_edit's fallback swatch.

Since v0.16.3 the colours are those of a colour mode (latex/SlideMage_setup.tex, "Colour modes and role colours"):
the template's \SMDeclareMode, \SMSetColor and \SMSetRole lines are read and resolved in the framework's order
(\SM@applymode): the mode's preset, then its palette lines, then each role from its explicit line, else the preset's
derived value, else the base mode's source. The role colours (c_text, c_canvas, ...) lead the menu."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import latex_edit, slide_templates

_NAME = r"[A-Za-z][A-Za-z0-9_]*"
_DEFINE_RE = re.compile(r"\\definecolor\{(" + _NAME + r")\}\{(HTML|RGB|rgb|gray)\}\{([^}]*)\}")
_LET_RE = re.compile(r"\\colorlet\{(" + _NAME + r")\}\{([A-Za-z0-9_!.]+)\}")
_DECLARE_RE = re.compile(r"\\SMDeclareMode\{(\w+)\}\{(\w*)\}")
_SETCOLOR_RE = re.compile(r"\\SMSetColor\{(" + _NAME + r")\}\{(\w+)\}\{(HTML|RGB|rgb|gray)\}\{([^}]*)\}")
_SETROLE_RE = re.compile(r"\\SMSetRole\{(\w+)\}\{(\w+)\}\{([A-Za-z0-9_!.]+)\}")
_INPUT_RE = re.compile(r"\\input\{([A-Za-z0-9_.-]+)\}")
_CATEGORIES = {"custom": 0, "primary": 1, "secondary": 2, "tertiary": 3}

# The role colours slides can name, their base-mode source and what the menu says they are (SlideMage_setup.tex).
ROLES: dict[str, tuple[str, str]] = {
    "text": ("c_primary_dark", "body text, lines"),
    "text_muted": ("c_primary_gray", "secondary text"),
    "text_on_accent": ("c_primary_dark", "text on a colored fill"),
    "link": ("c_custom_gray", "links"),
    "canvas": ("SMCanvasColor", "slide background"),
    "card": ("SMCardBackgroundColor", "card fill"),
    "line": ("SMCardBorderColor", "card border"),
}
_ROLE_FALLBACK = {"SMCanvasColor": "white", "SMCardBackgroundColor": "white", "SMCardBorderColor": "c_primary_dark"}
_PRESET_DARK = {"canvas": "c_primary_dark!83!white", "card": "c_primary_dark!77!white", "line": "c_true_white",
                "text": "c_true_white", "text_muted": "c_primary_gray!60!white", "text_on_accent": "c_true_black",
                "link": "c_true_white"}
_GREY_NAMES = ("c_primary_dark c_primary_highlight c_primary_gray c_secondary_violet c_tertiary_violet "
               "c_secondary_blue c_tertiary_blue c_secondary_green c_tertiary_green c_secondary_red c_tertiary_red "
               "c_secondary_orange c_tertiary_orange c_secondary_yellow c_tertiary_yellow c_tertiary_gray "
               "c_custom_gray c_custom_red c_custom_green c_custom_brown SMLightOrange SMLightGreen "
               "SMDeepYellowOrange SMAnthracite").split()
_COLORBLIND = {"blue": "#0072b2", "green": "#009e73", "red": "#d55e00", "orange": "#e69f00", "yellow": "#f0e442",
               "violet": "#cc79a7"}
_BUILTIN = {"white": "#ffffff", "black": "#000000", "c_true_white": "#ffffff", "c_true_black": "#000000"}


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


def _rgb(value: str) -> list[float]:
    return [int(value[i:i + 2], 16) / 255 for i in (1, 3, 5)]


def _format(rgb: list[float]) -> str:
    return "#" + "".join(f"{round(min(max(v, 0), 1) * 255):02x}" for v in rgb)


def evaluate(expression: str, colors: dict[str, str]) -> str | None:
    """"#rrggbb" of an xcolor expression `a`, `a!p` (p % of a, the rest white) or `a!p!b!q!c...` over `colors`; None
    when a name is unknown."""
    parts = expression.strip().split("!")
    known = {**_BUILTIN, **colors}
    if parts[0] not in known:
        return None
    current = _rgb(known[parts[0]])
    rest = parts[1:]
    while rest:
        try:
            percent = float(rest[0]) / 100
        except ValueError:
            return None
        other_name = rest[1] if len(rest) > 1 else "white"
        if other_name not in known:
            return None
        other = _rgb(known[other_name])
        current = [percent * a + (1 - percent) * b for a, b in zip(current, other)]
        rest = rest[2:]
    return _format(current)


@dataclass
class _Theme:
    colors: dict[str, str] = field(default_factory=dict)
    modes: list[tuple[str, str]] = field(default_factory=list)                 # (id, derive), the first is the base
    set_colors: list[tuple[str, str, str]] = field(default_factory=list)       # (name, mode, "#rrggbb")
    set_roles: list[tuple[str, str, str]] = field(default_factory=list)        # (role, mode, expression)


def _read(name: str, root: Path, theme: _Theme, seen: set[Path]) -> None:
    for folder in slide_templates.template_dirs(root):
        path = folder / (name if name.endswith(".tex") else name + ".tex")
        if path.is_file():
            break
    else:
        return
    if path in seen:
        return
    seen.add(path)
    _read_text(path.read_text(encoding="utf-8", errors="replace"), root, theme, seen)


def _read_text(text: str, root: Path, theme: _Theme, seen: set[Path]) -> None:
    for line in text.splitlines():
        code = re.split(r"(?<!\\)%", line, maxsplit=1)[0]
        for found in _INPUT_RE.finditer(code):
            _read(found.group(1), root, theme, seen)
        for found in _DEFINE_RE.finditer(code):
            value = _hex(found.group(2), found.group(3))
            if value:
                theme.colors[found.group(1)] = value
        for found in _LET_RE.finditer(code):
            value = evaluate(found.group(2), theme.colors)
            if value:
                theme.colors[found.group(1)] = value
        for found in _DECLARE_RE.finditer(code):
            if all(found.group(1) != known for known, _ in theme.modes):
                theme.modes.append((found.group(1), found.group(2)))
        for found in _SETCOLOR_RE.finditer(code):
            value = _hex(found.group(3), found.group(4))
            if value:
                theme.set_colors.append((found.group(1), found.group(2), value))
        for found in _SETROLE_RE.finditer(code):
            theme.set_roles.append(found.group(1, 2, 3))


def _load(template: str, root: Path) -> _Theme:
    theme = _Theme()
    _read(f"{slide_templates.TEMPLATE_PREFIX}{template}", root, theme, set())
    return theme


def _resolve(theme: _Theme, mode: str) -> dict[str, str]:
    colors = dict(theme.colors)
    base = theme.modes[0][0] if theme.modes else ""
    mode = mode or base              # as \SM@activemode; an undeclared mode gets no preset, only its own lines
    derive = dict(theme.modes).get(mode) if mode != base else None
    derived: dict[str, str] = {}
    if derive == "dark":
        derived = dict(_PRESET_DARK)
    elif derive == "gray":
        for name in _GREY_NAMES:
            if name in colors:
                r, g, b = _rgb(colors[name])
                colors[name] = _format([0.3 * r + 0.59 * g + 0.11 * b] * 3)
    elif derive == "colorblind":
        for hue, value in _COLORBLIND.items():
            colors[f"c_secondary_{hue}"] = value
            colors[f"c_tertiary_{hue}"] = evaluate("x!50!white", {"x": value}) or value
    if mode:
        for name, line_mode, value in theme.set_colors:
            if line_mode == mode:
                colors[name] = value
    explicit = {role: expression for role, line_mode, expression in theme.set_roles if mode and line_mode == mode}
    for role, (source, _) in ROLES.items():
        expression = explicit.get(role) or derived.get(role)
        if expression is None:
            expression = source if source in colors else _ROLE_FALLBACK.get(source, source)
        value = evaluate(expression, colors)
        if value:
            colors["c_" + role] = value
    return colors


def theme_colors(template: str, root: Path, mode: str = "") -> dict[str, str]:
    """{colour name: "#rrggbb"} the template `template` gives in colour mode `mode` ("" or an undeclared one: its base
    mode), for the project at `root`: the palette and the role colours c_text, c_canvas, ..."""
    return _resolve(_load(template, root), mode)


def theme_colors_for_text(text: str, root: Path, mode: str = "") -> dict[str, str]:
    """theme_colors() of a template's text that may not be saved (the theme form's buffer): the files it \\inputs
    (SlideMage_setup first) are read from the project at `root` as for a deck."""
    theme = _Theme()
    _read_text(text, root, theme, set())
    return _resolve(theme, mode)


def swatches(template: str, root: Path, mode: str = "") -> dict[str, str]:
    """The Color menu's names in menu order and their swatches under `template` in `mode`: the role colours first,
    then the palette, its own colours over latex_edit's fallback ones."""
    resolved = theme_colors(template, root, mode)
    roles = {"c_" + role: resolved["c_" + role] for role in ROLES if "c_" + role in resolved}
    merged = {**latex_edit.TEXTCOLOR_SWATCHES, **resolved}
    palette = sorted((n for n in merged if n.split("_")[1:2] and n.split("_")[1] in _CATEGORIES),
                     key=lambda n: (_CATEGORIES[n.split("_")[1]], n))
    return {**roles, **{name: merged[name] for name in palette}}


def role_hint(name: str) -> str:
    """What the role colour `name` is for ("" for a palette name)."""
    role = ROLES.get(name[2:]) if name.startswith("c_") else None
    return role[1] if role else ""
