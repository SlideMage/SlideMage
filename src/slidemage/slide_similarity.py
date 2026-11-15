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
from .tex_source import VERBATIM_ENV_RE, VERB_RE, blanked_verbatim, comment_start

# Plan §6, 2026-11-15: fixed thresholds, deliberately not settings.
MIN_OVERLAP = 0.5
MAX_TRIPLE_FREQUENCY = 0.05
MIN_WORDS = 5
VERSION_RE = re.compile(r"\\setSlideVersion\s*\{[^}]*\}")
MACRO_RE = re.compile(r"\\[A-Za-z@]+\*?")
TOKEN_RE = re.compile(r"media/[^\s{}\\]+|[^\W_]+|[=<>+\-*/^_]", re.UNICODE)
MATH_RE = re.compile(r"(?<!\\)(?:\$\$.*?\$\$|\$[^$]*\$|\\\(.*?\\\)|\\\[.*?\\\]|"
                     r"\\begin\{(?P<env>math|displaymath|equation\*?|align\*?|alignat\*?|gather\*?|multline\*?)\}"
                     r".*?\\end\{(?P=env)\})", re.DOTALL)
STRUCTURAL_RE = re.compile(r"\\(?:titleframe|sectionframe)(?![A-Za-z@])|\\begin\s*\{sectionframe\}")


@dataclass
class Cluster:
    kind: Literal["exact", "same_words", "similar"]
    ids: list[str]                 # sorted bare slide IDs
    overlap: float                # weakest matching edge in the component
    fingerprint: str
    sequence_deck: Path | None


def uncomment(text: str) -> str:
    """Remove comments while preserving percent signs in verbatim content."""
    lines = []
    for line, mask in zip(text.splitlines(keepends=True), blanked_verbatim(text).splitlines(keepends=True)):
        cut = comment_start(mask)
        lines.append(line if cut < 0 else line[:cut] + ("\n" if line.endswith("\n") else ""))
    return "".join(lines)


def normalise(text: str) -> str:
    """Remove comments and version metadata; preserve verbatim whitespace."""
    verbatim = []

    def keep(match):
        verbatim.append(match.group())
        return f"\x00{len(verbatim) - 1}\x00"

    text = uncomment(text)
    for pattern in (VERBATIM_ENV_RE, VERB_RE):
        text = pattern.sub(keep, text)
    text = " ".join(VERSION_RE.sub("", text).split())
    return re.sub(r"\x00(\d+)\x00", lambda m: verbatim[int(m[1])], text)


def tokens(text: str) -> list[str]:
    """Lower-case words, numbers, media paths and formulas, retaining math macro names."""
    text = re.sub(MATH_RE.pattern + "|" + MACRO_RE.pattern,
                  lambda m: m[0] if MATH_RE.fullmatch(m[0]) else " ", normalise(text), flags=re.DOTALL)
    return [token if token.startswith("\\") else token.lower()
            for token in re.findall(MACRO_RE.pattern + "|" + TOKEN_RE.pattern, text)]


def usage_index(ctx: ProjectContext) -> dict[str, list[deck_scan.Deck]]:
    """Index expanded active calls once, shared by sequence detection and usage labels."""
    usage = defaultdict(list)
    decks = deck_scan.scan_decks(ctx)
    for path in sorted((ctx.root / "blocks").glob("*.tex")):
        try:
            decks.append(deck_scan.read_deck(path))
        except OSError:
            continue
    for deck in decks:
        try:
            expanded, _ = deck_language.expand_fragments(deck)
        except OSError:
            continue
        for slide_id in dict.fromkeys(call.id for call in deck_language.active_calls(expanded)):
            usage[slide_id].append(deck)
    return usage


def find_clusters(ctx: ProjectContext, *, usage=None) -> list[Cluster]:
    """Connected components per kind; each pair belongs to its strongest kind only."""
    bundled = bundled_copies.read_manifest(ctx.root).get("manual", {}).get("files", {})
    codes = languages.project_languages(ctx).codes
    texts, words, own, hashes = {}, {}, {}, {}
    for path in sorted(ctx.slides_dir.glob("*-current.tex")):
        if path.name.startswith("ZZ") or path.relative_to(ctx.root).as_posix() in bundled:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
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

    if usage is None:
        usage = usage_index(ctx)

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
            common = set.intersection(*(set(deck.path for deck in usage.get(i, [])) for i in ids))
            clusters.append(Cluster(kind, ids, overlap, fingerprint, min(common) if common else None))
    return clusters
