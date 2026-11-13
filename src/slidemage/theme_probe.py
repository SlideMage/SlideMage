# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
r"""Where on the sample slides a colour is used (docs/plans/theme-editor.md, section 3.3, stage C1c part 2): the theme
form dims everything but the parts of the slides that a focused colour field changes.

The sample deck is rendered once more with every colour role (or every palette colour) given a colour of its own from
PROBES, added as lines right before \input{SlideMage_base} of a copy of the theme. In that PDF every piece of text and
every drawn path carries its colour exactly, so `usage_map` reads those (no pixels: an anti-aliased edge between two
probe colours can look like a third) and keeps a box for each. One probe render per kind ("role", "palette") and colour
mode, made when a colour field first gets the focus and kept until the text changes."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from . import theme_fields
from .theme_file import ThemeFile

KINDS = ("role", "palette")
PAD_X, PAD_Y = 1.5, 1.0     # points of room around text, lines and small shapes
JOIN_GAP = 3.0              # points: boxes on one line no further apart become one (a word space)
MIN_SIDE = 0.5              # points: a thinner rest of a covered box is dropped
_LEVELS = (0x10, 0x50, 0x90, 0xD0)
# Colours far from each other (64 per channel) and from greys, so a probe colour says whose it is.
PROBES: tuple[str, ...] = tuple(f"{r:02X}{g:02X}{b:02X}" for r in _LEVELS for g in _LEVELS for b in _LEVELS
                                if len({r, g, b}) > 1)
EXTRA_HOOKS = ("SMHighlightTitleTextColor",)     # a colour hook that is no role of the mode layer


def names(kind: str, file: ThemeFile) -> list[str]:
    """What a probe render of `kind` tells apart: role ids (and the extra hooks), or palette colour names."""
    if kind == "role":
        roles = [f.name[5:] for f in theme_fields.FIELDS if f.name.startswith("role:")]
        return roles + list(EXTRA_HOOKS)
    palette = [f.name for f in theme_fields.FIELDS if f.group == "palette"]
    own = [s.key for s in file.settings if s.kind in ("colour", "colorlet") and s.editable
           and s.key not in theme_fields.BY_NAME]
    return palette + list(dict.fromkeys(own))


def probe_text(text: str, kind: str, mode: str) -> tuple[str, dict[str, str]]:
    """The theme's text with the probe lines for `kind` in colour mode `mode` ("" for the base) and {probe hex: name}."""
    file = ThemeFile(text)
    at = file.base_line_start
    if at < 0:
        raise ValueError("The theme has no \\input{SlideMage_base}.")
    declared = [m for m, _ in file.modes()]
    lines: list[str] = []
    if not declared:
        lines.append("\\SMDeclareMode{probe}{}")       # a theme without modes: lines of its base mode need one
        target = "probe"
    else:
        target = mode or declared[0]
    wanted = names(kind, file)
    if len(wanted) > len(PROBES):
        wanted = wanted[:len(PROBES)]
    mapping: dict[str, str] = {}
    for index, name in enumerate(wanted):
        probe = PROBES[index]
        mapping[probe] = name
        if kind == "palette":
            lines.append(f"\\SMSetColor{{{name}}}{{{target}}}{{HTML}}{{{probe}}}")
        elif name in EXTRA_HOOKS:
            lines.append(f"\\definecolor{{SMProbe{index}}}{{HTML}}{{{probe}}}")
            lines.append(f"\\renewcommand{{\\{name}}}{{SMProbe{index}}}")
        else:
            lines.append(f"\\definecolor{{SMProbe{index}}}{{HTML}}{{{probe}}}")
            lines.append(f"\\SMSetRole{{{name}}}{{{target}}}{{SMProbe{index}}}")
    block = "% theme form: where each color is used (probe render)\n" + "\n".join(lines) + "\n"
    return text[:at] + block + text[at:], mapping


class Box(NamedTuple):
    """A rectangle of a page in fractions of its width and height. `exact`: the outline of a filled rectangle (the title
    bar); else a box with a little room around a piece of text, a line or a small shape. `order`: its place in the
    page's painting (what is painted later lies on top)."""
    x0: float
    y0: float
    x1: float
    y1: float
    exact: bool = False
    order: int = 0


@dataclass
class UsageMap:
    """Where each colour is on each page: `pages[p][i]` are the boxes of `names[i]` on page p + 1."""
    kind: str
    mode: str
    names: list[str]
    pages: list[list[list[Box]]] = field(default_factory=list)

    def pages_using(self, name: str) -> list[int]:
        """1-based numbers of the pages where `name` shows."""
        if name not in self.names:
            return []
        index = self.names.index(name)
        return [number for number, page in enumerate(self.pages, start=1) if page[index]]

    def boxes(self, page: int, name: str) -> list[Box]:
        """Where `name` shows on page `page` (1-based)."""
        if name not in self.names or not 1 <= page <= len(self.pages):
            return []
        return self.pages[page - 1][self.names.index(name)]

    def at(self, page: int, x: float, y: float) -> list[str]:
        """The names that show at the point (x, y), in fractions of page `page` (1-based): the topmost first."""
        if not 1 <= page <= len(self.pages):
            return []
        found: list[tuple[int, str]] = []
        for name, boxes in zip(self.names, self.pages[page - 1]):
            orders = [box.order for box in boxes if box.x0 <= x <= box.x1 and box.y0 <= y <= box.y1]
            if orders:
                found.append((max(orders), name))
        return [name for _order, name in sorted(found, key=lambda entry: -entry[0])]


def _name_of(colour, by_rgb: dict[tuple, int]) -> int:
    """The 1-based index of the probe a PDF colour (floats, grey or RGB) is, or 0. The PDF holds the colour as it was
    set, so only rounding separates it from the probe."""
    if colour is None:
        return 0
    if len(colour) == 1:
        colour = tuple(colour) * 3
    if len(colour) != 3:
        return 0
    rgb = tuple(min(_LEVELS, key=lambda level: abs(level - c * 255)) for c in colour)
    if any(abs(level - c * 255) > 2 for level, c in zip(rgb, colour)):
        return 0
    return by_rgb.get(rgb, 0)


def _minus(a: tuple, b: tuple) -> list[tuple]:
    """The parts of rectangle `a` (x0, y0, x1, y1) outside rectangle `b`."""
    if b[0] >= a[2] or b[2] <= a[0] or b[1] >= a[3] or b[3] <= a[1]:
        return [a]
    top, bottom = max(a[1], b[1]), min(a[3], b[3])
    parts = [(a[0], a[1], a[2], top), (a[0], bottom, a[2], a[3]), (a[0], top, b[0], bottom), (b[2], top, a[2], bottom)]
    return [p for p in parts if p[2] - p[0] > MIN_SIDE and p[3] - p[1] > MIN_SIDE]


def _joined(rects: list[tuple]) -> list[tuple]:
    """Rectangles (x0, y0, x1, y1, order) on one line that are a word space apart or less become one, so a line of
    text is one bar."""
    rects = list(rects)
    merged = True
    while merged:
        merged = False
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                a, b = rects[i], rects[j]
                overlap = min(a[3], b[3]) - max(a[1], b[1])
                gap = max(a[0], b[0]) - min(a[2], b[2])
                if gap <= JOIN_GAP and overlap >= 0.5 * min(a[3] - a[1], b[3] - b[1]):
                    rects[i] = (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]), max(a[4], b[4]))
                    del rects[j]
                    merged = True
                    break
            if merged:
                break
    return rects


def _painted(page, by_rgb: dict[tuple, int]) -> list[tuple[int, int, tuple, bool]]:
    """What the page paints, in its order: (sequence number, index of the name or 0, rectangle in points, covers: an
    opaque filled rectangle, which hides what was painted under it)."""
    found: list[tuple[int, int, tuple, bool]] = []
    for drawing in page.get_drawings():
        rect = tuple(drawing["rect"])
        items = drawing.get("items") or []
        fill = drawing.get("fill")
        if fill is not None:
            code = _name_of(fill, by_rgb)
            opacity = drawing.get("fill_opacity")
            opaque = opacity is None or opacity >= 0.99
            if items and all(item[0] == "re" for item in items):
                found += [(drawing["seqno"], code, tuple(item[1]), opaque) for item in items]
            else:
                found.append((drawing["seqno"], code, rect, False))
        if drawing.get("color") is not None and "s" in (drawing.get("type") or ""):
            half = (drawing.get("width") or 0.0) / 2
            found.append((drawing["seqno"], _name_of(drawing["color"], by_rgb),
                          (rect[0] - half, rect[1] - half, rect[2] + half, rect[3] + half), False))
    for span in page.get_texttrace():
        if span.get("type") != 3:       # 3: invisible text
            found.append((span["seqno"], _name_of(span.get("color"), by_rgb), tuple(span["bbox"]), False))
    found.sort(key=lambda entry: entry[0])
    return found


def _page_boxes(page, by_rgb: dict[tuple, int], count: int) -> list[list[Box]]:
    """The boxes of one page for every name (by index)."""
    painted = _painted(page, by_rgb)
    width, height = page.rect.width, page.rect.height
    exact: list[list[tuple]] = [[] for _ in range(count)]
    soft: list[list[tuple]] = [[] for _ in range(count)]
    for at, (seqno, code, rect, covers) in enumerate(painted):
        if not code:
            continue
        parts = [rect]
        for later_seqno, later_code, later_rect, later_covers in painted[at + 1:]:
            if later_covers and later_code != code and later_seqno > seqno:
                parts = [piece for part in parts for piece in _minus(part, later_rect)]
                if not parts:
                    break
        if covers:
            exact[code - 1] += [(*p, seqno) for p in parts]
        else:       # text, lines and small shapes: a little room around them
            soft[code - 1] += [(p[0] - PAD_X, p[1] - PAD_Y, p[2] + PAD_X, p[3] + PAD_Y, seqno) for p in parts]
    result: list[list[Box]] = []
    for index in range(count):
        boxes: list[Box] = []
        for rects, is_exact in ((exact[index], True), (_joined(soft[index]), False)):
            for r in rects:
                x0, y0, x1, y1 = max(r[0], 0.0), max(r[1], 0.0), min(r[2], width), min(r[3], height)
                if x1 > x0 and y1 > y0:
                    boxes.append(Box(x0 / width, y0 / height, x1 / width, y1 / height, is_exact, r[4]))
        result.append(boxes)
    return result


def usage_map(pdf: Path, mapping: dict[str, str], kind: str, mode: str) -> UsageMap:
    """Read a probe render: every piece of text and every drawn path whose colour is a probe colour, as boxes; what an
    opaque rectangle painted later covers is cut out of them."""
    import pymupdf

    order = list(mapping.values())
    by_rgb = {tuple(int(probe[i:i + 2], 16) for i in (0, 2, 4)): index
              for index, probe in enumerate(mapping, start=1)}
    result = UsageMap(kind, mode, order)
    with pymupdf.open(pdf) as doc:
        for page in doc:
            result.pages.append(_page_boxes(page, by_rgb, len(order)))
    return result
