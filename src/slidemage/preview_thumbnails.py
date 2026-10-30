# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Choose left-panel images from the same verified full-slide renders as Preview.

The old flat snapshots are Instructor references shared by decks, versions and
occurrences. Keep them useful as clearly labelled fallbacks, never as evidence
that the selected view was rendered. No compile or raster process starts here.

A whole-deck compile's page of a slide is a verified render too (2026-10-30, direct request: a full Instructor
render still left 'Shared Instructor reference' on every slide). Those pages live in the background previews' render
store, which the caller reads through `stored_page`; that only looks up the index and names a PNG file.
"""
from __future__ import annotations

from dataclasses import replace

from . import compiler, deck_outline, preview_cache, preview_target, slide_snapshot
from .preview_requests import PreviewRequest, RenderOptions, SourceRevision
from .preview_selection import SelectedImage, legacy_reference, select_image


def for_outline(ctx, deck, outline, view, language, *, read_source=None, paths=None,
                validation=None, revision_sink=None, stored_page=None):
    """`stored_page(target, view, language, deck_name) -> Path | None` names the render store's PNG of the slide if a
    current one is there (background_previews.stored_page_path, which works with background rendering switched off).
    A store page ranks after the saved single-slide render of the preview cache and before any older image."""
    cache = preview_cache.PreviewCache(ctx.root)
    validation = validation or preview_cache.ValidationPass()
    env = None
    frames = None
    revisions = {}
    paths = None if paths is None else {path.resolve() for path in paths}

    def image(row):
        nonlocal env, frames
        path = ctx.slides_dir / row.call.source_filename
        if paths is not None and path.resolve() not in paths:
            return row
        if row.hidden:
            return replace(row, thumbnail=None, thumbnail_verified=False, stale_preview=False,
                           thumbnail_note=f'Hidden in {view}; no thumbnail for this view.', image_selection=None)
        # Reset any previous verified image before considering a new context.
        reference = legacy_reference(ctx, row.call.id, slide_snapshot.detect_template(deck.preamble_text),
                                     row.call.id_slug)
        fallback = replace(row, thumbnail=reference, thumbnail_verified=False,
                           stale_preview=reference is not None and deck_outline._older(reference, path),
                           thumbnail_note=('Shared Instructor reference; not verified for this deck, view, '
                                           'version or reveal steps. Render this slide to match Preview.'
                                           if reference else 'No matching thumbnail yet. Render this slide in the selected view.'),
                           image_selection=None)
        try:
            if env is None:
                env = compiler.build_env(ctx)
            if frames is None:
                # Match for_call's Instructor numbering, computed once rather
                # than resolving the entire deck again for every row.
                frames = {r.key: r.frame_number for r in deck_outline.resolve_slots(ctx, deck, 'instructor', language)}
            target = preview_target.for_call(ctx, deck, row.call, row.position, frame_number=row.frame_number)
            target = replace(target, occurrence_key=row.key, presenter_frame_number=frames.get(row.key))
            source = path.resolve()
            if source not in revisions:
                text = read_source(path) if read_source is not None else None
                revisions[source] = SourceRevision.capture(path, text)
            revision = revisions[source]
            if revision_sink is not None:
                revision_sink[source] = revision.content_hash
            specs = (PreviewRequest(target, revision, view, language, RenderOptions(saved=True)),)
            selected = select_image(cache, specs, env, thumbnail=True, validation=validation, reference=reference)
            if not selected.fresh and stored_page is not None:
                page = stored_page(target, view, language, deck.name)
                if page is not None:
                    selected = SelectedImage('verified', page, specs[0], None, view, None,
                                             f'{view}, {language}: whole slide, last included reveal step.',
                                             None, None, revision.content_hash)
            if selected.image is not None:
                note = selected.note + (' Region, element and individual-step previews can differ.'
                                        if selected.fresh else '')
                return replace(row, thumbnail=selected.image, thumbnail_verified=selected.fresh,
                               stale_preview=selected.state == 'previous', thumbnail_note=note,
                               image_selection=selected)
            return replace(row, thumbnail=None, thumbnail_verified=False, stale_preview=False,
                           thumbnail_note=selected.note, image_selection=selected)
        except (OSError, ValueError):
            pass  # An unavailable source/cache remains an explicitly unverified reference.
        return fallback

    return [replace(section, rows=[image(row) for row in section.rows]) for section in outline]
