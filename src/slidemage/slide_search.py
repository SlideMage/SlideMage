"""Full-text search of the project's own source files, for the command palette
(2026-10-10; the slide search dialog of 2026-08-26 became its "Text in project
files" group).

Searched are every slide's `slides/<id>-<slug>-current.tex` (a slide's text is
what one searches for, with or without an image), the decks `decks/*.tex` and
`decks/archive/*.tex`, and `Slidemaster.bib`. A plain case-insensitive substring
match against the raw source, not a regex or a maintained index: ~665 slide
files of a few KB each are re-read in well under a second, so there is nothing
to keep in sync. Matching the raw source is deliberate too: it also finds a
citation key, a macro name or an exact LaTeX fragment.

The palette runs the search on a worker thread and cancels it when the query
changes, hence `cancelled`, asked between two files.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import alt_blocks
from .deck_scan import PROJECT_ROOT

# Characters of context kept on each side of the match: a palette row shows one line.
_SNIPPET_CONTEXT = 40
SLIDE_SUFFIX = "-current.tex"
BIB_NAME = "Slidemaster.bib"


@dataclass(frozen=True)
class SearchHit:
    path: Path
    line: int       # 1-based line of the first match
    title: str      # "1y8 · Frame title" for a slide, else the path within the project
    snippet: str    # collapsed-whitespace context around the match


def project_files(root: Path) -> list[Path]:
    """The files that are searched, slides first."""
    files = sorted((root / "slides").glob(f"*{SLIDE_SUFFIX}"))
    for folder in (root / "decks", root / "decks" / "archive"):
        # "_slidemage_preview-*.tex" are the preview's throwaway wrappers
        files += sorted(p for p in folder.glob("*.tex") if not p.name.startswith("_"))
    bib = root / BIB_NAME
    return files + ([bib] if bib.is_file() else [])


def search_project(
    query: str, root: Path | None = None, cancelled: Callable[[], bool] = lambda: False,
) -> list[SearchHit]:
    """One hit per file that contains `query` (case-insensitive): "which file has
    this text" is the question, not how often it appears. [] for a blank query, and
    whatever was found so far once `cancelled()` says so."""
    query = query.strip()
    if not query:
        return []
    root = root or PROJECT_ROOT
    needle = query.lower()
    hits: list[SearchHit] = []
    for path in project_files(root):
        if cancelled():
            break
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        index = text.lower().find(needle)
        if index == -1:
            continue
        if path.name.endswith(SLIDE_SUFFIX):
            slide_id, title = alt_blocks._slide_title(text, path)
            title = f"{slide_id} · {title}"
        else:
            title = path.relative_to(root).as_posix()
        hits.append(SearchHit(
            path=path, line=text.count("\n", 0, index) + 1, title=title,
            snippet=_snippet(text, index, len(query))))
    return hits


def _snippet(text: str, index: int, match_len: int) -> str:
    start = max(0, index - _SNIPPET_CONTEXT)
    end = min(len(text), index + match_len + _SNIPPET_CONTEXT)
    excerpt = " ".join(text[start:end].split())  # collapse newlines/indentation
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{excerpt}{suffix}"
