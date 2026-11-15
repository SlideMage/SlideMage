# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Project library sets, keyed by a translation group's original bare ID."""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field

from . import bundled_copies, deck_context, deck_language, deck_scan, slide_language
from .fileio import atomic_write, read_json
from .project import ProjectContext, call_files
from .slide_similarity import STRUCTURAL_RE

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


def _normalise(ctx: ProjectContext, data: LibraryData) -> LibraryData:
    ids = group_ids(ctx)
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


def read(ctx: ProjectContext) -> LibraryData:
    """Missing files are empty; Nextcloud conflict copies contribute their sets by union."""
    data = LibraryData()
    conflicts = sorted(ctx.settings_dir.glob("library (conflict*).json"))
    for path in [ctx.settings_dir / "library.json", *conflicts]:
        raw = read_json(path)
        data.pool.update(raw.get("pool", []))
        data.not_reusable.update(raw.get("not_reusable", []))
        for slide_id, topics in raw.get("topics", {}).items():
            data.topics.setdefault(slide_id, set()).update(topics)
        for entry in raw.get("different_on_purpose", []):
            data.different_on_purpose.add((frozenset(entry["ids"]), entry["fingerprint"]))
        if path in conflicts:
            log.debug("Merged library conflict copy by union: %s", path)
    return _normalise(ctx, data) if data != LibraryData() else data


def write(ctx: ProjectContext, data: LibraryData) -> None:
    """Prune unknown IDs and write sorted JSON, one set entry per line, atomically."""
    data = _normalise(ctx, data)
    fields = {
        "different_on_purpose": [{"fingerprint": fingerprint, "ids": sorted(ids)}
                                 for ids, fingerprint in sorted(data.different_on_purpose,
                                                               key=lambda e: (sorted(e[0]), e[1]))],
        "not_reusable": sorted(data.not_reusable),
        "pool": sorted(data.pool),
        "topics": {i: sorted(topics) for i, topics in sorted(data.topics.items())},
    }
    atomic_write(ctx.settings_dir / "library.json", json.dumps(fields, ensure_ascii=False, indent=2) + "\n")


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


def suggestions(ctx: ProjectContext) -> list[Suggestion]:
    """Maximal shared runs per pair of real decks, then reusable singles outside them.

    Already linked occurrences count as deck usage, but need no suggestion alone.
    Structural slides, excluded groups, sources and section boundaries split runs.
    Variant/pin differences remain visible; the block action validates exact tokens.
    """
    data, ids = read(ctx), group_ids(ctx)
    links = slide_language.links_for(ctx)
    bundled = bundled_copies.read_manifest(ctx.root).get("manual", {}).get("files", {})
    excluded = set(data.not_reusable)
    for bare, path in links.paths.items():
        text = links.header(path.name[:-len(slide_language.CURRENT_SUFFIX)])
        if (path.name.startswith("ZZ") or path.relative_to(ctx.root).as_posix() in bundled
                or STRUCTURAL_RE.search(deck_language.masked(text))
                or {"contents", "section"}.intersection(deck_context.reasons(text))):
            excluded.add(ids[bare])
    pooled = set(data.pool)
    for path in call_files(ctx):
        if path.parent == ctx.blocks_dir:
            pooled.update(ids[c.id] for c in deck_language.calls_in(
                deck_language.masked(path.read_text(encoding="utf-8")), []) if c.id in ids)

    segments, usage = [], defaultdict(list)
    for deck in deck_scan.scan_decks(ctx):
        if deck.archived or deck.is_test_deck or deck_scan.TAG_MANUAL in deck.groups:
            continue
        segment = []
        for call in deck_language.expanded_calls(ctx, deck):
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
