# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
r"""Where on the sample slides a colour is used (docs/plans/theme-editor.md, section 3.3, stage C1c part 2): the theme
form dims everything but the parts of the slides that a focused colour field changes.

No geometry is needed: the sample deck is rendered once more with every colour role (or every palette colour) given a
colour of its own from PROBES, added as lines right before \input{SlideMage_base} of a copy of the theme, and every pixel
of that render that has one of those colours belongs to that role. One probe render per kind ("role", "palette") and
colour mode, made when a colour field first gets the focus and kept until the text changes."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import theme_fields
from .theme_file import ThemeFile

KINDS = ("role", "palette")
TOLERANCE = 10          # per channel: a solid fill or a glyph's inner pixels; anti-aliased edges are mixtures
_LEVELS = (0x10, 0x50, 0x90, 0xD0)
# Colours far from each other (64 per channel) and from greys, so a probe pixel says whose it is.
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
    block = "% theme form: where each colour is used (probe render)\n" + "\n".join(lines) + "\n"
    return text[:at] + block + text[at:], mapping


def _lookup(mapping: dict[str, str]) -> tuple[dict[bytes, int], list[str]]:
    """Every RGB triple within TOLERANCE of a probe, as bytes, to the probe's index (1-based) in the returned names."""
    order = list(mapping.values())
    table: dict[bytes, int] = {}
    span = range(-TOLERANCE, TOLERANCE + 1)
    for index, probe in enumerate(mapping, start=1):
        r, g, b = (int(probe[i:i + 2], 16) for i in (0, 2, 4))
        for dr in span:
            for dg in span:
                for db in span:
                    table[bytes((r + dr, g + dg, b + db))] = index
    return table, order


@dataclass
class UsageMap:
    """Where each colour is on each page: `pages[p]` is one byte per pixel of a width x height grid (0: none, else the
    1-based index into `names`)."""
    kind: str
    mode: str
    names: list[str]
    width: int = 0
    height: int = 0
    pages: list[bytes] = field(default_factory=list)

    def pages_using(self, name: str) -> list[int]:
        """1-based numbers of the pages where `name` shows."""
        if name not in self.names:
            return []
        code = self.names.index(name) + 1
        return [number for number, grid in enumerate(self.pages, start=1) if bytes((code,)) in grid]

    def mask(self, page: int, name: str) -> bytes:
        """One byte per pixel of page `page` (1-based): 255 where `name` shows, else 0."""
        if name not in self.names or not 1 <= page <= len(self.pages):
            return bytes(self.width * self.height)
        code = self.names.index(name) + 1
        return self.pages[page - 1].translate(bytes(255 if i == code else 0 for i in range(256)))


def usage_map(pdf: Path, mapping: dict[str, str], kind: str, mode: str, *, dpi: int, oversample: int = 2) -> UsageMap:
    """Read a probe render: each page at `dpi` x `oversample`, folded down to `dpi` (a pixel belongs to a colour when
    any of its sub-pixels does, so thin text strokes count)."""
    import pymupdf

    table, order = _lookup(mapping)
    result = UsageMap(kind, mode, order)
    with pymupdf.open(pdf) as doc:
        for page in doc:
            big = page.get_pixmap(dpi=dpi * oversample, alpha=False)
            small_w, small_h = big.width // oversample, big.height // oversample
            grid = bytearray(small_w * small_h)
            samples, stride = big.samples, big.stride
            get = table.get
            for y in range(small_h * oversample):
                row = y * stride
                target = (y // oversample) * small_w
                for x in range(small_w * oversample):
                    code = get(samples[row + 3 * x:row + 3 * x + 3])
                    if code:
                        grid[target + x // oversample] = code
            result.width, result.height = small_w, small_h
            result.pages.append(bytes(grid))
    return result
