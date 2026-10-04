"""Extract single slides from compiled decks as vector PDF pages ("crops")
for the SlideMage manual: example/media/screenshot-slide-<name>.pdf, shown
on the manual's slides like any other image (\\includegraphics).

A slide is found by the slide id its footer prints ("(slide id: abc ...") --
the title slide, which has no footer, by its invisible id stamp, which reads
the same -- and, for a slide with several reveal steps, the last of its pages
unless a step is given. Links and other annotations are dropped (they would
point into the source PDF).

    python tools/manual/make_crops.py gallery <compiled slidemage-manual.pdf>
    python tools/manual/make_crops.py versions <instructor.pdf> <during.pdf> <after.pdf>
    python tools/manual/make_crops.py one <pdf> <slide id> <name> [step]

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
    pattern = re.compile(r"\(slide id: " + re.escape(slide_id) + r"\b")
    return [i for i, page in enumerate(doc) if pattern.search(page.get_text())]


def crop(doc: fitz.Document, slide_id: str, name: str, step: int | None = None) -> Path:
    pages = pages_of(doc, slide_id)
    if not pages:
        raise SystemExit(f"slide {slide_id} not found in {doc.name}")
    index = pages[-1] if step is None else pages[step - 1]
    out = fitz.open()
    out.insert_pdf(doc, from_page=index, to_page=index, links=False, annots=False)
    path = MEDIA / f"screenshot-slide-{name}.pdf"
    out.save(path, garbage=4, deflate=True)
    out.close()
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
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
