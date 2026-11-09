# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared PDF slide identification and preview rasterization."""
from __future__ import annotations

import re
import hashlib
import threading
from collections import OrderedDict
from pathlib import Path

# `import fitz` still works but is deprecated in current PyMuPDF releases
# ("Use `import pymupdf` instead") -- aliased so the rest of this module
# reads the same either way.
import pymupdf as fitz

from .render_evidence import THUMBNAIL_MAX
from .preview_metrics import measure


# PDF content, dimensions -> PNG. Paths alone are unsafe when a job is rebuilt.
# Bounded by bytes as well as entries; no permanent extra artifacts on disk.
_PNG_CACHE: OrderedDict = OrderedDict()
_PNG_CACHE_BYTES = 32 * 1024 * 1024
_PNG_LOCK = threading.RLock()

# Every compiled frame carries this footer element unconditionally (theme
# footer template, SlideMage_base.tex) -- not something special
# to test builds. `\S+` stops at the space before a possible
# "| omitted from student deck" suffix, so the bare id is always what's
# captured regardless of that flag.
SLIDE_ID_RE = re.compile(r"slide id:\s*(\S+)")

FULL_SIZE = (1920, 1080)
THUMB_SIZE = (304, 171)


def slide_id_in(text: str) -> str | None:
    """The slide id a page's text names (its footer, or the invisible stamp of a frame without one)."""
    match = SLIDE_ID_RE.search(text)
    return match.group(1) if match else None


def slide_id_of(page: "fitz.Page") -> str | None:
    return slide_id_in(page.get_text())


@measure('png')
def _preview_pngs(pdf_path: Path, sizes) -> tuple[bytes, ...]:
    data = pdf_path.read_bytes()
    digest = hashlib.sha256(data).digest()
    with _PNG_LOCK:
        keys = [(digest, size) for size in sizes]
        missing = [key for key in keys if key not in _PNG_CACHE]
        if missing:
            from .preview_raster_client import render
            # Only bytes cross the boundary. MuPDF is unsafe in Python threads,
            # even with a mutex around calls (another thread can run its GC).
            images = render(data, tuple(key[1] for key in missing), FULL_SIZE)
            if not images:
                return ()
            _PNG_CACHE.update(zip(missing, images))
        result = tuple(_PNG_CACHE[key] for key in keys)
        for key in keys:
            _PNG_CACHE.move_to_end(key)
        while len(_PNG_CACHE) > 16 or sum(map(len, _PNG_CACHE.values())) > _PNG_CACHE_BYTES:
            _PNG_CACHE.popitem(last=False)
        return result


def prepare_preview_images(pdf_path: Path, snapshots: bool, widths, *, raw=False):
    """Pane and tool display sizes in one raster subprocess, with optional snapshots.

    With `raw`, write only the last page at the first width to a PPM beside the PDF and return its path.
    Otherwise return the display PNGs in `widths` order, followed by the list thumbnail.
    """
    if raw:
        from .preview_raster_client import render

        path = render(pdf_path.read_bytes(), ((widths[0], None),), FULL_SIZE,
                      raw=pdf_path.with_suffix('.ppm'))
        if not path:
            raise RuntimeError('Preview PDF has no pages')
        return (Path(path),), ()
    displays = tuple((width, None) for width in widths) + ((*THUMBNAIL_MAX, 'fit'),)
    sizes = (FULL_SIZE, THUMB_SIZE) + displays if snapshots else displays
    images = _preview_pngs(pdf_path, sizes)
    if not images:
        raise RuntimeError('Preview PDF has no pages')
    return images[-len(displays):], tuple(zip(sizes[:2], images[:2])) if snapshots else ()


def slide_runs(slide_ids) -> list[tuple[str, list[int]]]:
    """The slides of a deck PDF from the slide id of each page (None: a page that names none, skipped): each
    run of consecutive pages with one id is a slide, with its page indexes -- the last is its final build step."""
    runs: list[tuple[str, list[int]]] = []
    for index, slide_id in enumerate(slide_ids):
        if slide_id is None:
            continue
        if runs and runs[-1][0] == slide_id:
            runs[-1][1].append(index)
        else:
            runs.append((slide_id, [index]))
    return runs


def batch_runs(texts, bare_ids) -> list[list[int]]:
    """The page indexes of each of `bare_ids` in a PDF of several slides whose pages have the texts `texts`, in order.
    RuntimeError unless the slide ids of the pages are exactly those slides, in that order, each on a run of its own."""
    runs = slide_runs([slide_id_in(text) for text in texts])
    if [bare for bare, _pages in runs] != list(bare_ids) or sum(len(pages) for _bare, pages in runs) != len(texts):
        raise RuntimeError("the pages of the batch are not those of its slides")
    return [pages for _bare, pages in runs]
