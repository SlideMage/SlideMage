"""The readability check: its rules on synthetic PDFs built with MuPDF (text of chosen sizes, colours and positions, images,
figures) read by the real measurement code (readability_pdf.read_pages, in this process; one test goes through the raster
child), the classification of the text, the pages of a deck becoming slides, the reports, and the deck PDF's freshness. No
LaTeX is needed; the one end-to-end check against a real beamer page is skipped without lualatex."""
from __future__ import annotations

import json
import os
import shutil
import threading
from pathlib import Path

import pymupdf
import pytest
from conftest import SLIDE_TEXT, make_project  # noqa: F401 -- make_project is used through the root fixture

from slidemage import compile_records, compiler, preview_raster_client, readability, readability_check, readability_pdf
from slidemage.deck_scan import scan_decks
from slidemage.project import ProjectContext
from slidemage.readability import BODY, CITATION, ERROR, FIGURE_TEXT, HEADING, WARNING
from slidemage.slide_snapshot import slide_runs

W, H = 454.0, 255.0          # a 16:9 slide of 160 x 90 mm, as the templates set it
FOOTER_TOP = 248.0


def size(pct: float) -> float:
    """The font size (points) that is `pct` % of the slide height."""
    return pct / 100 * H


def footer(page, slide_id="abc", number=1) -> None:
    page.draw_rect(pymupdf.Rect(0, FOOTER_TOP, W, H), color=None, fill=(0.12, 0.12, 0.12))
    page.insert_text((12, 253.5), f"(slide id: {slide_id} | instructor deck) {number}", fontsize=4, color=(1, 1, 1))


def body(page, pct=4.0, count=3, top=60.0, x=12.0, text="An ordinary line of body text", spacing=1.4, color=(0.1, 0.1, 0.1)):
    for index in range(count):
        page.insert_text((x, top + index * size(pct) * spacing), text, fontsize=size(pct), color=color)


def title(page, pct=5.0, text="The slide title", y=22.0, color=(1, 1, 1)):
    page.draw_rect(pymupdf.Rect(0, 0, W, 32), color=None, fill=(0.12, 0.12, 0.12))
    page.insert_text((12, y), text, fontsize=size(pct), color=color)


def picture(page, rect, color=(200, 80, 40)) -> None:
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 160, 90))
    pixmap.set_rect(pixmap.irect, color)
    page.insert_image(pymupdf.Rect(*rect), pixmap=pixmap, keep_proportion=False)


def figure(page, rect) -> None:
    """A vector figure: a grid of lines, enough paths to be one."""
    x0, y0, x1, y1 = rect
    for index in range(14):
        page.draw_line((x0 + index * (x1 - x0) / 14, y0), (x0 + index * (x1 - x0) / 14, y1), color=(0, 0, 0))
    page.draw_rect(pymupdf.Rect(*rect), color=(0, 0, 0))


def pdf_of(tmp_path, *draws, name="deck.pdf") -> Path:
    doc = pymupdf.open()
    for draw in draws:
        draw(doc.new_page(width=W, height=H))
    path = tmp_path / name
    doc.save(path)
    return path


def measure(tmp_path, *draws, slide="abc") -> readability.Report:
    """The report of a one-slide render (every page is that slide's)."""
    pages = [readability.Page.from_dict(data) for data in readability_pdf.read_pages(pdf_of(tmp_path, *draws))]
    return readability.analyse(pages, [(slide, list(range(len(pages))))])


def slide(draw=None, **kwargs):
    """A page with the footer, a title and some body text, plus whatever `draw` adds."""
    def make(page):
        footer(page)
        title(page)
        body(page, **kwargs)
        if draw is not None:
            draw(page)
    return make


def findings(report, rule=None, cls=None, severity=None):
    return [f for f in report.findings
            if (rule is None or f.rule == rule) and (cls is None or f.cls == cls) and (severity is None or f.severity == severity)]


# -- the text size rules ------------------------------------------------------------------------------------------

def test_body_text_below_the_floor_is_an_error_near_it_a_warning_and_from_the_floor_up_fine(tmp_path):
    error, = findings(measure(tmp_path, slide(pct=2.8)), "text_size", BODY)
    assert (error.severity, error.threshold, error.needs, error.count) == (ERROR, 3.3, readability.MIN, 3)
    assert error.measured == pytest.approx(2.8, abs=0.05) and error.excerpt == "An ordinary line of body text"
    assert error.suggestion.startswith("Body text 2.8 % of slide height (≈ 15 pt projected) is below the floor of 3.3 %: "
                                       "enlarge to \\small or larger, or split the slide.")
    near, = findings(measure(tmp_path, slide(pct=3.4)), "text_size", BODY)
    assert near.severity == WARNING and "close to the floor" in near.suggestion
    assert findings(measure(tmp_path, slide(pct=3.5)), "text_size") == []             # beamer's \footnotesize and up
    assert findings(measure(tmp_path, slide(pct=4.0))) == []


def test_the_size_is_relative_to_the_slide_not_in_points(tmp_path):
    def small_slide(page):                      # the same 10 pt text on a slide half as high is twice as large
        page.insert_text((6, 30), "An ordinary line of body text", fontsize=10)
    doc = pymupdf.open()
    small_slide(doc.new_page(width=W / 2, height=H / 2))
    path = tmp_path / "small.pdf"
    doc.save(path)
    page = readability.Page.from_dict(readability_pdf.read_pages(path)[0])
    assert page.pct(10) == pytest.approx(7.84, abs=0.01)
    assert readability.analyse([page], [("abc", [0])]).findings == []


def test_headings_have_the_body_floor_and_should_not_be_smaller_than_the_body(tmp_path):
    small, = findings(measure(tmp_path, slide(pct=4.0)), "text_size", HEADING) or [None]
    assert small is None                                         # 5 % title over 4 % body: fine
    def heading_at(pct):
        def make(page):
            footer(page)
            title(page, pct)
            body(page, 4.0)
        return make
    below, = findings(measure(tmp_path, heading_at(3.1)), "text_size", HEADING)
    assert below.severity == ERROR and below.excerpt == "The slide title" and "title" in below.suggestion
    smaller, = findings(measure(tmp_path, heading_at(3.7)), "text_size", HEADING)
    assert smaller.severity == WARNING and smaller.threshold == pytest.approx(4.0, abs=0.05)
    assert "smaller than the slide's body text" in smaller.suggestion


def test_a_large_title_in_the_upper_part_of_a_slide_is_a_heading(tmp_path):
    def section(page):
        footer(page)
        page.draw_rect(pymupdf.Rect(0, 0, W, 85), color=None, fill=(0.12, 0.12, 0.12))
        page.insert_text((12, 70), "The big picture", fontsize=size(8), color=(1, 1, 1))
        body(page, 4.0, top=110)
    assert findings(measure(tmp_path, section), "text_size") == []
    def tiny_section(page):
        footer(page)
        page.draw_rect(pymupdf.Rect(0, 0, W, 85), color=None, fill=(0.12, 0.12, 0.12))
        page.insert_text((12, 70), "The big picture", fontsize=size(3.0), color=(1, 1, 1))
        body(page, 2.0, top=110)                   # (the body is smaller still, so the title is not "larger")
    classes = {f.cls for f in measure(tmp_path, tiny_section).findings}
    assert BODY in classes


def test_citations_have_a_looser_floor_and_are_told_by_their_words_or_by_small_print_low_on_the_slide(tmp_path):
    def cite(pct, text):
        def make(page):
            footer(page)
            title(page)
            body(page, 4.0)
            page.insert_text((12, 238), text, fontsize=size(pct), color=(0.1, 0.1, 0.1))
        return make
    error, = findings(measure(tmp_path, cite(2.0, "Source: Own illustration, 2024")), "text_size")
    assert (error.cls, error.severity, error.threshold) == (CITATION, ERROR, 2.2)
    assert "move it to the notes" in error.suggestion
    assert findings(measure(tmp_path, cite(2.3, "Source: Own illustration, 2024")), "text_size", severity=WARNING)[0].cls == CITATION
    assert findings(measure(tmp_path, cite(2.6, "Source: Own illustration, 2024")), "text_size") == []
    assert findings(measure(tmp_path, cite(2.6, "Quelle: eigene Darstellung")), "text_size") == []
    # a footnote marker symbol of the template, and small print without any of the words
    assert findings(measure(tmp_path, cite(2.0, "£ A note on the claim above")), "text_size")[0].cls == CITATION
    assert findings(measure(tmp_path, cite(2.0, "Some small print low on the slide")), "text_size")[0].cls == CITATION
    # the same small text in the middle of the slide is a body line, judged by the body floor
    def middle(page):
        footer(page)
        title(page)
        body(page, 4.0)
        page.insert_text((12, 150), "Some small print in the middle", fontsize=size(2.0))
    assert findings(measure(tmp_path, middle), "text_size")[0].cls == BODY


def test_sideways_small_print_is_a_citation(tmp_path):
    def sideways(page):
        footer(page)
        title(page)
        body(page, 4.0)
        page.insert_text((440, 230), "Own illustration.", fontsize=size(1.25), rotate=90)
    found, = findings(measure(tmp_path, sideways), "text_size")
    assert found.cls == CITATION and found.severity == ERROR and found.measured == pytest.approx(1.25, abs=0.05)


def test_text_inside_a_figure_has_its_own_floor(tmp_path):
    def labelled(pct):
        def make(page):
            footer(page)
            title(page)
            body(page, 4.0, top=50)
            figure(page, (230, 90, 440, 200))
            page.insert_text((250, 150), "Axis label", fontsize=size(pct), color=(0, 0, 0))
        return make
    error, = findings(measure(tmp_path, labelled(2.3)), "text_size", FIGURE_TEXT)
    assert (error.severity, error.threshold) == (ERROR, 2.6) and "larger labels" in error.suggestion
    assert findings(measure(tmp_path, labelled(2.65)), "text_size", FIGURE_TEXT)[0].severity == WARNING
    assert findings(measure(tmp_path, labelled(3.0)), "text_size") == []              # below the body floor, but fine in a figure

    def outside(page):
        footer(page)
        title(page)
        body(page, 4.0, top=50)
        page.insert_text((250, 240), "Axis label", fontsize=size(3.2), color=(0, 0, 0))
    assert findings(measure(tmp_path, outside), "text_size")[0].cls == BODY


def test_the_footer_the_slide_id_stamp_and_invisible_text_are_not_content(tmp_path):
    def make(page):
        footer(page)                                                    # 1.6 % white text on the dark footer bar
        title(page)
        body(page, 4.0)
        page.insert_text((12, 20), "(slide id: abc)", fontsize=size(1.0), render_mode=3)           # the invisible stamp
        page.insert_text((300, 150), "Alt text of a figure, invisible", fontsize=size(0.9), render_mode=3)
        page.insert_text((12, 244), "(slide id: abc | instructor deck)", fontsize=size(1.0))        # visible, but a stamp
    assert measure(tmp_path, make).findings == []
    pages = readability_pdf.read_pages(pdf_of(tmp_path, make))
    texts = [line["text"] for line in pages[0]["lines"]]
    assert not any("Alt text" in text for text in texts) and any("instructor deck" in text for text in texts)


def test_a_superscript_marker_or_a_bullet_does_not_make_a_line_small(tmp_path):
    def make(page):
        footer(page)
        title(page)
        body(page, 4.0)
        page.insert_text((12, 150), "The claim with a note", fontsize=size(4.0))
        page.insert_text((150, 144), "£", fontsize=size(1.5))
        page.insert_text((300, 150), "•", fontsize=size(1.5))
    assert findings(measure(tmp_path, make), "text_size") == []


# -- images ------------------------------------------------------------------------------------------------------

def test_the_largest_image_shown_small_is_a_warning_and_the_report_names_its_pixels(tmp_path):
    small, = findings(measure(tmp_path, slide(lambda page: picture(page, (300, 80, 400, 140)))), "image_size")
    assert (small.severity, small.cls, small.threshold, small.needs) == (WARNING, readability.IMAGE, 25, readability.MIN)
    assert small.measured == pytest.approx(100 * 60 / (W * H) * 100, abs=0.1) and small.pixels == (160, 90)
    assert "may be too small to read" in small.suggestion
    assert small.bbox == pytest.approx((300 / W, 80 / H, 400 / W, 140 / H), abs=0.002)
    assert findings(measure(tmp_path, slide(lambda page: picture(page, (200, 40, 440, 240)))), "image_size") == []
    narrow, = findings(measure(tmp_path, slide(lambda page: picture(page, (300, 40, 350, 150)))), "image_size") or [None]
    assert narrow is not None and narrow.measured < 25                       # 50 x 110 points: small in area too


def test_a_tall_picture_is_not_judged_by_its_width_and_icons_and_backgrounds_are_not_judged_at_all(tmp_path):
    tall = slide(lambda page: picture(page, (380, 36, 440, 246)), pct=4.0)      # 13 % wide but 82 % high, 24 % of the area
    found, = findings(measure(tmp_path, tall), "image_size")
    assert found.measured < 25
    wide_enough = slide(lambda page: picture(page, (150, 36, 440, 246)))
    assert findings(measure(tmp_path, wide_enough), "image_size") == []
    narrow_tall = slide(lambda page: picture(page, (330, 36, 440, 246)))        # 24 % wide, 82 % high: 20 % of the area
    assert findings(measure(tmp_path, narrow_tall), "image_size")[0].unit == "% of the slide area"
    tall_enough = slide(lambda page: picture(page, (260, 36, 440, 246)))        # 40 % wide
    assert findings(measure(tmp_path, tall_enough), "image_size") == []
    logo = slide(lambda page: picture(page, (400, 5, 440, 25)))
    assert findings(measure(tmp_path, logo), "image_size") == []
    background = slide(lambda page: picture(page, (0, 0, W, H)))
    assert findings(measure(tmp_path, background), "image_size") == []


# -- contrast, clipping, overlap, density, spacing -------------------------------------------------------------

def test_low_contrast_is_an_error_with_the_wcag_ratio_and_headings_need_less(tmp_path):
    grey = measure(tmp_path, slide(color=(0.62, 0.62, 0.62)))
    found, = findings(grey, "contrast")
    assert (found.severity, found.threshold, found.needs) == (ERROR, 4.5, readability.MIN)
    assert found.measured == pytest.approx(readability.contrast_ratio(0x9E9E9E, 0xFFFFFF), abs=0.05)
    assert "darker text colour" in found.suggestion
    assert findings(measure(tmp_path, slide(color=(0.4, 0.4, 0.4))), "contrast") == []        # 5.7:1

    def grey_title(page):
        footer(page)
        page.draw_rect(pymupdf.Rect(0, 0, W, 32), color=None, fill=(0.98, 0.98, 0.98))
        page.insert_text((12, 22), "The slide title", fontsize=size(5.0), color=(0.45, 0.45, 0.45))     # 4.2:1
        body(page, 4.0)
    assert findings(measure(tmp_path, grey_title), "contrast") == []                        # a heading needs 3:1 only

    def white_on_white(page):
        footer(page)
        page.insert_text((12, 22), "The slide title", fontsize=size(5.0), color=(1, 1, 1))
        body(page, 4.0)
    assert findings(measure(tmp_path, white_on_white), "contrast")[0].measured == pytest.approx(1.0)


def test_the_background_is_the_topmost_filled_rectangle_under_the_text_and_a_picture_hides_it(tmp_path):
    def on_dark(page):
        footer(page)
        title(page)
        page.draw_rect(pymupdf.Rect(0, 40, W, 200), color=None, fill=(0.1, 0.1, 0.4))
        body(page, 4.0, color=(1, 1, 1))
    assert findings(measure(tmp_path, on_dark), "contrast") == []
    def dark_on_dark(page):
        footer(page)
        title(page)
        page.draw_rect(pymupdf.Rect(0, 40, W, 200), color=None, fill=(0.1, 0.1, 0.4))
        body(page, 4.0, color=(0.1, 0.1, 0.1))
    assert findings(measure(tmp_path, dark_on_dark), "contrast")[0].measured < 1.5
    def over_picture(page):
        footer(page)
        picture(page, (0, 40, W, 200))
        body(page, 4.0, color=(0.7, 0.7, 0.7))
    assert findings(measure(tmp_path, over_picture), "contrast") == []                  # no known background


def test_text_cut_off_by_the_page_or_running_into_the_footer_is_an_error(tmp_path):
    def cut(page):
        footer(page)
        title(page)
        body(page, 4.0)
        page.insert_text((400, 150), "Runs off the right edge of the slide", fontsize=size(4.0))
    found, = findings(measure(tmp_path, cut), "clipped")
    assert (found.severity, found.needs, found.threshold) == (ERROR, readability.MAX, 0)
    assert found.measured > 100 and found.unit == "pt beyond the page" and "cut off" in found.suggestion

    def into_footer(page):
        footer(page)
        title(page)
        body(page, 4.0)
        page.insert_text((12, 251), "Text that sits on the footer", fontsize=size(4.0))
    found, = findings(measure(tmp_path, into_footer), "clipped")
    assert found.unit == "pt into the footer" and "runs into the footer" in found.suggestion
    assert findings(measure(tmp_path, slide(pct=4.0)), "clipped") == []


def test_lines_set_on_top_of_each_other_overlap_and_normally_spaced_lines_do_not(tmp_path):
    def overlapping(page):
        footer(page)
        title(page)
        page.insert_text((12, 100), "The first line of the pair", fontsize=size(4.0))
        page.insert_text((12, 104), "The second line of the pair", fontsize=size(4.0))
    found, = findings(measure(tmp_path, overlapping), "overlap")
    assert found.severity == ERROR and found.measured > 25 and found.count == 2 and " / " in found.excerpt
    assert findings(measure(tmp_path, slide(pct=4.0, spacing=1.3)), "overlap") == []
    assert findings(measure(tmp_path, slide(pct=4.0, spacing=1.0)), "overlap") == []


def test_too_many_words_or_lines_of_body_text_is_a_warning(tmp_path):
    words = "word " * 18
    wordy = findings(measure(tmp_path, slide(pct=3.6, count=6, text=words)), "density")           # 108 words in 6 lines
    assert wordy[0].severity == WARNING and wordy[0].unit == "words" and wordy[0].measured == 108
    assert wordy[0].threshold == 90 and "split the slide" in wordy[0].suggestion
    lines = findings(measure(tmp_path, slide(pct=3.6, count=15, top=52, spacing=1.15, text="a few words")), "density")
    assert lines[0].unit == "lines" and lines[0].measured == 15 and lines[0].threshold == 14
    assert findings(measure(tmp_path, slide(pct=3.6, count=8, text="word " * 10)), "density") == []


def test_lines_set_tighter_than_the_font_size_are_a_warning(tmp_path):
    found, = findings(measure(tmp_path, slide(pct=4.0, count=4, spacing=0.85)), "line_spacing")
    assert found.severity == WARNING and found.measured == pytest.approx(0.85, abs=0.02) and found.needs == readability.MIN
    assert findings(measure(tmp_path, slide(pct=4.0, count=4, spacing=1.0)), "line_spacing") == []
    assert findings(measure(tmp_path, slide(pct=4.0, count=4, spacing=1.2)), "line_spacing") == []


# -- pages and slides ----------------------------------------------------------------------------------------------

def test_slide_runs_group_consecutive_pages_with_one_id_and_skip_pages_without(tmp_path):
    assert slide_runs([None, "a", "a", None, "b", "a"]) == [("a", [1, 2]), ("b", [4]), ("a", [5])]
    assert slide_runs([]) == [] and slide_runs([None]) == []


def test_only_the_last_page_of_a_slide_is_judged_except_for_text_cut_off_earlier(tmp_path):
    def step(small, cut=False):
        def make(page):
            footer(page, "abc")
            title(page)
            body(page, 2.0 if small else 4.0)
            if cut:
                page.insert_text((420, 200), "Cut off on an early step", fontsize=size(4.0))
        return make
    other = lambda page: (footer(page, "abd"), title(page), body(page, 4.0))        # noqa: E731
    pdf = pdf_of(tmp_path, step(True), step(True, cut=True), step(False), other)
    pages = [readability.Page.from_dict(data) for data in readability_pdf.read_pages(pdf)]
    runs = slide_runs([page.slide_id for page in pages])
    assert runs == [("abc", [0, 1, 2]), ("abd", [3])]
    report = readability.analyse(pages, runs)
    first, second = report.slides
    assert (first.slide_id, first.page, second.slide_id, second.page) == ("abc", 3, "abd", 4)
    assert [(f.rule, f.page) for f in first.findings] == [("clipped", 2)]            # the small text of steps 1 and 2 is not judged
    assert second.findings == []
    assert report.summary == "2 slides checked · 1 with errors · 0 with warnings"


def test_a_page_without_a_slide_id_is_skipped(tmp_path):
    pdf = pdf_of(tmp_path, lambda page: (title(page), body(page, 2.0)), slide(pct=4.0))
    pages = [readability.Page.from_dict(data) for data in readability_pdf.read_pages(pdf)]
    assert [page.slide_id for page in pages] == [None, "abc"]
    assert [slide_id for slide_id, _pages in slide_runs([page.slide_id for page in pages])] == ["abc"]


# -- the findings ---------------------------------------------------------------------------------------------------

def test_a_report_reads_as_text_for_the_agent_and_as_json_for_the_fix(tmp_path):
    report = measure(tmp_path, slide(lambda page: picture(page, (300, 80, 400, 140)), pct=2.8))
    text = report.to_text()
    assert text.startswith("1 slide checked · 1 with errors · 0 with warnings.")
    assert "abc, page 1:" in text and "error · body text · 2.8 % of slide height, needs ≥ 3.3 · 3 lines" in text
    assert '"An ordinary line of body text"' in text and "enlarge to \\small or larger, or split the slide." in text
    assert "warning · image · " in text and "160×90 px picture" in text
    data = json.loads(json.dumps(report.to_dict()))
    assert data["summary"] == report.summary and data["thresholds"]["body_pct"] == 3.3
    entry, = data["slides"]
    assert (entry["slide"], entry["page"]) == ("abc", 1)
    first = entry["findings"][0]
    assert set(first) >= {"slide_id", "page", "rule", "cls", "severity", "measured", "threshold", "needs", "unit", "bbox",
                          "excerpt", "suggestion", "count", "file", "image", "pixels"}
    assert first["rule"] == "text_size" and first["cls"] == "body" and len(first["bbox"]) == 4
    assert all(0 <= value <= 1 for value in first["bbox"])
    assert measure(tmp_path, slide(pct=4.0)).to_text().endswith("Nothing to report.")


def test_errors_come_before_warnings_and_a_long_report_can_be_cut(tmp_path):
    def mixed(page):
        slide(pct=3.4)(page)
        page.insert_text((400, 150), "Runs off the right edge of the slide", fontsize=size(4.0))
    report = measure(tmp_path, mixed)
    assert [f.severity for f in report.findings] == [ERROR, WARNING]
    many = readability.Report([readability.SlideReport(f"s{n}", n, findings=report.findings) for n in range(5)])
    text = many.to_text(limit=2)
    assert "s1" in text and "s2" not in text and "... and 3 more slides with findings." in text


def test_the_thresholds_are_one_frozen_set_and_a_check_can_use_another(tmp_path):
    with pytest.raises(Exception):
        readability.DEFAULTS.body_pct = 1.0
    pages = [readability.Page.from_dict(data) for data in readability_pdf.read_pages(pdf_of(tmp_path, slide(pct=3.0)))]
    assert readability.analyse(pages, [("abc", [0])]).findings != []
    relaxed = readability.Thresholds(body_pct=2.5)
    assert findings(readability.analyse(pages, [("abc", [0])], relaxed), "text_size") == []


def test_the_raster_child_reads_the_same_data(tmp_path):
    pdf = pdf_of(tmp_path, slide(lambda page: picture(page, (300, 80, 400, 140)), pct=2.8))
    assert json.loads(json.dumps(readability_pdf.read_pages(pdf))) == preview_raster_client.read_layout(pdf)
    with pytest.raises(RuntimeError, match="Cannot read the PDF"):
        preview_raster_client.read_layout(tmp_path / "missing.pdf")


# -- from a PDF to slides and files --------------------------------------------------------------------------

@pytest.fixture
def project(root):
    return ProjectContext.at(root)


def test_a_deck_pdf_becomes_slides_with_their_files_and_the_images_with_the_files_the_slide_includes(project, root):
    media = root / "media"
    media.mkdir(exist_ok=True)
    image = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 160, 90))
    image.set_rect(image.irect, (40, 80, 200))
    image.save(media / "chart.png")
    slide_path = root / "slides" / "abc-EN-Hello-current.tex"
    slide_path.write_text(slide_path.read_text().replace("\\end{standardframe}", "\\includegraphics{media/chart.png}\n\\end{standardframe}"),
                          encoding="utf-8", newline="")

    def abc(page):
        footer(page, "abc")
        title(page)
        body(page, 2.8)
        picture(page, (300, 80, 400, 140))
    pdf = pdf_of(root, abc, lambda page: (footer(page, "abd"), title(page), body(page, 4.0)),
                 lambda page: (footer(page, "zzz"), title(page), body(page, 2.8)))
    report = readability_check.check_pdf(project, pdf)
    assert [(s.slide_id, s.file) for s in report.slides] == [
        ("abc", "abc-EN-Hello-current.tex"), ("abd", "abd-EN-Second-current.tex"), ("zzz", "")]
    image_finding, = findings(report, "image_size")
    assert image_finding.image == "chart.png" and image_finding.file == "abc-EN-Hello-current.tex"
    assert "chart.png" in report.to_text()
    assert {f.file for f in report.slides[0].findings} == {"abc-EN-Hello-current.tex"}
    other = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 160, 90))             # a second file of the same pixel size
    other.save(media / "chart2.png")
    slide_path.write_text(slide_path.read_text().replace("media/chart.png}", "media/chart.png}\\includegraphics{media/chart2.png}"),
                          encoding="utf-8", newline="")
    assert findings(readability_check.check_pdf(project, pdf), "image_size")[0].image == "chart.png or chart2.png"
    single = readability_check.check_pdf(project, pdf, slide="abc")                 # a render of one slide: every page is its
    assert [s.slide_id for s in single.slides] == ["abc"] and single.slides[0].page == 3


# -- findings set by the template, and the findings known per slide ---------------------------------------------------

def small_print(pct=1.25):
    def make(page):
        footer(page)
        title(page)
        body(page, 2.8)
        page.insert_text((12, 238), "Source: Own illustration, 2024", fontsize=size(pct), color=(0.1, 0.1, 0.1))
    return make


def test_small_print_on_a_slide_that_sets_no_size_is_set_by_the_template(project, tmp_path):
    pdf = pdf_of(tmp_path, small_print())
    text = "\\begin{standardframe}{Hello}\n\\item A point\n\\source{Own illustration}\n\\end{standardframe}\n"
    entry, = readability_check.check_pdf(project, pdf, slide="abc", text=text).slides
    by_class = {(f.cls, f.rule): f for f in entry.findings}
    assert by_class[(CITATION, "text_size")].template_level and not by_class[(BODY, "text_size")].template_level
    assert entry.fixable == [by_class[(BODY, "text_size")]] and len(entry.findings) == 2
    assert entry.height_pt == H and entry.to_dict(fixable_only=True)["height_pt"] == H
    assert [f["cls"] for f in entry.to_dict(fixable_only=True)["findings"]] == ["body"]
    assert "Set by the template" in readability.Report([entry]).to_text()
    # the slide chooses the size of its own small print: that is its to fix
    for sized in ("\\source{\\tiny Own illustration}", "{\\fontsize{3}{4}\\selectfont x}", "\\begin{footnotesize}x\\end{footnotesize}"):
        entry, = readability_check.check_pdf(project, pdf, slide="abc", text=text.replace("\\source{Own illustration}", sized)).slides
        assert not any(f.template_level for f in entry.findings)
    commented = text.replace("\\source{Own illustration}", "% \\tiny\n\\source{Own illustration}")
    assert readability_check.check_pdf(project, pdf, slide="abc", text=commented).slides[0].fixable[0].cls == BODY


def test_only_the_citation_size_is_template_level(project, tmp_path):
    entry, = readability_check.check_pdf(project, pdf_of(tmp_path, slide(pct=2.8)), slide="abc", text="\\item x").slides
    assert entry.findings and not any(f.template_level for f in entry.findings) and entry.fixable == entry.findings


def test_the_known_findings_are_valid_for_the_text_that_was_measured(project, tmp_path):
    report = readability_check.check_pdf(project, pdf_of(tmp_path, slide(pct=2.8)), slide="abc", text="one")
    known = readability_check.KnownFindings()
    path = project.slides_dir / "abc-EN-Hello-current.tex"
    assert known.get(path, "one") is None and known.fixable(path, "one") == [] and not known.has_errors(path, "one")
    known.remember_slide(path, "one", report)
    assert known.has_errors(path, "one") and known.fixable(path, "one") == report.slides[0].fixable
    assert known.get(path, "one").to_dict(fixable_only=True)["slides"][0]["findings"]
    assert known.get(path, "two") is None and not known.has_errors(path, "two")      # an edit forgets them
    warning_only = readability_check.check_pdf(project, pdf_of(tmp_path, slide(pct=3.4), name="w.pdf"), slide="abc", text="one")
    known.remember_slide(path, "one", warning_only)
    assert known.fixable(path, "one") and not known.has_errors(path, "one")
    known.remember_slide(path, "one", readability.Report([]))                         # a render without pages
    assert known.fixable(path, "one") == []
    deck = readability_check.check_pdf(project, pdf_of(tmp_path, slide(pct=2.8), name="deck2.pdf"))
    known.remember_deck(project, deck)
    assert known.has_errors(path, path.read_text(encoding="utf-8").replace("\r\n", "\n"))


# -- the deck's PDF -------------------------------------------------------------------------------------------------

def record_for(project, deck, pdf: Path, inputs: list[Path], view="instructor", language="EN") -> dict:
    job = readability_check.deck_job(deck, view, language)
    record = {"format": compile_records.RECORD_FORMAT, "jobname": job.jobname, "pdf": str(pdf),
              "pdf_sha256": compile_records.sha256(pdf),
              "inputs": [{"path": str(path), "sha256": compile_records.sha256(path)} for path in inputs]}
    path = compile_records.record_path(project.build_dir, job.jobname)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")
    return record


def test_the_deck_pdf_is_used_only_while_nothing_it_was_made_from_changed(project, root):
    deck = next(d for d in scan_decks(project) if d.name == "test")
    pdf = pdf_of(root, slide(pct=4.0), name="test.pdf")
    inputs = [deck.path, root / "slides" / "abc-EN-Hello-current.tex"]
    with pytest.raises(readability_check.StalePdf, match="test has not been compiled yet"):
        readability_check.deck_pdf(project, deck, "instructor", "EN")
    record_for(project, deck, pdf, inputs)
    assert readability_check.deck_pdf(project, deck, "instructor", "EN") == pdf
    assert readability_check.check_deck(project, deck, "instructor", "EN").slides[0].slide_id == "abc"

    slide_file = root / "slides" / "abc-EN-Hello-current.tex"
    original = slide_file.read_bytes()
    slide_file.write_bytes(original + b"% changed\r\n")
    with pytest.raises(readability_check.StalePdf, match="abc-EN-Hello-current.tex changed since it was compiled"):
        readability_check.deck_pdf(project, deck, "instructor", "EN")
    slide_file.write_bytes(original)
    assert readability_check.deck_pdf(project, deck, "instructor", "EN") == pdf          # back to what was compiled

    pdf.write_bytes(pdf.read_bytes() + b"\n%")
    with pytest.raises(readability_check.StalePdf, match="test.pdf was replaced"):
        readability_check.deck_pdf(project, deck, "instructor", "EN")
    pdf.unlink()
    with pytest.raises(readability_check.StalePdf, match="test.pdf is gone"):
        readability_check.deck_pdf(project, deck, "instructor", "EN")


def test_the_check_ignores_a_changed_wrapper_but_the_snapshots_do_not(project, root):
    deck = next(d for d in scan_decks(project) if d.name == "test")
    pdf = pdf_of(root, slide(pct=4.0), name="test.pdf")
    record = record_for(project, deck, pdf, [deck.path])
    record["wrapper_sha256"] = "other"
    assert not compile_records.check_record(record, None)
    assert compile_records.check_record(record, "\\input{test.tex}\n").reasons[0] == "the deck's version settings changed"


# -- a real beamer page (opt-in, as the other real compiles: SLIDEMAGE_TEX_TESTS=1) -------------------------------------

@pytest.mark.skipif(not os.environ.get("SLIDEMAGE_TEX_TESTS") or not shutil.which("latexmk"),
                    reason="real LaTeX compile; set SLIDEMAGE_TEX_TESTS=1")
def test_a_real_beamer_deck_is_read_slide_by_slide(tmp_path, monkeypatch):
    repo = Path(__file__).resolve().parents[1]
    shutil.copytree(repo / "latex", tmp_path / "latex")
    shutil.copytree(repo / "example", tmp_path / "example",
                    ignore=shutil.ignore_patterns("pdf", ".build", ".previews", "snapshots"))
    root = tmp_path / "example"
    monkeypatch.setenv("SLIDEMASTER_LATEX", str(tmp_path / "latex"))
    monkeypatch.setenv("SLIDEMASTER_PROJECT", str(root))
    ctx = ProjectContext.at(root)
    (root / "decks" / "read-test.tex").write_text(
        "\\documentclass[aspectratio=169]{beamer}\n\\usetheme{gotham}\n\\makeatletter\\def\\input@path{{../}}\\makeatother\n"
        "\\input{Slidemaster_preamble_slidemage}\n\\newcommand{\\FooterText}{Readability test}\n"
        "\\begin{document}\n\\slide{1jv-EN-Anatomy-of-a-Project}\n\\slide{1c9-EN-Placing-Figures}\n\\end{document}\n",
        encoding="utf-8")
    deck = next(d for d in scan_decks(ctx) if d.name == "read-test")
    job = compiler.CompileJob(deck, None, None)
    job.footer_timestamp = False
    done = threading.Event()
    assert compiler.run_job(ctx, job, lambda _line: None, on_relocated=lambda ok, path: done.set())
    assert done.wait(60)
    report = readability_check.check_deck(ctx, deck, "instructor", "EN")
    assert [slide.slide_id for slide in report.slides] == ["1jv", "1c9"]
    assert {slide.file for slide in report.slides} == {"1jv-EN-Anatomy-of-a-Project-current.tex",
                                                       "1c9-EN-Placing-Figures-current.tex"}
    assert not any("slide id" in f.excerpt for f in report.findings)                 # the footer is not content
    json.dumps(report.to_dict())
