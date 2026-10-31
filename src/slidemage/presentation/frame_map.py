# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which PDF pages are the reveal steps of one slide (frame): the map itself and beamer's .nav format.

Kept apart from frames.py, which finds the .nav in a project's compile records, so that presenting a PDF without
a project (SlideMage Presenter, docs/plans/presenter-app.md) needs no project or compiler code.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
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
