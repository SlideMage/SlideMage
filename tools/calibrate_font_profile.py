# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Suggest the calibration numbers of a SlideMage layout profile from a compiled calibration deck.

A layout profile (latex/SlideMage_layout_<name>.tex) holds, under "Calibrations", lengths that were
measured against the rendered PDF for one font: where the footer text sits in its box, how far the frame
number and the footnotes are from the logo's edge, the pull-up of a frame the automatic Top Margin does not
manage, the label widths of the numbered lists, and so on. This tool compiles the calibration deck
(tests/fixtures/template_stress/decks/calibration.tex) with the profile under the SlideMage template, whose
hooks are the catalog's defaults, measures the PDF, and prints each number with its current value and the value
the measurement suggests. tools/check_layout.py then says whether the profile is clean.

Recipe for a new profile (the header of latex/SlideMage_setup.tex has it too):
  1. copy latex/SlideMage_layout_fira.tex to latex/SlideMage_layout_<name>.tex and change the fonts;
  2. python tools/calibrate_font_profile.py --profile <name>
  3. put the suggested values into the profile's "Calibrations" section and run the tool again: every
     line should read "ok" (the numbers it prints are within the tolerance of the measurement, 0.3pt);
  4. python tools/check_layout.py on the PDF of the deck compiled with a template that picks the profile
     (the project's stress-test template does); then adjust until the report is clean.
The last section of the output lists template hooks that follow from the font and that the template, not the
profile, holds (the title bar's bottom edge and the Top Margin as a coordinate).

Not measured, and kept as the Fira profile has them until a slide shows they are wrong:
\\SMEnumerateLabelBox, \\SMEnumerateTextExtra (the last is a design value: the outer numeral column against a bullet's),
\\SMSectionframeRefDepth, \\SMSectionframeBottomGap, \\SMSectionframeBottomPadCorrection.

usage: python tools/calibrate_font_profile.py --profile NAME [--template slidemage] [--project DIR]
           [--deck decks/calibration.tex] [--framework DIR] [--pdf FILE] [--keep-pdf FILE]
With --pdf the compile is skipped and FILE is measured (the profile's current values are still read from
--framework). Exit code 0 when every measured number is ok, 1 when a suggestion differs from the current value.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_layout as cl  # noqa: E402  (the measuring code: Page, pdf_info, the PDF's own margins)

REPO = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT = REPO / "tests" / "fixtures" / "template_stress"
DEFAULT_DECK = "decks/calibration.tex"
PT = 72.27 / 72                  # TeX points per PDF point (bp)
TOLERANCE = 0.3                  # pt: below this a measurement says "ok"
SMALL_SIZE = 10.0                # \small of an 11pt beamer class: the size the label calibrations were made at
SECTION_BOX_HEIGHT = "SMSectionframeBoxHeight"
# A columns[T] environment that starts a manual-top frame lands 2.36pt above a list in the Fira profile, whose
# \SMColumnsTTopCompensation was measured on plain frames: that offset is not the font's, so it is taken out.
T_COLUMNS_OFFSET = 2.36
# The advance box of the frame number and of a footnote line ends 0.22pt before the logo's edge in the Fira profile
# (the glyph's overhang): the profile was fitted to the ink, so that much is not the font's.
EDGE_BIAS = 0.22
NUMERAL_CLEARANCE = 0.43        # pt: the Fira profile's numeral slot (7.85pt) is its widest numeral (7.42pt) plus this
TEMPLATE_INPUT_RE = re.compile(r"\\input\{SlideMage_template_[^}]+\}")
SET_RE = r"\\setlength\{\\%s\}\{([^}]*)\}"
COMPILE_TIMEOUT_SECONDS = 600


@dataclass
class Row:
    name: str            # the profile's name without the backslash
    current: float | None
    suggested: float | None
    note: str
    advisory: bool = False   # shown, never counted: the measurement is known to disagree with the Fira profile

    @property
    def ok(self) -> bool:
        return (self.advisory or self.suggested is None or self.current is None
                or abs(self.suggested - self.current) <= TOLERANCE)


# ---------------------------------------------------------------- reading values out of the TeX files

def tex_length(text: str, name: str) -> float | None:
    """The value in pt of `\\setlength{\\name}{<number>pt}` in `text` (the last one), None if absent."""
    found = re.findall(SET_RE % re.escape(name), text)
    if not found:
        return None
    m = re.fullmatch(r"\s*(-?[\d.]+)\s*(pt|bp)\s*", found[-1])
    if not m:
        return None
    return float(m.group(1)) * (PT if m.group(2) == "bp" else 1.0)


def profile_text(framework: Path, profile: str) -> str:
    path = framework / f"SlideMage_layout_{profile}.tex"
    if not path.is_file():
        raise SystemExit(f"no layout profile {path}")
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------- compiling

def compile_deck(project: Path, deck: str, template: str, profile: str | None, framework: Path, out_pdf: Path) -> None:
    """Compile `deck` with its template input swapped for `template` under `profile` (None: the template picks its
    own, as the stress-test template does); leave the PDF at out_pdf."""
    deck_path = project / deck
    text = deck_path.read_text(encoding="utf-8")
    pick = f"\\newcommand{{\\SMLayoutProfile}}{{{profile}}}" if profile else ""
    swapped, n = TEMPLATE_INPUT_RE.subn(lambda _m: f"{pick}\\input{{SlideMage_template_{template}}}", text, count=1)
    if n != 1:
        raise SystemExit(f"{deck}: no \\input{{SlideMage_template_<key>}} line to swap")
    jobname = f"calibrate-{profile or 'own'}-{template}"
    wrapper = deck_path.parent / f"_{jobname}.tex"
    wrapper.write_text(swapped, encoding="utf-8", newline="")
    build = Path(tempfile.mkdtemp(prefix="calibrate-"))
    env = dict(os.environ, SLIDEMAGE_LATEX=str(framework), SOURCE_DATE_EPOCH="1700000000")
    cmd = ["latexmk", "-f", "-interaction=nonstopmode", f"-jobname={jobname}", f"-outdir={build.as_posix()}",
           f"-auxdir={build.as_posix()}", wrapper.relative_to(project).as_posix()]
    try:
        subprocess.run(cmd, cwd=project, env=env, capture_output=True, text=True, errors="replace",
                       timeout=COMPILE_TIMEOUT_SECONDS)
    finally:
        wrapper.unlink(missing_ok=True)
    pdf = build / f"{jobname}.pdf"
    if not pdf.is_file():
        log = build / f"{jobname}.log"
        tail = log.read_text(encoding="utf-8", errors="replace")[-1500:] if log.is_file() else "no log"
        raise SystemExit(f"the calibration deck did not compile; end of the log:\n{tail}")
    shutil.copy2(pdf, out_pdf)
    shutil.rmtree(build, ignore_errors=True)


# ---------------------------------------------------------------- measuring

class Deck:
    """A compiled calibration deck: its pages by slide id, and the numbers its PDF carries."""

    def __init__(self, path: Path):
        self.doc = fitz.open(path)
        self.info = cl.pdf_info(self.doc)
        self.pages: dict[str, list[fitz.Page]] = {}
        for page in self.doc:
            m = cl.ID_RE.search(page.get_text())
            if m:
                self.pages.setdefault(m.group(1), []).append(page)

    def page(self, slide_id: str) -> fitz.Page | None:
        pages = self.pages.get(slide_id)
        return pages[-1] if pages else None

    def chrome(self, page: fitz.Page) -> cl.Page:
        i = self.info
        return cl.Page(page, i["top_margin"], i["left_margin"], i["ascender"], i["title_bar_bottom"])

    def first_line_top(self, slide_id: str) -> float | None:
        """The top of the first body text line of a slide, in bp (the checker's measure: baseline minus ascender)."""
        page = self.page(slide_id)
        if page is None:
            return None
        texts = [r.y0 for kind, r, _ in self.chrome(page).items if kind == "text"]
        return min(texts) if texts else None


def words(page: fitz.Page) -> list[tuple[float, float, float, float, str]]:
    return [(w[0], w[1], w[2], w[3], w[4]) for w in page.get_text("words")]


def spans(page: fitz.Page) -> list[dict]:
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            out.extend(s for s in line["spans"] if s["text"].strip())
    return out


def frame_number_span(page: fitz.Page, chrome: cl.Page) -> dict | None:
    """The frame number: the rightmost digits inside the footer box."""
    found = [s for s in spans(page) if s["bbox"][1] >= chrome.footer_top - 1 and s["text"].strip().isdigit()]
    return max(found, key=lambda s: s["bbox"][2]) if found else None


def footer_text_gaps(page: fitz.Page, chrome: cl.Page, number: dict) -> tuple[float, float]:
    """The gap (bp) above and below the ink of the frame number inside the footer box, from pixels."""
    dpi = 1152
    x0, x1 = number["bbox"][0] - 0.3, min(number["bbox"][2] + 0.3, chrome.w - 0.3)
    clip = fitz.Rect(x0, chrome.footer_top, x1, chrome.h - 0.05)
    pix = page.get_pixmap(dpi=dpi, clip=clip, colorspace=fitz.csRGB, alpha=False)
    samples, n = pix.samples, pix.n
    background = samples[0:3]
    rows = [y for y in range(pix.height)
            if any(max(abs(samples[(y * pix.width + x) * n + k] - background[k]) for k in range(3)) > 60
                   for x in range(pix.width))]
    if not rows:
        raise SystemExit("no ink found in the footer's frame number")
    top = clip.y0 + rows[0] * 72 / dpi
    bottom = clip.y0 + (rows[-1] + 1) * 72 / dpi
    return top - chrome.footer_top, chrome.h - bottom


def measure(deck: Deck, profile: str, framework: Path, template: str) -> tuple[list[Row], list[str]]:
    text = profile_text(framework, profile)
    cur = lambda name: tex_length(text, name)   # noqa: E731
    rows: list[Row] = []
    hooks: list[str] = []

    def add(name: str, suggested: float | None, note: str, advisory: bool = False) -> None:
        rows.append(Row(name, cur(name), None if suggested is None else round(suggested, 2), note, advisory))

    # -- the footer and the right edge ------------------------------------------------------------
    probe = deck.page("ZC3")
    if probe is not None:
        chrome = deck.chrome(probe)
        number = frame_number_span(probe, chrome)
        if number is not None:
            above, below = footer_text_gaps(probe, chrome, number)
            # \vspace*{\SMFooterTextDrop} first in the footer: a larger value raises the text (measured: 0.1pt more moves the ink 0.09pt up)
            add("SMFooterTextDrop", (cur("SMFooterTextDrop") or 0.0) + (above - below) / 2 * PT,
                f"the frame number's ink sits {above:.2f}pt below the box's top edge and {below:.2f}pt above its bottom")
            delta = (chrome.logo_right - number["bbox"][2]) * PT - EDGE_BIAS
            add("SMFooterRightShift", (cur("SMFooterRightShift") or 0.0) + delta,
                f"the frame number ends {delta + EDGE_BIAS:+.2f}pt from the logo's right edge, {EDGE_BIAS}pt of it the Fira profile's own")
        if chrome.footnotes:
            delta = (chrome.logo_right - max(r.x1 for r in chrome.footnotes)) * PT - EDGE_BIAS
            add("SMFootnoteRightShift", (cur("SMFootnoteRightShift") or 0.0) + delta,
                f"the footnote lines end {delta + EDGE_BIAS:+.2f}pt from the logo's right edge, {EDGE_BIAS}pt of it the Fira profile's own")

    # -- the top of the frames the automatic Top Margin does not manage --------------------------------
    top_margin = deck.info["top_margin"]
    y_list, y_t, y_T = (deck.first_line_top(i) for i in ("ZCI", "ZCJ", "ZCK"))
    if y_list is not None:
        add("SMContentTopShift", (cur("SMContentTopShift") or 0.0) + (y_list - top_margin) * PT,
            f"the first line of a manual-top frame sits at {y_list:.2f}, the Top Margin is {top_margin:.2f}")
    if y_list is not None and y_t is not None:
        add("SMColumnsTopCorrection", (cur("SMColumnsTopCorrection") or 0.0) + (y_t - y_list) * PT,
            f"columns[t] first start {y_t - y_list:+.2f}pt below a list")
    if y_list is not None and y_T is not None:
        add("SMColumnsTTopCompensation", (cur("SMColumnsTTopCompensation") or 0.0) + (y_list - y_T) * PT - T_COLUMNS_OFFSET,
            f"columns[T] first start {y_T - y_list:+.2f}pt below a list, {T_COLUMNS_OFFSET}pt above is the Fira profile's own")

    # -- the section frame ------------------------------------------------------------------------------------
    section = deck.page("ZC2")
    setup = (framework / "SlideMage_setup.tex").read_text(encoding="utf-8")
    target = tex_length(setup, SECTION_BOX_HEIGHT)
    if section is not None and target is not None:
        # The bar is drawn in bp: the Fira profile's 85.04 reads 85.02 here, so the numbers are compared as they stand.
        bar = deck.chrome(section).bar_bottom
        add("SMSectionframeHeightCorrection", (cur("SMSectionframeHeightCorrection") or 0.0) + (target - bar),
            f"the section frame's bar ends at {bar:.2f}bp, \\{SECTION_BOX_HEIGHT} is {target:.2f}")

    # -- lists with labels ------------------------------------------------------------------------------------------
    labelled = deck.page("ZC5")
    if labelled is not None:
        sp = spans(labelled)
        label_em = [(s["bbox"][2] - s["bbox"][0]) / s["size"] for s in sp
                    if re.fullmatch(r"[a-z0-9][).]", s["text"].strip())]
        if label_em:
            add("SMLabelItemWidth", max(label_em) * SMALL_SIZE + 0.1,
                f"the widest label ({max(label_em):.3f}em) at {SMALL_SIZE:g}pt, plus 0.1pt of clearance")
        c_em = None
        for block in labelled.get_text("rawdict")["blocks"]:
            for line in block.get("lines", []):
                for s in line["spans"]:
                    if "".join(c["c"] for c in s["chars"]).startswith("Calculate"):
                        char = s["chars"][0]
                        c_em = (char["bbox"][2] - char["bbox"][0]) / s["size"]
        if c_em:
            add("SMLabelItemSep", 2.0 + c_em * SMALL_SIZE / 2,
                f"2pt and half a C ({c_em:.3f}em) at {SMALL_SIZE:g}pt")

    # -- numerals of a nested enumerate -------------------------------------------------------------------------
    nested = deck.page("ZCL")
    if nested is not None:
        ws = words(nested)
        numerals = [w for w in ws if re.fullmatch(r"\d\.", w[4]) and w[0] > 20]
        if numerals:
            widest = max(numerals, key=lambda w: w[2] - w[0])
            width = widest[2] - widest[0]
            slot = width + NUMERAL_CLEARANCE
            add("SMEnumerateNestedMinNumber", slot,
                f"the widest numeral, {widest[4]!r}, is {width:.2f}pt wide, plus {NUMERAL_CLEARANCE}pt")
            sep = cur("SMEnumerateNestedLabelSep")
            if sep is not None:
                add("SMEnumerateNestedLeftMargin", slot + sep,
                    f"the numeral slot and \\SMEnumerateNestedLabelSep ({sep:.2f}pt, a gap kept as it is)")

    # -- hooks of the catalog that follow from the font -------------------------------------------------
    section_info = deck.info
    bars = [deck.chrome(p).bar_bottom for p in (deck.page("ZC3"), deck.page("ZC4")) if p is not None]
    if bars:
        bottom_pt = bars[0] * PT
        hooks.append(f"\\SMTitleBarBottomAlign = {bottom_pt:.2f}pt: the title bar ends at {bars[0]:.2f}bp "
                     f"(the PDF records {section_info['title_bar_bottom']:.2f}); the template sets it, the catalog default "
                     f"is 25.32pt for Fira")
        hooks.append(f"\\SMTopMargin = {section_info['top_margin']:.2f}bp and \\SMContentTopAlign (its coordinate in pt) "
                     f"must keep to the title bar's bottom edge plus the gap the template wants "
                     f"(Fira: 41.58 - 25.32 = 16.26pt)")
    hooks.append(f"text font ascender read from the font: {section_info['ascender']}em "
                 f"(the profile's \\SMFontAscender is only the fallback)")
    return rows, hooks


# ---------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--profile", required=True, help="the layout profile's name, e.g. lmsans")
    ap.add_argument("--template", default="slidemage", help="the template key to compile under (default slidemage)")
    ap.add_argument("--project", default=str(DEFAULT_PROJECT), help="the project holding the calibration deck")
    ap.add_argument("--deck", default=DEFAULT_DECK, help="the calibration deck, relative to the project")
    ap.add_argument("--framework", default=str(REPO / "latex"), help="the framework's latex/ folder")
    ap.add_argument("--pdf", help="measure this PDF instead of compiling")
    ap.add_argument("--keep-pdf", help="also copy the compiled PDF here")
    args = ap.parse_args(argv)
    project, framework = Path(args.project).resolve(), Path(args.framework).resolve()
    if args.pdf:
        pdf = Path(args.pdf)
    else:
        pdf = Path(tempfile.mkdtemp(prefix="calibrate-pdf-")) / "calibration.pdf"
        compile_deck(project, args.deck, args.template, args.profile, framework, pdf)
        if args.keep_pdf:
            shutil.copy2(pdf, args.keep_pdf)
    rows, hooks = measure(Deck(pdf), args.profile, framework, args.template)

    print(f"profile {args.profile}, template {args.template}: current value, suggestion (pt)")
    width = max((len(r.name) for r in rows), default=10)
    for r in rows:
        current = "-" if r.current is None else f"{r.current:.2f}"
        suggested = "-" if r.suggested is None else f"{r.suggested:.2f}"
        flag = "ok " if r.ok else "SET"
        print(f"  {flag} \\{r.name:<{width}}  {current:>8} -> {suggested:>8}   {r.note}")
    print("template hooks that follow from the font:")
    for line in hooks:
        print(f"  {line}")
    return 0 if all(r.ok for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
