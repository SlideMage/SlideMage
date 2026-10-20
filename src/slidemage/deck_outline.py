# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
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

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

from . import ai_review, alt_blocks, deck_editor, deck_language, latex_lint, slide_language, slide_snapshot
from .project import ProjectContext
from .deck_editor import SlideCall
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
    unreviewed: bool = False
    frame_number: Optional[int] = None
    thumbnail_verified: bool = False
    thumbnail_note: str = ""
    image_selection: object | None = None

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


def _source_facts(ctx: ProjectContext, call: SlideCall) -> tuple[bool, str]:
    """(the source has a lint error, the slide's title): the frame title, else
    the slug without its language segment ("EN-Quote-Demo" -> "Quote Demo")."""
    path = ctx.slides_dir / call.source_filename
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        # A missing slide file is an error (lint_file reports it).
        return True, _title("", call.id_slug)
    cached = _source_cache.get(path)
    if cached is None or cached[0] != mtime:
        errors = any(i.severity == latex_lint.ERROR for i in latex_lint.lint_file(ctx, path))
        text = path.read_text(encoding="utf-8", errors="replace")
        cached = _source_cache[path] = (mtime, errors, _title(text, call.id_slug))
    return cached[1], cached[2]


def _title(source: str, id_slug: str) -> str:
    # Named as the current file whichever version the source is of, so that a
    # slide without a frame title falls back to its slug alone.
    return alt_blocks.slide_title(source, Path(slide_language.current_name(id_slug)))[1]


def slide_file_title(path: Path, id_slug: str) -> str:
    """The title of a slide file that is not a call of the open deck (any version of `id_slug`)."""
    return _title(path.read_text(encoding="utf-8", errors="replace") if path.is_file() else "", id_slug)


def _row(ctx: ProjectContext, slot: deck_language.SlideSlot, key: tuple, position: int, template: str, view: str, language: str,
         links: slide_language.TranslationLinks, unreviewed_paths: set[str]) -> SlideRow:
    call = slot.call
    path = ctx.slides_dir / call.source_filename
    png = slide_snapshot.snapshot_path(ctx, call.id, template, slide_snapshot.THUMB_SIZE, call.id_slug)
    badge = slide_language.badge_for(ctx, call.id_slug, links=links)
    lint_error, title = _source_facts(ctx, call)
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
        missing_translation=badge.own in slide_language.TRANSLATION_LANGUAGES and badge.own != language,
        original_call=slot.original,
        folded_calls=slot.folded,
        related_ids=slot.related_ids,
        unreviewed=f"slides/{call.source_filename}" in unreviewed_paths,
    )


def _call_key(call: SlideCall) -> tuple:
    """What a call *is*, apart from where it stands."""
    return (call.macro, call.id_slug, call.version,
            tuple(call.conditions) if call.conditions else None, call.steps)


@dataclass(frozen=True)
class ResolvedSlot:
    slot: deck_language.SlideSlot
    key: tuple
    position: int
    frame_number: int
    hidden: bool


def resolve_slots(ctx: ProjectContext, deck: Deck, view: str, language: str, *,
                  links: slide_language.TranslationLinks | None = None) -> tuple[ResolvedSlot, ...]:
    """Logical occurrences and their per-view frame counters (hidden steps consume none)."""
    if view not in deck_editor.VIEWS:
        raise ValueError(f"Invalid preview view: {view!r}")
    occurrences = {}
    frame = 0
    result = []
    for position, slot in enumerate(deck_language._slots(deck_language.active_calls(deck), language,
                                                      links or slide_language.TranslationLinks(ctx.slides_dir)), 1):
        base = _call_key(slot.original)
        occurrence = occurrences.get(base, 0)
        occurrences[base] = occurrence + 1
        hidden = not slot.call.included_in(view)
        if not (hidden and slot.call.macro == "slidestep"):
            frame += 1
        result.append(ResolvedSlot(slot, base + (occurrence,), position, frame, hidden))
    return tuple(result)


def _sections(ctx: ProjectContext, deck: Deck, view: str, language: str, resolved: tuple[ResolvedSlot, ...],
              links: slide_language.TranslationLinks) -> list[SectionRow]:
    template = slide_snapshot.detect_template(deck.preamble_text)
    by_section: dict[Optional[int], list[SlideRow]] = {None: []}
    unreviewed_paths = set(ai_review.unreviewed(ctx))
    for slot in resolved:
        call = slot.slot.original
        row = _row(ctx, slot.slot, slot.key, slot.position, template, view, language, links, unreviewed_paths)
        by_section.setdefault(call.chapter.start if call.chapter else None, []).append(
            replace(row, frame_number=slot.frame_number))
    sections = [SectionRow(None, UNSECTIONED, False, by_section[None])] if by_section[None] else []
    sections += [
        SectionRow(chapter, chapter.title, deck_editor.section_editable(deck.text, chapter),
                   by_section.get(chapter.start, []))
        for chapter in deck.chapters
    ]
    return sections


def build_outline(ctx: ProjectContext, deck: Deck, view: str, language: str) -> list[SectionRow]:
    """The sections of `deck` in file order, as seen in `view` (a deck version)
    while editing in `language` ("EN"/"DE")."""
    links = slide_language.TranslationLinks(ctx.slides_dir)
    return _sections(ctx, deck, view, language, resolve_slots(ctx, deck, view, language, links=links), links)


@dataclass(frozen=True, eq=False)
class Outline:
    """The deck as the slide list resolved it, kept for whoever else needs a slide's row, the translation
    links or the Instructor frame numbers (WorkspaceState.outline): resolving the deck takes a scan of the
    slides folder and of every slot, too much to repeat for every click on a slide.

    It describes one project, deck text, view and language (`matches`); a reader whose state differs
    resolves afresh. Its rows are the list's own, thumbnails and previews that went stale included. What a
    row says about its source file (title, translation partner) is as old as the list's last rebuild; the
    workspace drops the outline when a slide file is written (WorkspaceState.drop_outline)."""
    ctx: ProjectContext
    deck_path: Path
    deck_text: str
    view: str
    language: str
    sections: list[SectionRow]
    links: slide_language.TranslationLinks     # the scan the rows were built with
    instructor_frames: dict[tuple, int]        # occurrence key -> frame number in the Instructor view

    def matches(self, ctx: ProjectContext, deck: Deck, language: str, view: str | None = None) -> bool:
        """Whether this is the outline of `deck` in `language` (and `view`, unless None)."""
        return (self.ctx == ctx and self.deck_path == deck.path and self.deck_text == deck.text
                and self.language == language and view in (None, self.view))

    @property
    def rows(self) -> list[SlideRow]:
        """Every slide row in the order of the deck."""
        return [row for section in self.sections for row in section.rows]

    def with_sections(self, sections: list[SectionRow]) -> "Outline":
        """The same resolution with rows the list has patched since (a thumbnail that arrived)."""
        return replace(self, sections=sections)

    def row(self, slide_id: str, occurrence_key: tuple | None = None) -> Optional[SlideRow]:
        """The occurrence with `occurrence_key` of slide `slide_id`, otherwise its first call (see slide_row)."""
        matches = [row for row in self.rows if row.matches(slide_id)]
        return next((row for row in matches if row.key == occurrence_key), matches[0] if matches else None)


def resolve_outline(ctx: ProjectContext, deck: Deck, view: str, language: str) -> Outline:
    """`build_outline`, with what resolving it learnt kept for others to reuse."""
    links = slide_language.TranslationLinks(ctx.slides_dir)
    resolved = resolve_slots(ctx, deck, view, language, links=links)
    instructor = resolved if view == deck_editor.VIEW_INSTRUCTOR else resolve_slots(
        ctx, deck, deck_editor.VIEW_INSTRUCTOR, language, links=links)
    return Outline(ctx, deck.path, deck.text, view, language, _sections(ctx, deck, view, language, resolved, links), links,
                   {r.key: r.frame_number for r in instructor})


def outline_rows(ctx: ProjectContext, deck: Deck, view: str, language: str, *, outline: Outline | None = None) -> list[SlideRow]:
    """Every slide row of `deck` in order: `outline`'s when it describes this deck, view and language, else resolved afresh."""
    if outline is not None and outline.matches(ctx, deck, language, view):
        return outline.rows
    return [row for section in build_outline(ctx, deck, view, language) for row in section.rows]


def slide_row(ctx: ProjectContext, deck: Deck, slide_id: str, view: str, language: str, *, occurrence_key: tuple | None = None,
              outline: Outline | None = None) -> Optional[SlideRow]:
    """The focused occurrence, otherwise the first call of slide `slide_id` in `deck`, without building the whole outline
    (or, when `outline` describes this deck, view and language, without resolving anything)."""
    if outline is not None and outline.matches(ctx, deck, language, view):
        return outline.row(slide_id, occurrence_key)
    template = slide_snapshot.detect_template(deck.preamble_text)
    links = slide_language.TranslationLinks(ctx.slides_dir)
    unreviewed_paths = set(ai_review.unreviewed(ctx))
    matches = [r for r in resolve_slots(ctx, deck, view, language, links=links) if r.slot.matches(slide_id)]
    selected = next((r for r in matches if r.key == occurrence_key), matches[0] if matches else None)
    if selected is not None:
        return replace(_row(ctx, selected.slot, selected.key, selected.position, template, view, language,
                            links, unreviewed_paths), frame_number=selected.frame_number)
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
