# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""tools/check_layout.py takes the Top and Left Margin from the PDF's info dictionary (no TeX involved)."""
import importlib.util
from pathlib import Path

import pymupdf

TOOL = Path(__file__).resolve().parents[1] / "tools" / "check_layout.py"
spec = importlib.util.spec_from_file_location("check_layout", TOOL)
cl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cl)


def pdf(tmp_path, **info):
    """A one-page PDF whose info dictionary holds `info` as PDF strings, as SlideMage_base.tex writes them."""
    doc = pymupdf.open()
    doc.new_page(width=455.24, height=256.07)
    doc.set_metadata({"title": "probe"})
    kind, ref = doc.xref_get_key(-1, "Info")
    for key, value in info.items():
        doc.xref_set_key(int(ref.split()[0]), key, f"({value})")
    path = tmp_path / "probe.pdf"
    doc.save(path)
    return pymupdf.open(path)


def test_margins_come_from_the_pdf(tmp_path):
    doc = pdf(tmp_path, SMTopMargin="50.5", SMLeftMargin="20.25")
    assert cl.pdf_margins(doc) == (50.5, 20.25)
    page = cl.Page(doc[0], *cl.pdf_margins(doc))
    assert (page.top_margin, page.left_margin) == (50.5, 20.25)


def test_a_pdf_without_the_keys_falls_back_to_the_slidemage_template(tmp_path):
    assert cl.pdf_margins(pdf(tmp_path)) == (cl.TOP_MARGIN, cl.LEFT_MARGIN)
    assert cl.pdf_margins(pdf(tmp_path, SMTopMargin="45")) == (45.0, cl.LEFT_MARGIN)
    assert cl.pdf_margins(pdf(tmp_path, SMLeftMargin="not a number")) == (cl.TOP_MARGIN, cl.LEFT_MARGIN)


def test_the_fonts_ascender_and_title_bar_come_from_the_pdf_too(tmp_path):
    doc = pdf(tmp_path, SMTopMargin="50", SMLeftMargin="15.5", SMFontAscender="0.806", SMTitleBarBottom="30.43")
    info = cl.pdf_info(doc)
    assert info == {"top_margin": 50.0, "left_margin": 15.5, "ascender": 0.806, "title_bar_bottom": 30.43}
    page = cl.Page(doc[0], info["top_margin"], info["left_margin"], info["ascender"], info["title_bar_bottom"])
    assert (page.ascender, page.title_bar_bottom) == (0.806, 30.43)
    # an older PDF is checked against the SlideMage template's Fira ascender and title bar
    (tmp_path / "old").mkdir()
    old = cl.pdf_info(pdf(tmp_path / "old"))
    assert (old["ascender"], old["title_bar_bottom"]) == (cl.FIRA_ASCENDER, cl.TITLE_BAR_BOTTOM)


def test_a_frame_has_the_ordinary_title_bar_when_its_bar_ends_near_the_decks_own(tmp_path):
    def page_with_bar(bottom, title_bar_bottom):
        doc = pymupdf.open()
        page = doc.new_page(width=455.24, height=256.07)
        page.insert_text((20, 120), "(slide id: ZZ1 | v1)", fontsize=4)
        page.draw_rect(pymupdf.Rect(0, 0, 455.24, bottom), color=None, fill=(0.1, 0.1, 0.1))
        return cl.Page(page, 41.58, 12.55, 0.935, title_bar_bottom)
    assert page_with_bar(25.2, cl.TITLE_BAR_BOTTOM).standard
    assert not page_with_bar(30.4, cl.TITLE_BAR_BOTTOM).standard      # another template's bar is not "ordinary" for Fira's
    assert page_with_bar(30.4, 30.43).standard                          # but it is for the deck that says so
    assert not page_with_bar(85.0, 30.43).standard                      # a section frame's bar never is


def test_maths_fonts_are_not_body_fonts_and_the_others_are():
    for name in ("LMRoman10-Italic", "CMR10", "CMMI8", "CMSY10", "LMMathItalic10-Regular", "ABCDEF+CMR10"):
        assert cl.MATH_FONT_RE.match(name), name
    for name in ("FiraSans-Light", "FiraMono-Regular", "LMSans10-Regular", "LMMono10-Regular", "LMSans10-Bold"):
        assert not cl.MATH_FONT_RE.match(name), name


def test_the_usual_last_footnote_line_is_the_decks_own(tmp_path):
    class Stub:
        def __init__(self, tops, standard=True, slide_id=None):
            self.footnotes = [pymupdf.Rect(0, y, 10, y + 5) for y in tops]
            self.standard = standard
            self.slide_id = slide_id
    assert cl.usual_footnote_top([]) == cl.FOOTNOTE_LAST_TOP
    assert cl.usual_footnote_top([Stub([]), Stub([], standard=False)]) == cl.FOOTNOTE_LAST_TOP
    # the highest last line of any ordinary frame, plus the allowance for a source line without a raised marker
    assert cl.usual_footnote_top([Stub([230.0, 241.9]), Stub([243.1]), Stub([200.0], standard=False)]) == \
        241.9 + cl.FOOTNOTE_MARKER_ALLOWANCE
    # only a slide's last step counts: on an earlier one a footnote of revealed content is hidden (v10.12.0)
    steps = [Stub([238.0], slide_id="ZCM"), Stub([238.0, 243.0], slide_id="ZCM"), Stub([243.1], slide_id="ZC8")]
    assert cl.usual_footnote_top(steps) == 243.0 + cl.FOOTNOTE_MARKER_ALLOWANCE


def test_the_geometric_hooks_come_from_the_pdf_and_an_older_pdf_has_none(tmp_path):
    doc = pdf(tmp_path, SMTopMargin="50", SMFrametitleRightPadding="14.17322", SMTitleframeBottomPad="8.505",
              SMFontAscender="0.806")
    assert cl.pdf_hooks(doc) == {"SMFrametitleRightPadding": 14.17322, "SMTitleframeBottomPad": 8.505}      # the four margin keys have readers of their own
    (tmp_path / "old").mkdir()
    assert cl.pdf_hooks(pdf(tmp_path / "old")) == {}


def page_with(draw, hooks):
    """A page of the deck size on which `draw(page)` puts what a check looks at, wrapped in a check_layout.Page."""
    doc = pymupdf.open()
    page = doc.new_page(width=455.24, height=256.07)
    draw(page)
    return cl.Page(page, 41.58, 12.55, 0.935, 25.2, hooks)


def test_the_frame_number_and_the_footnotes_must_end_on_the_logos_padding_edge():
    width = 455.24

    def footer(end_of_number, end_of_note):
        def draw(page):
            page.draw_rect(pymupdf.Rect(0, 246, width, 256.07), color=None, fill=(0.3, 0.3, 0.3))
            page.insert_text((end_of_number - pymupdf.get_text_length("12", fontsize=6), 253), "12", fontsize=6, color=(1, 1, 1))
            page.insert_text((end_of_note - pymupdf.get_text_length("A footnote.", fontsize=3.4), 240), "A footnote.", fontsize=3.4)
        return draw

    hooks = {"SMFrametitleRightPadding": 14.0}
    edge = width - 14.0
    assert page_with(footer(edge, edge), hooks).check_edge(0.3) == []
    assert page_with(footer(edge - 0.2, edge + 0.2), hooks).check_edge(0.3) == []         # within the tolerance
    found = page_with(footer(edge - 3, edge), hooks).check_edge(0.3)
    assert len(found) == 1 and "frame number" in found[0] and "-3.00" in found[0]
    found = page_with(footer(edge, edge + 2), hooks).check_edge(0.3)
    assert len(found) == 1 and "footnote line" in found[0] and "+2.00" in found[0]


def test_the_title_frame_bottom_pad_is_the_space_from_the_last_lines_bottom_to_the_boxs_edge():
    box_height, pad = 178.0, 30.0

    def title_frame(baseline, text="Subtitle gjpqy"):
        def draw(page):
            page.draw_rect(pymupdf.Rect(0, 0, 403.0, box_height), color=None, fill=(0.1, 0.5, 0.2))
            page.insert_text((50, 60), "Title", fontsize=24, color=(1, 1, 1))
            page.insert_text((50, baseline), text, fontsize=14, color=(1, 1, 1))
        return draw

    # where the deepest ink of the descender line lies under its baseline in this font
    probe = page_with(title_frame(100.0), {})
    depth = cl.ink_extent(probe.page, pymupdf.Rect(40, 94, 200, 120)) - 100.0
    assert depth > 2.5
    hooks = {"SMTitleframeBoxHeight": box_height, "SMTitleframeBottomPad": pad}
    exact = box_height - pad - depth
    assert page_with(title_frame(exact), hooks).check_titlepad(0.3) == []
    found = page_with(title_frame(exact + 4), hooks).check_titlepad(0.3)
    assert len(found) == 1 and "26.00" in found[0] and "pad says 30.00" in found[0]
    # a last line without descenders has a line box the PDF does not describe: not checked
    assert page_with(title_frame(exact + 4, "Subtitle"), hooks).check_titlepad(0.3) == []
    # no keys, no check; a quote frame's box (another height, or the same one) is left alone
    assert page_with(title_frame(exact + 4), {}).check_titlepad(0.3) == []
    assert page_with(title_frame(exact + 4), {**hooks, "SMQuoteBoxHeight": box_height}).check_titlepad(0.3) == []
    assert page_with(title_frame(exact + 4), {**hooks, "SMTitleframeBoxHeight": 150.0}).check_titlepad(0.3) == []
