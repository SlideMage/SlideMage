# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Update version → New slide (v8.58.0, direct request: "When updating the version of a slide, offer the option to
save this version as a new slide (that then takes the place of the old slide in the deck where it was edited, and
maybe offers the option to switch other decks that use the slide to the new slide as well)").

The edits since the slide's version become a slide of their own, with a fresh id and version history
(slide_add.create_copy); the old slide goes back to that version, unchanged (slide_versioning.revert_to_version),
so every deck that keeps it typesets what it did before. The decks asked for load the new slide instead
(deck_editor.retarget_slide_calls): every call there that follows the current content, each keeping its kind,
conditions and steps. A call pinned to a version of the old slide stays as it is, since that version exists only
there. Nothing links the two slides; a translation of the old slide stays the old slide's.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from . import deck_editor, slide_add, slide_source, slide_usage, slide_versioning
from .project import ProjectContext


@dataclass
class Branched:
    created: slide_add.CreatedSlide
    reverted_to: slide_versioning.Version             # the version the old slide is back at
    decks: dict[str, int] = field(default_factory=dict)   # deck name -> calls now loading the new slide
    previous_texts: dict[str, str] = field(default_factory=dict)   # deck name -> its text before (for Undo)


def following_calls(usage: slide_usage.DeckUsage) -> list:
    """The calls of a deck that load the slide's current content (not a pinned version) and may be changed."""
    return [call for call in usage.calls if call.editable and call.macro not in slide_usage.PINNED]


def can_branch(ctx: ProjectContext, id_slug: str) -> str | None:
    """Why the slide cannot become a new slide now, or None: it needs edits since a frozen version."""
    current = slide_add.slide_path(ctx, id_slug)
    text = slide_source.read_slide_source(current)[0]
    try:
        new, base = slide_versioning.plan_update(current, id_slug, text, "patch")
    except ValueError as exc:
        return str(exc)
    if new == base or not slide_versioning.frozen_path(current, id_slug, base).exists():
        return f"{id_slug} has no earlier version to keep: it is new since its last version."
    return None


def save_as_new_slide(ctx: ProjectContext, id_slug: str, slug: str, decks: Iterable[str]) -> Branched:
    """The current content of `id_slug` as a new slide called `slug`, the old slide back at its version, and the
    decks named in `decks` loading the new slide. Raises ValueError (and leaves nothing half done for the slides)
    when it cannot; a deck that changed on disk meanwhile raises deck_editor.StaleFileError after the slides are
    done, naming it."""
    reason = can_branch(ctx, id_slug)
    if reason:
        raise ValueError(reason)
    if not slide_add.SLUG_RE.match(slug):
        raise ValueError(f"{slug!r} is not a usable name: letters and digits, joined by single hyphens.")
    created = slide_add.create_copy(ctx, id_slug, slug)
    try:
        reverted = slide_versioning.revert_to_version(ctx, slide_add.slide_path(ctx, id_slug), id_slug)
    except Exception:
        slide_add.remove_created(ctx, created)
        raise
    result = Branched(created, reverted)
    wanted = set(decks)
    for usage in slide_usage.find_usage(ctx, id_slug):
        if usage.deck.name not in wanted:
            continue
        calls = following_calls(usage)
        if calls:
            deck_editor.retarget_slide_calls(usage.deck.path, usage.deck.text, calls, created.id_slug)
            result.decks[usage.deck.name] = len(calls)
            result.previous_texts[usage.deck.name] = usage.deck.text
    return result
