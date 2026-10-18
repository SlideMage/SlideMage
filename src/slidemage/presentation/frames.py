"""Which PDF pages are the reveal steps of one slide (frame), from beamer's .nav file.

The PDF alone cannot tell (its named destinations exist for every page), but beamer writes one
`\beamer@framepages {first}{last}` line per frame into the deck's .nav file, with 1-based page numbers. The
Presenter compile's .nav is kept next to its compile record (`.build/compile-records/<jobname>/`) or is still
in a build folder. A file only counts when it fits the PDF: the last frame ends on its last page.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .. import compile_records, compiler, project
from ..deck_scan import Deck

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


def candidate_jobnames(deck: Deck, pdf: Path) -> list[str]:
    """The names a Presenter compile of this deck is recorded under: the deck's language and the other one."""
    from dataclasses import replace

    from ..deck_settings import read_settings
    version = "instructor" if deck.supports_version else None
    job = compiler.CompileJob(deck, version, None, presenter=True)
    other = "DE" if read_settings(deck.text).language.lower() == "en" else "EN"
    names = [job.jobname, replace(job, language=other).jobname, pdf.stem]
    return list(dict.fromkeys(names))


def nav_files(ctx: project.ProjectContext, jobname: str) -> list[Path]:
    """The kept .nav of a job, then any build folder's, newest first."""
    kept = compile_records.aux_dir(ctx.build_dir, jobname) / f"{jobname}.nav"
    found = [kept] if kept.is_file() else []
    if ctx.build_dir.is_dir():
        builds = sorted(ctx.build_dir.glob(f"{jobname}-*/{jobname}.nav"), key=lambda f: f.stat().st_mtime, reverse=True)
        found += builds
    return found


def load_for(ctx: project.ProjectContext, deck: Deck, pdf: Path, page_count: int) -> Optional[FrameMap]:
    """The frame map of the presented PDF, or None (the page numbers are used then)."""
    for jobname in candidate_jobnames(deck, pdf):
        for nav in nav_files(ctx, jobname):
            try:
                frames = parse_nav(nav.read_text(encoding="utf-8", errors="replace"), page_count)
            except OSError:
                continue
            if frames is not None:
                return frames
    return None
