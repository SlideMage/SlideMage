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
        def __init__(self, tops, standard=True):
            self.footnotes = [pymupdf.Rect(0, y, 10, y + 5) for y in tops]
            self.standard = standard
    assert cl.usual_footnote_top([]) == cl.FOOTNOTE_LAST_TOP
    assert cl.usual_footnote_top([Stub([]), Stub([], standard=False)]) == cl.FOOTNOTE_LAST_TOP
    # the highest last line of any ordinary frame, plus the allowance for a source line without a raised marker
    assert cl.usual_footnote_top([Stub([230.0, 241.9]), Stub([243.1]), Stub([200.0], standard=False)]) == \
        241.9 + cl.FOOTNOTE_MARKER_ALLOWANCE
