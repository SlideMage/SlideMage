# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Check the page layout of a compiled deck against the deck-wide margins.

Checks, per page (all coordinates in PDF units, the same "pt" every measurement
in the slide comments and the preamble uses -- 41.58 Top Margin etc.):

  top     first body content (text, image or drawing) starts on the Top Margin line
          (41.58 in the SlideMage template, the top of a plain first line's line box); only on frames with the
          ordinary title bar
  coltop  every column starts there too: a text line with nothing above it in its own
          horizontal range sits on the Top Margin (text beside a taller figure in
          vertically centred minipages fails this)
  left    no body content left of the Left Margin (12.55 in the SlideMage template: the title text's left edge)
  right   no body content right of the Right Margin (the logo's right edge), except
          things deliberately flush with the page edge (side images, strips)
  bottom  body content stays clear of the footnote/source lines and the footer box, and
          the last footnote line sits at its usual height (a lower one means the frame is
          overfull and pushed it down)
  bleed   table rules (booktabs \\toprule etc.) extend no further than the table's text
  jitter  between overlay pages of one slide nothing that is on both pages moves
  edge    the frame number and the footnote lines end on the logo's padding edge (the page's width less
          \\SMFrametitleRightPadding), where the footer and footnote shifts of the base put them
  titlepad  on a title frame the last subtitle line stands \\SMTitleframeBottomPad above the box's bottom edge,
          measured from the bottom of its line box (the hook's value comes from the PDF)

A slide can exempt itself from a check -- a deliberate exception, e.g. a figure centred
between title bar and footer -- with a comment line in its own slide file:

  %% layout-check: skip top -- figure is centred vertically (direct instruction)

(several checks comma-separated, or "all"). Exempted findings are counted, not listed.

The Top and Left Margin are the deck's own: SlideMage_base.tex writes them into the PDF
(info keys SMTopMargin, SMLeftMargin, since v10.5.0), and since v10.6.0 also the text font's
ascender (SMFontAscender) and the title bar's bottom edge (SMTitleBarBottom), so that a template
with another font, other margins or another title bar is checked against its own values. An
older PDF is checked against the SlideMage template's 41.58, 12.55, 0.935 and 25.2. Since v10.10.0 the geometric hooks
are in the PDF too (one key per hook, in bp; pdf_hooks()); `edge` and `titlepad` need them and are skipped on an older PDF
(edge falls back to the logo's visible edge). Exemptions are read from the slide files of the project the PDF
belongs to: --project, else the folder with slide_ids.csv above the PDF, else
$SLIDEMAGE_PROJECT.

usage: python tools/check_layout.py [--project DIR] [--checks top,right,...] [--tol 0.6] deck.pdf [...]
Exit code 1 if anything is reported.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import fitz

CHECKS = ("top", "coltop", "left", "right", "bottom", "bleed", "jitter", "edge", "titlepad")

TOP_MARGIN = 41.58       # top of a plain first body line's line box (\SMTopMargin in SlideMage_setup.tex, 41.58bp)
LEFT_MARGIN = 12.55      # title text's left edge (bullet dots start at 12.75): \SMFrametitleLeftPadding
# Both are only the fallback for a PDF from before SlideMage v10.5.0: since then the base writes the deck's own
# margins into the PDF's info dictionary (SMTopMargin, SMLeftMargin, in bp), which pdf_margins() reads.
FOOTNOTE_LAST_TOP = 242.64  # line-box top of the last footnote line when nothing pushes it (the fallback: see usual_footnote_top)
FOOTNOTE_MARKER_ALLOWANCE = 1.5  # a footnote line with its raised marker has a line box this much higher than a \source line
FOOTER_GAP = 1.0         # minimum clearance above footnotes / footer box
FOOTER_TEXT_MIN_SIZE = 3.6  # footer text is 3.99 pt and up; footnote/source lines 3.19 pt
FOOTER_TEXT_MAX_SIZE = 6.5  # a footer's text without a frame number to measure: no template sets it larger
FIRA_ASCENDER = 0.935    # Fira Sans ascender / em: a text line's top is baseline - this x size (the fallback: SMFontAscender)
TITLE_BAR_BOTTOM = 25.23    # the visible bottom edge of the SlideMage template's title bar, bp (the fallback: SMTitleBarBottom)
TITLE_BAR_TOLERANCE = 5.0   # a frame whose title bar ends this far from it has a title bar of another kind
# Fonts of displayed maths (and of the symbols in it): a line set only in these is not body text.
MATH_FONT_RE = re.compile(r"^(?:[A-Z]{6}\+)?(?:LMRoman|LMMath|CM(?:R|MI|SY|EX|BX|SS|TT|M)|MSAM|MSBM|EUFM|EUSM|rsfs|STIX|Cambria)")

ID_RE = re.compile(r"slide id: (\w+)")
SKIP_RE = re.compile(r"^\s*%+\s*layout-check:\s*skip\s+([a-z, ]+)", re.M)

_skip_cache: dict[tuple[Path, str], set[str]] = {}


def find_project(pdf: Path, given: str | None) -> Path | None:
    """The project a PDF belongs to: --project, the folder with slide_ids.csv
    above the PDF, or $SLIDEMAGE_PROJECT."""
    if given:
        return Path(given).resolve()
    for folder in pdf.resolve().parents:
        if (folder / "slide_ids.csv").is_file():
            return folder
    env = os.environ.get("SLIDEMAGE_PROJECT")
    return Path(env).resolve() if env else None


def exemptions(project: Path | None, slide_id: str) -> set[str]:
    if project is None:
        return set()
    if (project, slide_id) not in _skip_cache:
        skips: set[str] = set()
        for folder in (project / "slides",):
            for path in folder.glob(f"{slide_id}-*-current.tex"):
                for m in SKIP_RE.finditer(path.read_text(encoding="utf-8", errors="replace")):
                    skips |= {c.strip() for c in m.group(1).split(",") if c.strip()}
        if "all" in skips:
            skips = set(CHECKS)
        _skip_cache[(project, slide_id)] = skips
    return _skip_cache[(project, slide_id)]


def is_white(color) -> bool:
    return color is not None and all(c > 0.985 for c in color)


LOGO_DPI = 288


def logo_visible_right(page: fitz.Page, width: float, bar_bottom: float, logo_height: float | None = None) -> float:
    """The institute logo's visible right edge: the rightmost rendered pixel
    in the top-right corner that differs from the page's corner colour.
    Measured on pixels, not on the PDF's drawing list: a logo's outermost
    shape can be a white card with a dark outline (SlideMage's own logo) or
    a small text mark (an institution logo's "®"), and the drawing-list version skipped
    both and put the margin 2.4pt (SlideMage) to 12.7pt (such a mark) too far left.
    A title or quote frame has no ordinary title bar (bar_bottom stays 0): the 20pt fallback below fits the
    shipped templates' own small logos (\\SMLogoHeight 3ex, about 13pt), but a template with a taller one (the
    stress-test template's calibration logo is about 22pt tall) can draw it low enough that a flat 20pt misses
    its lower, often widest, part -- step 13, found via calibrate_font_profile.py --profile fira --template
    stress-test, where the logo sits a few points lower than under lmsans. \\SMLogoHeight (a hook the base
    writes into the PDF since v10.10.0) gives the window real headroom instead of another guessed constant."""
    top = max(bar_bottom, (logo_height or 0.0) + 25.0, 20.0)
    clip = fitz.Rect(width - 60, 0, width, top)
    pix = page.get_pixmap(dpi=LOGO_DPI, clip=clip, colorspace=fitz.csRGB, alpha=False)
    samples, n = pix.samples, pix.n
    background = samples[(pix.width - 1) * n:(pix.width - 1) * n + 3]   # top-right pixel

    def differs(x: int, y: int) -> bool:
        i = (y * pix.width + x) * n
        return max(abs(samples[i + k] - background[k]) for k in range(3)) > 40

    for x in range(pix.width - 1, -1, -1):
        if any(differs(x, y) for y in range(pix.height)):
            return clip.x0 + (x + 1) * 72 / LOGO_DPI
    return width - 9.6


def pdf_info(doc: fitz.Document) -> dict[str, float]:
    """The deck's own numbers from its PDF's info dictionary (SMTopMargin, SMLeftMargin, SMFontAscender,
    SMTitleBarBottom, written by SlideMage_base.tex), each falling back to the SlideMage template's
    value when the PDF lacks it."""
    def read(key: str, default: float) -> float:
        try:
            kind, ref = doc.xref_get_key(-1, "Info")
            if kind != "xref":
                return default
            kind, value = doc.xref_get_key(int(ref.split()[0]), key)
            return float(value) if kind in ("string", "real", "int") else default
        except (ValueError, RuntimeError):
            return default
    return {"top_margin": read("SMTopMargin", TOP_MARGIN), "left_margin": read("SMLeftMargin", LEFT_MARGIN),
            "ascender": read("SMFontAscender", FIRA_ASCENDER),
            "title_bar_bottom": read("SMTitleBarBottom", TITLE_BAR_BOTTOM)}


def pdf_hooks(doc: fitz.Document) -> dict[str, float]:
    """The geometric hooks SlideMage_base.tex writes into the PDF's info dictionary since v10.10.0 (key = the hook's
    name without the backslash, value in bp): the ones that are there. An older PDF yields none of them, and the
    checks that need one are skipped."""
    out: dict[str, float] = {}
    try:
        kind, ref = doc.xref_get_key(-1, "Info")
        if kind != "xref":
            return out
        xref = int(ref.split()[0])
        for key in doc.xref_get_keys(xref):
            if key.startswith("SM") and key not in ("SMTopMargin", "SMLeftMargin", "SMFontAscender", "SMTitleBarBottom"):
                kind, value = doc.xref_get_key(xref, key)
                if kind in ("string", "real", "int"):
                    out[key] = float(value)
    except (ValueError, RuntimeError):
        pass
    return out


def pdf_margins(doc: fitz.Document) -> tuple[float, float]:
    """The deck's Top and Left Margin (pdf_info's first two numbers)."""
    info = pdf_info(doc)
    return info["top_margin"], info["left_margin"]


class Page:
    """The measurable pieces of one page: frame chrome and body content."""

    def __init__(self, page: fitz.Page, top_margin: float = TOP_MARGIN, left_margin: float = LEFT_MARGIN,
                 ascender: float = FIRA_ASCENDER, title_bar_bottom: float = TITLE_BAR_BOTTOM,
                 hooks: dict[str, float] | None = None):
        self.page = page
        self.hooks = hooks or {}
        self.top_margin, self.left_margin = top_margin, left_margin
        self.ascender, self.title_bar_bottom = ascender, title_bar_bottom
        self.w, self.h = page.rect.width, page.rect.height
        text = page.get_text()
        m = ID_RE.search(text)
        self.slide_id = m.group(1) if m else None
        drawings = page.get_drawings()

        # title bar: a non-white fill from the top-left corner across the page
        bars = [d for d in drawings if d.get("fill") is not None and not is_white(d["fill"])
                and d["rect"].x0 < 0.5 and d["rect"].y0 < 0.5 and d["rect"].width > self.w - 1]
        self.bar_bottom = max((d["rect"].y1 for d in bars), default=0.0)
        # the white trim patch below the bar marks the *visible* bar bottom
        patches = [d for d in drawings if is_white(d.get("fill")) and d["rect"].x0 < 0.5
                   and d["rect"].width > self.w - 1 and 0 < d["rect"].y0 < self.bar_bottom]
        if patches:
            self.bar_bottom = min(d["rect"].y0 for d in patches)
        # footer box: a non-white fill across the page touching the bottom edge
        feet = [d for d in drawings if d.get("fill") is not None and not is_white(d["fill"])
                and d["rect"].width > self.w - 1 and d["rect"].y1 > self.h - 0.5]
        self.footer_top = min((d["rect"].y0 for d in feet), default=self.h)
        self.standard = self.slide_id is not None and abs(self.bar_bottom - self.title_bar_bottom) < TITLE_BAR_TOLERANCE

        # logo: its visible right edge, the Right Margin
        self.logo_right = logo_visible_right(page, self.w, self.bar_bottom, self.hooks.get("SMLogoHeight"))

        self.items: list[tuple[str, fitz.Rect, str]] = []   # (kind, rect, label)
        self.footnotes: list[fitz.Rect] = []
        self.vertical: list[fitz.Rect] = []                  # rotated text lines
        # horizontal text lines: (rect, baseline y, largest font size, glyph-box top,
        # set in a body font -- not only maths fonts)
        self.baselines: list[tuple[fitz.Rect, float, float, float, bool]] = []
        self.has_strip = False                               # \progressstrip under the bar
        top, bottom = self.bar_bottom + 0.3, self.footer_top - 0.3
        area = fitz.Rect(0, top, self.w, bottom)
        # Text is measured by line box (get_text "dict"), the measure every slide comment
        # uses; the text trace only tells which spans are invisible (render mode 3: the
        # alt-text layer beside informative images), matched by baseline origin.
        invisible = {(round(c[2][0], 1), round(c[2][1], 1))
                     for s in page.get_texttrace()
                     if s.get("type") == 3 or s.get("opacity", 1) == 0
                     for c in s.get("chars", ())}
        small: list[tuple[fitz.Rect, str]] = []
        blocks = page.get_text("dict")["blocks"]
        footer_size = footer_text_size(blocks, self.footer_top)
        for block in blocks:
            for line in block.get("lines", []):
                spans = [s for s in line["spans"] if s["text"].strip()
                         and (round(s["origin"][0], 1), round(s["origin"][1], 1)) not in invisible]
                if not spans:
                    continue
                r = fitz.Rect(line["bbox"])
                # a line an overfull frame pushed past the page's bottom edge is kept (v10.18.0): it is the
                # clearest overflow of all, and it used to be dropped here unseen
                if r.is_empty or not (r.intersects(page.rect) or r.y0 >= self.h - 0.5):
                    continue
                # top = baseline - the text font's ascender, from the non-superscript
                # spans only: a footnote marker or a math font's taller ascender
                # would otherwise lift the line box without the text moving
                body_spans = [s for s in spans if not s["flags"] & 1] or spans
                r.y0 = min(s["origin"][1] - self.ascender * s["size"] for s in body_spans)
                label = "".join(s["text"] for s in spans).strip()
                if abs(line["dir"][1]) > 0.5:
                    self.vertical.append(r)      # rotated (source strip, axis label)
                else:
                    self.baselines.append((r, max(s["origin"][1] for s in spans),
                                           max(s["size"] for s in spans), line["bbox"][1],
                                           any(not MATH_FONT_RE.match(s["font"]) for s in spans)))
                # a footnote line an overfull frame pushed into (or under) the footer
                # box still counts -- it is smaller than any footer text
                size = max(s["size"] for s in spans)
                if (size < 4.6 and r.y0 > 150
                        and (r.y1 <= self.footer_top + 0.5 or size < FOOTER_TEXT_MIN_SIZE)
                        and abs(line["dir"][1]) < 0.01):
                    small.append((r, label))
                elif area.contains(fitz.Point(r.x0 + 0.1, (r.y0 + r.y1) / 2)):
                    self.items.append(("text", r, label))
                elif (r.y0 + r.y1) / 2 >= self.footer_top - 0.3 and size > footer_size + 0.3 \
                        and self.footer_top > self.h / 2 and abs(line["dir"][1]) < 0.01:
                    # (a footer in the lower half: a standout frame's full-page fill also touches the bottom edge)
                    # body text an overfull frame pushed into or under the footer box, or off the page (v10.18.0;
                    # step 15 found a bullet of slide 1gr that the footer box covered, and this check did not see
                    # it): larger than the footer's own text, so it is not the footer's
                    self.items.append(("text", r, label))
        # footnote / \source lines: the right-aligned small lines at the bottom,
        # plus the lines of the same (wrapped) block directly above them
        self.footnotes = [r for r, _ in small if r.x1 > self.logo_right - 4]
        rest = sorted((t for t in small if t[0].x1 <= self.logo_right - 4), key=lambda t: -t[0].y1)
        for r, lab in rest:
            if self.footnotes and r.y1 >= min(f.y0 for f in self.footnotes) - 2:
                self.footnotes.append(r)
            else:
                # Not a footnote continuation: still a candidate for `bottom` (an overfull frame can push
                # it into or under the footer box, past `area`'s own bottom edge) and for `left`/`right`,
                # so it must reach self.items regardless of where on the page it landed.
                self.items.append(("text", r, lab))
        for info in page.get_image_info(xrefs=True):
            r = fitz.Rect(info["bbox"])
            if r.intersects(area) and not (r.x0 > self.w - 40 and r.y1 < self.bar_bottom + 1):
                self.items.append(("image", r & page.rect, f"image {r.width:.0f}x{r.height:.0f}"))
        for d in drawings:
            r = fitz.Rect(d["rect"])
            if d.get("color") is not None and d.get("width"):
                # a stroked line has a zero-height (or -width) rect; give it its
                # stroke width, or PyMuPDF treats it as empty
                half = d["width"] / 2
                if r.height < d["width"]:
                    r.y0, r.y1 = r.y0 - half, r.y1 + half
                if r.width < d["width"]:
                    r.x0, r.x1 = r.x0 - half, r.x1 + half
            if is_white(d.get("fill")) and d.get("color") is None:
                continue
            if not r.intersects(area) or r.y0 < top - 0.5 or r.y1 > bottom + 0.5:
                continue
            if r.width > self.w - 1:          # full-width strips (progress strip)
                if r.y0 < self.bar_bottom + 20:
                    self.has_strip = True
                continue
            self.items.append(("drawing", r, f"drawing {r.width:.0f}x{r.height:.0f}"))

    # -- checks ---------------------------------------------------------------------
    def check_top(self, tol, group=None):
        """Top Margin, over all overlay pages of the slide (`group`): an early
        reveal step may show only part of the content."""
        pages = group or [self]
        if not self.standard or any(p.has_strip for p in pages):
            return []                     # a progress strip moves the start on purpose
        items = [it for p in pages for it in p.items]
        if not items:
            return []
        cands = [(r.y0, k, lab) for k, r, lab in items
                 if not (k == "image" and r.x1 > self.w - 0.5)]   # side filler images
        if not cands:
            return []
        y, kind, label = min(cands)
        if abs(y - self.top_margin) > tol:
            return [f"first content at {y:.2f} ({'+' if y > self.top_margin else ''}{y - self.top_margin:.2f} "
                    f"vs. Top Margin {self.top_margin:.2f}): {kind} {label[:40]!r}"]
        return []

    def check_coltop(self, tol, group=None):
        """Every column starts on the Top Margin: a text line with nothing starting
        above it in its own horizontal range (it opens a column; a frame or box
        around it counts as above) must sit on the Top Margin.
        Catches text set beside a taller figure in vertically *centred* minipages
        (LaTeX's default [c] alignment) -- the figure is on the margin, so `top`
        is satisfied, but the text column starts lower (m2k, 2026-10-01). Measured
        on the slide's last overlay page (all reveals shown)."""
        page = (group or [self])[-1]
        if not self.standard or page.has_strip:   # a progress strip moves the start on purpose
            return []
        base_of = {id(r): (b, size, raw, fira) for r, b, size, raw, fira in page.baselines}
        first = min((q.y0 for _, q, _ in page.items), default=0.0)
        # Body text lines only: horizontal (not a rotated source strip or axis
        # label), at least 12 characters (not a piece of a displayed equation set
        # on its own PDF line, like the "=" beside a fraction), starting in the
        # upper half of the page (lower down it's a caption or footnote).
        texts = [(r, lab) for k, r, lab in page.items if k == "text"
                 and id(r) in base_of and len(lab) >= 12 and r.y0 < self.h / 2
                 and base_of[id(r)][1] >= 6           # not a small source line
                 and base_of[id(r)][3]]               # body font: not a piece of a displayed equation
        graphics = [q for k, q, _ in page.items if k != "text" and q.width > 20 and q.height > 20]
        out = []
        for r, lab in sorted(texts, key=lambda t: t[0].y0):
            b, _, raw, _ = base_of[id(r)]
            if r.y0 <= self.top_margin + max(tol, 3.0) or raw <= self.top_margin + max(tol, 3.0):
                continue      # on the margin (raw: tall maths -- brackets, fractions -- reaching it)
            if r.y0 <= first + 0.5:
                continue      # the first content of the slide: that is `top`'s finding
            # a row of a grid: another line elsewhere shares its baseline (a table
            # column whose first cell is empty, an equation's raised fraction)
            if any(abs(b2 - b) < 0.6 and q is not r and (q.x1 < r.x0 or q.x0 > r.x1)
                   for q, b2, _, _, _ in page.baselines):
                continue
            # a label inside a diagram or picture
            centre = fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
            if any(q.contains(centre) for q in graphics):
                continue
            above = [q for k, q, _ in page.items
                     if q is not r and q.y0 < r.y0 - 0.5 and q.y1 > self.top_margin - 5
                     and min(q.x1, r.x1) - max(q.x0, r.x0) > 1]
            if not above:
                out.append(f"column starts at {r.y0:.2f} (+{r.y0 - self.top_margin:.2f} vs. Top Margin "
                           f"{self.top_margin:.2f}) with nothing above it: {lab[:40]!r}")
        return out[:2]

    def check_left(self, tol):
        out = []
        for k, r, lab in self.items:
            if r.x0 < self.left_margin - tol and r.x0 > 0.5:
                out.append(f"{k} starts at x={r.x0:.2f} (Left Margin {self.left_margin:.2f}): {lab[:40]!r}")
        return out[:3]

    def check_right(self, tol):
        out = []
        # a side image's panel, flush with the page's right edge from the title bar down: what is drawn inside it is
        # the picture's own (v10.18.0: a vector side image's strokes were judged against the Right Margin, which a
        # template with a wider logo padding moves left of them)
        panels = [r for k, r, _ in self.items if k in ("drawing", "image") and r.x1 >= self.w - 0.5
                  and r.height > 0.5 * (self.footer_top - self.bar_bottom)]
        for k, r, lab in self.items:
            if any(p.contains(r) for p in panels):
                continue
            if r.x1 > self.logo_right + tol and r.x1 < self.w - 0.5:
                out.append(f"{k} ends at x={r.x1:.2f}, {r.x1 - self.logo_right:.2f} past the "
                           f"Right Margin ({self.logo_right:.2f}): {lab[:40]!r}")
        return out[:3]

    def check_bottom(self, tol, footnote_last_top=FOOTNOTE_LAST_TOP):
        out = []
        limit = (min(r.y0 for r in self.footnotes) if self.footnotes else self.footer_top) - FOOTER_GAP
        fn_top = min((r.y0 for r in self.footnotes), default=self.footer_top)

        def exempt(k, r):
            if k == "image" and r.x1 > self.w - 0.5:
                return True       # side filler image, flush with the footer by design
            if k == "drawing" and r.height < 1.2 and r.y0 >= fn_top - 1:
                return True       # hyperlink underline inside a footnote/source line
            return False
        low = [(r.y1, k, lab) for k, r, lab in self.items if r.y1 > limit + tol and not exempt(k, r)]
        if low:
            y, k, lab = max(low)
            what = "footnote/source line" if self.footnotes else "footer box"
            out.append(f"{k} reaches y={y:.2f}, into the {FOOTER_GAP}pt clearance above the {what} "
                       f"({limit + FOOTER_GAP:.2f}): {lab[:40]!r}")
        if self.standard and self.footnotes:
            last = max(r.y0 for r in self.footnotes)
            if last > footnote_last_top + max(tol, 0.3):
                out.append(f"last footnote line at {last:.2f}, {last - footnote_last_top:.2f} below its "
                           f"usual {footnote_last_top:.2f} (frame overfull?)")
        return out

    def check_bleed(self, tol):
        rules = [r for k, r, lab in self.items if k == "drawing" and r.height < 1.3 and r.width > 15]
        groups: dict[tuple, list[fitz.Rect]] = defaultdict(list)
        for r in rules:
            groups[(round(r.x0), round(r.x1))].append(r)
        out = []
        for (x0, x1), rs in groups.items():
            if len(rs) < 2:
                continue
            y0, y1 = min(r.y0 for r in rs), max(r.y1 for r in rs)
            # rules joined by vertical rules at both ends are a frame (a code
            # panel, \SMCodeFile; a box around a picture), not a table's rules
            sides = [q for k, q, _ in self.items if k == "drawing" and q.width < 1.6
                     and q.height > 3 and q.y0 >= y0 - 1.5 and q.y1 <= y1 + 1.5]
            if (any(abs(q.x0 - rs[0].x0) <= 4 for q in sides)
                    and any(abs(q.x1 - rs[0].x1) <= 4 for q in sides)):
                continue
            texts = [r for k, r, lab in self.items if k == "text" and y0 < (r.y0 + r.y1) / 2 < y1
                     and r.x1 > x0 - 1 and r.x0 < x1 + 1]
            if not texts:
                continue
            tx0, tx1 = min(r.x0 for r in texts), max(r.x1 for r in texts)
            left, right = tx0 - rs[0].x0, rs[0].x1 - tx1
            if left > max(tol, 1.0) or right > max(tol, 1.0):
                out.append(f"table rules {rs[0].x0:.2f}-{rs[0].x1:.2f} extend past the text "
                           f"{tx0:.2f}-{tx1:.2f} (left {left:.2f}, right {right:.2f})")
        return out

    def check_edge(self, tol):
        """The frame number and the footnote lines end on the logo's padding edge: the page's width less
        \\SMFrametitleRightPadding, the line the base's derived shifts (\\SMFooterRightShift, \\SMFootnoteRightShift) put
        them on whatever the template's margin, padding and font are. A PDF without that key is checked against the logo's
        visible right edge, which lies up to a point inside the padding edge (the logo's own margin), with a point of room."""
        padding = self.hooks.get("SMFrametitleRightPadding")
        if padding is None and not self.standard:
            return []                      # no key: the logo's visible edge is the reference, found only under an ordinary title bar
        edge, room = (self.w - padding, 0.0) if padding is not None else (self.logo_right, 1.0)
        ends: list[tuple[str, float]] = []
        numbers = [s["bbox"][2] for block in self.page.get_text("dict")["blocks"] for line in block.get("lines", [])
                   for s in line["spans"] if s["text"].strip().isdigit() and s["bbox"][1] >= self.footer_top - 1
                   and abs(line["dir"][1]) < 0.01]
        if numbers:
            ends.append(("frame number", max(numbers)))
        ends += [("footnote line", r.x1) for r in self.footnotes if r.x1 > self.logo_right - 4]
        return [f"{what} ends at x={x:.2f}, {x - edge:+.2f} from the logo's padding edge ({edge:.2f})"
                for what, x in ends if abs(x - edge) > tol + room][:3]

    def check_titlepad(self, tol):
        """On a title frame (\\titleframe: a colored box from the page's corner as high as \\SMTitleframeBoxHeight, narrower
        than the page) the last line of the subtitle stands \\SMTitleframeBottomPad above the box's bottom edge, measured from
        the bottom of its line box. TeX's line box reaches down to the deepest glyph of the line when that is deeper than
        its strut, so for a last line with descenders (g, j, p, q, y: ink more than a point under the baseline) the
        ink's bottom edge is the line box's; a last line without any is not checked, its depth is the strut's and
        the PDF does not say what that is. Needs the box height and the pad in the PDF; a quote frame's box (another
        height) is left alone."""
        if "SMTitleframeBoxHeight" not in self.hooks or "SMTitleframeBottomPad" not in self.hooks:
            return []
        height, pad = self.hooks["SMTitleframeBoxHeight"], self.hooks["SMTitleframeBottomPad"]
        if abs(height - self.hooks.get("SMQuoteBoxHeight", -1.0)) < 0.2:
            return []                       # a title frame and a quote frame of one height cannot be told apart
        boxes = [d["rect"] for d in self.page.get_drawings() if d.get("fill") is not None and not is_white(d["fill"])
                 and d["rect"].x0 < 0.5 and d["rect"].y0 < 0.5 and d["rect"].width < self.w - 1
                 and abs(d["rect"].height - height) < 0.2]
        if not boxes:
            return []
        box = boxes[0]
        lines = [(r, b) for r, b, size, _, _ in self.baselines if size > 8 and r.y1 < box.y1 + 0.5 and r.x1 <= box.x1 + 0.5]
        if not lines:
            return []
        rect, baseline = max(lines, key=lambda t: t[1])
        clip = fitz.Rect(rect.x0, baseline - 6, min(rect.x1 + 2, box.x1), box.y1 - 0.2)
        ink_bottom = ink_extent(self.page, clip)
        if ink_bottom is None or ink_bottom - baseline < 1.0:
            return []                       # no descenders: the line box is the strut's, which the PDF does not record
        gap = box.y1 - ink_bottom
        if abs(gap - pad) > tol:
            return [f"the last subtitle line's deepest glyph ends {gap:.2f} above the box's bottom edge ({box.y1:.2f}); "
                    f"the pad says {pad:.2f}"]
        return []


def ink_extent(page: fitz.Page, clip: fitz.Rect, dpi: int = 1152) -> float | None:
    """The bottom edge (page y, bp) of the lowest ink in `clip`: pixels that differ from the clip's top right corner."""
    pix = page.get_pixmap(dpi=dpi, clip=clip, colorspace=fitz.csRGB, alpha=False)
    samples, n = pix.samples, pix.n
    corner = (pix.width - 1) * n
    background = samples[corner:corner + 3]
    for y in range(pix.height - 1, -1, -1):
        row = y * pix.width * n
        if any(max(abs(samples[row + x * n + k] - background[k]) for k in range(3)) > 60 for x in range(pix.width)):
            return clip.y0 + (y + 1) * 72 / dpi
    return None


def footer_text_size(blocks: list[dict], footer_top: float) -> float:
    """The size of the footer's own text: the frame number's (the rightmost digits inside the footer box, set in the
    footer text size, the largest text the footer has), else FOOTER_TEXT_MAX_SIZE. Body text larger than this inside
    or under the footer box is not the footer's."""
    numbers = [s for b in blocks for line in b.get("lines", []) for s in line["spans"]
               if s["text"].strip().isdigit() and s["bbox"][1] >= footer_top - 1]
    return max(numbers, key=lambda s: s["bbox"][2])["size"] if numbers else FOOTER_TEXT_MAX_SIZE


def usual_footnote_top(pages: list[Page]) -> float:
    """Where the last footnote line of a frame sits when nothing pushes it. The footer, the footnote size and
    the footnote offset are the template's, so the number is the deck's own: the highest last line of any
    frame (an overfull frame pushes it lower, never higher), plus FOOTNOTE_MARKER_ALLOWANCE for the frames
    whose last line is a source line, which has no raised marker to lift its line box. A deck without a
    footnote keeps the SlideMage template's. Only the last step of a slide counts: on an earlier one a footnote
    of revealed content is hidden (v10.12.0), and the visible lines above it end higher than the block does."""
    last_steps = [p for i, p in enumerate(pages)
                  if not p.slide_id or i + 1 == len(pages) or pages[i + 1].slide_id != p.slide_id]
    tops = [max(r.y0 for r in p.footnotes) for p in last_steps if p.standard and p.footnotes]
    return min(tops) + FOOTNOTE_MARKER_ALLOWANCE if tops else FOOTNOTE_LAST_TOP


def jitter(prev: Page, cur: Page, tol) -> list[str]:
    """Things on both overlay pages must not move."""
    def index(p):
        seen = defaultdict(list)
        for k, r, lab in p.items:
            key = (k, lab) if k == "text" else (k, round(r.width, 1), round(r.height, 1))
            seen[key].append(r)
        return {key: rs[0] for key, rs in seen.items() if len(rs) == 1}
    a, b = index(prev), index(cur)
    moves = []
    for key in a.keys() & b.keys():
        ra, rb = a[key], b[key]
        dx, dy = rb.x0 - ra.x0, rb.y0 - ra.y0
        if max(abs(dx), abs(dy)) > max(tol, 0.25):
            moves.append((max(abs(dx), abs(dy)), dx, dy, key))
    if not moves:
        return []
    moves.sort(reverse=True)
    _, dx, dy, key = moves[0]
    return [f"{len(moves)} element(s) move between overlay steps, largest dx={dx:.2f} dy={dy:.2f}: "
            f"{key[0]} {str(key[1])[:40]!r}"]


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pdf", nargs="+")
    ap.add_argument("--project", help="the project whose slide files hold the exemptions")
    ap.add_argument("--checks", default=",".join(CHECKS))
    ap.add_argument("--tol", type=float, default=0.6, help="tolerance in pt (default 0.6)")
    ap.add_argument("--ignore-exemptions", action="store_true")
    args = ap.parse_args(argv)
    checks = [c for c in args.checks.split(",") if c]
    total = 0
    exempted = 0
    for path in args.pdf:
        doc = fitz.open(path)
        project = find_project(Path(path), args.project)
        info = pdf_info(doc)
        hooks = pdf_hooks(doc)
        pages = [Page(p, info["top_margin"], info["left_margin"], info["ascender"], info["title_bar_bottom"], hooks)
                 for p in doc]
        footnote_top = usual_footnote_top(pages)
        # consecutive pages of one slide = its overlay steps
        group_of: dict[int, list[Page]] = {}
        start = 0
        for i in range(1, len(pages) + 1):
            if i == len(pages) or not pages[i].slide_id or pages[i].slide_id != pages[start].slide_id:
                for j in range(start, i):
                    group_of[j] = pages[start:i]
                start = i
        counts: dict[str, int] = defaultdict(int)
        prev = None
        for number, page in enumerate(pages, 1):
            last_of_group = group_of[number - 1][-1] is page
            findings = []
            for c in checks:
                if c == "jitter":
                    if prev is not None and prev.slide_id and prev.slide_id == page.slide_id:
                        findings += [("jitter", f) for f in jitter(prev, page, args.tol)]
                elif c in ("top", "coltop"):
                    if last_of_group:   # once per slide, over all its steps
                        findings += [(c, f) for f in getattr(page, "check_" + c)(args.tol, group_of[number - 1])]
                else:
                    extra = (footnote_top,) if c == "bottom" else ()
                    findings += [(c, f) for f in getattr(page, "check_" + c)(args.tol, *extra)]
            prev = page
            skips = set() if args.ignore_exemptions or not page.slide_id else exemptions(project, page.slide_id)
            for c, f in findings:
                if c in skips:
                    exempted += 1
                    continue
                counts[c] += 1
                total += 1
                print(f"{Path(path).name} p{number} {page.slide_id or '-'}: {c}: {f}")
        summary = ", ".join(f"{c} {counts[c]}" for c in checks)
        print(f"== {Path(path).name}: {len(doc)} pages; {summary}")
    if exempted:
        print(f"({exempted} finding(s) exempted by layout-check comments)")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
