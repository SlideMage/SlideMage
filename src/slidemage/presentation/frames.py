# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which PDF pages are the reveal steps of one slide (frame), from beamer's .nav file.

The PDF alone cannot tell (its named destinations exist for every page), but beamer writes one
`\beamer@framepages {first}{last}` line per frame into the deck's .nav file, with 1-based page numbers. The
Presenter compile's .nav is kept next to its compile record (`.build/compile-records/<jobname>/`) or is still
in a build folder. A file only counts when it fits the PDF: the last frame ends on its last page.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .. import compile_records, compiler, project
from ..deck_scan import Deck
from .frame_map import FrameMap, parse_nav


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
