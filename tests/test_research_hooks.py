"""The hooks of docs/plans/research-theme.md, step F1: the plain frame title, its alignment, a template without a logo,
the page border, the footer without a box and in its own font, and background pictures per kind of frame.

The research-hooks template (tests/fixtures/template_research/) switches each on with a value of its own; its deck
has one frame of each kind the hooks treat differently (title, left title, centred title, section, standout, quote).
The compile is opt-in (SLIDEMAGE_TEX_TESTS=1 and latexmk), like the other tests that compile. That the defaults
change nothing is checked by tools/framework_regression.py on the manual (all templates), not here.
"""
import os
import shutil
from pathlib import Path

import pymupdf
import pytest
from conftest import load_tool

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "template_research"
BP = 72 / 72.27                       # bp per TeX point
TOL = 0.05                            # bp


needs_tex = pytest.mark.skipif(not os.environ.get("SLIDEMAGE_TEX_TESTS") or not shutil.which("latexmk"),
                               reason="compiles the research-hooks deck: SLIDEMAGE_TEX_TESTS=1 and latexmk")

# The fixture template's values (tests/fixtures/template_research/SlideMage_template_research-test.tex), in pt.
INSET_TOP, INSET_LEFT, INSET_RIGHT, BORDER_WIDTH, FOOTER_BOX = 12, 9, 11, 0.9, 14
TITLE_LEFT_PADDING = 20
BORDER_RED = (0.8, 0.0, 0.0)          # c_custom_red, cc0000
TITLE, LEFT, CENTRED, SECTION, STANDOUT, QUOTE = range(6)


@pytest.fixture(scope="module")
def deck(tmp_path_factory):
    cal = load_tool("calibrate_font_profile")
    out = tmp_path_factory.mktemp("research") / "research.pdf"
    cal.compile_deck(FIXTURE, "decks/research.tex", "research-test", None, ROOT / "latex", out)
    return pymupdf.open(out)


def border(page):
    """The page border: a stroked rectangle in the border's color, or None."""
    found = [d for d in page.get_drawings() if d.get("color") and d.get("width")
             and all(abs(a - b) < 0.01 for a, b in zip(d["color"], BORDER_RED)) and d["rect"].width > 300]
    return found[0] if found else None


def spans(page):
    return [s for b in page.get_text("dict")["blocks"] for line in b.get("lines", []) for s in line["spans"]
            if s["text"].strip()]


def span_with(page, text):
    return next(s for s in spans(page) if text in s["text"])


@needs_tex
def test_the_border_lies_at_its_insets_and_its_bottom_edge_on_the_footer_box(deck):
    page = deck[LEFT]
    w, h = page.rect.width, page.rect.height
    found = border(page)
    assert found is not None
    r = found["rect"]
    assert abs(r.x0 - INSET_LEFT * BP) < TOL
    assert abs(r.y0 - INSET_TOP * BP) < TOL
    assert abs(r.x1 - (w - INSET_RIGHT * BP)) < TOL
    assert abs(r.y1 - (h - FOOTER_BOX * BP)) < TOL
    assert abs(found["width"] - BORDER_WIDTH * BP) < 0.01


@needs_tex
def test_the_border_is_on_the_kinds_it_names_and_not_on_frames_that_cover_the_page(deck):
    for index in (TITLE, LEFT, CENTRED, SECTION):
        assert border(deck[index]) is not None, f"page {index + 1}"
    for index in (STANDOUT, QUOTE):
        assert border(deck[index]) is None, f"page {index + 1}"


@needs_tex
def test_a_plain_title_has_no_bar(deck):
    page = deck[LEFT]
    w = page.rect.width
    title = span_with(page, "Left title")
    # the page's own white canvas is the only wide fill that reaches the title's line
    bars = [d for d in page.get_drawings() if d.get("fill") is not None and d["fill"] != (1.0, 1.0, 1.0)
            and d["rect"].width > w - 1 and d["rect"].y0 < title["bbox"][1] < d["rect"].y1]
    assert not bars


@needs_tex
def test_a_left_title_starts_at_its_padding_and_a_centred_one_in_the_middle(deck):
    left = span_with(deck[LEFT], "Left title")
    assert abs(left["bbox"][0] - TITLE_LEFT_PADDING * BP) < 0.5        # the glyph's side bearing
    centred = span_with(deck[CENTRED], "Centred title")
    middle = (centred["bbox"][0] + centred["bbox"][2]) / 2
    assert abs(middle - deck[CENTRED].rect.width / 2) < 0.5
    assert abs(centred["bbox"][1] - left["bbox"][1]) < TOL            # the same line as the left title


@needs_tex
def test_the_footer_has_no_box_takes_its_font_and_stays_under_the_border(deck):
    page = deck[LEFT]
    h = page.rect.height
    footer = span_with(page, "Research hooks deck")
    assert "Italic" in footer["font"]
    assert footer["bbox"][1] > h - FOOTER_BOX * BP - TOL
    boxes = [d for d in page.get_drawings() if d.get("fill") is not None and d["fill"] != (1.0, 1.0, 1.0)
             and d["rect"].y0 > h - FOOTER_BOX * BP - 1 and d["rect"].width > page.rect.width - 1]
    assert not boxes


@needs_tex
def test_the_slide_number_ends_where_the_footer_right_edge_hook_says(deck):
    page = deck[LEFT]
    number = [s for s in spans(page) if s["bbox"][1] > page.rect.height - FOOTER_BOX * BP - TOL][-1]
    assert abs(number["bbox"][2] - (page.rect.width - INSET_RIGHT * BP)) < 0.6      # the digit ends on the border's right line


@needs_tex
def test_a_footnote_stays_inside_the_border(deck):
    page = deck[LEFT]
    note = span_with(page, "The footnote.")
    assert note["bbox"][3] < page.rect.height - FOOTER_BOX * BP


@needs_tex
def test_the_background_picture_is_drawn_per_kind_and_embedded_once(deck):
    kinds = [{x[0] for x in deck[i].get_xobjects()} for i in range(len(deck))]
    for index in (TITLE, LEFT, CENTRED, SECTION):
        assert kinds[index], f"page {index + 1} has no background picture"
    assert not kinds[STANDOUT] and not kinds[QUOTE]
    # two sizes (title/section 0.8 paper heights, content 2): the same file is one object in the PDF
    assert len(set().union(*kinds)) == 1


def lines(page):
    """Each text line of the page: (its text, its bbox)."""
    found = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(s["text"] for s in line["spans"]).strip()
            if text:
                found.append((text, pymupdf.Rect(line["bbox"])))
    return found


def line_with(page, text):
    return next(rect for line, rect in lines(page) if text in line)


def dark_fills(page, wide):
    """Dark fills from the page's top-left corner, as the title frame's box and the section frame's bar are (the
    background picture's own dark shapes, drawn faint, lie elsewhere)."""
    return [d for d in page.get_drawings() if d.get("fill") is not None and max(d["fill"]) < 0.5
            and d["rect"].width > wide and d["rect"].x0 < 0.5 and d["rect"].y0 < 0.5]


@needs_tex
def test_a_plain_title_frame_has_no_box_and_centres_its_lines_in_order(deck):
    page = deck[TITLE]
    middle = page.rect.width / 2
    assert not dark_fills(page, 100)                                      # no title box
    order = ["Research hooks", "The test deck", "Ann Author", "First University", "Second Institute",
             "Journal of Tests"]
    rects = [line_with(page, text) for text in order]
    for text, rect in zip(order, rects):
        assert abs((rect.x0 + rect.x1) / 2 - middle) < 1.5, text          # centred (superscripts: a little slack)
    tops = [rect.y0 for rect in rects]
    assert tops == sorted(tops)
    # the logo row (0.9cm high) sits between the affiliations and the venue
    assert rects[-1].y0 - rects[-2].y1 > 0.9 / 2.54 * 72
    border_top = INSET_TOP * BP
    assert rects[0].y0 > border_top and rects[-1].y1 < page.rect.height - FOOTER_BOX * BP


@needs_tex
def test_a_plain_divider_centres_title_and_body_and_keeps_the_footer(deck):
    page = deck[SECTION]
    middle = page.rect.width / 2
    assert not dark_fills(page, 100)                                      # no bar
    title, body = line_with(page, "A section"), line_with(page, "frame’s body")
    assert abs((title.x0 + title.x1) / 2 - middle) < 0.5
    assert abs((body.x0 + body.x1) / 2 - middle) < 0.5
    assert title.y1 < body.y0
    assert span_with(page, "Research hooks deck")                         # the footer is there


@needs_tex
def test_the_frame_number_links_to_the_appendix_overview_without_a_logo(tmp_path_factory):
    cal = load_tool("calibrate_font_profile")
    out = tmp_path_factory.mktemp("research-link") / "link.pdf"
    cal.compile_deck(FIXTURE, "decks/link.tex", "research-test", None, ROOT / "latex", out)
    doc = pymupdf.open(out)
    overview = len(doc) - 1
    for index in range(len(doc)):
        page = doc[index]
        links = [link for link in page.get_links() if link.get("page") == overview]
        assert len(links) == 1, f"page {index + 1}"
        assert page.get_textbox(links[0]["from"]).strip() == str(index + 1)


@needs_tex
def test_a_template_without_a_logo_draws_none(deck):
    page = deck[LEFT]
    w = page.rect.width
    corner = pymupdf.Rect(w - 60, 0, w, 40)
    assert not [d for d in page.get_drawings() if d["rect"] in corner and d.get("fill") is not None]
