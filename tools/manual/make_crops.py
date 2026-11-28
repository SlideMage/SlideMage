# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Render single slides of compiled decks as images ("crops") for the
SlideMage manual: example/media/screenshot-slide-<name>.png, shown on the
manual's slides like any other image (\\includegraphics).

PNG at 4x the slide's point size (1814 px wide), not a vector PDF page: an
embedded PDF page brings its text along, so the slide showing it would
contain the cropped slide's footer -- "(slide id: ...)" -- before its own,
and SlideMage's preview capture (slide_snapshot, first slide id in the page
text) filed the gallery page as the title slide's preview; a screen reader
would read every cropped slide's text, too.

A slide is found by the slide id its footer prints ("(slide id: abc ...") --
the title slide, which has no footer, by its invisible id stamp, which reads
the same -- and, for a slide with several reveal steps, the last of its pages
unless a step is given.

    python tools/manual/make_crops.py gallery <compiled slidemage-manual.pdf>
    python tools/manual/make_crops.py versions <instructor.pdf> <during.pdf> <after.pdf>
    python tools/manual/make_crops.py one <pdf> <slide id> <name> [step]
    python tools/manual/make_crops.py titled <pdf> <page title> <name>

The manual's own slides are cropped from a compile of the manual itself (the
crops then lag one compile behind the slides they show, like a table of
contents); rerun after changing a cropped slide.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import fitz  # PyMuPDF

REPO = Path(__file__).resolve().parents[2]
MEDIA = REPO / "example" / "media"

# (name, slide id) for the frame-type gallery on the manual's slide 1td
GALLERY = [
    ("titleframe", "1jh"),
    ("sectionframe", "1y9"),
    ("standardframe", "1y8"),
    ("quoteframe", "1i4"),
    ("fullbleedframe", "1vk"),
    ("figureframe", "1rb"),
    ("sideimageframe", "1vh"),
    ("highlightframe", "1mb"),
    ("standout", "1xf"),
]
# the slide shown in the three deck versions on slide 1rv
VERSIONS_SLIDE = "1th"


def pages_of(doc: fitz.Document, slide_id: str) -> list[int]:
    # the page's first slide id, the way slide_snapshot reads it
    first = re.compile(r"\(slide id: ([^\s|)]+)")
    pages = []
    for i, page in enumerate(doc):
        match = first.search(page.get_text())
        if match and match.group(1) == slide_id:
            pages.append(i)
    return pages


def crop(doc: fitz.Document, slide_id: str, name: str, step: int | None = None) -> Path:
    pages = pages_of(doc, slide_id)
    if not pages:
        raise SystemExit(f"slide {slide_id} not found in {doc.name}")
    index = pages[-1] if step is None else pages[step - 1]
    path = MEDIA / f"screenshot-slide-{name}.png"
    doc[index].get_pixmap(dpi=288).save(path)
    print(f"{path.name}  <- {Path(doc.name).name} page {index + 1}")
    return path


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    mode = argv[0]
    if mode == "gallery":
        doc = fitz.open(argv[1])
        for name, slide_id in GALLERY:
            crop(doc, slide_id, f"gallery-{name}")
    elif mode == "versions":
        for version, pdf in zip(("instructor", "during-course", "after-course"), argv[1:4]):
            doc = fitz.open(pdf)
            for step, _page in enumerate(pages_of(doc, VERSIONS_SLIDE), start=1):
                crop(doc, VERSIONS_SLIDE, f"version-{version}-step{step}", step)
    elif mode == "one":
        doc = fitz.open(argv[1])
        crop(doc, argv[2], argv[3], int(argv[4]) if len(argv) > 4 else None)
    elif mode == "titled":
        # the first page whose text starts with a title, e.g. a generated
        # appendix page (no slide id of its own): titled <pdf> <title> <name>
        doc = fitz.open(argv[1])
        index = next(i for i, page in enumerate(doc)
                     if page.get_text().lstrip().startswith(argv[2]) and i > len(doc) // 2)
        path = MEDIA / f"screenshot-slide-{argv[3]}.png"
        doc[index].get_pixmap(dpi=288).save(path)
        print(f"{path.name}  <- {Path(doc.name).name} page {index + 1}")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
