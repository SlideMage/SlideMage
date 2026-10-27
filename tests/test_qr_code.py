# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""qr_code.py: what each kind of code holds, the files, the recommended size, what the
project keeps, and how \\SMQRCode is seen by the image scan, the pre-render check and the
transcript."""
from datetime import datetime, timezone

import pymupdf as fitz
import pytest

from slidemage import alt_blocks, alt_images, latex_lint, qr_code, transcript
from slidemage.project import ProjectContext
from slidemage.qr_code import QRSpec


def test_url_gets_https_and_rejects_spaces():
    assert qr_code.payload(QRSpec("url", {"url": "uni-graz.at/x"})) == "https://uni-graz.at/x"
    assert qr_code.payload(QRSpec("url", {"url": "mailto:a@b.at"})) == "mailto:a@b.at"
    for bad in ("", "a b.at", "https://"):
        with pytest.raises(ValueError):
            qr_code.payload(QRSpec("url", {"url": bad}))


def test_email_is_a_mailto_link():
    spec = QRSpec("email", {"to": "a@b.at", "subject": "Hi there", "body": "x&y"})
    assert qr_code.payload(spec) == "mailto:a@b.at?subject=Hi%20there&body=x%26y"
    with pytest.raises(ValueError, match="not an email address"):
        qr_code.payload(QRSpec("email", {"to": "nobody"}))


def test_contact_is_a_vcard_with_family_and_given_name():
    for name in ("Stefan Palan", "Palan, Stefan"):
        data = qr_code.payload(QRSpec("contact", {"name": name, "organization": "Uni Graz",
                                                  "website": "uni-graz.at"}))
        assert data.startswith("BEGIN:VCARD\r\nVERSION:3.0\r\n")
        assert "N:Palan;Stefan" in data and "FN:Stefan Palan" in data
        assert "ORG:Uni Graz" in data and "URL:https://uni-graz.at" in data
    assert qr_code.alt_text(QRSpec("contact", {"name": "Palan, Stefan"})) == "QR code: add contact Stefan Palan"


def test_event_times_are_utc_and_text_is_escaped():
    data = qr_code.payload(QRSpec("event", {"title": "Exam, part 1", "start": "2026-12-14 10:00",
                                            "location": "HS 15.01; ground floor"}))
    start = datetime(2026, 12, 14, 10, 0).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    assert data.startswith("BEGIN:VEVENT\r\nSUMMARY:Exam\\, part 1\r\n")
    assert f"DTSTART:{start}" in data and "DTEND:" in data          # one hour by default
    assert "LOCATION:HS 15.01\\; ground floor" in data and data.endswith("END:VEVENT")
    with pytest.raises(ValueError, match="ends before"):
        qr_code.payload(QRSpec("event", {"title": "x", "start": "2026-12-14 10:00", "end": "2026-12-14 09:00"}))
    with pytest.raises(ValueError, match="not a date"):
        qr_code.payload(QRSpec("event", {"title": "x", "start": "14.12.2026"}))


def test_all_day_event_ends_the_day_after_its_last_day():
    data = qr_code.payload(QRSpec("event", {"title": "Course", "start": "2026-12-14", "end": "2026-12-15",
                                            "all_day": "true"}))
    assert "DTSTART;VALUE=DATE:20261214" in data and "DTEND;VALUE=DATE:20261216" in data


@pytest.mark.parametrize("place", ["47.0777, 15.4495", "https://www.google.com/maps/place/x/@47.0777,15.4495,17z",
                                   "https://www.openstreetmap.org/?mlat=47.0777&mlon=15.4495#map=17/47.0777/15.4495",
                                   "https://maps.apple.com/?ll=47.0777,15.4495"])
def test_location_reads_coordinates_from_text_and_map_links(place):
    assert qr_code.parse_coordinates(place) == (47.0777, 15.4495)
    assert qr_code.payload(QRSpec("location", {"place": place})) == \
        "https://www.google.com/maps/search/?api=1&query=47.0777,15.4495"
    assert qr_code.payload(QRSpec("location", {"place": place, "map_link": "geo"})) == "geo:47.0777,15.4495"


def test_location_from_an_address_needs_no_lookup():
    spec = QRSpec("location", {"place": "Universitätsplatz 3, Graz", "label": "Main building"})
    assert qr_code.parse_coordinates(spec.value("place")) is None
    assert qr_code.payload(spec).startswith("https://www.google.com/maps/search/?api=1&query=Universit%C3%A4tsplatz")
    spec.fields["map_link"] = "osm"
    assert qr_code.payload(spec).startswith("https://www.openstreetmap.org/search?query=")
    assert qr_code.default_caption(spec) == "Main building"


def test_recommended_height_grows_with_the_room_and_the_grid():
    url = qr_code.make(QRSpec("url", {"url": "https://uni-graz.at"}))
    (seminar, low), (hall, high) = qr_code.size_advice(url)
    assert (seminar, hall) == ("Seminar room", "Lecture hall") and low < high and high == pytest.approx(2 * low)
    assert qr_code.recommended_height(10, 1) == qr_code.MIN_HEIGHT
    note = qr_code.size_note(url)
    assert "Seminar room ≥" in note and "Lecture hall ≥" in note
    long_card = qr_code.make(QRSpec("contact", {"name": "A B", "street": "x" * 300}, "L"))
    assert "too dense" in qr_code.size_note(long_card)


def test_caption_latex():
    spec = QRSpec("url", {"url": "https://x.org/a_b?q=1%20#top"})
    assert qr_code.caption_latex(spec, "content") == "\\url{https://x.org/a_b?q=1\\%20\\#top}"
    assert qr_code.caption_latex(spec, "none") == ""
    assert qr_code.caption_latex(spec, "custom", "QR 1 & 50%") == "QR 1 \\& 50\\%"
    assert qr_code.snippet("media/qr-1.pdf", 0.6, "QR 1") == "\\SMQRCode[0.60\\textheight]{media/qr-1.pdf}{QR 1}"


@pytest.mark.parametrize("fmt", qr_code.FORMATS)
def test_every_format_is_written(tmp_path, fmt):
    code = qr_code.make(QRSpec("url", {"url": "https://uni-graz.at"}))
    path = qr_code.save(code, tmp_path / f"code.{fmt}")
    head = path.read_bytes()[:16]
    assert {"pdf": b"%PDF", "png": b"\x89PNG", "svg": b"<svg", "eps": b"%!PS"}[fmt] in head


def test_the_pdf_draws_exactly_the_codes_modules(tmp_path):
    code = qr_code.make(QRSpec("url", {"url": "https://uni-graz.at/en/course"}))
    path = qr_code.save(code, tmp_path / "code.pdf", border=4)
    total = qr_code.modules(code, 4)
    pixmap = fitz.open(path)[0].get_pixmap(matrix=fitz.Matrix(10, 10), colorspace=fitz.csGRAY)
    step = pixmap.width / total
    drawn = [[pixmap.pixel(int((4 + x + 0.5) * step), int((4 + y + 0.5) * step))[0] < 128
              for x in range(total - 8)] for y in range(total - 8)]
    assert drawn == [[bool(cell) for cell in row] for row in code.matrix]


def test_the_pdf_is_solid_on_a_page_with_thin_lines(tmp_path):
    """segno's own PDF stroked its rows without a line width, so on a slide -- whose thin lines it inherited
    through \\includegraphics -- every row was a hairline: 20 % of a dark module inked (2026-10-26, a deck
    preview). Ours is filled: placed on a page that sets 0.1 pt lines, every dark module is fully dark."""
    code = qr_code.make(QRSpec("url", {"url": "https://www.youtube.com/watch?v=cfSIC8jwbQs"}))
    path = qr_code.save(code, tmp_path / "code.pdf")
    total = qr_code.modules(code)
    assert b" S" not in fitz.open(path)[0].read_contents()                # no strokes at all
    slide = fitz.open()
    page = slide.new_page(width=200, height=200)
    page.show_pdf_page(page.rect, fitz.open(path), 0)
    xref = page.get_contents()[0]
    slide.update_stream(xref, b"0.1 w\n" + slide.xref_stream(xref))      # a thin line width around the code
    pixmap = page.get_pixmap(matrix=fitz.Matrix(6, 6), colorspace=fitz.csGRAY)
    step = pixmap.width / total
    for y, row in enumerate(code.matrix):
        for x, cell in enumerate(row):
            samples = [pixmap.pixel(int((4 + x + 0.1 + 0.2 * i) * step), int((4 + y + 0.1 + 0.2 * j) * step))[0] < 128
                       for i in range(5) for j in range(5)]
            assert all(samples) if cell else not any(samples), (x, y)


def test_svg_and_eps_fill_one_rectangle_per_run(tmp_path):
    code = qr_code.make(QRSpec("url", {"url": "https://uni-graz.at"}))
    runs = qr_code._runs(code, 4)
    svg = qr_code.save(code, tmp_path / "code.svg").read_text(encoding="utf-8")
    eps = qr_code.save(code, tmp_path / "code.eps").read_text(encoding="ascii")
    assert svg.count("z") == len(runs) and "stroke" not in svg
    assert eps.count("rectfill") == len(runs) + 1 and " stroke" not in eps     # + the white square
    assert sum(length for _x, _y, length in runs) == sum(map(sum, code.matrix))


def test_png_is_at_least_png_width_wide(tmp_path):
    code = qr_code.make(QRSpec("url", {"url": "https://uni-graz.at"}))
    pixmap = fitz.Pixmap(str(qr_code.save(code, tmp_path / "code.png")))
    assert pixmap.width >= qr_code.PNG_WIDTH


def test_create_writes_media_file_spec_and_alt_text(tmp_path):
    ctx = ProjectContext.at(tmp_path)
    spec = QRSpec("url", {"url": "https://uni-graz.at/course"})
    first = qr_code.create(ctx, spec, caption_mode="custom", caption="QR 1")
    assert first.image == "media/qr-1.pdf" and first.path.is_file()
    assert first.snippet == f"\\SMQRCode[0.60\\textheight]{{{first.image}}}{{QR 1}}"
    second = qr_code.create(ctx, spec, caption_mode="custom", caption="QR 1")
    assert second.image == "media/qr-1-2.pdf" and first.path.is_file()      # never overwrites
    stored, options = qr_code.load_spec(ctx, first.image)
    assert stored.kind == "url" and stored.fields == spec.fields and options == {"caption_mode": "custom", "caption": "QR 1"}
    entry = alt_images.load_store(ctx)[first.image]
    assert entry.short == "QR code linking to https://uni-graz.at/course" and entry.status == alt_images.STATUS_REVIEWED


def test_create_replaces_in_place_and_refuses_svg(tmp_path):
    ctx = ProjectContext.at(tmp_path)
    made = qr_code.create(ctx, QRSpec("url", {"url": "https://a.org"}))
    again = qr_code.create(ctx, QRSpec("url", {"url": "https://b.org"}), replace=made.image)
    assert again.image == made.image and qr_code.load_spec(ctx, made.image)[0].fields["url"] == "https://b.org"
    with pytest.raises(ValueError, match="LuaLaTeX"):
        qr_code.create(ctx, QRSpec("url", {"url": "https://a.org"}), fmt="svg")
    with pytest.raises(ValueError, match="caption"):
        qr_code.create(ctx, QRSpec("url", {"url": "https://a.org"}), caption_mode="custom")


def test_smqrcode_is_an_image_reference_everywhere(tmp_path):
    ctx = ProjectContext.at(tmp_path)
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "qr-1.pdf").write_bytes(b"%PDF-1.4\n")
    call = "\\SMQRCode[0.60\\textheight]{media/qr-1.pdf}{QR 1}"
    assert "media/qr-1.pdf" in alt_blocks.referenced_images(f"\\begin{{standardframe}}{{T}}\n{call}\n\\end{{standardframe}}\n")
    issues = latex_lint.lint_text(ctx, "\\SMQRCode{media/missing.pdf}{}\n")
    assert [i.message for i in issues if i.code == "image"] == ["image file 'media/missing.pdf' does not exist"]
    assert not [i for i in latex_lint.lint_text(ctx, call + "\n") if i.code == "image"]

    path = tmp_path / "abc-EN-QR-current.tex"
    path.write_text(f"\\begin{{standardframe}}{{Scan}}\nSee QR 1.\n\n{call}\n\\end{{standardframe}}\n", encoding="utf-8")
    entry = transcript.render_slide(ctx, transcript.DeckSlide(1, "abc", path, True), "during-course", {})
    assert entry is not None and "QR 1" in entry.body and "qr-1.pdf" not in entry.body
