# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Find advisory similarities among the user's current slides, without a cache."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Literal

from . import bundled_copies, deck_context, deck_language, deck_scan, languages, slide_language
from .project import ProjectContext
from .tex_source import COMMENT_RE

# Plan §6, 2026-11-15: fixed thresholds, deliberately not settings.
MIN_OVERLAP = 0.5
MAX_TRIPLE_FREQUENCY = 0.05
MIN_WORDS = 5
VERSION_RE = re.compile(r"\\setSlideVersion\s*\{[^}]*\}")
MACRO_RE = re.compile(r"\\[A-Za-z@]+\*?")
TOKEN_RE = re.compile(r"media/[^\s{}\\]+|[^\W_]+|[=<>+\-*/^_]", re.UNICODE)
STRUCTURAL_RE = re.compile(r"\\(?:titleframe|sectionframe)(?![A-Za-z@])|\\begin\s*\{sectionframe\}")


@dataclass
class Cluster:
    kind: Literal["exact", "same_words", "similar"]
    ids: list[str]                 # sorted bare slide IDs
    overlap: float                # weakest matching edge in the component
    fingerprint: str
    sequence_deck: Path | None


def normalise(text: str) -> str:
    """Remove comments and version metadata, then canonicalise whitespace."""
    return " ".join(VERSION_RE.sub("", COMMENT_RE.sub("", text)).split())


def tokens(text: str) -> list[str]:
    """Lower-case words, numbers, formula symbols and media paths, without macro names."""
    return TOKEN_RE.findall(MACRO_RE.sub(" ", normalise(text)).lower())


def find_clusters(ctx: ProjectContext) -> list[Cluster]:
    """Connected components per kind; each pair belongs to its strongest kind only."""
    bundled = bundled_copies.read_manifest(ctx.root).get("manual", {}).get("files", {})
    codes = languages.project_languages(ctx).codes
    texts, words, own, hashes = {}, {}, {}, {}
    for path in sorted(ctx.slides_dir.glob("*-current.tex")):
        if path.name.startswith("ZZ") or path.relative_to(ctx.root).as_posix() in bundled:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if (STRUCTURAL_RE.search(deck_language.masked(text))
                or {"contents", "section"}.intersection(deck_context.reasons(text))):
            continue
        slug = path.name[:-len(slide_language.CURRENT_SUFFIX)]
        slide_id = slide_language.bare_id(slug)
        texts[slide_id] = normalise(text)
        words[slide_id] = tuple(tokens(text))
        own[slide_id] = slide_language.own_language(slug, codes)
        hashes[slide_id] = hashlib.sha256(texts[slide_id].encode()).hexdigest()

    pairs = {}
    for values, kind in ((hashes, "exact"), (words, "same_words")):
        groups = defaultdict(list)
        for slide_id, value in values.items():
            if kind == "exact" or len(words[slide_id]) >= MIN_WORDS:
                groups[own[slide_id], value].append(slide_id)
        for members in groups.values():
            for pair in combinations(members, 2):
                pairs.setdefault(pair, (kind, 1.0))

    triples = {slide_id: set(zip(w, w[1:], w[2:]))
               for slide_id, w in words.items() if len(w) >= MIN_WORDS}
    frequency = Counter(triple for found in triples.values() for triple in found)
    index = defaultdict(list)
    for slide_id, found in triples.items():
        triples[slide_id] = {t for t in found if frequency[t] <= MAX_TRIPLE_FREQUENCY * len(texts)}
        for triple in triples[slide_id]:
            index[own[slide_id], triple].append(slide_id)
    intersections = Counter(pair for members in index.values() for pair in combinations(members, 2))
    for (a, b), count in intersections.items():
        if (a, b) in pairs:
            continue
        overlap = count / (len(triples[a]) + len(triples[b]) - count)
        if overlap >= MIN_OVERLAP:
            pairs[a, b] = ("similar", overlap)

    # Read usage only once, through the existing fragment expansion. Blocks are also useful on their own.
    usage = defaultdict(set)
    decks = deck_scan.scan_decks(ctx)
    decks.extend(deck_scan.read_deck(p) for p in sorted((ctx.root / "blocks").glob("*.tex")))
    for deck in decks:
        expanded, _ = deck_language.expand_fragments(deck)
        for call in deck_language.active_calls(expanded):
            usage[call.id].add(deck.path)

    clusters = []
    for kind in ("exact", "same_words", "similar"):
        neighbours = defaultdict(set)
        for (a, b), (pair_kind, _) in pairs.items():
            if pair_kind == kind:
                neighbours[a].add(b)
                neighbours[b].add(a)
        seen = set()
        for start in sorted(neighbours):
            if start in seen:
                continue
            members, todo = {start}, [start]
            while todo:
                for other in neighbours[todo.pop()] - members:
                    members.add(other)
                    todo.append(other)
            seen.update(members)
            ids = sorted(members)
            overlap = min(score for (a, b), (pair_kind, score) in pairs.items()
                          if pair_kind == kind and a in members and b in members)
            fingerprint = hashlib.sha256(json.dumps(sorted(texts[i] for i in ids),
                                                    ensure_ascii=False).encode()).hexdigest()
            common = set.intersection(*(usage[i] for i in ids))
            clusters.append(Cluster(kind, ids, overlap, fingerprint, min(common) if common else None))
    return clusters
