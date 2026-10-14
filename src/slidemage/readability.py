"""The readability check: can an audience read a rendered slide? Deterministic, no AI, no MuPDF and no Qt in here.

readability_pdf.py reads a rendered PDF (in the raster child process) into `Page` data; `analyse()` classifies the
text of the last page of each slide, applies the rules below and gives a `Report` of `Finding`s that the UI shows,
the agent tool prints (`to_text()`) and the "Make readable" task will hand to a model (`to_dict()`).

Sizes are judged relative to the slide height, not in LaTeX points, so that a projected slide is judged whatever
its paper size: a 7.5 in (540 pt) slide is the reference for the "projected pt" in the messages. Every threshold
is a field of `Thresholds` (one frozen set of defaults, `DEFAULTS`):

- body text >= 3.3 % of the slide height (about 18 pt on a 7.5 in slide; beamer's 11 pt body on a 96 mm slide is
  4.0 %, \\footnotesize 3.3 %); within 5 % above the floor is a warning (9 pt code on a 90 mm slide, 3.5 %, passes);
- headings: the same floor, and not smaller than the slide's own body text (a warning);
- citations and footnotes >= 2.2 % (\\tiny at an 11 pt base) as a hard floor: small print, but a reader in the
  back row can still make it out;
- text in figures >= 2.6 %: figure labels are read at a glance, so they get a looser floor than running text;
- a raster image cannot be read inside, so only its displayed size counts: the slide's largest image showing
  less than 25 % of the slide area, or narrower than 35 % of the width unless it fills 75 % of the height (a tall
  portrait cannot grow without cropping), "may be too small to read" (a warning). Images below 3 % of the slide
  (logos, icons) and pictures covering 80 % or more (backgrounds) are not judged;
- contrast: WCAG 4.5:1, 3:1 for headings and text from 5 % of the slide height (large text);
- clipped text (outside the page or running into the footer) and overlapping lines from different lines are
  errors; more than 90 words or 14 lines of body text on one slide, and lines set closer than 1.0 times the
  font size, are warnings.

Severity: error (below a floor, clipped or overlapping, contrast) or warning (near a floor, small image, density,
line spacing).

Classification (per line, as the PDF sets it; the footer and the slide-id stamp are not content and are left out):
text whose centre lies in an image or a vector figure is `figure text`; a line that starts like a source or a
footnote (Source:, Quelle:, Image source, a footnote symbol, (c)), or is small print low on the slide or turned
sideways (as the template sets \\source), is a `citation`; the lines of the title bar at the top, and larger text in
the upper third, are `heading`s; everything else is `body`. The text size of a line is that of its dominant font
(a superscript marker or a bullet does not make a line small), and lines without letters or digits are ignored.
Backgrounds come from the filled rectangles of the page (the topmost one under the text, else white); text over a
raster image has no known background and is left out of the contrast rule.

Pages and slides: a slide may have several overlay pages. The last page of each slide's run of pages (the same
rule as the slide snapshots, slide_snapshot.slide_runs) is judged; earlier pages only for clipped text.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Optional

ERROR, WARNING = "error", "warning"
BODY, HEADING, CITATION, FIGURE_TEXT, IMAGE = "body", "heading", "citation", "figure text", "image"
TEXT_SIZE, IMAGE_SIZE, CONTRAST, CLIPPED, OVERLAP, DENSITY, SPACING = (
    "text_size", "image_size", "contrast", "clipped", "overlap", "density", "line_spacing")
MIN, MAX = "min", "max"          # a measured value must be at least / at most its threshold


@dataclass(frozen=True)
class Thresholds:
    reference_height_pt: float = 540.0     # the 7.5 in slide the projected sizes are quoted for
    body_pct: float = 3.3                  # text sizes: % of the slide height
    citation_pct: float = 2.2
    figure_text_pct: float = 2.6
    near_factor: float = 1.05              # a size below floor * this is a warning
    image_min_area_pct: float = 25.0       # images: % of the slide area, width and height
    image_min_width_pct: float = 35.0
    image_tall_pct: float = 75.0
    image_ignore_area_pct: float = 3.0
    image_background_pct: float = 80.0
    figure_min_area_pct: float = 4.0       # a vector figure covers at least this much of the slide
    contrast: float = 4.5
    contrast_large: float = 3.0
    large_text_pct: float = 5.0
    max_words: int = 90
    max_lines: int = 14
    min_line_spacing: float = 1.0          # baseline distance / font size
    overlap_pct: float = 25.0              # of the smaller line, once both are shrunk to their core
    clip_tolerance_pct: float = 1.0        # % of the slide height: a font's box reaches beyond its ink
    footer_band_pct: float = 95.0          # where the footer starts when no filled bar shows it
    title_band_pct: float = 15.0           # the title bar: lines starting above this are headings
    title_search_pct: float = 35.0         # larger text above this is a heading too
    heading_ratio: float = 1.15            # "larger": at least this times the body size
    citation_ratio: float = 0.75           # small print: at most this times the body size
    citation_band_pct: float = 65.0        # ... and starting below this (or turned sideways)


DEFAULTS = Thresholds()
LABELS = {BODY: "Body text", HEADING: "Heading", CITATION: "Source or footnote text", FIGURE_TEXT: "Text in a figure",
          IMAGE: "Image"}
_SOURCE_RE = re.compile(
    r"^\s*(?:[£¥₹₽₺₴₪₫₦₡₩ƒ¢€†‡§*]\s*)?(?:(?:image |figure |data )?sources?\b|quellen?\b|bildquellen?\b|credits?\b|"
    r"photos?\b|fotos?\b|©|\[\d+\])", re.IGNORECASE)
_STAMP_RE = re.compile(r"slide id:", re.IGNORECASE)


# -- the page data (readability_pdf.py) --------------------------------------------------------------------------

@dataclass(frozen=True)
class Line:
    text: str
    size: float                    # points
    color: int                     # 0xRRGGBB
    origin_y: float
    block: int
    bbox: tuple[float, float, float, float]
    vertical: bool

    @property
    def alnum(self) -> int:
        return sum(ch.isalnum() for ch in self.text)


@dataclass(frozen=True)
class Placed:
    bbox: tuple[float, float, float, float]
    width: int                     # pixels of the picture itself
    height: int


@dataclass(frozen=True)
class Page:
    width: float
    height: float
    slide_id: Optional[str]
    lines: list[Line]
    images: list[Placed]
    fills: list[tuple]             # (x0, y0, x1, y1, 0xRRGGBB) in paint order
    figures: list[tuple]

    @classmethod
    def from_dict(cls, data: dict) -> "Page":
        return cls(
            data["width"], data["height"], data.get("slide_id"),
            [Line(**{**line, "bbox": tuple(line["bbox"])}) for line in data["lines"]],
            [Placed(tuple(image["bbox"]), image["width"], image["height"]) for image in data["images"]],
            [tuple(fill) for fill in data["fills"]], [tuple(box) for box in data["figures"]])

    def pct(self, size: float) -> float:
        return size / self.height * 100


# -- the findings ------------------------------------------------------------------------------------------------

def _num(value: float) -> str:
    return f"{round(value, 2):g}"


@dataclass
class Finding:
    slide_id: str
    page: int                          # 1-based page of the PDF
    rule: str
    cls: str
    severity: str
    measured: float
    threshold: float
    needs: str                         # MIN or MAX: what the threshold asks of the measured value
    unit: str
    bbox: tuple[float, float, float, float]    # fractions of the page: left, top, right, bottom
    excerpt: str
    suggestion: str
    count: int = 1                     # lines (text) it covers
    file: str = ""                     # the slide's source file name
    image: str = ""                    # an image finding: the file, when the slide's source names it
    pixels: tuple[int, int] = ()       # an image finding: the picture's own size

    @property
    def measure_text(self) -> str:
        return f"{_num(self.measured)} {self.unit}, needs {'≥' if self.needs == MIN else '≤'} {_num(self.threshold)}"

    def to_text(self) -> str:
        what = self.image or self.excerpt or (f"{self.pixels[0]}×{self.pixels[1]} px picture" if self.pixels else "")
        return (f"{self.severity} · {LABELS[self.cls].lower()} · {self.measure_text}"
                + (f" · {self.count} lines" if self.count > 1 else "")
                + (f" · \"{what}\"" if what else "") + f"\n    {self.suggestion}")

    def to_dict(self) -> dict:
        data = asdict(self)
        data["bbox"] = [round(v, 3) for v in self.bbox]
        data["measured"], data["threshold"] = round(self.measured, 2), round(self.threshold, 2)
        return data


@dataclass
class SlideReport:
    slide_id: str
    page: int                          # the judged page
    file: str = ""
    findings: list[Finding] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == WARNING]

    def to_dict(self) -> dict:
        return dict(slide=self.slide_id, file=self.file, page=self.page, findings=[f.to_dict() for f in self.findings])


@dataclass
class Report:
    slides: list[SlideReport]
    thresholds: Thresholds = DEFAULTS

    @property
    def findings(self) -> list[Finding]:
        return [f for slide in self.slides for f in slide.findings]

    @property
    def summary(self) -> str:
        errors = sum(1 for slide in self.slides if slide.errors)
        warnings = sum(1 for slide in self.slides if slide.warnings and not slide.errors)
        return (f"{len(self.slides)} slide{'' if len(self.slides) == 1 else 's'} checked · {errors} with errors · "
                f"{warnings} with warnings")

    def to_text(self, limit: Optional[int] = None) -> str:
        """The summary and each slide's findings; `limit` slides at most (then it says how many more)."""
        lines = [self.summary + "."]
        with_findings = [slide for slide in self.slides if slide.findings]
        for slide in with_findings[:limit]:
            lines.append(f"\n{slide.slide_id}" + (f" ({slide.file})" if slide.file else "") + f", page {slide.page}:")
            lines += ["  " + finding.to_text().replace("\n", "\n  ") for finding in slide.findings]
        if limit is not None and len(with_findings) > limit:
            lines.append(f"\n... and {len(with_findings) - limit} more slides with findings.")
        if len(lines) == 1:
            lines[0] += " Nothing to report."
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return dict(summary=self.summary, thresholds=asdict(self.thresholds),
                    slides=[slide.to_dict() for slide in self.slides if slide.findings])


# -- the rules ---------------------------------------------------------------------------------------------------

@dataclass
class _Item:
    line: Line
    cls: str
    pct: float
    background: Optional[int]          # None: unknown (a picture behind the text)


def _contains(box, x: float, y: float) -> bool:
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def _union(boxes) -> tuple[float, float, float, float]:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _luminance(color: int) -> float:
    def channel(value: int) -> float:
        value /= 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(color >> 16 & 255) + 0.7152 * channel(color >> 8 & 255) + 0.0722 * channel(color & 255)


def contrast_ratio(first: int, second: int) -> float:
    """The WCAG contrast ratio of two 0xRRGGBB colours (1 to 21)."""
    light, dark = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


class _PageCheck:
    """The rules applied to one page."""

    def __init__(self, page: Page, number: int, slide_id: str, thresholds: Thresholds) -> None:
        self.page, self.number, self.slide_id, self.t = page, number, slide_id, thresholds
        self.footer_top = self._footer_top()
        self.figure_boxes = [image.bbox for image in page.images if self._area_pct(image.bbox) < thresholds.image_background_pct]
        self.figure_boxes += [box for box in page.figures if self._area_pct(box) >= thresholds.figure_min_area_pct]
        self.lines = [line for line in page.lines if not _STAMP_RE.search(line.text)]
        self.content = [line for line in self.lines if self._centre(line)[1] < self.footer_top and line.alnum >= 2]
        self.body_size = self._body_size()
        self.items = [self._item(line) for line in self.content]

    # -- reading the page

    def _area_pct(self, box) -> float:
        return (box[2] - box[0]) * (box[3] - box[1]) / (self.page.width * self.page.height) * 100

    @staticmethod
    def _centre(line: Line) -> tuple[float, float]:
        return (line.bbox[0] + line.bbox[2]) / 2, (line.bbox[1] + line.bbox[3]) / 2

    def _footer_top(self) -> float:
        width, height = self.page.width, self.page.height
        bars = [fill[1] for fill in self.page.fills
                if fill[0] <= 0.02 * width and fill[2] >= 0.98 * width and fill[3] >= 0.98 * height
                and 0.01 * height <= fill[3] - fill[1] <= 0.2 * height]
        return min(bars) if bars else self.t.footer_band_pct / 100 * height

    def _body_size(self) -> Optional[float]:
        """The size most characters below the title bar are set in."""
        sizes: Counter = Counter()
        for line in self.content:
            if not line.vertical and line.bbox[1] >= self.t.title_band_pct / 100 * self.page.height \
                    and not self._in_figure(line):
                sizes[round(line.size * 4) / 4] += line.alnum
        return sizes.most_common(1)[0][0] if sizes else None

    def _in_figure(self, line: Line) -> bool:
        x, y = self._centre(line)
        return any(_contains(box, x, y) for box in self.figure_boxes)

    def _background(self, line: Line) -> Optional[int]:
        x, y = self._centre(line)
        if any(_contains(image.bbox, x, y) for image in self.page.images):
            return None
        return next((fill[4] for fill in reversed(self.page.fills) if _contains(fill, x, y)), 0xFFFFFF)

    def _item(self, line: Line) -> _Item:
        t, page = self.t, self.page
        if self._in_figure(line):
            cls = FIGURE_TEXT
        elif _SOURCE_RE.match(line.text) or (
                self.body_size and line.size <= t.citation_ratio * self.body_size
                and (line.vertical or line.bbox[1] >= t.citation_band_pct / 100 * page.height)):
            cls = CITATION
        elif line.bbox[1] < t.title_band_pct / 100 * page.height:
            cls = HEADING if not self.body_size or line.size >= t.citation_ratio * self.body_size else CITATION
        elif self.body_size and line.bbox[1] < t.title_search_pct / 100 * page.height \
                and line.size >= t.heading_ratio * self.body_size and not line.vertical:
            cls = HEADING
        else:
            cls = BODY
        return _Item(line, cls, page.pct(line.size), self._background(line))

    # -- the findings

    def _finding(self, rule: str, cls: str, severity: str, measured: float, threshold: float, needs: str, unit: str,
                 lines: list[Line], suggestion: str, excerpt: Optional[str] = None) -> Finding:
        box = _union([line.bbox for line in lines])
        page = self.page
        return Finding(
            self.slide_id, self.number, rule, cls, severity, measured, threshold, needs, unit,
            (box[0] / page.width, box[1] / page.height, box[2] / page.width, box[3] / page.height),
            (excerpt if excerpt is not None else lines[0].text)[:80], suggestion, len(lines))

    def projected(self, pct: float) -> str:
        return f"≈ {pct / 100 * self.t.reference_height_pt:.0f} pt projected"

    def all_findings(self) -> list[Finding]:
        found = [*self.text_sizes(), *self.contrast(), *self.clipping(), *self.overlaps(), *self.density(),
                 *self.spacing(), *self.images()]
        return sorted(found, key=lambda f: f.severity != ERROR)

    def text_sizes(self) -> list[Finding]:
        t = self.t
        floors = {BODY: t.body_pct, HEADING: t.body_pct, CITATION: t.citation_pct, FIGURE_TEXT: t.figure_text_pct}
        advice = {BODY: "enlarge to \\small or larger, or split the slide",
                  HEADING: "use a larger title size or a shorter title",
                  CITATION: "use a larger footnote size, shorten the reference, or move it to the notes",
                  FIGURE_TEXT: "enlarge the figure, or redraw it with larger labels"}
        found = []
        for cls, floor in floors.items():
            items = [item for item in self.items if item.cls == cls]
            for severity, chosen in ((ERROR, [i for i in items if i.pct < floor]),
                                     (WARNING, [i for i in items if floor <= i.pct < floor * t.near_factor])):
                if chosen:
                    worst = min(chosen, key=lambda item: item.pct)
                    what = "is below the floor" if severity == ERROR else "is close to the floor"
                    found.append(self._finding(
                        TEXT_SIZE, cls, severity, worst.pct, floor, MIN, "% of slide height", [i.line for i in chosen],
                        f"{LABELS[cls]} {worst.pct:.1f} % of slide height ({self.projected(worst.pct)}) {what} of "
                        f"{floor:g} %: {advice[cls]}.", worst.line.text))
        small = [i for i in self.items if i.cls == HEADING and self.body_size
                 and floors[HEADING] * t.near_factor <= i.pct < self.page.pct(self.body_size) * 0.98]
        if small:
            worst = min(small, key=lambda item: item.pct)
            body = self.page.pct(self.body_size)
            found.append(self._finding(
                TEXT_SIZE, HEADING, WARNING, worst.pct, body, MIN, "% of slide height", [i.line for i in small],
                f"Heading {worst.pct:.1f} % of slide height is smaller than the slide's body text ({body:.1f} %): "
                "make the title at least as large as the body.", worst.line.text))
        return found

    def contrast(self) -> list[Finding]:
        low = []
        for item in self.items:
            if item.background is None:
                continue
            ratio = contrast_ratio(item.line.color, item.background)
            large = item.cls == HEADING or item.pct >= self.t.large_text_pct
            limit = self.t.contrast_large if large else self.t.contrast
            if ratio < limit:
                low.append((ratio, limit, item))
        if not low:
            return []
        ratio, limit, worst = min(low, key=lambda entry: entry[0])
        return [self._finding(
            CONTRAST, worst.cls, ERROR, ratio, limit, MIN, ":1", [entry[2].line for entry in low],
            f"Contrast {ratio:.1f}:1 between the text colour and its background; needs ≥ {limit:g}:1: use a darker "
            "text colour or a lighter background.", worst.line.text)]

    def clipping(self) -> list[Finding]:
        page, tolerance = self.page, self.t.clip_tolerance_pct / 100 * self.page.height
        off = [line for line in self.lines if self._centre(line)[1] < self.footer_top and (
            line.bbox[0] < -tolerance or line.bbox[1] < -tolerance
            or line.bbox[2] > page.width + tolerance or line.bbox[3] > page.height + tolerance)]
        into_footer = [line for line in self.content if line.bbox[3] > self.footer_top + tolerance]
        found = []
        if off:
            overhang = max(max(-line.bbox[0], -line.bbox[1], line.bbox[2] - page.width, line.bbox[3] - page.height)
                           for line in off)
            found.append(self._finding(
                CLIPPED, BODY, ERROR, overhang, 0, MAX, "pt beyond the page", off,
                "Text is cut off by the edge of the slide: shorten it, reduce its size or move it."))
        if into_footer:
            found.append(self._finding(
                CLIPPED, BODY, ERROR, max(line.bbox[3] for line in into_footer) - self.footer_top, 0, MAX,
                "pt into the footer", into_footer,
                "Text runs into the footer: shorten it, reduce what is on the slide or split it."))
        return found

    def overlaps(self) -> list[Finding]:
        items = [i for i in self.items if not i.line.vertical]

        def core(line: Line):
            shrink = (line.bbox[3] - line.bbox[1]) * 0.2
            return line.bbox[0], line.bbox[1] + shrink, line.bbox[2], line.bbox[3] - shrink

        found = []
        for index, first in enumerate(items):
            for second in items[index + 1:]:
                if first.cls == second.cls == FIGURE_TEXT or abs(first.line.size - second.line.size) > 0.25 * max(
                        first.line.size, second.line.size):
                    continue
                a, b = core(first.line), core(second.line)
                width, height = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
                if width <= 0 or height <= 0:
                    continue
                smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
                share = width * height / smaller * 100 if smaller > 0 else 0
                if share > self.t.overlap_pct:
                    found.append(self._finding(
                        OVERLAP, first.cls, ERROR, share, self.t.overlap_pct, MAX, "% of the smaller line",
                        [first.line, second.line],
                        "Text overlaps other text: add space between the lines or reduce what is on the slide.",
                        f"{first.line.text[:35]} / {second.line.text[:35]}"))
        return found[:5]

    def density(self) -> list[Finding]:
        body = [i.line for i in self.items if i.cls == BODY and not i.line.vertical]
        words = sum(1 for line in body for word in line.text.split() if any(ch.isalnum() for ch in word))
        if not body or (words <= self.t.max_words and len(body) <= self.t.max_lines):
            return []
        by_words = words > self.t.max_words
        return [self._finding(
            DENSITY, BODY, WARNING, words if by_words else len(body),
            self.t.max_words if by_words else self.t.max_lines, MAX, "words" if by_words else "lines", body,
            f"{words} words in {len(body)} lines of body text (up to {self.t.max_words} words or "
            f"{self.t.max_lines} lines read well): cut to the key points or split the slide.")]

    def spacing(self) -> list[Finding]:
        blocks: dict[int, list[Line]] = {}
        for item in self.items:
            if item.cls == BODY and not item.line.vertical:
                blocks.setdefault(item.line.block, []).append(item.line)
        tight = []
        for lines in blocks.values():
            lines.sort(key=lambda line: line.origin_y)
            for first, second in zip(lines, lines[1:]):
                size = min(first.size, second.size)
                distance = second.origin_y - first.origin_y
                same_column = min(first.bbox[2], second.bbox[2]) - max(first.bbox[0], second.bbox[0]) > 0
                if same_column and abs(first.size - second.size) <= 0.1 * size \
                        and 0.3 * size < distance and round(distance / size, 2) < self.t.min_line_spacing:
                    tight.append((distance / size, second))
        if not tight:
            return []
        ratio, worst = min(tight, key=lambda entry: entry[0])
        return [self._finding(
            SPACING, BODY, WARNING, ratio, self.t.min_line_spacing, MIN, "× the font size", [e[1] for e in tight],
            f"Lines are set at {ratio:.2f} × the font size, which is cramped: increase the line spacing "
            "(\\linespread or \\baselineskip) or reduce the text.", worst.text)]

    def images(self) -> list[Finding]:
        t, page = self.t, self.page
        shown = [(self._area_pct(image.bbox), image) for image in page.images]
        shown = [(area, image) for area, image in shown if t.image_ignore_area_pct <= area < t.image_background_pct]
        if not shown:
            return []
        area, image = max(shown, key=lambda entry: entry[0])
        width = (image.bbox[2] - image.bbox[0]) / page.width * 100
        height = (image.bbox[3] - image.bbox[1]) / page.height * 100
        if area < t.image_min_area_pct:
            measured, threshold, unit = area, t.image_min_area_pct, "% of the slide area"
        elif width < t.image_min_width_pct and height < t.image_tall_pct:
            measured, threshold, unit = width, t.image_min_width_pct, "% of the slide width"
        else:
            return []
        box = image.bbox
        return [Finding(
            self.slide_id, self.number, IMAGE_SIZE, IMAGE, WARNING, measured, threshold, MIN, unit,
            (box[0] / page.width, box[1] / page.height, box[2] / page.width, box[3] / page.height), "",
            f"The image shows at {area:.0f} % of the slide area ({width:.0f} % of its width) and may be too small to "
            f"read: enlarge it to at least {t.image_min_area_pct:g} % of the slide, give it the full width, or crop "
            "it to the part that matters.", pixels=(image.width, image.height))]


def analyse(pages: list[Page], runs: list[tuple[str, list[int]]], thresholds: Thresholds = DEFAULTS) -> Report:
    """The report for `runs`: (slide id, the indexes of its pages in `pages`). The last page of a run is judged
    fully; an earlier page only for text cut off by the page."""
    slides = []
    for slide_id, indexes in runs:
        last = indexes[-1]
        slide = SlideReport(slide_id, last + 1)
        slide.findings = _PageCheck(pages[last], last + 1, slide_id, thresholds).all_findings()
        for index in indexes[:-1]:
            check = _PageCheck(pages[index], index + 1, slide_id, thresholds)
            slide.findings += check.clipping()
        slides.append(slide)
    return Report(slides, thresholds)
