# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Every geometric hook of the catalog (latex/SlideMage_setup.tex) puts something where its name says (v10.10.0).

The stress-test template (tests/fixtures/template_stress/) gives each hook a value of its own; the calibration deck
and the geometry deck are compiled with it, and each test reads the value from the PDF's info dictionary (the base
writes the hooks there, in bp) and looks for it on the page: the title bar's text and bottom edge, the footer box,
the text margins, the title frame's bottom pad, the side footnotes' strip, the blocks, the quote frame. The compile is
opt-in (SLIDEMAGE_TEX_TESTS=1 and latexmk), like the other tests that compile; the table of which hook is read where is
always checked (every length of the catalog is either measured here or says why it cannot be).
"""
import importlib.util
import os
import re
import shutil
import sys
from pathlib import Path

import pymupdf
import pytest

ROOT = Path(__file__).resolve().parents[1]
STRESS = ROOT / "tests" / "fixtures" / "template_stress"
BS = chr(92)
PT = 72.27 / 72                       # TeX points per PDF point (bp)
BP = 72 / 72.27                       # bp per TeX point


def load(name: str):
    path = ROOT / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
    return module


cl = load("check_layout")
cal = load("calibrate_font_profile")

# Each length of the catalog is measured by a test below, or is listed with the reason it is not read back from a PDF.
MEASURED = {
    "SMLogoHeight": "test_the_logo_is_as_high_as_the_hook_and_ends_its_right_padding_from_the_edge",
    "SMTextMarginLeft": "test_text_margins_are_where_the_lines_begin_and_end",
    "SMTextMarginRight": "test_text_margins_are_where_the_lines_begin_and_end",
    "SMFrametitleTopPadding": "test_the_title_bar_text_and_box_follow_the_paddings",
    "SMFrametitleBottomPadding": "test_the_title_bar_text_and_box_follow_the_paddings",
    "SMFrametitleLeftPadding": "test_the_title_bar_text_and_box_follow_the_paddings",
    "SMFrametitleRightPadding": "test_the_logo_is_as_high_as_the_hook_and_ends_its_right_padding_from_the_edge",
    "SMFrameSubtitleStrutEnd": "test_a_subtitle_makes_the_title_box_as_much_taller_as_the_hook_says",
    "SMFooterBoxHeight": "test_the_footer_box_and_its_texts",
    "SMFootlineSidePadding": "test_the_footer_box_and_its_texts",
    "SMFootnoteFooterGap": "test_footnotes_stand_the_gap_above_the_footer_and_the_sep_apart",
    "SMFootnoteSep": "test_footnotes_stand_the_gap_above_the_footer_and_the_sep_apart",
    "SMSideFootnoteHsize": "test_the_side_footnote_strip_is_as_long_and_as_far_from_the_edge_as_the_hooks_say",
    "SMSideFootnoteTopSep": "test_the_side_footnote_strip_is_as_long_and_as_far_from_the_edge_as_the_hooks_say",
    "SMSideFootnoteRightInset": "test_the_side_footnote_strip_is_as_long_and_as_far_from_the_edge_as_the_hooks_say",
    "SMBlockSideMargin": "test_a_block_sets_its_text_the_side_margin_in",
    "SMTitleframeBoxHeight": "test_the_title_frame_text_stands_the_bottom_pad_above_the_boxs_edge",
    "SMTitleframeBottomPad": "test_the_title_frame_text_stands_the_bottom_pad_above_the_boxs_edge",
    "SMSectionframeBoxHeight": "test_the_section_and_quote_boxes_are_as_high_as_their_hooks",
    "SMQuoteBoxHeight": "test_the_section_and_quote_boxes_are_as_high_as_their_hooks",
    "SMQuoteAttributionGap": "test_the_quote_attribution_hangs_the_gap_under_the_box",
}
# Lengths with no clean reading in the PDF, each with the reason. Everything here is still read by the base or the theme
# (tests/test_template_catalog.py) and set by the stress-test template.
NOT_READ_BACK = {
    "SMFootlineHeight": "the footline box's height; the footnotes' offset is derived from it, so only the frame text area's end moves with it",
    "SMFootlineDepth": "the footline box's depth; derived into the footnotes' offset like the height",
    "SMRightFooterPadding": "cancelled in the footer: \\SMFooterRightShift puts the frame number on the logo's edge whatever this is",
    "SMBlockTitleMarkerWidth": "the width a block title leaves for its marker; visible only when a title wraps (the marker sits at the right edge)",
    "SMTitleframeTextSep": "the title/subtitle spacing in the title frame; the default look is held by the regression harness",
    "SMTitleframeBandGap": "the title/subtitle spacing in the title frame; the default look is held by the regression harness",
    "SMSectionframeContentDrop": "the section frame's body drop under its bar, measured against a standard frame's by step 10",
    "SMProgressStripHeight": "the offset the content below a \\progressstrip is moved down by; the strip is drawn at a size of its own",
    "SMSideFootnoteMarkerShift": "shifts a footnote marker 1-2pt right, below the resolution of a reliable reading",
    "SMLabelItemItemsep": "item spacing of labelled lists",
    "SMEnumerateTextExtra": "text offset of an enumerate, checked by the calibration tool through the numeral gap",
    "SMTightDisplaySkip": "space around a display in \\SMTightDisplaySkips",
    "SMImageBorderWidth": "line width of the image border style",
    "SMWarningSignPadding": "padding in \\SMWarningSign",
    "SMWarningSignBorderWidth": "border of \\SMWarningSign",
    "SMTopMargin": "a macro, checked by tools/check_layout.py's top check on every deck (see test_top_margin_...)",
}


def info_numbers(doc) -> dict[str, float]:
    return {**cl.pdf_hooks(doc), **{"SMTopMargin": cl.pdf_info(doc)["top_margin"]}}


def catalog_lengths() -> set[str]:
    text = (ROOT / "latex" / "SlideMage_setup.tex").read_text(encoding="utf-8")
    code = "\n".join(line for line in text.split("\n") if not line.lstrip().startswith("%"))
    return set(re.findall(r"\\newlength\{\\(SM[A-Za-z]+)\}", code))


def test_every_length_of_the_catalog_is_measured_here_or_says_why_not():
    lengths = catalog_lengths()
    # the derived names are no longer lengths of the catalog; what is left is a hook
    unaccounted = sorted(lengths - set(MEASURED) - set(NOT_READ_BACK))
    assert not unaccounted, f"hooks with no geometry test and no reason: {unaccounted}"
    stale = sorted((set(MEASURED) | set(NOT_READ_BACK)) - lengths - {"SMTopMargin", "SMFootlineSidePadding"})      # the two are macros (a value in bp, one in ex)
    assert not stale, f"table entries for hooks that are not lengths of the catalog: {stale}"
    here = {name for name in dir(sys.modules[__name__]) if name.startswith("test_")}
    assert set(MEASURED.values()) <= here


def test_the_base_writes_every_measured_hook_into_the_pdf():
    base = (ROOT / "latex" / "SlideMage_base.tex").read_text(encoding="utf-8")
    block = base.split("\\clist_map_function:nN")[1].split("\\SM_pdfinfo_length:n")[0]
    listed = set(re.findall(r"SM[A-Za-z]+", block))
    reported = {"SMFooterBoxHeight", "SMFootnoteFooterGap", "SMFootlineSidePadding", "SMFrametitleLeftPadding"}
    missing = sorted(set(MEASURED) - listed - reported)
    assert not missing, f"measured hooks the base does not put into the PDF info: {missing}"


needs_tex = pytest.mark.skipif(not os.environ.get("SLIDEMAGE_TEX_TESTS") or not shutil.which("latexmk"),
                               reason="compiles the calibration and geometry decks: SLIDEMAGE_TEX_TESTS=1 and latexmk")


@pytest.fixture(scope="module")
def decks(tmp_path_factory):
    out = tmp_path_factory.mktemp("geometry")
    framework = ROOT / "latex"
    cal.compile_deck(STRESS, "decks/calibration.tex", "stress-test", None, framework, out / "cal.pdf")
    cal.compile_deck(STRESS, "decks/geometry.tex", "stress-test", None, framework, out / "geo.pdf")
    cal.compile_deck(STRESS, "decks/calibration.tex", "slidemage", "fira", framework, out / "fira.pdf")
    return {name: cal.Deck(out / f"{name}.pdf") for name in ("cal", "geo", "fira")}


def first_fill(page, wide=True):
    """The colored title bar's or box's rectangle at the page's corner, before the logo's white patch trims it."""
    w = page.rect.width
    found = [d["rect"] for d in page.get_drawings() if d.get("fill") is not None and not cl.is_white(d["fill"])
             and d["rect"].x0 < 0.5 and d["rect"].y0 < 0.5 and ((d["rect"].width > w - 1) if wide else (d["rect"].width < w - 1))]
    return found[0] if found else None


def title_span(page):
    found = [s for s in cal.spans(page) if s["origin"][1] < 45 and s["size"] > 12]
    return found[0]


def logo_ink(page):
    """The union of the logo's drawings in the top right corner (its artwork, not its margin)."""
    w = page.rect.width
    rects = [d["rect"] for d in page.get_drawings() if d["rect"].x0 > w - 60 and d["rect"].y1 < 45
             and d["rect"].width < 30 and d.get("fill") is not None and not cl.is_white(d["fill"])]
    ink = rects[0]
    for r in rects[1:]:
        ink |= r
    return ink


@needs_tex
def test_top_margin_is_where_the_first_line_of_a_frame_starts(decks):
    deck = decks["cal"]
    assert deck.info["top_margin"] == 50.0
    assert abs(deck.first_line_top("ZC3") - 50.0) < 0.3


@needs_tex
def test_text_margins_are_where_the_lines_begin_and_end(decks):
    geo = decks["geo"]
    page, hooks = geo.page("ZG1"), cl.pdf_hooks(geo.doc)
    left, right = hooks["SMTextMarginLeft"], hooks["SMTextMarginRight"]
    assert abs(left - 19.84) < 0.01 and abs(right - 17.01) < 0.01          # the stress template's 0.7cm and 0.6cm
    rule = [d["rect"] for d in page.get_drawings() if d["rect"].width > 100 and d["rect"].height < 2
            and d["rect"].y0 > 40 and d["rect"].width < page.rect.width - 1]
    assert len(rule) == 1
    assert abs(rule[0].x0 - left) < 0.02 and abs(page.rect.width - rule[0].x1 - right) < 0.02
    # the lines of a paragraph begin at the left margin and none passes the right one
    lines = [line for block in page.get_text("dict")["blocks"] for line in block.get("lines", [])
             if 60 < line["spans"][0]["origin"][1] < 200 and line["spans"][0]["size"] < 12]
    assert len(lines) >= 4
    assert all(abs(line["spans"][0]["origin"][0] - left) < 0.02 for line in lines)
    assert max(line["bbox"][2] for line in lines) <= page.rect.width - right + 0.02


@needs_tex
def test_the_title_bar_text_and_box_follow_the_paddings(decks):
    deck = decks["cal"]
    page, hooks = deck.page("ZC3"), cl.pdf_hooks(deck.doc)
    top, bottom, left = hooks["SMFrametitleTopPadding"], hooks["SMFrametitleBottomPadding"], deck.info["left_margin"]
    xheight = float(deck_info(deck.doc, "SMFrametitleXHeight"))
    title = title_span(page)
    assert abs(title["origin"][0] - left) < 0.02                              # left padding: where the title text begins
    assert abs(title["origin"][1] - (top + xheight)) < 0.02                   # top padding: from the bar's top to the capitals
    bar = first_fill(page)
    assert abs(bar.y1 - (title["origin"][1] + bottom)) < 0.02                 # bottom padding: baseline to the box's bottom
    # the visible bar is the box trimmed to the logo's bottom edge: its bottom comes from the top padding, the title
    # font and the logo (SMTitleBarBottom), so a bottom padding larger than the logo's overhang is not seen
    assert deck.chrome(page).bar_bottom == pytest.approx(deck.info["title_bar_bottom"], abs=0.02)
    assert bar.y1 > deck.info["title_bar_bottom"] + 1


def deck_info(doc, key):
    kind, ref = doc.xref_get_key(-1, "Info")
    return doc.xref_get_key(int(ref.split()[0]), key)[1]


@needs_tex
def test_a_subtitle_makes_the_title_box_as_much_taller_as_the_hook_says(decks):
    geo = decks["geo"]
    page, hooks = geo.page("ZG1"), cl.pdf_hooks(geo.doc)
    title = title_span(page)
    bar = first_fill(page)
    assert abs(bar.y1 - (title["origin"][1] + hooks["SMFrametitleBottomPadding"] + hooks["SMFrameSubtitleStrutEnd"])) < 0.02
    assert hooks["SMFrameSubtitleStrutEnd"] > 1


@needs_tex
def test_the_logo_is_as_high_as_the_hook_and_ends_its_right_padding_from_the_edge(decks):
    deck = decks["cal"]
    page, hooks = deck.page("ZC3"), cl.pdf_hooks(deck.doc)
    # the logo file (cropped to its artwork plus a margin of its own) scaled to \SMLogoHeight
    logo = pymupdf.open(STRESS / "media" / "chapter-logo-building-blocks.pdf")[0]
    art = [d["rect"] for d in logo.get_drawings()]
    ink = art[0]
    for r in art[1:]:
        ink |= r
    scale = hooks["SMLogoHeight"] / logo.rect.height
    placed = logo_ink(page)
    assert placed.height == pytest.approx(ink.height * scale, abs=0.05)
    assert page.rect.width - hooks["SMFrametitleRightPadding"] - placed.x1 == pytest.approx((logo.rect.width - ink.x1) * scale, abs=0.05)


@needs_tex
def test_the_footer_box_and_its_texts(decks):
    deck = decks["cal"]
    page, hooks = deck.page("ZC8"), cl.pdf_hooks(deck.doc)
    chrome = deck.chrome(page)
    assert chrome.h - chrome.footer_top == pytest.approx(hooks["SMFooterBoxHeight"], abs=0.02)
    template = (STRESS / "SlideMage_template_stress-test.tex").read_text(encoding="utf-8")
    text_size = float(re.search(r"SMFooterTextSize\}\{" + re.escape(BS) + r"fontsize\{([\d.]+)\}", template).group(1))
    id_size = float(re.search(r"SMFooterIDSize\}\{" + re.escape(BS) + r"fontsize\{([\d.]+)\}", template).group(1))
    footer = [s for s in cal.spans(page) if s["origin"][1] > chrome.footer_top]
    left = min(footer, key=lambda s: s["origin"][0])
    ident = [s for s in footer if abs(s["size"] - id_size * BP) < 0.01][0]
    assert left["size"] == pytest.approx(text_size * BP, abs=0.01) and ident["size"] == pytest.approx(id_size * BP, abs=0.01)
    assert left["origin"][0] == pytest.approx(hooks["SMFootlineSidePadding"], abs=0.02)      # the footline's left padding


@needs_tex
def test_footnotes_stand_the_gap_above_the_footer_and_the_sep_apart(decks):
    deck = decks["cal"]
    page, hooks = deck.page("ZC8"), cl.pdf_hooks(deck.doc)
    chrome = deck.chrome(page)
    template = (STRESS / "SlideMage_template_stress-test.tex").read_text(encoding="utf-8")
    size = float(re.search(r"SMFootnoteSize\}\{" + re.escape(BS) + r"fontsize\{([\d.]+)\}", template).group(1))
    notes = sorted([s for s in cal.spans(page) if s["size"] < 4.6 and s["origin"][1] < chrome.footer_top and s["origin"][1] > 200],
                   key=lambda s: s["origin"][1])
    text = [s for s in notes if s["size"] > 3]          # the lines' own text; the raised markers are smaller
    assert text and all(s["size"] == pytest.approx(size * BP, abs=0.01) for s in text)
    # the last baseline's descenders clear the footer box by the gap
    last = max(s["origin"][1] for s in text)
    assert chrome.h - last - hooks["SMFootnoteDescender"] - hooks["SMFooterBoxHeight"] == pytest.approx(hooks["SMFootnoteFooterGap"], abs=0.02)
    # two single-line footnotes: their baselines are the sep and the strut's depth apart
    firsts = sorted({round(s["origin"][1], 3) for s in text})
    assert len(firsts) >= 2
    assert firsts[1] - firsts[0] == pytest.approx(hooks["SMFootnoteSep"] + hooks["SMFootnoteDescender"], abs=0.1)


@needs_tex
def test_the_side_footnote_strip_is_as_long_and_as_far_from_the_edge_as_the_hooks_say(decks):
    geo = decks["geo"]
    page, hooks = geo.page("ZG2"), cl.pdf_hooks(geo.doc)
    strip = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            if abs(line["dir"][1]) > 0.5 and line["bbox"][0] > page.rect.width - 20:
                strip.append(fitz_rect(line["bbox"]))
    assert len(strip) >= 2                                           # the footnote wraps onto a second line
    right = max(r.x1 for r in strip)
    assert right == pytest.approx(page.rect.width - hooks["SMSideFootnoteRightInset"], abs=0.5)    # inset: the strip's edge
    # the title block ends at the white patch's bottom edge (the box and beamer's gap below it); the strip hangs from
    # there by the top sep and is as long as Hsize
    patch = [d["rect"] for d in page.get_drawings() if cl.is_white(d.get("fill")) and d["rect"].x0 > 400 and d["rect"].y0 < 1
             and d["rect"].width < 60]
    foot = patch[0].y1
    top = foot + hooks["SMSideFootnoteTopSep"]
    lengths = [r.height for r in strip]
    assert max(lengths) <= hooks["SMSideFootnoteHsize"] + 0.3
    assert max(lengths) >= 0.9 * hooks["SMSideFootnoteHsize"]
    assert min(r.y0 for r in strip) >= top - 0.3
    assert max(r.y1 for r in strip) <= top + hooks["SMSideFootnoteHsize"] + 0.5


def fitz_rect(bbox):
    return pymupdf.Rect(bbox)


@needs_tex
def test_a_block_sets_its_text_the_side_margin_in(decks):
    deck = decks["cal"]
    page, hooks = deck.page("ZC7"), cl.pdf_hooks(deck.doc)
    body = [s for s in cal.spans(page) if s["text"].startswith("Neutral")][0]
    assert body["origin"][0] - hooks["SMTextMarginLeft"] == pytest.approx(hooks["SMBlockSideMargin"], abs=0.02)


@needs_tex
def test_the_section_and_quote_boxes_are_as_high_as_their_hooks(decks):
    deck = decks["cal"]
    hooks = cl.pdf_hooks(deck.doc)
    assert first_fill(deck.page("ZC2")).y1 == pytest.approx(hooks["SMSectionframeBoxHeight"], abs=0.03)
    assert first_fill(deck.page("ZC9"), wide=False).y1 == pytest.approx(hooks["SMQuoteBoxHeight"], abs=0.03)


def ink_rows(page, clip, dpi=1152):
    """(first, last) row of ink in `clip`, in bp from the page's top: pixels that differ from the clip's top left corner."""
    pix = page.get_pixmap(dpi=dpi, clip=clip, colorspace=pymupdf.csRGB, alpha=False)
    s, n = pix.samples, pix.n
    bg = s[(pix.width - 1) * n:(pix.width - 1) * n + 3]               # the top right corner
    rows = [y for y in range(pix.height)
            if any(max(abs(s[(y * pix.width + x) * n + k] - bg[k]) for k in range(3)) > 60 for x in range(pix.width))]
    return clip.y0 + rows[0] * 72 / dpi, clip.y0 + (rows[-1] + 1) * 72 / dpi


@needs_tex
def test_the_quote_attribution_hangs_the_gap_under_the_box(decks):
    deck = decks["cal"]
    page, hooks = deck.page("ZC9"), cl.pdf_hooks(deck.doc)
    box = first_fill(page, wide=False)
    attribution = [s for s in cal.spans(page) if "Saint" in s["text"] and s["size"] > 8][0]
    clip = pymupdf.Rect(attribution["bbox"][0], box.y1 + 0.3, attribution["bbox"][2], attribution["bbox"][3] + 2)
    ink_top, _ = ink_rows(page, clip)
    # the node hangs from the box's edge; its top is its tallest glyph (a parenthesis or an ascender)
    assert ink_top - box.y1 == pytest.approx(hooks["SMQuoteAttributionGap"], abs=0.5)     # TeX's box of the tallest character, not its ink


@needs_tex
def test_the_title_frame_text_stands_the_bottom_pad_above_the_boxs_edge(decks):
    deck = decks["cal"]
    page, hooks = deck.page("ZC1"), cl.pdf_hooks(deck.doc)
    box = first_fill(page, wide=False)
    assert box.height == pytest.approx(hooks["SMTitleframeBoxHeight"], abs=0.03)       # the box: as high as the hook says
    lines = [line for block in page.get_text("dict")["blocks"] for line in block.get("lines", [])
             if line["spans"][0]["size"] > 8]
    assert len(lines) == 3 and "gjpqy" in "".join(s["text"] for s in lines[-1]["spans"])
    baseline = lines[-1]["spans"][0]["origin"][1]
    # by the descender the base reports ...
    assert box.y1 - baseline - hooks["SMTitleframeDescender"] == pytest.approx(hooks["SMTitleframeBottomPad"], abs=0.01)
    # ... and in the page: the deepest ink of the last line (a g, j, p, q or y) is the pad above the edge
    clip = pymupdf.Rect(lines[-1]["bbox"][0], baseline - 8, lines[-1]["bbox"][2] + 4, box.y1 - 0.3)
    _, ink_bottom = ink_rows(page, clip)
    assert box.y1 - ink_bottom == pytest.approx(hooks["SMTitleframeBottomPad"], abs=0.12)
    # check_layout reads the same keys and finds it right, and finds a pad that is off
    chrome = deck.chrome(page)
    chrome.hooks = hooks
    assert chrome.check_titlepad(0.6) == []
    chrome.hooks = {**hooks, "SMTitleframeBottomPad": hooks["SMTitleframeBottomPad"] + 5}
    assert chrome.check_titlepad(0.6)                      # a pad that is 5bp off is reported


@needs_tex
def test_the_default_title_frame_has_the_text_of_v10_9_0(decks):
    """The new default pad (8.505pt) reproduces the positions the old placement through the frame gave with 41pt."""
    page = decks["fira"].doc[0]
    lines = [line["spans"][0] for block in page.get_text("dict")["blocks"] for line in block.get("lines", [])
             if line["spans"][0]["size"] > 8]
    assert [round(s["origin"][1], 2) for s in lines] == pytest.approx([95.24, 154.41, 175.03], abs=0.01)
    assert all(abs(s["origin"][0] - 39.571) < 0.01 for s in lines)


@needs_tex
def test_the_frame_number_and_the_footnotes_end_on_the_logos_padding_edge(decks):
    for name in ("cal", "fira"):
        deck = decks[name]
        hooks = cl.pdf_hooks(deck.doc)
        assert "SMFrametitleRightPadding" in hooks
        for slide in ("ZC3", "ZC8"):
            chrome = deck.chrome(deck.page(slide))
            chrome.hooks = hooks
            assert chrome.check_edge(0.2) == [], (name, slide)
        wrong = deck.chrome(deck.page("ZC8"))
        wrong.hooks = {**hooks, "SMFrametitleRightPadding": hooks["SMFrametitleRightPadding"] + 3}
        assert wrong.check_edge(0.2)                       # an edge 3bp off is reported
