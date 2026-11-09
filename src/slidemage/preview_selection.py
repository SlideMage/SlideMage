# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Transient preview-cache publication, retained until the cache writer is removed."""
from __future__ import annotations

from pathlib import Path

from . import preview_cache
from .preview_requests import PreviewRequest, cache_identity


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
