# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""\\SMQRCode with real TeX (skipped without latexmk): the code is a link to what it encodes -- from the
[link] argument, or for an older call from a caption that is just \\url{...} -- and an \\href in the caption
keeps its underline right under its text even when the text is wider than the code (2026-10-29)."""
from __future__ import annotations

import shutil

import pymupdf
import pytest

from conftest import EXAMPLE_PROJECT
from slidemage import qr_code, slide_preview
from slidemage.qr_code import QRSpec

pytestmark = pytest.mark.skipif(shutil.which("latexmk") is None or shutil.which("lualatex") is None,
                                reason="needs a TeX installation")


def underline_gaps(page):
    """(gap below the baseline / font size) of each link underline, with the text it is under."""
    lines = [(span["text"], span["origin"][1], span["size"], span["bbox"])
             for block in page.get_text("dict")["blocks"] for line in block.get("lines", []) for span in line["spans"]]
    gaps = {}
    for drawing in page.get_drawings():
        rect = drawing["rect"]
        if drawing["type"] != "s" or rect.height > 0.5 or rect.width < 5:
            continue
        under = [(text, base, size) for text, base, size, bbox in lines
                 if bbox[0] < rect.x1 and bbox[2] > rect.x0 and base <= rect.y0 + 0.5]
        if under:
            text, base, size = max(under, key=lambda item: item[1])          # the nearest line above
            gaps[text.strip()] = (rect.y0 - base) / size
    return gaps


def test_the_code_links_and_a_caption_href_keeps_its_underline(tmp_path):
    image = tmp_path / "qr-x.pdf"
    qr_code.save(qr_code.make(QRSpec("url", {"url": "https://example.org/page"})), image)
    path = image.as_posix()
    link = qr_code.snippet(path, 0.2, "\\href{https://example.org/page}{example.org/page/long}",
                           "https://example.org/page?a=1&b=2#top")
    old = f"\\SMQRCode[0.25\\textheight]{{{path}}}{{\\url{{https://example.org/old}}}}"
    plain = f"\\SMQRCode[0.25\\textheight]{{{path}}}{{QR 3}} [not a link]"
    body = ("\\begin{standardframe}{QR}\nSee \\href{https://example.org/body}{the body link} here.\n\n"
            f"{link}\\hspace{{1cm}}{old}\\hspace{{1cm}}{plain}\n\\end{{standardframe}}\n")
    pdf = slide_preview.render_slide_text_to_pdf(EXAMPLE_PROJECT, "zz8-EN-QR-Test", body,
                                                 deck_version="instructor", capture_snapshot=False)
    with pymupdf.open(pdf) as doc:
        page = doc[0]
        links = [(item["uri"], item["from"]) for item in page.get_links() if item.get("uri")]
        codes = [(uri, rect) for uri, rect in links if rect.height > 30]          # the codes, not the text links
        assert [uri for uri, _rect in codes] == ["https://example.org/page?a=1&b=2#top", "https://example.org/old"]
        assert not [d for d in page.get_drawings() if d["type"] == "s" and d["rect"].height > 30]   # no link border
        assert "[not a link]" in page.get_text()

        gaps = underline_gaps(page)
        body_gap = next(gap for text, gap in gaps.items() if text.startswith("the body link"))
        caption_gap = next(gap for text, gap in gaps.items() if text.startswith("example.org/page/long"))
        assert 0.1 < body_gap < 0.25
        assert abs(caption_gap - body_gap) < 0.03, gaps                  # was a whole line lower


def test_an_href_wider_than_its_line_keeps_its_underline_under_its_text_anywhere():
    # \SMHrefUnderline is one box: TeX broke the line at its negative \hspace wherever the link text was wider
    # than the room left (a narrow table cell, a narrow box), not only in a QR caption (2026-10-29).
    body = ("\\begin{standardframe}{Links}\nSee \\href{https://example.org/body}{the body link} here.\n\n"
            "\\parbox[t]{1.5cm}{\\href{https://example.org/narrow}{a link much wider than its box}}\n"
            "\\end{standardframe}\n")
    pdf = slide_preview.render_slide_text_to_pdf(EXAMPLE_PROJECT, "zz9-EN-Link-Test", body,
                                                 deck_version="instructor", capture_snapshot=False)
    with pymupdf.open(pdf) as doc:
        gaps = underline_gaps(doc[0])
    body_gap = next(gap for text, gap in gaps.items() if text.startswith("the body link"))
    narrow_gap = next(gap for text, gap in gaps.items() if text.startswith("a link much wider"))
    assert abs(narrow_gap - body_gap) < 0.03, gaps
