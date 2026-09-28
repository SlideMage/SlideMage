"""Renders .pdf media references to a cached PNG (2026-08-26, direct
instruction) -- both the Images tab's own preview and the Ollama vision
model need a raster image; a .pdf media file (icons, diagrams, occasional
real figure) is a vector original neither can read directly.

Mirrors slide_snapshot.py's own mtime-based cache-freshness check (a
cache PNG at least as new as its source .pdf is fresh, else PyMuPDF --
imported as `fitz`, this project's one PDF-rendering dependency, already
used by slide_snapshot.py -- redoes it), not a content hash: this is a
single-machine local cache, not shared across others, so a bumped mtime
from git/cloud-sync round-tripping identical bytes is the only
false-positive risk, and re-rendering one page is cheap enough not to
bother guarding against it.

The slide's own .tex source keeps \\includegraphics{...pdf} untouched --
only this SlideMage-side preview/description pipeline ever reads the
rendered PNG; nothing that reaches the compiled deck does.
"""
from __future__ import annotations

from pathlib import Path

import pymupdf as fitz

from .deck_scan import PROJECT_ROOT

# Gitignored (see .gitignore), same as .previews/slide_previews/ -- a
# regeneratable, best-effort cache, not project content worth tracking.
# Moved under previews/ 2026-09-18, then .previews/ the same day (was a
# project-root folder before that; dot-prefixed since nothing here is ever
# something the user needs to interact with).
RENDER_DIR = PROJECT_ROOT / ".previews" / "pdf_render_cache"

# ~216 DPI at PyMuPDF's 72-DPI-per-unit default (matrix scale = DPI/72) --
# same reasoning as slide_snapshot.py's own zoom choice: enough detail to
# read a chart's numbers off it, without an oversized file for what's
# usually a small icon or diagram.
_ZOOM = 3.0


def rendered_png_path(pdf_path: Path) -> Path:
    return RENDER_DIR / f"{pdf_path.stem}.png"


def is_fresh(pdf_path: Path) -> bool:
    png = rendered_png_path(pdf_path)
    return png.is_file() and png.stat().st_mtime >= pdf_path.stat().st_mtime


def ensure_rendered(pdf_path: Path) -> Path:
    """The cached PNG of `pdf_path`'s first page, rendering it first if
    missing or stale. Raises RuntimeError (wrapping whatever PyMuPDF
    raised) on a genuinely broken/unreadable PDF -- callers decide
    per-context whether that means skipping the image or showing an
    error, so it isn't swallowed here."""
    png = rendered_png_path(pdf_path)
    if is_fresh(pdf_path):
        return png
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    try:
        doc = fitz.open(pdf_path)
        try:
            page = doc[0]
            pixmap = page.get_pixmap(matrix=fitz.Matrix(_ZOOM, _ZOOM))
            pixmap.save(png)
        finally:
            doc.close()
    except Exception as exc:  # noqa: BLE001 -- re-raised with context, not swallowed
        raise RuntimeError(f"Could not render {pdf_path.name}: {exc}") from exc
    return png
