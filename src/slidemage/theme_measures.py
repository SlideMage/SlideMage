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


def marks(key: str, value_bp: Optional[float], geometry: dict) -> list[Mark]:
    """The marks of the field `key` at `value_bp` (None: as rendered) on a slide of the sample deck."""
    if PAGE_WIDTH not in geometry:
        return []
    width, height = geometry[PAGE_WIDTH], geometry[PAGE_HEIGHT]
    value = value_bp if value_bp is not None else rendered(key, geometry)
    title_bottom = geometry.get("SMTitleBarBottom")
    found: list[Mark] = []
    if key == "SMTopMargin" and value is not None:
        found.append(Mark("h", value, f"Top Margin {value:.1f}bp", True, arrow=True))
        if title_bottom is not None:
            found.append(Mark("h", title_bottom, "title bar ends"))
    elif key in MARGIN_KEYS:
        left = value if key == "SMTextMarginLeft" and value is not None else geometry.get("SMTextMarginLeft")
        right = value if key == "SMTextMarginRight" and value is not None else geometry.get("SMTextMarginRight")
        if left is not None:
            found.append(Mark("v", left, f"left margin {left:.1f}bp", key == "SMTextMarginLeft", arrow=True))
        if right is not None:
            found.append(Mark("v", width - right, f"right margin {right:.1f}bp", key == "SMTextMarginRight",
                              arrow=True))
    elif key == "SMFooterBoxHeight" and value is not None:
        found.append(Mark("box", height - value, f"footer box {value:.1f}bp", True, size=value))
    elif key in TITLE_BAR_KEYS:
        if title_bottom is not None:
            found.append(Mark("h", title_bottom, f"title bar ends at {title_bottom:.1f}bp (after the next render)"
                              if value_bp is not None and key != "SMFrametitleLeftPadding" else
                              f"title bar ends at {title_bottom:.1f}bp", key in ("SMFrametitleTopPadding",
                                                                               "SMFrametitleBottomPadding",
                                                                               "SMLogoHeight")))
        left = value if key == "SMFrametitleLeftPadding" and value is not None else geometry.get("SMLeftMargin")
        if left is not None:
            found.append(Mark("v", left, f"title starts {left:.1f}bp", key == "SMFrametitleLeftPadding"))
        right = value if key == "SMFrametitleRightPadding" and value is not None else \
            geometry.get("SMFrametitleRightPadding")
        if right is not None:
            found.append(Mark("v", width - right, f"logo padding {right:.1f}bp", key == "SMFrametitleRightPadding"))
    return found


def title_bar_check(top_bp: Optional[float], geometry: dict) -> tuple[str, bool]:
    """("n bp below the title bar", True) or ("n bp above the title bar's bottom edge", False); ("", True) unknown."""
    title_bottom = geometry.get("SMTitleBarBottom")
    if top_bp is None or title_bottom is None:
        return "", True
    gap = top_bp - title_bottom
    if gap >= 0:
        return f"{gap:.1f}bp below the title bar", True
    return f"{-gap:.1f}bp above the title bar's bottom edge: the first line would start inside the bar", False
