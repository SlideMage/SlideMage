# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Choose stored whole-slide thumbnails without compiling or rasterizing."""
from __future__ import annotations

import time
from dataclasses import replace

from . import preview_target, render_evidence, render_lookup, timing
from .preview_requests import PreviewRequest, SourceRevision


def for_outline(ctx, deck, outline, view, language, *, resolver, read_source=None, paths=None,
                validation=None, revision_sink=None):
    validation = validation or render_evidence.ValidationPass()
    revisions = {}
    states = dict(current=0, previous=0, reference=0, missing=0)
    spent = dict(capture=0.0, select=0.0)
    paths = None if paths is None else {path.resolve() for path in paths}

    def image(row):
        path = ctx.slides_dir / row.call.source_filename
        if paths is not None and path.resolve() not in paths:
            return row
        state, thumbnail = 'missing', None
        try:
            if resolver is None:
                return replace(row, thumbnail=None, thumbnail_verified=False, stale_preview=False)
            target = preview_target.for_call(ctx, deck, row.call, row.position, frame_number=row.frame_number, hidden=row.hidden)
            source = path.resolve()
            if source not in revisions:
                began = time.perf_counter()
                text = read_source(path) if read_source is not None else None
                revisions[source] = SourceRevision.capture(path, text)
                spent['capture'] += time.perf_counter() - began
            revision = revisions[source]
            if revision_sink is not None:
                revision_sink[source] = revision.content_hash
            spec = PreviewRequest(target, revision, view, language)
            began = time.perf_counter()
            state, record = render_lookup.select(dict(resolver=resolver, unit=spec.unit, spec=spec,
                                                      validation=validation), strict=False)
            spent['select'] += time.perf_counter() - began
            if record is not None:
                thumbnail = resolver.store.thumbnail_path(record)
        except (OSError, ValueError):
            state = 'hidden' if row.hidden else 'missing'
        states['missing' if state == 'hidden' else state] += 1
        note = {
            'current': f'{view}, {language}: whole slide, last included reveal step. Region, element and individual-step previews can differ.',
            'previous': f'Previous render for {view}, {language}; outdated.',
            'reference': 'Instructor reference; not verified for this deck or view.',
            'hidden': f'Hidden in {view}; no thumbnail for this view.',
            'missing': 'No matching thumbnail yet. Render this slide in the selected view.',
        }[state]
        return replace(row, thumbnail=thumbnail, thumbnail_verified=state == 'current' and thumbnail is not None,
                       stale_preview=state == 'previous', thumbnail_note=note)

    result = [replace(section, rows=[image(row) for row in section.rows]) for section in outline]
    timing.event(ctx.root, "thumbnails.states", **states, **{f"{k}_s": round(v, 3) for k, v in spent.items()})
    return result
