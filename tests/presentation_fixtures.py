"""A presenter-like PDF built without LaTeX: double-width pages, the slide (a colour block) on the left and a
note on the right, as SlideMage's Presenter compile makes them (measured in docs/plans/presentation-mode.md)."""
from __future__ import annotations

from pathlib import Path

import pymupdf

HEIGHT = 255.12
SLIDE_WIDTH = 453.54           # 16:9


def page_color(index: int) -> tuple[float, float, float]:
    """The slide colour of page `index` (0-based), as 0..1 floats; each page is told apart by its red."""
    return (0.15 + 0.12 * index, 0.3, 0.55)


def make_pdf(path: Path, pages: int = 6, two_up: bool = True) -> Path:
    """Page 0 has a web link (left half) and a link to page 3 (left half), and a link in the notes half that
    must be ignored."""
    doc = pymupdf.open()
    width = SLIDE_WIDTH * (2 if two_up else 1)
    for index in range(pages):
        page = doc.new_page(width=width, height=HEIGHT)
        page.draw_rect(pymupdf.Rect(0, 0, SLIDE_WIDTH, HEIGHT), color=None, fill=page_color(index))
        page.insert_text((20, 30), f"Slide {index + 1}", fontsize=18, color=(1, 1, 1))
        if two_up:
            page.insert_text((SLIDE_WIDTH + 20, 30), f"Note {index + 1}", fontsize=14)
    page = doc[0]      # the links come after all pages exist: one of them points at page 4
    page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(50, 50, 150, 80), "uri": "https://example.org/x"})
    page.insert_link({"kind": pymupdf.LINK_GOTO, "from": pymupdf.Rect(200, 50, 300, 80), "page": 3,
                      "to": pymupdf.Point(0, 0)})
    if two_up:
        page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(600, 50, 700, 80), "uri": "https://example.org/notes"})
    doc.save(str(path))
    doc.close()
    return path


# where the two links of page 0 are, as slide fractions
URI_SPOT = (100 / SLIDE_WIDTH, 65 / HEIGHT)
JUMP_SPOT = (250 / SLIDE_WIDTH, 65 / HEIGHT)
