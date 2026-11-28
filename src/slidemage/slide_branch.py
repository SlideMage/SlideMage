# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Save as new slide, from one captured revision."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection
from dataclasses import replace
from pathlib import Path

from . import deck_editor, slide_add, slide_ids, slide_language, slide_usage, slide_versioning


def capture_identity(ctx, cap: slide_versioning.Proposal, current: Path, created=None) -> slide_versioning.Proposal:
    """Draw the library ID once, and retain it when checking the approval again."""
    from . import fileio, slide_rename
    try:
        registry = fileio.read_text_exact(ctx.slide_ids_csv)
    except FileNotFoundError:
        registry = None
    except UnicodeDecodeError as exc:
        raise ValueError(f"{ctx.slide_ids_csv} is not valid UTF-8.") from exc
    if created is None:
        slug = current.name.removesuffix(slide_language.CURRENT_SUFFIX)
        _, language, name = slide_rename.parse_id_slug(slug, cap.codes)
        id_slug = f"{slide_ids.mint_slide_id(ctx)}-{language or cap.codes[0]}-{name}"
        created = slide_add.CreatedSlide(id_slug, current.parent / slide_language.current_name(id_slug))
    used = {s.casefold() for s in slide_ids.existing_ids_from_disk(ctx)}
    used.update(line.strip().strip('"').casefold() for line in (registry or "").splitlines()[1:])
    if slide_language.bare_id(created.id_slug).casefold() in used:
        raise fileio.StaleFileError(f"The ID of {created.id_slug} is already in use.")
    return replace(cap, created=created, inputs={**cap.inputs, ctx.slide_ids_csv: registry})


def following_calls(usage: slide_usage.DeckUsage) -> list:
    return [call for call in usage.calls if call.version is None]


def switch_sources(cap: slide_versioning.Proposal, id_slug: str) -> dict[Path, tuple[int, list[Path]]]:
    """Number of switchable physical calls in each file and the decks that execute them."""
    users = defaultdict(set)
    for deck, call in cap.occurrences:
        if call.id_slug == id_slug and call.version is None:
            users[call.source].add(deck)
    return {u.deck.path: (len(calls), sorted(users[u.deck.path])) for u in cap.usages
            if (calls := following_calls(u))}


def branch(cap: slide_versioning.Proposal, current: Path, registry: Path, slug: str,
           sources: Collection[Path]) -> slide_versioning.Proposal:
    new, base = cap.update(current, "patch")
    if new == base or cap.base_file(current) not in cap.frozen:
        raise ValueError(f"{current.name} has no earlier version to keep.")
    if not slide_add.SLUG_RE.fullmatch(slug):
        raise ValueError(f"{slug!r} is not a usable name: letters and digits, joined by single hyphens.")
    slide_id, language, _ = cap.created.id_slug.split("-", 2)
    id_slug = f"{slide_id}-{language}-{slug}"
    created = slide_add.CreatedSlide(id_slug, current.parent / slide_language.current_name(id_slug))
    raw = cap.inputs[current]
    body = slide_versioning.strip_marker(slide_ids.body_of(raw))
    edits = {created.path: (None, slide_ids.build_new_slide_header() + body)}
    edits.update(slide_versioning.revert_edits(cap, current))
    for usage in cap.usages:
        if usage.deck.path in sources and (calls := following_calls(usage)):
            text = usage.deck.text
            edits[usage.deck.path] = (text, deck_editor.retarget_slide_calls(text, calls, id_slug))
    before = cap.inputs[registry]
    prefix = '"id"\r\n' if before is None else before
    if prefix and not prefix.endswith(("\r", "\n")):
        prefix += "\r\n"
    edits[registry] = (before, prefix + f'"{slide_id}"\r\n')
    return replace(cap.with_edits(edits), created=created)
