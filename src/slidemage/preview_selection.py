# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""One final-page selection policy for the main Preview and deck thumbnails.

Freshness is established only by a current validated cache lookup. Historical
pixels and shared Instructor snapshots are display references, never render hits.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import time

from . import preview_cache, render_evidence, slide_snapshot
from .preview_requests import PreviewRequest, cache_identity, image_group

_transient_pdfs: dict[tuple[str, str, str], Path] = {}


@dataclass(frozen=True)
class SelectedImage:
    state: str  # verified, previous, reference, missing, hidden
    image: bytes | Path | None
    request: PreviewRequest | None
    artifact_id: str | None
    representative_view: str | None
    pdf: Path | None
    note: str
    classification_evidence: str | None = None
    cache_entry: preview_cache.CachedPreview | None = None
    artifact_revision_hash: str | None = None

    @property
    def fresh(self) -> bool:
        return self.state == 'verified'


def legacy_reference(ctx, bare_id: str, template: str, id_slug: str) -> Path | None:
    """Use one canonical legacy Instructor image on both surfaces."""
    for size in (slide_snapshot.FULL_SIZE, slide_snapshot.THUMB_SIZE):
        path = slide_snapshot.snapshot_path(ctx, bare_id, template, size, id_slug)
        if path.is_file():
            return path
    return None


def remember_transient(spec: PreviewRequest, png: bytes | None, pdf: Path | None = None,
                       *, cached=False, observed_at=None) -> None:
    """Make an accepted but unverified whole-slide image available to both surfaces."""
    if (png is None or cached or spec.target.hidden or spec.options.mode != 'slide'
            or spec.options.overlay is not None):
        return
    cache = preview_cache.PreviewCache(spec.target.context.root)
    if pdf is not None and pdf.is_relative_to(cache.root):
        return
    identity = cache_identity(spec)
    cache.remember_transient(identity, png, spec.view, observed_at=observed_at)
    if pdf is not None:
        context = render_evidence.digest(cache.display_context(identity))
        checksum = hashlib.sha256(png).hexdigest()
        _transient_pdfs[(str(cache.project_root), context, checksum)] = pdf
        while len(_transient_pdfs) > 64:
            del _transient_pdfs[next(iter(_transient_pdfs))]


def select_image(cache: preview_cache.PreviewCache, specs: tuple[PreviewRequest, ...], env: dict,
                 *, thumbnail=False, validation=None, reference: Path | None = None) -> SelectedImage:
    """Choose one whole-slide image, using the same precedence on both surfaces."""
    if specs and specs[0].target.hidden:
        return SelectedImage('hidden', None, specs[0], None, None, None,
                             f'Hidden in {specs[0].view}; no preview for this view.')

    observed_at = time.time_ns()
    for spec in specs:
        identity = cache_identity(spec)
        group = image_group(spec)
        found = cache.group_lookup(group[0], env, validation=validation, thumbnail=thumbnail,
                                   display_only=not thumbnail) if group else None
        if found is not None:
            artifact, representative_view, representative_identity, evidence = found
            remembered_identity = representative_identity
        else:
            artifact = (cache.thumbnail_path(identity, env, validation) if thumbnail else
                        cache.display_lookup(identity, env, validation=validation))
            representative_view, evidence = spec.view, None
            remembered_identity = identity
        if artifact is not None:
            image = artifact if thumbnail else artifact.display_png
            if image is not None:
                cache.remember_display(identity, remembered_identity, representative_view,
                                       evidence=evidence, observed_at=observed_at)
                pdf = None if thumbnail or representative_view != spec.view else artifact.pdf
                artifact_id = cache.canonical_image_id(artifact) if thumbnail else hashlib.sha256(image).hexdigest()
                return SelectedImage('verified', image, spec, artifact_id, representative_view, pdf,
                                     f'{spec.view}, {spec.language}: whole slide, last included reveal step.', evidence,
                                     None if thumbnail else artifact, spec.revision.content_hash)

    # Do not reclassify the old source: history stores the representative that
    # actually supplied this requested view's pixels before inputs changed.
    historical = []
    for spec in specs:
        identity = cache_identity(spec)
        previous = cache.previous_display(identity, validation=validation, thumbnail=thumbnail)
        if previous is not None:
            artifact, representative_view, representative_identity, evidence, when = previous
            source_hash = representative_identity.get('source', {}).get('content_hash')
        else:
            artifact = (cache.previous_thumbnail_path(identity, validation) if thumbnail else
                        cache.display_lookup(identity, {}, validation=validation, historical=True))
            representative_view, evidence = spec.view, None
            representative_identity, when = identity, 0
            source_hash = spec.revision.content_hash
        if artifact is not None:
            image = artifact if thumbnail else artifact.display_png
            if image is not None:
                historical.append((when, spec, artifact, image, representative_view, source_hash, evidence, False))
        transient = cache.previous_transient(identity, thumbnail=thumbnail)
        if transient is not None:
            image, _, source_hash, representative_view, when = transient
            historical.append((when, spec, None, image, representative_view, source_hash, None, True))
    if historical:
        _, spec, artifact, image, representative_view, source_hash, evidence, transient = max(
            historical, key=lambda candidate: candidate[0])
        artifact_id = (cache.canonical_image_id(image) if thumbnail and not transient else
                       image.stem if thumbnail else hashlib.sha256(image).hexdigest())
        pdf = artifact.pdf if artifact is not None and not thumbnail and representative_view == spec.view else None
        if transient and not thumbnail and representative_view == spec.view:
            key = (str(cache.project_root), render_evidence.digest(cache.display_context(cache_identity(spec))), artifact_id)
            candidate = _transient_pdfs.get(key)
            pdf = candidate if candidate is not None and candidate.is_file() else None
        return SelectedImage('previous', image, spec, artifact_id, representative_view, pdf,
                             f'Previous render for {spec.view}, {spec.language}; render to verify current source and settings.',
                             evidence, None if thumbnail else artifact,
                             source_hash)

    if reference is not None and reference.is_file():
        return SelectedImage('reference', reference, specs[0] if specs else None, str(reference.resolve()), 'instructor', None,
                             'Shared Instructor reference; not verified for this deck, view, version or reveal steps.')
    return SelectedImage('missing', None, specs[0] if specs else None, None, None, None,
                         'No matching preview yet. Render this slide in the selected view.')
