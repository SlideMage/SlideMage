# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Check a SlideMage layout profile against a compiled calibration deck.

A layout profile (latex/SlideMage_layout_<name>.tex) holds the font files and the font's metrics, and since v9.9.0
no length measured against the rendered PDF: everything follows from the font where it is used, from the page, or is
a hook of the catalog (v9.7.0-v9.9.0): where the title bar ends, the right edges of the frame number and the
footnotes, where the footer number sits in its box, the label and numeral boxes of the lists, the footnotes' offset,
the section frame's corrections and the pull-up of the frames the automatic Top Margin does not correct by their
content (\\SMContentTopShift and the two columns corrections, measured from where the frame's body begins). This tool
compiles the calibration deck (tests/fixtures/template_stress/decks/calibration.tex) with the profile under the
SlideMage template, whose hooks are the catalog's defaults, measures the PDF and checks each derived value against
the geometry its hooks ask for (the footer number's ink centred in the box, the label gap, the numeral slot and gap,
the footnotes' clearance above the footer, the section bar's height, the first line of the three manual-top frames
on the Top Margin). tools/check_layout.py then says whether the profile is clean.

Recipe for a new profile (the header of latex/SlideMage_setup.tex has it too):
  1. copy latex/SlideMage_layout_fira.tex to latex/SlideMage_layout_<name>.tex and change the fonts;
  2. python tools/calibrate_font_profile.py --profile <name>
     every check should read "ok" (within the tolerance of the measurement, 0.3pt unless the check says);
  3. python tools/check_layout.py on the PDF of the deck compiled with a template that picks the profile
     (the project's stress-test template does); then adjust until the report is clean.
The last section of the output reports what the base derives from the font and the template, read back from
the PDF: the title bar's bottom edge, the Top Margin, the ascender, and how far the frame number's and the
footnotes' right edges are from the logo's visible edge.

usage: python tools/calibrate_font_profile.py --profile NAME [--template slidemage] [--project DIR]
           [--deck decks/calibration.tex] [--framework DIR] [--pdf FILE] [--keep-pdf FILE]
With --pdf the compile is skipped and FILE is measured (the profile's current values are still read from
--framework). Exit code 0 when every check is ok, 1 when one fails.
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
SECTION_BOX_HEIGHT = "SMSectionframeBoxHeight"
TEMPLATE_INPUT_RE = re.compile(r"\\input\{SlideMage_template_[^}]+\}")
SET_RE = r"\\setlength\{\\%s\}\{([^}]*)\}"
COMPILE_TIMEOUT_SECONDS = 600


@dataclass
class Check:
    """A derived value against the geometry its hooks ask for: `measured` and `expected` in pt."""
    name: str            # what is checked, e.g. "footnote clearance above the footer"
    measured: float | None
    expected: float | None
    note: str
    tolerance: float = TOLERANCE

    @property
    def ok(self) -> bool:
        return self.measured is None or self.expected is None or abs(self.measured - self.expected) <= self.tolerance


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


def info_bp(doc: fitz.Document, key: str) -> float | None:
    """A number the base wrote into the PDF's info dictionary (in bp), None if the PDF lacks it."""
    try:
        kind, ref = doc.xref_get_key(-1, "Info")
        if kind != "xref":
            return None
        kind, value = doc.xref_get_key(int(ref.split()[0]), key)
        return float(value) if kind in ("string", "real", "int") else None
    except (ValueError, RuntimeError):
        return None


def em_default(setup: str, name: str) -> float | None:
    """The catalog's default of `\\newcommand{\\name}{<number>em}`, in em."""
    found = re.findall(r"\\newcommand\{\\%s\}\{(-?[\d.]+)em\}" % re.escape(name), setup)
    return float(found[-1]) if found else None


def label_gap(page: fitz.Page) -> list[tuple[str, float, float]]:
    """(label, gap in pt, label size in pt) for each list label that has the item's text in a span of its own after it."""
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            sp = [s for s in line["spans"] if s["text"].strip()]
            for first, second in zip(sp, sp[1:]):
                if re.fullmatch(r"[a-z0-9][).]", first["text"].strip()):
                    out.append((first["text"].strip(), (second["bbox"][0] - first["bbox"][2]) * PT, first["size"] * PT))
                    break
    return out


def measure(deck: Deck, profile: str, framework: Path, template: str) -> tuple[list[Check], list[str]]:
    profile_text(framework, profile)       # the profile exists
    setup = (framework / "SlideMage_setup.tex").read_text(encoding="utf-8")
    checks: list[Check] = []
    hooks: list[str] = []
    edges: list[str] = []

    # -- the footer and the right edge ------------------------------------------------------------
    probe = deck.page("ZC3")
    if probe is not None:
        chrome = deck.chrome(probe)
        number = frame_number_span(probe, chrome)
        if number is not None:
            above, below = footer_text_gaps(probe, chrome, number)
            # \SMFooterTextDrop is derived from the digits' ink: the ink sits as far from the box's top edge as from its bottom
            checks.append(Check("footer number centred in its box (gap above less gap below)", (above - below) * PT, 0.0,
                                f"the ink sits {above:.2f}pt below the box's top edge and {below:.2f}pt above its bottom",
                                tolerance=2 * 0.15))
            edges.append(f"the frame number ends {(chrome.logo_right - number['bbox'][2]) * PT:+.2f}pt inside the logo's "
                         f"visible right edge (\\SMFooterRightShift, derived)")
        if chrome.footnotes:
            edges.append(f"the footnote lines end {(chrome.logo_right - max(r.x1 for r in chrome.footnotes)) * PT:+.2f}pt inside "
                         f"the logo's visible right edge (\\SMFootnoteRightShift, derived)")

    # -- the footnotes' clearance above the footer box (\SMFootlineVOffset, derived) ---------------------------
    notes = deck.page("ZC8")
    gap_key = info_bp(deck.doc, "SMFootnoteFooterGap")
    descender = info_bp(deck.doc, "SMFootnoteDescender")
    box_height = info_bp(deck.doc, "SMFooterBoxHeight")
    if notes is not None and None not in (gap_key, descender, box_height):
        chrome = deck.chrome(notes)
        baselines = [s["origin"][1] for s in spans(notes)
                     if s["size"] < 4.6 and s["origin"][1] > chrome.footer_top - 40 and s["origin"][1] < chrome.footer_top]
        if baselines:
            above = chrome.h - max(baselines)         # the last footnote line's baseline above the page's bottom edge
            checks.append(Check("footnote descenders above the footer box (\\SMFootnoteFooterGap)",
                                (above - descender - box_height) * PT, gap_key * PT,
                                f"the last baseline is {above:.2f}bp above the page's bottom, the descender {descender:.2f}bp, "
                                f"the footer box {box_height:.2f}bp high"))

    # -- the top of the frames the automatic Top Margin does not correct by their content -----------------
    # (v9.9.0: \SMContentTopShift is measured from the frames' body origin, the two columns corrections against a list
    # where the columns begin; a manual-top frame's first line sits on the Top Margin whatever the font and template)
    top_margin = deck.info["top_margin"]
    for slide_id, what, derived in (("ZCI", "a list", "\\SMContentTopShift"),
                                    ("ZCJ", "a columns[t]", "\\SMColumnsTopCorrection"),
                                    ("ZCK", "a columns[T]", "\\SMColumnsTTopCompensation")):
        y = deck.first_line_top(slide_id)
        if y is not None:
            checks.append(Check(f"manual-top frame, {what} first, on the Top Margin ({derived}, derived)",
                                (y - top_margin) * PT, 0.0,
                                f"the first line sits at {y:.2f}bp, the Top Margin is {top_margin:.2f}bp"))

    # -- the section frame: the bar is as high as the hook says ------------------------------------------------
    section = deck.page("ZC2")
    target = tex_length(setup, SECTION_BOX_HEIGHT)
    if section is not None and target is not None:
        bar = deck.chrome(section).bar_bottom
        checks.append(Check(f"section bar height (\\{SECTION_BOX_HEIGHT})", bar * PT, target,
                            f"the bar ends at {bar:.2f}bp = {bar * PT:.2f}pt, \\{SECTION_BOX_HEIGHT} is {target:.2f}pt",
                            tolerance=0.1))

    # -- lists with labels: the gap between a label and the item's text (\SMLabelItemGap) --------------------------
    labelled = deck.page("ZC5")
    gap_em = em_default(setup, "SMLabelItemGap")
    if labelled is not None and gap_em is not None:
        found = label_gap(labelled)
        if found:
            worst = max(found, key=lambda f: abs(f[1] - gap_em * f[2]))
            checks.append(Check("label to item text (\\SMLabelItemGap)", worst[1], gap_em * worst[2],
                                f"{len(found)} labels, the worst {worst[0]!r}: {worst[1]:.2f}pt against {gap_em:g}em of {worst[2]:.2f}pt"))

    # -- numerals of a nested enumerate: slot and gap (\SMEnumerateNestedSlotExtra, \SMEnumerateNestedLabelGap) ----
    nested = deck.page("ZCL")
    extra_em, label_em = em_default(setup, "SMEnumerateNestedSlotExtra"), em_default(setup, "SMEnumerateNestedLabelGap")
    if nested is not None and extra_em is not None and label_em is not None:
        ws = words(nested)
        numerals = [w for w in ws if re.fullmatch(r"\d\.", w[4]) and w[0] > 20]
        sizes = [s["size"] for s in spans(nested) if re.fullmatch(r"\d\.", s["text"].strip())]
        if numerals and sizes:
            widest = max(numerals, key=lambda w: w[2] - w[0])
            following = [w for w in ws if abs(w[1] - widest[1]) < 2 and w[0] > widest[2] and not re.fullmatch(r"\d\.", w[4])]
            checks.append(Check("nested numerals share a left edge", (max(w[0] for w in numerals) - min(w[0] for w in numerals)) * PT, 0.0,
                                f"{len(numerals)} numerals"))
            if following:
                width = (widest[2] - widest[0]) * PT
                size = sizes[0] * PT
                offset = (min(following, key=lambda w: w[0])[0] - widest[0]) * PT
                checks.append(Check("numeral to item text (widest numeral, slot extra, gap)", offset,
                                    width + (extra_em + label_em) * size,
                                    f"the widest numeral {widest[4]!r} is {width:.2f}pt, the text starts {offset:.2f}pt after its left edge"))

    # -- hooks of the catalog that follow from the font -------------------------------------------------
    section_info = deck.info
    bars = [deck.chrome(p).bar_bottom for p in (deck.page("ZC3"), deck.page("ZC4")) if p is not None]
    if bars:
        hooks.append(f"\\SMTitleBarBottomAlign (derived) = {section_info['title_bar_bottom'] * PT:.2f}pt: the PDF records "
                     f"{section_info['title_bar_bottom']:.2f}bp, the title bar is drawn to {bars[0]:.2f}bp")
    hooks.append(f"\\SMTopMargin = {section_info['top_margin']:.2f}bp; \\SMContentTopAlign (derived) is that distance in pt")
    hooks.extend(edges)
    hooks.append(f"text font ascender read from the font: {section_info['ascender']}em "
                 f"(the profile's \\SMFontAscender is only the fallback)")
    return checks, hooks


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
    checks, hooks = measure(Deck(pdf), args.profile, framework, args.template)

    print(f"profile {args.profile}, template {args.template}")
    print("derived from the font and the hooks, measured in the PDF against what they ask for (pt):")
    for c in checks:
        measured = "-" if c.measured is None else f"{c.measured:.2f}"
        expected = "-" if c.expected is None else f"{c.expected:.2f}"
        print(f"  {'ok  ' if c.ok else 'FAIL'} {c.name}: measured {measured}, expected {expected}   {c.note}")
    print("derived by the base, read back from the PDF:")
    for line in hooks:
        print(f"  {line}")
    return 0 if all(c.ok for c in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
