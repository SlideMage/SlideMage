# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Project library sets, keyed by a translation group's original bare ID."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from . import slide_language
from .fileio import atomic_write, read_json
from .project import ProjectContext

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
