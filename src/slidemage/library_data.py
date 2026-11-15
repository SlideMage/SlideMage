# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Project library sets, keyed by a translation group's original bare ID."""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field

from . import deck_language, deck_scan, slide_language, slide_usage
from .fileio import StaleFileError, atomic_write, read_text_exact
from .filelock import build_lock
from .project import ProjectContext
from .slide_similarity import is_structural, user_slides

log = logging.getLogger(__name__)


@dataclass
class LibraryData:
    pool: set[str] = field(default_factory=set)
    not_reusable: set[str] = field(default_factory=set)
    topics: dict[str, set[str]] = field(default_factory=dict)
    # (original IDs, normalised-text fingerprint); both parts identify a dismissal.
    different_on_purpose: set[tuple[frozenset[str], str]] = field(default_factory=set)


def group_ids(ctx: ProjectContext) -> dict[str, str]:
    """Current bare IDs mapped to their group's original (or themselves for unrooted groups)."""
    links = slide_language.links_for(ctx)
    return {slide_id: slide_language.bare_id(links.group(slide_id).original or slide_id)
            for slide_id in links.paths}


def _normalise(ctx: ProjectContext, data: LibraryData, *, prune=True) -> LibraryData:
    ids = group_ids(ctx)
    if not prune:
        stored = data.pool | data.not_reusable | data.topics.keys() | {
            i for members, _fingerprint in data.different_on_purpose for i in members}
        ids.update({i: i for i in stored if i not in ids})
    topics = {}
    for slide_id, values in data.topics.items():
        if slide_id in ids:
            topics.setdefault(ids[slide_id], set()).update(values)
    dismissals = set()
    for members, fingerprint in data.different_on_purpose:
        members = frozenset(ids[i] for i in members if i in ids)
        if len(members) >= 2:
            dismissals.add((members, fingerprint))
    return LibraryData({ids[i] for i in data.pool if i in ids},
                       {ids[i] for i in data.not_reusable if i in ids}, topics, dismissals)


def _read(paths) -> LibraryData:
    data = LibraryData()
    for text in paths.values():
        raw = json.loads(text) if text is not None else {}
        data.pool.update(raw.get("pool", []))
        data.not_reusable.update(raw.get("not_reusable", []))
        for slide_id, topics in raw.get("topics", {}).items():
            data.topics.setdefault(slide_id, set()).update(topics)
        for entry in raw.get("different_on_purpose", []):
            data.different_on_purpose.add((frozenset(entry["ids"]), entry["fingerprint"]))
    return data


def _snapshots(ctx):
    paths = {}
    for path in [ctx.settings_dir / "library.json", *sorted(ctx.settings_dir.glob("library (conflict*).json"))]:
        try:
            paths[path] = read_text_exact(path)
        except FileNotFoundError:
            paths[path] = None
    return paths


def read(ctx: ProjectContext) -> LibraryData:
    """Missing files are empty; Nextcloud conflict copies contribute their sets by union."""
    return _normalise(ctx, _read(_snapshots(ctx)))


def update(ctx: ProjectContext, change) -> LibraryData:
    """Re-read, apply change(data), and persist under the shared cross-process lock."""
    with build_lock(ctx.settings_dir / "library.lock"):
        for attempt in range(3):
            snapshots = _snapshots(ctx)
            data = _normalise(ctx, _read(snapshots), prune=False)  # Rename still needs old IDs.
            change(data)
            data = _normalise(ctx, data)
            try:
                _write(ctx, data, snapshots[ctx.settings_dir / "library.json"])
            except StaleFileError:
                if attempt == 2:
                    raise
                continue
            for path, before in list(snapshots.items())[1:]:
                try:
                    if before is not None and read_text_exact(path) == before:
                        path.unlink()
                        log.debug("Merged and removed library conflict copy: %s", path)
                except OSError:
                    log.exception("Could not retire merged library conflict copy: %s", path)
            return data


def pooled_ids(data: LibraryData, block_calls, ids: dict[str, str]) -> set[str]:
    """Group IDs in the pool: marked, or called by a topic block (`block_calls`: one call list per block)."""
    return data.pool | {ids.get(call.id, call.id) for calls in block_calls for call in calls}


def change_members(data: LibraryData, ids, action, value=True) -> None:
    if action == "pool":
        if value:
            data.pool.update(ids)
            data.not_reusable.difference_update(ids)
        else:
            data.pool.difference_update(ids)
    elif action == "not_reusable":
        data.not_reusable.update(ids)
        data.pool.difference_update(ids)
    else:
        for bare in ids:
            topics = data.topics.setdefault(bare, set())
            topics.discard(value) if action == "remove_topic" else topics.add(value)


def _write(ctx, data, before):
    fields = {
        "different_on_purpose": [{"fingerprint": fingerprint, "ids": sorted(ids)}
                                 for ids, fingerprint in sorted(data.different_on_purpose,
                                                               key=lambda e: (sorted(e[0]), e[1]))],
        "not_reusable": sorted(data.not_reusable),
        "pool": sorted(data.pool),
        "topics": {i: sorted(topics) for i, topics in sorted(data.topics.items())},
    }
    atomic_write(ctx.settings_dir / "library.json", json.dumps(fields, ensure_ascii=False, indent=2) + "\n",
                 expected_text=before)


# Plan §5.2, 2026-11-15: fixed thresholds, deliberately not settings.
MIN_SHARED_RUN = 3
MIN_SHARED_DECKS = 2


@dataclass
class Suggestion:
    ids: tuple[str, ...]  # translation groups' original IDs, in call order
    occurrences: list[tuple[deck_scan.Deck, list[deck_language.ExpandedCall]]]

    @property
    def kind(self) -> str:
        return "run" if len(self.ids) >= MIN_SHARED_RUN else "single"

    @property
    def title(self) -> str:
        chapter = self.occurrences[0][1][0].chapter
        return chapter.title if chapter else "Shared slides"


def suggestions(ctx: ProjectContext, scanned: list | None = None) -> list[Suggestion]:
    """Maximal shared runs per pair of real decks, then reusable singles outside them.

    Already linked occurrences count as deck usage, but need no suggestion alone.
    Structural slides, excluded groups, sources and section boundaries split runs.
    Variant/pin differences remain visible; the block action validates exact tokens.
    """
    data, ids = read(ctx), group_ids(ctx)
    links = slide_language.links_for(ctx)
    users = set(user_slides(ctx))
    excluded = set(data.not_reusable)
    for bare, path in links.paths.items():
        if path not in users or is_structural(links.header(path.name[:-len(slide_language.CURRENT_SUFFIX)])):
            excluded.add(ids[bare])
    pooled = pooled_ids(data, (deck_language.calls_in(deck_language.masked(read_text_exact(path)), [])
                               for path in deck_language.block_files(ctx)), ids)

    segments, usage = [], defaultdict(list)
    for deck, calls in slide_usage.deck_calls(ctx) if scanned is None else scanned:
        if deck.archived or deck.is_test_deck or deck_scan.TAG_MANUAL in deck.groups:
            continue
        segment = []
        for call in calls:
            original = ids.get(call.id)
            eligible = original is not None and original not in excluded
            if eligible:
                usage[original].append((deck, call))
            if segment and (not eligible or call.chapter != segment[-1].chapter
                            or call.source != segment[-1].source
                            or call.index is not None and call.call_start != segment[-1].call_start):
                segments.append((deck, segment))
                segment = []
            if eligible:
                segment.append(call)
        if segment:
            segments.append((deck, segment))

    runs = {}
    for n, (left_deck, left) in enumerate(segments):
        a_ids = [ids[c.id] for c in left]
        for right_deck, right in segments[n + 1:]:
            if left_deck.path == right_deck.path:
                continue
            b_ids = [ids[c.id] for c in right]
            positions = defaultdict(list)
            for b, original in enumerate(b_ids):
                positions[original].append(b)
            for a, original in enumerate(a_ids):
                for b in positions[original]:
                    if a and b and a_ids[a - 1] == b_ids[b - 1]:
                        continue  # not maximal on the left
                    size = 0
                    while a + size < len(left) and b + size < len(right) and a_ids[a + size] == b_ids[b + size]:
                        size += 1
                    if size < MIN_SHARED_RUN:
                        continue
                    occurrences = runs.setdefault(tuple(a_ids[a:a + size]), {})
                    for deck, calls in ((left_deck, left[a:a + size]), (right_deck, right[b:b + size])):
                        occurrences[deck.path, calls[0].identity] = (deck, calls)
    result = [Suggestion(key, list(occurrences.values())) for key, occurrences in runs.items()
              if any(call.source == deck.path for deck, calls in occurrences.values() for call in calls)]
    covered = {(deck.path, call.identity) for run in result for deck, calls in run.occurrences for call in calls}
    for original, found in sorted(usage.items()):
        outside = [(deck, [call]) for deck, call in found if (deck.path, call.identity) not in covered]
        if original not in pooled and len({deck.path for deck, _calls in outside}) >= MIN_SHARED_DECKS:
            result.append(Suggestion((original,), outside))
    return result
