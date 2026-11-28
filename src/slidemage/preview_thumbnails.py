# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Choose stored whole-slide thumbnails without compiling or rasterizing."""
from __future__ import annotations

import os
import time
from dataclasses import replace

from . import deck_context, deck_editor, deck_language, preview_target, render_evidence, render_lookup, timing
from .preview_requests import PreviewRequest, SourceRevision


VIEW_NAMES = {'instructor': 'Instructor', 'during-course': 'During course', 'after-course': 'After course'}


def step_thumbnail(ctx, store, record, steps):
    """(path, page, pages): the list thumbnail of the last step that a \\slidestep call shows, taken from the stored render
    of the whole slide (one page per step) and shrunk like the store's own thumbnail of the last page. A page before the
    last is made once and kept under .build/step-thumbnails. (None, 0, pages) when there is no such page."""
    pages = record.get('pages') or 0
    try:
        chosen = deck_editor.expand_steps(steps, pages)
    except ValueError:
        return None, 0, pages
    if not chosen:
        return None, 0, pages
    page = max(chosen)
    if page >= pages:
        return store.thumbnail_path(record), page, pages
    path = ctx.build_dir / 'step-thumbnails' / f"{record['key']}-{page:03d}.webp"
    if not path.is_file():
        data = store.page(record, page)
        if data is None:
            return None, 0, pages
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + '.part')
        part.write_bytes(render_evidence.webp(data, render_evidence.THUMBNAIL_MAX))
        os.replace(part, path)
    return path, page, pages


def for_outline(ctx, deck, outline, view, language, *, resolver, read_source=None, paths=None,
                validation=None, revision_sink=None, resolution=None):
    validation = validation or render_evidence.ValidationPass()
    if resolver is not None and resolution is None:
        resolution = deck_language.resolve(deck)
    revisions = {}
    states = dict(current=0, previous=0, reference=0, missing=0)
    spent = dict(capture=0.0, select=0.0)
    paths = None if paths is None else {path.resolve() for path in paths}

    def image(row):
        path = ctx.slides_dir / row.call.source_filename
        if paths is not None and path.resolve() not in paths:
            return row
        state, thumbnail, needs, step_note = 'missing', None, (), None
        try:
            if resolver is None:
                return replace(row, thumbnail=None, thumbnail_verified=False, stale_preview=False)
            target = preview_target.for_call(ctx, deck, row.call, row.position, frame_number=row.frame_number, hidden=row.hidden,
                                             resolution=resolution)
            needs = target.needs_context
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
            step_row = not spec.complete and target.macro == 'slidestep' and bool(target.steps)
            began = time.perf_counter()
            state, record = render_lookup.select(dict(resolver=resolver, unit=spec.unit, spec=spec,
                                                      validation=validation, whole_slide=step_row), strict=False)
            spent['select'] += time.perf_counter() - began
            if record is not None and step_row:
                thumbnail, page, pages = step_thumbnail(ctx, resolver.store, record, target.steps)
                if thumbnail is not None:
                    step_note = f'{view}, {language}: step {page} of {pages} of the whole slide.'
            elif record is not None:
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
        if state == 'current' and step_note:
            note = step_note
        if state == 'missing' and needs:
            note = (f'No thumbnail: this slide shows {deck_context.describe(needs)} of the deck, so it can only be rendered '
                    f'inside the deck. Compile the deck once ({VIEW_NAMES.get(view, view)}) and it appears.')
        return replace(row, thumbnail=thumbnail, thumbnail_verified=state == 'current' and thumbnail is not None,
                       stale_preview=state == 'previous', thumbnail_note=note)

    result = [replace(section, rows=[image(row) for row in section.rows]) for section in outline]
    timing.event(ctx.root, "thumbnails.states", **states, **{f"{k}_s": round(v, 3) for k, v in spent.items()})
    return result
