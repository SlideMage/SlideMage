# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The presenter PDF as slides and notes.

SlideMage's "Presenter" compile (latex/SlideMage_base.tex, \\SMPresenterModeOverride) makes one
double-width page per beamer overlay: the slide in the left half, its note page in the right half. A plain
PDF has single-width pages and no notes; it is shown the same way, just without a notes half.
Rendering is synchronous: a 1920 px slide takes about 13 ms (M0 measurement in the plan), so a small cache
of rendered images and no worker thread keep MuPDF in one thread.
"""
from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pymupdf
from PySide6.QtGui import QImage

from .frame_map import FrameMap, from_labels

# A slide is 16:9 or 4:3 (at most 1.78 wide); two of them side by side are at least 2.67 wide.
TWO_UP_MIN_RATIO = 2.2
CACHE_IMAGES = 24

SLIDE, NOTES = "slide", "notes"

# PyMuPDF returns a label written as a PDF hex string as it stands, "<FEFF0032>" for "2" (beamer's labels are).
HEX_STRING_RE = re.compile(r"<([0-9A-Fa-f]*)>")
UTF16_BOM = b"\xfe\xff"


def decode_label(label: str) -> str:
    def text(match: re.Match) -> str:
        raw = bytes.fromhex(match.group(1) + "0" * (len(match.group(1)) % 2))
        return raw.decode("utf-16", errors="replace") if raw.startswith(UTF16_BOM) else raw.decode("latin-1")
    return HEX_STRING_RE.sub(text, label)


@dataclass(frozen=True)
class Link:
    """A clickable area of a slide. `rect` is (x0, y0, x1, y1) in slide fractions (0..1); a link either
    jumps to `page` (0-based) or opens `uri`."""
    rect: tuple[float, float, float, float]
    page: Optional[int] = None
    uri: Optional[str] = None

    def contains(self, x: float, y: float) -> bool:
        return self.rect[0] <= x <= self.rect[2] and self.rect[1] <= y <= self.rect[3]


class PresentationDeck:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._doc = pymupdf.open(str(self.path))
        if self._doc.page_count == 0:
            self._doc.close()
            raise ValueError(f"{self.path.name} has no pages")
        first = self._doc[0].rect
        self.two_up = first.width / first.height >= TWO_UP_MIN_RATIO
        self._images: OrderedDict[tuple, QImage] = OrderedDict()
        self._links: dict[int, list[Link]] = {}

    @property
    def page_count(self) -> int:
        return self._doc.page_count

    @property
    def has_notes(self) -> bool:
        return self.two_up

    def slide_rect(self, page: int = 0) -> pymupdf.Rect:
        rect = self._doc[page].rect
        return pymupdf.Rect(rect.x0, rect.y0, rect.x0 + rect.width / 2, rect.y1) if self.two_up else rect

    def notes_rect(self, page: int = 0) -> Optional[pymupdf.Rect]:
        if not self.two_up:
            return None
        rect = self._doc[page].rect
        return pymupdf.Rect(rect.x0 + rect.width / 2, rect.y0, rect.x1, rect.y1)

    @property
    def aspect(self) -> float:
        """Width over height of one slide (of the notes half too: it is as large as the slide)."""
        rect = self.slide_rect(0)
        return rect.width / rect.height

    def render(self, page: int, part: str, width: int, height: int) -> Optional[QImage]:
        """`part` ("slide" or "notes") of `page`, scaled to fit inside width x height pixels."""
        if not 0 <= page < self.page_count or width < 1 or height < 1:
            return None
        rect = self.slide_rect(page) if part == SLIDE else self.notes_rect(page)
        if rect is None:
            return None
        key = (page, part, width, height)
        image = self._images.get(key)
        if image is not None:
            self._images.move_to_end(key)
            return image
        scale = min(width / rect.width, height / rect.height)
        pixmap = self._doc[page].get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=rect, alpha=False)
        image = QImage(pixmap.samples, pixmap.width, pixmap.height, pixmap.stride,
                       QImage.Format.Format_RGB888).copy()
        self._images[key] = image
        while len(self._images) > CACHE_IMAGES:
            self._images.popitem(last=False)
        return image

    def links(self, page: int) -> list[Link]:
        if page in self._links:
            return self._links[page]
        found: list[Link] = []
        slide = self.slide_rect(page)
        for item in self._doc[page].get_links():
            rect = pymupdf.Rect(item["from"])
            centre = pymupdf.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
            if not slide.contains(centre):
                continue
            normal = (max(0.0, (rect.x0 - slide.x0) / slide.width), max(0.0, (rect.y0 - slide.y0) / slide.height),
                      min(1.0, (rect.x1 - slide.x0) / slide.width), min(1.0, (rect.y1 - slide.y0) / slide.height))
            kind = item.get("kind")
            if kind == pymupdf.LINK_URI and item.get("uri"):
                found.append(Link(normal, uri=item["uri"]))
            elif kind in (pymupdf.LINK_GOTO, pymupdf.LINK_NAMED) and item.get("page", -1) >= 0:
                found.append(Link(normal, page=min(item["page"], self.page_count - 1)))
        self._links[page] = found
        return found

    def link_at(self, page: int, x: float, y: float) -> Optional[Link]:
        return next((link for link in self.links(page) if link.contains(x, y)), None)

    def page_labels(self) -> Optional[list[str]]:
        """Every page's label, or None when the PDF has none or they cannot be trusted: a presenter PDF compiled
        before SlideMage v0.11.2 has one label rule for the slide and one for the note page of every page, so more
        rules start than there are pages, and every other label is wrong."""
        rules = self._doc.get_page_labels()
        if not rules or any(rule.get("startpage", 0) >= self.page_count for rule in rules):
            return None
        return [decode_label(self._doc[page].get_label()) for page in range(self.page_count)]

    def frame_map(self) -> Optional[FrameMap]:
        """Which pages are the reveal steps of one slide, from the page labels; None for page numbers only."""
        return from_labels(self.page_labels())

    def title(self, page: int) -> str:
        """The first text line of a slide (for the jump list)."""
        text = self._doc[page].get_text(clip=self.slide_rect(page)).strip()
        return text.split("\n", 1)[0] if text else ""

    def close(self) -> None:
        self._images.clear()
        self._doc.close()
