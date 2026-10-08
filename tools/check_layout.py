"""Check the page layout of a compiled deck against the deck-wide margins.

Checks, per page (all coordinates in PDF units, the same "pt" every measurement
in the slide comments and the preamble uses -- 41.58 Top Margin etc.):

  top     first body content (text, image or drawing) starts on the Top Margin line
          (41.58, the top of a plain first line's line box); only on frames with the
          ordinary title bar
  coltop  every column starts there too: a text line with nothing above it in its own
          horizontal range sits on the Top Margin (text beside a taller figure in
          vertically centred minipages fails this)
  left    no body content left of the Left Margin (12.55, the title text's left edge)
  right   no body content right of the Right Margin (the logo's right edge), except
          things deliberately flush with the page edge (side images, strips)
  bottom  body content stays clear of the footnote/source lines and the footer box, and
          the last footnote line sits at its usual height (a lower one means the frame is
          overfull and pushed it down)
  bleed   table rules (booktabs \\toprule etc.) extend no further than the table's text
  jitter  between overlay pages of one slide nothing that is on both pages moves

A slide can exempt itself from a check -- a deliberate exception, e.g. a figure centred
between title bar and footer -- with a comment line in its own slide file:

  %% layout-check: skip top -- figure is centred vertically (direct instruction)

(several checks comma-separated, or "all"). Exempted findings are counted, not listed.

The margins are the framework's (Slidemaster_preamble_base.tex), the same in
every template. Exemptions are read from the slide files of the project the PDF
belongs to: --project, else the folder with slide_ids.csv above the PDF, else
$SLIDEMASTER_PROJECT.

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

CHECKS = ("top", "coltop", "left", "right", "bottom", "bleed", "jitter")

TOP_MARGIN = 41.58       # top of a plain first body line's line box
LEFT_MARGIN = 12.55      # title text's left edge (bullet dots start at 12.75)
FOOTNOTE_LAST_TOP = 242.64  # line-box top of the last footnote line when nothing pushes it
FOOTER_GAP = 1.0         # minimum clearance above footnotes / footer box
FOOTER_TEXT_MIN_SIZE = 3.6  # footer text is 3.99 pt and up; footnote/source lines 3.19 pt
FIRA_ASCENDER = 0.935    # Fira Sans ascender / em: a text line's top is baseline - this x size

ID_RE = re.compile(r"slide id: (\w+)")
SKIP_RE = re.compile(r"^\s*%+\s*layout-check:\s*skip\s+([a-z, ]+)", re.M)

_skip_cache: dict[tuple[Path, str], set[str]] = {}


def find_project(pdf: Path, given: str | None) -> Path | None:
    """The project a PDF belongs to: --project, the folder with slide_ids.csv
    above the PDF, or $SLIDEMASTER_PROJECT."""
    if given:
        return Path(given).resolve()
    for folder in pdf.resolve().parents:
        if (folder / "slide_ids.csv").is_file():
            return folder
    env = os.environ.get("SLIDEMASTER_PROJECT")
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


def logo_visible_right(page: fitz.Page, width: float, bar_bottom: float) -> float:
    """The institute logo's visible right edge: the rightmost rendered pixel
    in the top-right corner that differs from the page's corner colour.
    Measured on pixels, not on the PDF's drawing list: a logo's outermost
    shape can be a white card with a dark outline (SlideMage's own logo) or
    a small text mark (MCI's "®"), and the drawing-list version skipped
    both and put the margin 2.4pt (SlideMage) to 12.7pt (MCI) too far left."""
    top = max(bar_bottom, 20.0)
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


class Page:
    """The measurable pieces of one page: frame chrome and body content."""

    def __init__(self, page: fitz.Page):
        self.page = page
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
        self.standard = self.slide_id is not None and 20 < self.bar_bottom < 30

        # logo: its visible right edge, the Right Margin
        self.logo_right = logo_visible_right(page, self.w, self.bar_bottom)

        self.items: list[tuple[str, fitz.Rect, str]] = []   # (kind, rect, label)
        self.footnotes: list[fitz.Rect] = []
        self.vertical: list[fitz.Rect] = []                  # rotated text lines
        # horizontal text lines: (rect, baseline y, largest font size, glyph-box top,
        # set in the body font Fira Sans -- not only maths fonts)
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
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = [s for s in line["spans"] if s["text"].strip()
                         and (round(s["origin"][0], 1), round(s["origin"][1], 1)) not in invisible]
                if not spans:
                    continue
                r = fitz.Rect(line["bbox"])
                if not r.intersects(page.rect) or r.is_empty:
                    continue
                # top = baseline - Fira Sans ascender, from the non-superscript
                # spans only: a footnote marker or a math font's taller ascender
                # would otherwise lift the line box without the text moving
                body_spans = [s for s in spans if not s["flags"] & 1] or spans
                r.y0 = min(s["origin"][1] - FIRA_ASCENDER * s["size"] for s in body_spans)
                label = "".join(s["text"] for s in spans).strip()
                if abs(line["dir"][1]) > 0.5:
                    self.vertical.append(r)      # rotated (source strip, axis label)
                else:
                    self.baselines.append((r, max(s["origin"][1] for s in spans),
                                           max(s["size"] for s in spans), line["bbox"][1],
                                           any("Fira" in s["font"] for s in spans)))
                # a footnote line an overfull frame pushed into (or under) the footer
                # box still counts -- it is smaller than any footer text
                size = max(s["size"] for s in spans)
                if (size < 4.6 and r.y0 > 150
                        and (r.y1 <= self.footer_top + 0.5 or size < FOOTER_TEXT_MIN_SIZE)
                        and abs(line["dir"][1]) < 0.01):
                    small.append((r, label))
                elif area.contains(fitz.Point(r.x0 + 0.1, (r.y0 + r.y1) / 2)):
                    self.items.append(("text", r, label))
        # footnote / \source lines: the right-aligned small lines at the bottom,
        # plus the lines of the same (wrapped) block directly above them
        self.footnotes = [r for r, _ in small if r.x1 > self.logo_right - 4]
        rest = sorted((t for t in small if t[0].x1 <= self.logo_right - 4), key=lambda t: -t[0].y1)
        for r, lab in rest:
            if self.footnotes and r.y1 >= min(f.y0 for f in self.footnotes) - 2:
                self.footnotes.append(r)
            elif area.contains(fitz.Point(r.x0 + 0.1, (r.y0 + r.y1) / 2)):
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
        if abs(y - TOP_MARGIN) > tol:
            return [f"first content at {y:.2f} ({'+' if y > TOP_MARGIN else ''}{y - TOP_MARGIN:.2f} "
                    f"vs. Top Margin {TOP_MARGIN}): {kind} {label[:40]!r}"]
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
            if r.y0 <= TOP_MARGIN + max(tol, 3.0) or raw <= TOP_MARGIN + max(tol, 3.0):
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
                     if q is not r and q.y0 < r.y0 - 0.5 and q.y1 > TOP_MARGIN - 5
                     and min(q.x1, r.x1) - max(q.x0, r.x0) > 1]
            if not above:
                out.append(f"column starts at {r.y0:.2f} (+{r.y0 - TOP_MARGIN:.2f} vs. Top Margin "
                           f"{TOP_MARGIN}) with nothing above it: {lab[:40]!r}")
        return out[:2]

    def check_left(self, tol):
        out = []
        for k, r, lab in self.items:
            if r.x0 < LEFT_MARGIN - tol and r.x0 > 0.5:
                out.append(f"{k} starts at x={r.x0:.2f} (Left Margin {LEFT_MARGIN}): {lab[:40]!r}")
        return out[:3]

    def check_right(self, tol):
        out = []
        for k, r, lab in self.items:
            if r.x1 > self.logo_right + tol and r.x1 < self.w - 0.5:
                out.append(f"{k} ends at x={r.x1:.2f}, {r.x1 - self.logo_right:.2f} past the "
                           f"Right Margin ({self.logo_right:.2f}): {lab[:40]!r}")
        return out[:3]

    def check_bottom(self, tol):
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
            if last > FOOTNOTE_LAST_TOP + max(tol, 0.3):
                out.append(f"last footnote line at {last:.2f}, {last - FOOTNOTE_LAST_TOP:.2f} below its "
                           f"usual {FOOTNOTE_LAST_TOP} (frame overfull?)")
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
        pages = [Page(p) for p in doc]
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
                    findings += [(c, f) for f in getattr(page, "check_" + c)(args.tol)]
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
