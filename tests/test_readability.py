# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Readability rules on synthetic PDFs and an opt-in Beamer compile."""
from __future__ import annotations

import json
import os
import shutil
import threading
from pathlib import Path

import pymupdf
import pytest

from slidemage import compile_records, compiler, preview_raster_client, readability, readability_check, readability_pdf
from slidemage.deck_scan import scan_decks
from slidemage.project import ProjectContext
from slidemage.readability import BODY, CITATION, ERROR, FIGURE_TEXT, HEADING, WARNING
from slidemage.slide_snapshot import slide_runs

W, H = 454.0, 255.0  # 160 × 90 mm
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


def pdf_of(tmp_path, *draws, name="deck.pdf", width=W, height=H) -> Path:
    path = tmp_path / name
    with pymupdf.open() as doc:
        for draw in draws:
            draw(doc.new_page(width=width, height=height))
        doc.save(path)
    return path


def read_pages(path):
    return [readability.Page.from_dict(data) for data in readability_pdf.read_pages(path)]


def measure(tmp_path, *draws) -> readability.Report:
    pages = read_pages(pdf_of(tmp_path, *draws))
    return readability.analyse(pages, [("abc", list(range(len(pages))))])


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


def test_body_text_below_the_floor_is_an_error_near_it_a_warning_and_from_the_floor_up_fine(tmp_path):
    error, = findings(measure(tmp_path, slide(pct=2.8)), "text_size", BODY)
    assert (error.severity, error.threshold, error.needs, error.count) == (ERROR, 3.3, readability.MIN, 3)
    assert error.measured == pytest.approx(2.8, abs=0.05) and error.excerpt == "An ordinary line of body text"
    assert r"enlarge to \small or larger" in error.suggestion
    near, = findings(measure(tmp_path, slide(pct=3.4)), "text_size", BODY)
    assert near.severity == WARNING and "close to the floor" in near.suggestion
    assert measure(tmp_path, slide(pct=3.5)).findings == []

    half_size = pdf_of(tmp_path, lambda p: body(p, pct=4.0, top=30), width=W / 2, height=H / 2)
    page, = read_pages(half_size)
    assert page.pct(size(4.0)) == pytest.approx(8.0)
    assert readability.analyse([page], [("abc", [0])]).findings == []


def test_headings_have_the_body_floor_and_should_not_be_smaller_than_the_body(tmp_path):
    def heading(pct):
        return lambda page: (footer(page), title(page, pct), body(page))
    below, = findings(measure(tmp_path, heading(3.1)), "text_size", HEADING)
    assert below.severity == ERROR and below.excerpt == "The slide title"
    smaller, = findings(measure(tmp_path, heading(3.7)), "text_size", HEADING)
    assert smaller.severity == WARNING and smaller.threshold == pytest.approx(4.0, abs=0.05)
    assert "smaller than the slide's body text" in smaller.suggestion
    assert measure(tmp_path, heading(5.0)).findings == []


def test_only_a_large_title_in_the_upper_part_of_a_slide_is_a_heading(tmp_path):
    def section(pct):
        def draw(page):
            # This contrast passes for headings and fails for body text.
            page.insert_text((12, 70), "The big picture", fontsize=size(pct), color=(0.5, 0.5, 0.5))
            body(page, top=110)
        return draw

    assert measure(tmp_path, section(8.0)).findings == []
    assert {f.cls for f in measure(tmp_path, section(3.0)).findings} == {BODY}


def test_citations_have_a_looser_floor_and_are_identified_by_words_position_or_marker(tmp_path):
    def citation(pct, text, y=238):
        return slide(lambda page: page.insert_text((12, y), text, fontsize=size(pct)))

    source = "Source: Own illustration, 2024"
    error, = findings(measure(tmp_path, citation(2.0, source, y=150)), "text_size")
    assert (error.cls, error.severity, error.threshold) == (CITATION, ERROR, 2.2)
    assert "move it to the notes" in error.suggestion
    near, = findings(measure(tmp_path, citation(2.3, source)), "text_size")
    assert (near.cls, near.severity) == (CITATION, WARNING)
    assert measure(tmp_path, citation(2.6, source)).findings == []
    for text, y, expected_class in (
        ("£ A note on the claim above", 238, CITATION),
        ("Some small print", 238, CITATION),
        ("Some small print", 150, BODY),
    ):
        found, = findings(measure(tmp_path, citation(2.0, text, y)), "text_size")
        assert found.cls == expected_class


def test_sideways_small_print_is_a_citation(tmp_path):
    draw = slide(lambda page: page.insert_text((440, 230), "Own illustration.", fontsize=size(1.25), rotate=90))
    found, = findings(measure(tmp_path, draw), "text_size")
    assert found.cls == CITATION and found.severity == ERROR and found.measured == pytest.approx(1.25, abs=0.05)


def test_text_inside_a_figure_has_its_own_floor(tmp_path):
    def labelled(pct, y=150):
        def draw(page):
            figure(page, (230, 90, 440, 200))
            page.insert_text((250, y), "Axis label", fontsize=size(pct))
        return slide(draw)

    error, = findings(measure(tmp_path, labelled(2.3)), "text_size", FIGURE_TEXT)
    assert (error.severity, error.threshold) == (ERROR, 2.6) and "larger labels" in error.suggestion
    assert findings(measure(tmp_path, labelled(2.65)), "text_size", FIGURE_TEXT)[0].severity == WARNING
    assert findings(measure(tmp_path, labelled(3.0)), "text_size") == []
    assert findings(measure(tmp_path, labelled(3.2, y=240)), "text_size")[0].cls == BODY


def test_footers_invisible_text_and_small_glyphs_do_not_count_as_body_text(tmp_path):
    def extra_content(page):
        page.insert_text((12, 20), "(slide id: abc)", fontsize=size(1.0), render_mode=3)
        page.insert_text((300, 150), "Alt text", fontsize=size(0.9), render_mode=3)
        page.insert_text((12, 244), "(slide id: abc | instructor deck)", fontsize=size(1.0))
        page.insert_text((12, 150), "The claim with a note", fontsize=size(4.0))
        page.insert_text((150, 144), "£", fontsize=size(1.5))
        page.insert_text((300, 150), "•", fontsize=size(1.5))

    data = readability_pdf.read_pages(pdf_of(tmp_path, slide(extra_content)))
    pages = [readability.Page.from_dict(page) for page in data]
    assert readability.analyse(pages, [("abc", [0])]).findings == []
    texts = [line["text"] for line in data[0]["lines"]]
    assert not any("Alt text" in text for text in texts)
    assert any("instructor deck" in text for text in texts)


def test_the_largest_image_shown_small_is_a_warning_and_the_report_names_its_pixels(tmp_path):
    small, = findings(measure(tmp_path, slide(lambda page: picture(page, (300, 80, 400, 140)))), "image_size")
    assert (small.severity, small.cls, small.threshold, small.needs) == (WARNING, readability.IMAGE, 25, readability.MIN)
    assert small.measured == pytest.approx(100 * 60 / (W * H) * 100, abs=0.1) and small.pixels == (160, 90)
    assert "may be too small to read" in small.suggestion
    assert small.bbox == pytest.approx((300 / W, 80 / H, 400 / W, 140 / H), abs=0.002)
    assert findings(measure(tmp_path, slide(lambda page: picture(page, (200, 40, 440, 240)))), "image_size") == []
    tall = slide(lambda page: picture(page, (380, 36, 440, 246)))
    narrow, = findings(measure(tmp_path, tall), "image_size")
    assert narrow.measured == pytest.approx(60 * 210 / (W * H) * 100, abs=0.1)
    assert narrow.unit == "% of the slide area"
    for rect in ((400, 5, 440, 25), (0, 0, W, H)):
        assert findings(measure(tmp_path, slide(lambda page: picture(page, rect))), "image_size") == []


def test_contrast_uses_the_topmost_background_and_headings_need_less(tmp_path):
    grey = (0.62, 0.62, 0.62)
    found, = findings(measure(tmp_path, slide(color=grey)), "contrast")
    assert (found.severity, found.threshold, found.needs) == (ERROR, 4.5, readability.MIN)
    assert found.measured == pytest.approx(readability.contrast_ratio(0x9E9E9E, 0xFFFFFF), abs=0.05)
    assert "darker text color" in found.suggestion

    def heading(page, color):
        footer(page)
        page.insert_text((12, 22), "The slide title", fontsize=size(5.0), color=color)
        body(page)

    assert findings(measure(tmp_path, lambda page: heading(page, (0.45, 0.45, 0.45))), "contrast") == []
    white = (1, 1, 1)
    white_on_white, = findings(measure(tmp_path, lambda page: heading(page, white)), "contrast")
    assert white_on_white.measured == pytest.approx(1.0)

    def layered(page, text_color, image=False):
        page.draw_rect(pymupdf.Rect(0, 40, W, 220), color=None, fill=white)
        page.draw_rect(pymupdf.Rect(0, 40, W, 200), color=None, fill=(0.1, 0.1, 0.4))
        if image:
            picture(page, (0, 40, W, 200))
        body(page, color=text_color)

    assert findings(measure(tmp_path, lambda page: layered(page, white)), "contrast") == []
    dark = (0.1, 0.1, 0.1)
    assert findings(measure(tmp_path, lambda page: layered(page, dark)), "contrast")[0].measured < 1.5
    assert findings(measure(tmp_path, lambda page: layered(page, dark, image=True)), "contrast") == []


def test_text_cut_off_by_the_page_or_running_into_the_footer_is_an_error(tmp_path):
    cut = slide(lambda page: page.insert_text((400, 150), "Runs off the right edge of the slide", fontsize=size(4.0)))
    found, = findings(measure(tmp_path, cut), "clipped")
    assert (found.severity, found.needs, found.threshold) == (ERROR, readability.MAX, 0)
    assert found.measured > 100 and found.unit == "pt beyond the page"

    into_footer = slide(lambda page: page.insert_text((12, 251), "Text that sits on the footer", fontsize=size(4.0)))
    found, = findings(measure(tmp_path, into_footer), "clipped")
    assert found.unit == "pt into the footer" and "runs into the footer" in found.suggestion
    assert findings(measure(tmp_path, slide()), "clipped") == []


def test_overlapping_lines_are_an_error_and_tight_line_spacing_is_a_warning(tmp_path):
    found, = findings(measure(tmp_path, slide(count=2, spacing=0.4)), "overlap")
    assert found.severity == ERROR and found.measured > 25 and found.count == 2 and " / " in found.excerpt
    found, = findings(measure(tmp_path, slide(count=4, spacing=0.85)), "line_spacing")
    assert found.severity == WARNING and found.measured == pytest.approx(0.85, abs=0.02)
    assert found.needs == readability.MIN
    report = measure(tmp_path, slide(count=4, spacing=1.0))
    assert not findings(report, "overlap") and not findings(report, "line_spacing")


def test_too_many_words_or_lines_of_body_text_is_a_warning(tmp_path):
    words = "word " * 18
    wordy = findings(measure(tmp_path, slide(pct=3.6, count=6, text=words)), "density")           # 108 words in 6 lines
    assert wordy[0].severity == WARNING and wordy[0].unit == "words" and wordy[0].measured == 108
    assert wordy[0].threshold == 90 and "split the slide" in wordy[0].suggestion
    lines = findings(measure(tmp_path, slide(pct=3.6, count=15, top=52, spacing=1.15, text="a few words")), "density")
    assert lines[0].unit == "lines" and lines[0].measured == 15 and lines[0].threshold == 14
    assert findings(measure(tmp_path, slide(pct=3.6, count=8, text="word " * 10)), "density") == []


def test_slide_runs_group_consecutive_pages_with_one_id_and_skip_pages_without():
    assert slide_runs([None, "a", "a", None, "b", "a"]) == [("a", [1, 2]), ("b", [4]), ("a", [5])]
    assert slide_runs([]) == [] and slide_runs([None]) == []


def test_only_the_last_page_of_a_slide_is_judged_except_for_text_cut_off_earlier(tmp_path):
    def cut(page):
        page.insert_text((420, 200), "Cut off on an early step", fontsize=size(4.0))

    pages = read_pages(pdf_of(tmp_path,
        lambda page: body(page, 2.0), slide(pct=2.0), slide(cut, pct=2.0), slide(),
        lambda page: (footer(page, "abd"), title(page), body(page))))
    assert [page.slide_id for page in pages] == [None, "abc", "abc", "abc", "abd"]
    runs = slide_runs([page.slide_id for page in pages])
    assert runs == [("abc", [1, 2, 3]), ("abd", [4])]
    first, second = readability.analyse(pages, runs).slides
    assert (first.slide_id, first.page, second.slide_id, second.page) == ("abc", 4, "abd", 5)
    assert [(f.rule, f.page) for f in first.findings] == [("clipped", 3)]
    assert second.findings == []


def test_errors_come_before_warnings_and_a_long_report_can_be_cut(tmp_path):
    def mixed(page):
        slide(pct=3.4)(page)
        page.insert_text((400, 150), "Runs off the right edge of the slide", fontsize=size(4.0))
    report = measure(tmp_path, mixed)
    assert [f.severity for f in report.findings] == [ERROR, WARNING]
    many = readability.Report([readability.SlideReport(f"s{n}", n, findings=report.findings) for n in range(5)])
    text = many.to_text(limit=2)
    assert "s1" in text and "s2" not in text and "... and 3 more slides with findings." in text
    assert '"Runs off the right edge of the slide"' in report.to_text()
    entry, = json.loads(json.dumps(report.to_dict()))["slides"]
    assert (entry["slide"], entry["page"]) == ("abc", 1)
    assert [f["rule"] for f in entry["findings"]] == ["clipped", "text_size"]
    assert all(0 <= value <= 1 for value in entry["findings"][-1]["bbox"])


def test_the_thresholds_are_one_frozen_set_and_a_check_can_use_another(tmp_path):
    with pytest.raises(Exception):
        readability.DEFAULTS.body_pct = 1.0
    pages = read_pages(pdf_of(tmp_path, slide(pct=3.0)))
    assert readability.analyse(pages, [("abc", [0])]).findings != []
    relaxed = readability.Thresholds(body_pct=2.5)
    assert findings(readability.analyse(pages, [("abc", [0])], relaxed), "text_size") == []


def test_the_raster_child_reads_the_same_data(tmp_path):
    pdf = pdf_of(tmp_path, slide(lambda page: picture(page, (300, 80, 400, 140)), pct=2.8))
    assert json.loads(json.dumps(readability_pdf.read_pages(pdf))) == preview_raster_client.read_layout(pdf)
    with pytest.raises(RuntimeError, match="Cannot read the PDF"):
        preview_raster_client.read_layout(tmp_path / "missing.pdf")


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


def test_small_print_on_a_slide_that_sets_no_size_is_set_by_the_template(project, tmp_path):
    def source(page):
        page.insert_text((12, 238), "Source: Own illustration, 2024", fontsize=size(1.25))

    pdf = pdf_of(tmp_path, slide(source, pct=2.8))
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


@pytest.mark.skipif(not os.environ.get("SLIDEMAGE_TEX_TESTS") or not shutil.which("latexmk"),
                    reason="real LaTeX compile; set SLIDEMAGE_TEX_TESTS=1")
def test_a_real_beamer_deck_is_read_slide_by_slide(tmp_path, monkeypatch):
    repo = Path(__file__).resolve().parents[1]
    shutil.copytree(repo / "latex", tmp_path / "latex")
    shutil.copytree(repo / "example", tmp_path / "example",
                    ignore=shutil.ignore_patterns("pdf", ".build", ".previews", "snapshots"))
    root = tmp_path / "example"
    monkeypatch.setenv("SLIDEMAGE_LATEX", str(tmp_path / "latex"))
    monkeypatch.setenv("SLIDEMAGE_PROJECT", str(root))
    ctx = ProjectContext.at(root)
    (root / "decks" / "read-test.tex").write_text(
        "\\documentclass[aspectratio=169]{beamer}\n\\makeatletter\\def\\input@path{{../}}\\makeatother\n"
        "\\input{SlideMage_template_slidemage}\n\\newcommand{\\FooterText}{Readability test}\n"
        "\\begin{document}\n\\slide{1jv-EN-Anatomy-of-a-Project}\n\\slide{1c9-EN-Placing-Figures}\n\\end{document}\n",
        encoding="utf-8")
    deck = next(d for d in scan_decks(ctx) if d.name == "read-test")
    job = compiler.CompileJob(deck, None, None)
    done = threading.Event()
    assert compiler.run_job(ctx, job, lambda _line: None, on_relocated=lambda ok, path: done.set())
    assert done.wait(60)
    report = readability_check.check_deck(ctx, deck, "instructor", "EN")
    assert [slide.slide_id for slide in report.slides] == ["1jv", "1c9"]
    assert {slide.file for slide in report.slides} == {"1jv-EN-Anatomy-of-a-Project-current.tex",
                                                       "1c9-EN-Placing-Figures-current.tex"}
    assert not any("slide id" in f.excerpt for f in report.findings)                 # the footer is not content
    json.dumps(report.to_dict())
