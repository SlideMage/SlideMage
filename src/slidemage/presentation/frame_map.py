# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which PDF pages are the reveal steps of one slide (frame): the map itself, beamer's .nav format, and the
PDF's page labels (beamer gives every reveal step of a frame the frame's number as its label).

Kept apart from frames.py, which finds the .nav in a project's compile records, so that presenting a PDF without
a project (SlideMage Presenter, docs/plans/presenter-app.md) needs no project or compiler code.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from collections.abc import Sequence
from typing import Optional

FRAMEPAGES_RE = re.compile(r"\\beamer@framepages\s*\{(\d+)\}\{(\d+)\}")


@dataclass(frozen=True)
class FrameMap:
    frames: tuple[tuple[int, int], ...]      # (first page, last page), 0-based, in order

    @property
    def count(self) -> int:
        return len(self.frames)

    def frame_of(self, page: int) -> tuple[int, int, int]:
        """(slide number, step, steps) of a page; all 1-based. A page in no frame belongs to the one before."""
        index = 0
        for position, (first, _last) in enumerate(self.frames):
            if first <= page:
                index = position
        first, last = self.frames[index]
        return index + 1, min(max(page, first), last) - first + 1, last - first + 1

    def first_page(self, slide: int) -> int:
        """The first page (step) of slide number `slide`, which is clamped to the existing slides."""
        return self.frames[min(max(slide, 1), self.count) - 1][0]


def parse_nav(text: str, page_count: int) -> Optional[FrameMap]:
    """The frames of a .nav file, or None when they do not fit a PDF of `page_count` pages."""
    frames = [(int(first) - 1, int(last) - 1) for first, last in FRAMEPAGES_RE.findall(text)]
    if not frames or frames[0][0] != 0 or frames[-1][1] != page_count - 1:
        return None
    if any(first > last or (position and first <= frames[position - 1][1]) for position, (first, last) in enumerate(frames)):
        return None
    return FrameMap(tuple(frames))


def from_labels(labels: Optional[Sequence[str]]) -> Optional[FrameMap]:
    """The frames of a PDF whose page labels are beamer's frame numbers: neighbouring pages with the same label
    are the reveal steps of one frame. None when that tells nothing: no labels, an empty one, every page its
    own frame (the page numbers say as much), or a single label for a PDF of several pages."""
    if not labels or any(not label for label in labels):
        return None
    frames: list[tuple[int, int]] = []
    for page, label in enumerate(labels):
        if page and label == labels[page - 1]:
            frames[-1] = (frames[-1][0], page)
        else:
            frames.append((page, page))
    if len(frames) == len(labels) or len(frames) == 1:
        return None
    return FrameMap(tuple(frames))


def label_rules(frames: FrameMap) -> list[dict]:
    """PyMuPDF page-label rules (Document.set_page_labels) that give every page its slide number: one rule per
    frame, the number as a fixed prefix with no numbering style, so all reveal steps share it."""
    return [{"startpage": first, "prefix": str(number), "style": "", "firstpagenum": 1}
            for number, (first, _last) in enumerate(frames.frames, start=1)]
