"""Full-text search across every slide's own .tex source (2026-08-26,
direct instruction) -- unlike alt_blocks.scan_slides_raw() (image-review
focused, skips any slide with no image entirely), this scans *every*
slides/<id>-<slug>-current.tex file, since a slide's text is exactly what
you'd search for regardless of whether it happens to carry an image too.

Plain case-insensitive substring match against the raw TeX source, not a
regex/fuzzy search or a maintained index -- this project's slide corpus
(~665 files, each a few KB) is small enough to re-scan fresh on every
search (confirmed directly: well under a second), so there is nothing to
keep in sync or invalidate the way a real index would need. Searching the
raw source (not a macro-stripped rendering of it) is deliberate too: it
also finds a citation key, a macro name, or an exact LaTeX fragment,
which is often exactly what's wanted when working with source files
directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import alt_blocks
from .deck_scan import PROJECT_ROOT

# Characters of context kept on each side of a match, for the results
# list's own preview snippet. 150 (2026-08-26, direct instruction --
# raised from 60, too short to place a match in context) rather than
# something huge: the results list wraps each snippet to two visible
# lines already (see qt_slide_search_dialog.py's setWordWrap(True)), so a
# snippet much longer than what that already shows just gets clipped.
_SNIPPET_CONTEXT = 150


@dataclass
class SlideSearchResult:
    path: Path
    slide_id: str
    title: str
    snippet: str  # collapsed-whitespace context around the first match


def search_slides(query: str, slides_dir: Path | None = None) -> list[SlideSearchResult]:
    """Every slide whose raw source contains `query` (case-insensitive),
    one result per slide, not per occurrence -- "which slide has this
    text" is the question this answers, not "how many times does it
    appear there." Returns [] for a blank/whitespace-only query rather
    than matching every slide."""
    query = query.strip()
    if not query:
        return []
    needle = query.lower()
    directory = slides_dir or (PROJECT_ROOT / "slides")

    results: list[SlideSearchResult] = []
    for path in sorted(directory.glob("*-current.tex")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        index = text.lower().find(needle)
        if index == -1:
            continue
        slide_id, title = alt_blocks._slide_title(text, path)
        results.append(SlideSearchResult(
            path=path, slide_id=slide_id, title=title,
            snippet=_snippet(text, index, len(query)),
        ))
    return results


def _snippet(text: str, index: int, match_len: int) -> str:
    start = max(0, index - _SNIPPET_CONTEXT)
    end = min(len(text), index + match_len + _SNIPPET_CONTEXT)
    excerpt = " ".join(text[start:end].split())  # collapse newlines/indentation
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{excerpt}{suffix}"
