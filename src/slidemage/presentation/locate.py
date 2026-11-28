# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which PDF to present (plan 4.9)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .. import compiler, project
from ..compiler import DeckPdf
from ..deck_scan import Deck


@dataclass
class Found:
    presenter: Optional[DeckPdf]      # the newest presenter PDF of the deck
    stale: bool                       # ... older than the deck's own files
    plain: Optional[DeckPdf]          # a normal PDF to present without notes


def newest_source_time(ctx: project.ProjectContext, deck: Deck) -> float:
    """The latest change among the deck file and the slide files."""
    times = [deck.path.stat().st_mtime] if deck.path.exists() else []
    if ctx.slides_dir.is_dir():
        times += [f.stat().st_mtime for f in ctx.slides_dir.glob("*.tex")]
    return max(times, default=0.0)


def find_presenter_pdf(ctx: project.ProjectContext, deck: Deck) -> Found:
    pdfs = compiler.deck_pdfs(ctx, deck)    # newest first
    presenters = [p for p in pdfs if p.label.startswith("Presenter") and "chapter" not in p.label]
    presenters.sort(key=lambda p: " · " in p.label)    # the deck's own language first (variants say " · XX")
    presenter = presenters[0] if presenters else None
    ordinary = [p for p in pdfs if not p.label.startswith("Presenter") and "chapter" not in p.label]
    plain = next((p for p in ordinary if p.preferred), ordinary[0] if ordinary else None)
    stale = presenter is not None and presenter.mtime < newest_source_time(ctx, deck)
    return Found(presenter, stale, plain)
