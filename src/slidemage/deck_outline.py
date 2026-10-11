"""The deck's slide list as the workspace shows it (UI_REDESIGN_PLAN.md, step 4):
sections with their slides, and for each slide what is worth a glance --
its title, a lint error in its source, a preview older than its source, not
typeset in the view being edited, no translation into the language being
edited.

Nothing here starts LaTeX or opens a window. The checks read a few small
files per slide (its source, once, for the title and the lint; the preview's
timestamp), so a deck of 600 slides takes well under a second the first time
and about 100 ms after, because what a slide's source says is kept until the
file changes (forget_lint() drops it, e.g. after the bibliography or an image
changed).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import alt_blocks, deck_editor, deck_language, latex_lint, slide_language, slide_snapshot
from .deck_editor import SLIDES_DIR, SlideCall
from .deck_scan import Chapter, Deck

# What the first section is called when slides come before the first \section.
UNSECTIONED = "(before the first section)"

# path -> (mtime_ns, source has a lint error, frame title)
_source_cache: dict[Path, tuple[int, bool, str]] = {}


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
    original_call: Optional[SlideCall] = None
    folded_calls: tuple[SlideCall, ...] = ()
    related_ids: tuple[str, ...] = ()

    @property
    def deck_call(self) -> SlideCall:
        """The physical call to edit; `call` is the file shown in this language."""
        return self.original_call or self.call

    def matches(self, slide_id: str) -> bool:
        return deck_language.SlideSlot(self.deck_call, self.call, self.folded_calls, self.related_ids).matches(slide_id)


@dataclass(frozen=True)
class SectionRow:
    chapter: Optional[Chapter]   # None: the slides before the first \section
    title: str
    editable: bool               # the marker has a line of its own, so it can be renamed, moved, removed
    rows: list[SlideRow]


def forget_lint() -> None:
    _source_cache.clear()


def _source_facts(call: SlideCall) -> tuple[bool, str]:
    """(the source has a lint error, the slide's title): the frame title, else
    the slug without its language segment ("EN-Quote-Demo" -> "Quote Demo")."""
    path = SLIDES_DIR / call.source_filename
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        # A missing slide file is an error (lint_file reports it).
        return True, _title("", call.id_slug)
    cached = _source_cache.get(path)
    if cached is None or cached[0] != mtime:
        errors = any(i.severity == latex_lint.ERROR for i in latex_lint.lint_file(path))
        text = path.read_text(encoding="utf-8", errors="replace")
        cached = _source_cache[path] = (mtime, errors, _title(text, call.id_slug))
    return cached[1], cached[2]


def _title(source: str, id_slug: str) -> str:
    # Named as the current file whichever version the source is of, so that a
    # slide without a frame title falls back to its slug alone.
    return alt_blocks.slide_title(source, Path(f"{id_slug}-current.tex"))[1]


def slide_file_title(path: Path, id_slug: str) -> str:
    """The title of a slide file that is not a call of the open deck (any version of `id_slug`)."""
    return _title(path.read_text(encoding="utf-8", errors="replace") if path.is_file() else "", id_slug)


def _row(slot: deck_language.SlideSlot, key: tuple, position: int, template: str, view: str, language: str) -> SlideRow:
    call = slot.call
    path = SLIDES_DIR / call.source_filename
    png = slide_snapshot.snapshot_path(call.id, template, slide_snapshot.THUMB_SIZE, call.id_slug)
    badge = slide_language.badge_for(call.id_slug, path)
    if slot.related_ids and badge.own in ("EN", "DE"):
        badge.cross_referenced = "DE" if badge.own == "EN" else "EN"
    lint_error, title = _source_facts(call)
    return SlideRow(
        call=call,
        key=key,
        position=position,
        title=title,
        badge=badge.text(),
        thumbnail=png if png.is_file() else None,
        lint_error=lint_error,
        stale_preview=png.is_file() and _older(png, path),
        hidden=not call.included_in(view),
        missing_translation=badge.own in ("EN", "DE") and badge.own != language,
        original_call=slot.original,
        folded_calls=slot.folded,
        related_ids=slot.related_ids,
    )


def _call_key(call: SlideCall) -> tuple:
    """What a call *is*, apart from where it stands."""
    return (call.macro, call.id_slug, call.version,
            tuple(call.conditions) if call.conditions else None, call.steps)


def build_outline(deck: Deck, view: str, language: str) -> list[SectionRow]:
    """The sections of `deck` in file order, as seen in `view` (a deck version)
    while editing in `language` ("EN"/"DE")."""
    template = slide_snapshot.detect_template(deck.preamble_text)
    by_section: dict[Optional[int], list[SlideRow]] = {None: []}
    occurrences: dict[tuple, int] = {}
    for position, slot in enumerate(deck_language.deck_slots(deck, language), start=1):
        call = slot.original
        base = _call_key(call)
        occurrences[base] = occurrences.get(base, 0) + 1
        by_section.setdefault(call.chapter.start if call.chapter else None, []).append(
            _row(slot, base + (occurrences[base] - 1,), position, template, view, language))
    sections = [SectionRow(None, UNSECTIONED, False, by_section[None])] if by_section[None] else []
    sections += [
        SectionRow(chapter, chapter.title, deck_editor.section_editable(deck.text, chapter),
                   by_section.get(chapter.start, []))
        for chapter in deck.chapters
    ]
    return sections


def slide_row(deck: Deck, slide_id: str, view: str, language: str) -> Optional[SlideRow]:
    """The row of the first call of slide `slide_id` in `deck`, without building the whole outline."""
    template = slide_snapshot.detect_template(deck.preamble_text)
    for position, slot in enumerate(deck_language.deck_slots(deck, language), start=1):
        if slot.matches(slide_id):
            return _row(slot, _call_key(slot.original) + (0,), position, template, view, language)
    return None


def _older(png: Path, source: Path) -> bool:
    try:
        return png.stat().st_mtime < source.stat().st_mtime
    except OSError:
        return False


def ordered_items(outline: list[SectionRow]) -> list[Chapter | SlideRow]:
    """Section markers and slides in the order of the deck file."""
    return [item for section in outline
            for item in ([section.chapter] if section.chapter else []) + section.rows]
