# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
r"""Marks of margins and paddings on the sample slides (docs/plans/theme-editor.md, section 3.3, stage C2b): while a
layout field has the focus, the sample slide shows what it sets as a line or a box, at the value in the field, so the
mark moves as the user types, before the slides render again.

Where things are comes from the last render: SlideMage_base writes the length hooks into the PDF's info dictionary
(theme_sample.read_geometry), so the title bar's bottom edge (derived from the paddings, the title font and the logo)
and lengths in ex or em are known as TeX worked them out. A value being typed is turned into bp at once when its unit is
absolute (pt, bp, cm, mm, in ...); one in ex or em is scaled from the rendered value of the same unit."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .theme_form_model import split_length
from .theme_sample import PAGE_HEIGHT, PAGE_WIDTH

_PT = 72 / 72.27
TO_BP = {"bp": 1.0, "pt": _PT, "cm": 72 / 2.54, "mm": 72 / 25.4, "in": 72.0, "pc": 12 * _PT,
         "dd": 1238 / 1157 * _PT, "cc": 12 * 1238 / 1157 * _PT, "sp": _PT / 65536}
TITLE_BAR_KEYS = ("SMFrametitleTopPadding", "SMFrametitleBottomPadding", "SMFrametitleLeftPadding", "SMLogoHeight",
                  "SMFrametitleRightPadding")
MARGIN_KEYS = ("SMTextMarginLeft", "SMTextMarginRight")
MEASURED = ("SMTopMargin", "SMFooterBoxHeight", *MARGIN_KEYS, *TITLE_BAR_KEYS)
# The unit the form shows lengths in (the user's choice, 2026-11-12: one unit to compare them in; mm unless pt is
# picked). The theme file keeps each length in the unit it was written in: ex and em follow the font on purpose.
DISPLAY_UNITS = ("mm", "pt")
DEFAULT_DISPLAY_UNIT = "mm"
# The info key a hook's rendered value is under, where it is not its own name.
_INFO_KEY = {"SMFrametitleLeftPadding": "SMLeftMargin", "SMTopMargin": "SMTopMargin"}


@dataclass(frozen=True)
class Mark:
    kind: str           # "h" (a line across, at `at` from the top), "v" (a line down, at `at` from the left), "box"
    at: float           # bp; for a box its top edge
    label: str
    focus: bool = False     # the mark of the field in focus (drawn strong), else context (drawn thin)
    size: float = 0.0       # a box's height (it spans the page's width)
    arrow: bool = False     # a dimension arrow from the page's edge to the line


def from_bp(value_bp: float, unit: str) -> float:
    return value_bp / TO_BP[unit]


def show(value_bp: float, unit: str = DEFAULT_DISPLAY_UNIT) -> str:
    """A length in bp as the form shows it: "15.9 mm", "45.2 pt"."""
    return f"{from_bp(value_bp, unit):.1f} {unit}"


def number_in(value_bp: float, unit: str) -> str:
    """The number of a length in `unit`, as a field holds it ("4.5", not "4.50")."""
    return f"{from_bp(value_bp, unit):.2f}".rstrip("0").rstrip(".")


def rendered(key: str, geometry: dict) -> Optional[float]:
    return geometry.get(_INFO_KEY.get(key, key))


def to_bp(value: str, key: str, geometry: dict, rendered_value: str = "") -> Optional[float]:
    """`value` ("45bp", "1cm", "3ex") in bp; ex and em by the rendered value of `rendered_value`, the value the last
    render had, when it was in the same unit. None when it cannot be known before the next render."""
    parts = split_length(value)
    if parts is None:
        return None
    number, unit = float(parts[0]), parts[1]
    if unit in TO_BP:
        return number * TO_BP[unit]
    old = split_length(rendered_value)
    before = rendered(key, geometry)
    if old and old[1] == unit and float(old[0]) and before is not None:
        return before * number / float(old[0])
    return None


def marks(key: str, value_bp: Optional[float], geometry: dict, unit: str = DEFAULT_DISPLAY_UNIT) -> list[Mark]:
    """The marks of the field `key` at `value_bp` (None: as rendered) on a slide of the sample deck, labelled in
    `unit`."""
    if PAGE_WIDTH not in geometry:
        return []
    width, height = geometry[PAGE_WIDTH], geometry[PAGE_HEIGHT]
    value = value_bp if value_bp is not None else rendered(key, geometry)
    title_bottom = geometry.get("SMTitleBarBottom")
    found: list[Mark] = []
    if key == "SMTopMargin" and value is not None:
        found.append(Mark("h", value, f"Top Margin {show(value, unit)}", True, arrow=True))
        if title_bottom is not None:
            found.append(Mark("h", title_bottom, "title bar ends"))
    elif key in MARGIN_KEYS:
        left = value if key == "SMTextMarginLeft" and value is not None else geometry.get("SMTextMarginLeft")
        right = value if key == "SMTextMarginRight" and value is not None else geometry.get("SMTextMarginRight")
        if left is not None:
            found.append(Mark("v", left, f"left margin {show(left, unit)}", key == "SMTextMarginLeft", arrow=True))
        if right is not None:
            found.append(Mark("v", width - right, f"right margin {show(right, unit)}", key == "SMTextMarginRight",
                              arrow=True))
    elif key == "SMFooterBoxHeight" and value is not None:
        found.append(Mark("box", height - value, f"footer box {show(value, unit)}", True, size=value))
    elif key in TITLE_BAR_KEYS:
        if title_bottom is not None:
            found.append(Mark("h", title_bottom, f"title bar ends at {show(title_bottom, unit)} (after the next "
                              "render)" if value_bp is not None and key != "SMFrametitleLeftPadding" else
                              f"title bar ends at {show(title_bottom, unit)}", key in ("SMFrametitleTopPadding",
                                                                               "SMFrametitleBottomPadding",
                                                                               "SMLogoHeight")))
        left = value if key == "SMFrametitleLeftPadding" and value is not None else geometry.get("SMLeftMargin")
        if left is not None:
            found.append(Mark("v", left, f"title starts {show(left, unit)}", key == "SMFrametitleLeftPadding"))
        right = value if key == "SMFrametitleRightPadding" and value is not None else \
            geometry.get("SMFrametitleRightPadding")
        if right is not None:
            found.append(Mark("v", width - right, f"logo padding {show(right, unit)}",
                              key == "SMFrametitleRightPadding"))
    return found


def logo_rect(geometry: dict) -> Optional[tuple[float, float, float, float]]:
    """Where the logo is in the ordinary title bar, (x0, y0, x1, y1) in bp from the top left: its bottom edge is the
    bar's, its right edge the right padding away from the page's. None when the render did not tell (SMLogoWidth is
    written by the sample deck)."""
    width, bottom = geometry.get(PAGE_WIDTH), geometry.get("SMTitleBarBottom")
    wide, high, pad = (geometry.get(key) for key in ("SMLogoWidth", "SMLogoHeight", "SMFrametitleRightPadding"))
    if None in (width, bottom, wide, high, pad) or wide <= 0 or high <= 0:
        return None
    return (width - pad - wide, bottom - high, width - pad, bottom)


def on_logo(x: float, y: float, geometry: dict) -> bool:
    rect = logo_rect(geometry)
    return rect is not None and rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]


def keys_at(x: float, y: float, geometry: dict) -> list[str]:
    """The layout settings of what is at the point (x, y), in bp from the top left, of a slide with the ordinary title
    bar and footer: the likeliest first. In the footer and the title bar what shapes them; in a margin that margin;
    inside the text area the margins, the nearest first, and the body font size."""
    if PAGE_WIDTH not in geometry:
        return []
    width, height = geometry[PAGE_WIDTH], geometry[PAGE_HEIGHT]
    footer = rendered("SMFooterBoxHeight", geometry)
    if footer is not None and y >= height - footer:
        return ["SMFooterBoxHeight", "SMFooterTextSize", "SMFootlineSidePadding"]
    title_bottom = geometry.get("SMTitleBarBottom")
    if title_bottom is not None and y <= title_bottom:
        title_left = geometry.get("SMLeftMargin")
        if title_left is not None and x <= title_left:
            first = ["SMFrametitleLeftPadding"]
        elif x >= 0.85 * width:         # where the logo is
            first = ["SMLogoHeight", "SMFrametitleRightPadding"]
        else:
            first = []
        return first + [key for key in TITLE_BAR_KEYS if key not in first]
    top = rendered("SMTopMargin", geometry)
    left = rendered("SMTextMarginLeft", geometry)
    right = rendered("SMTextMarginRight", geometry)
    away = [(max(0.0, y - top), "SMTopMargin")] if top is not None else []
    away += [(max(0.0, x - left), "SMTextMarginLeft")] if left is not None else []
    away += [(max(0.0, width - right - x), "SMTextMarginRight")] if right is not None else []
    inside = [key for distance, key in away if distance == 0]
    if inside:
        return inside
    return [key for _distance, key in sorted(away)] + ["SMBodyFontSize"]


def title_bar_check(top_bp: Optional[float], geometry: dict, unit: str = DEFAULT_DISPLAY_UNIT) -> tuple[str, bool]:
    """("n bp below the title bar", True) or ("n bp above the title bar's bottom edge", False); ("", True) unknown."""
    title_bottom = geometry.get("SMTitleBarBottom")
    if top_bp is None or title_bottom is None:
        return "", True
    gap = top_bp - title_bottom
    if gap >= 0:
        return f"{show(gap, unit)} below the title bar", True
    return f"{show(-gap, unit)} above the title bar's bottom edge: the first line would start inside the bar", False
