"""The deck's slide list as the workspace shows it (UI_REDESIGN_PLAN.md, step 4):
sections with their slides, and for each slide what is worth a glance --
a lint error in its source, a preview older than its source, not typeset in
the view being edited, no translation into the language being edited.

Nothing here starts LaTeX or opens a window. The checks read a few small
files per slide (its source, once, for the lint; the preview's timestamp), so
a deck of 600 slides takes well under a second the first time and about 100 ms
after, because a slide's lint result is kept until the file changes
(forget_lint() drops them, e.g. after the bibliography or an image changed).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import deck_editor, latex_lint, slide_language, slide_snapshot
from .deck_editor import SLIDES_DIR, SlideCall
from .deck_scan import Chapter, Deck

# What the first section is called when slides come before the first \section.
UNSECTIONED = "(before the first section)"

# path -> (mtime_ns, source has a lint error)
_lint_cache: dict[Path, tuple[int, bool]] = {}


@dataclass(frozen=True)
class SlideRow:
    call: SlideCall
    key: tuple               # what a call *is*, so a rescan can find it again
    position: int            # 1-based among the deck's slide calls
    title: str
    badge: str               # "[EN]", "[EN + DE]" ... ("" for a slide without a language)
    thumbnail: Optional[Path]
    lint_error: bool
    stale_preview: bool
    hidden: bool             # not typeset in the view being edited
    missing_translation: bool   # no version in the language being edited


@dataclass(frozen=True)
class SectionRow:
    chapter: Optional[Chapter]   # None: the slides before the first \section
    title: str
    editable: bool               # the marker has a line of its own, so it can be renamed, moved, removed
    rows: list[SlideRow]


def forget_lint() -> None:
    _lint_cache.clear()


def has_lint_error(path: Path) -> bool:
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return True   # a missing slide file is an error (lint_file reports it)
    cached = _lint_cache.get(path)
    if cached is None or cached[0] != mtime:
        errors = any(i.severity == latex_lint.ERROR for i in latex_lint.lint_file(path))
        cached = _lint_cache[path] = (mtime, errors)
    return cached[1]


def slide_title(call: SlideCall) -> str:
    """The slug without its language segment, as words: "EN-Quote-Demo" -> "Quote Demo"."""
    language, _, rest = call.slug.partition("-")
    slug = rest if language in slide_language.LANGUAGES and rest else call.slug
    return slug.replace("-", " ")


def build_outline(deck: Deck, view: str, language: str) -> list[SectionRow]:
    """The sections of `deck` in file order, as seen in `view` (a deck version)
    while editing in `language` ("EN"/"DE")."""
    template = slide_snapshot.detect_template(deck.preamble_text)
    by_section: dict[Optional[int], list[SlideRow]] = {None: []}
    occurrences: dict[tuple, int] = {}
    for position, call in enumerate(deck_editor.parse_slide_calls(deck), start=1):
        hidden = not call.included_in(view)
        path = SLIDES_DIR / call.source_filename
        base = (call.macro, call.id_slug, call.version,
                tuple(call.conditions) if call.conditions else None, call.steps)
        occurrences[base] = occurrences.get(base, 0) + 1
        png = slide_snapshot.snapshot_path(call.id, template, slide_snapshot.THUMB_SIZE, call.id_slug)
        badge = slide_language.badge_for(call.id_slug, path)
        by_section.setdefault(call.chapter.start if call.chapter else None, []).append(SlideRow(
            call=call,
            key=base + (occurrences[base] - 1,),
            position=position,
            title=slide_title(call),
            badge=badge.text(),
            thumbnail=png if png.is_file() else None,
            lint_error=has_lint_error(path),
            stale_preview=png.is_file() and _older(png, path),
            hidden=hidden,
            missing_translation=badge.own in ("EN", "DE") and badge.own != language
            and badge.cross_referenced != language,
        ))
    sections = [SectionRow(None, UNSECTIONED, False, by_section[None])] if by_section[None] else []
    sections += [
        SectionRow(chapter, chapter.title, deck_editor.section_editable(deck.text, chapter),
                   by_section.get(chapter.start, []))
        for chapter in deck.chapters
    ]
    return sections


def _older(png: Path, source: Path) -> bool:
    try:
        return png.stat().st_mtime < source.stat().st_mtime
    except OSError:
        return False


def ordered_items(outline: list[SectionRow]) -> list[Chapter | SlideRow]:
    """Section markers and slides in the order of the deck file."""
    return [item for section in outline
            for item in ([section.chapter] if section.chapter else []) + section.rows]
