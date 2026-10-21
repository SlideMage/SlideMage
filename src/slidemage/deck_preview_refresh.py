# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolve and render the actual preview requests of one deck.

The plan is immutable: each logical occurrence is resolved in each requested
course view before any compilation starts. A failed source therefore does not
prevent later occurrences from being attempted.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import deck_outline, preview_batch, preview_target, slide_language
from .deck_editor import VIEWS
from .preview_requests import PreviewRequest, RenderOptions, SourceRevision


@dataclass(frozen=True)
class DeckProgress:
    occurrence_key: tuple
    frame_number: int
    source: Path
    view: str
    index: int
    total: int
    status: str
    done: int = 0       # how many had finished (renders run several at once)


@dataclass(frozen=True)
class DeckRefreshResult:
    deck_name: str
    scope: str
    language: str
    results: tuple

    @property
    def total(self) -> int:
        return len(self.results)

    def count(self, status: str) -> int:
        return sum(result.status == status for result in self.results)

    @property
    def failed(self) -> tuple:
        return tuple(result for result in self.results if result.status in ('failed', 'cancelled')
                     or result.publication_status in ('failed', 'superseded'))


def plan(ctx, deck, *, scope='all', selected_view='instructor', language='EN',
         force=False) -> tuple[PreviewRequest, ...]:
    """Capture saved sources for every occurrence, including hidden and pinned calls."""
    if scope not in ('selected', 'all'):
        raise ValueError("scope must be 'selected' or 'all'")
    if selected_view not in VIEWS:
        raise ValueError(f'Unknown course view: {selected_view}')
    views = VIEWS if scope == 'all' else (selected_view,)
    links = slide_language.TranslationLinks(ctx.slides_dir)
    slots = {view: deck_outline.resolve_slots(ctx, deck, view, language, links=links) for view in views}
    instructor_frames = {row.key: row.frame_number for row in
                         deck_outline.resolve_slots(ctx, deck, 'instructor', language, links=links)}
    revisions: dict[Path, SourceRevision] = {}
    errors: dict[Path, str] = {}
    requests = []
    for index in range(max((len(rows) for rows in slots.values()), default=0)):
        for view in views:
            if index >= len(slots[view]):
                continue
            row = slots[view][index]
            call = row.slot.call  # translated/pinned call chosen for this language
            target = preview_target.PreviewTarget(
                ctx, call.macro, call.id_slug, call.version, call.conditions, call.steps,
                row.frame_number, deck.preamble_text, row.key, row.hidden,
                instructor_frames.get(row.key))
            source = target.source_path.resolve()
            if source not in revisions:
                try:
                    revisions[source] = SourceRevision.capture(source)
                except OSError as exc:
                    revisions[source] = SourceRevision.capture(source, '')
                    errors[source] = str(exc)
            requests.append(PreviewRequest(target, revisions[source], view, language,
                                           RenderOptions(saved=True, force=force),
                                           errors.get(source)))
    return tuple(requests)


def run(service, deck, requests, *, scope='all', language='EN', cancel=None,
        progress=None, publish=None, log=None, batch_size=1) -> DeckRefreshResult:
    """Use the common scheduler/cache and report every occurrence/view outcome. `batch_size` slides still to render
    share one document (preview_batch.render_batch)."""
    requests = tuple(requests)

    def notify(event: preview_batch.BatchProgress):
        if progress is None:
            return
        spec = requests[event.index - 1]
        progress(DeckProgress(spec.target.occurrence_key, spec.target.frame_number or 0,
                              spec.target.source_path, event.view, event.index,
                              event.total, event.status, event.done))

    results = preview_batch.render_batch(service, requests, cancel=cancel, progress=notify,
                                         publish=publish, log=log, batch_size=batch_size)
    return DeckRefreshResult(deck.name, scope, language, results)
