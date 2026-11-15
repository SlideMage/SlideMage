# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Find similar slides and act on exact copies, without a cache."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Literal

from . import (alt_images, bundled_copies, deck_context, deck_editor, deck_language, deck_scan,
               languages, project, slide_language)
from .fileio import StaleFileError, write_texts
from .project import ProjectContext, call_files
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
    for path in call_files(ctx):
        try:
            deck = deck_scan.read_deck(path)
            calls = deck_language.active_calls(deck)
        except OSError:
            continue
        for slide_id in dict.fromkeys(call.id for call in calls):
            usage[slide_id].append(deck)
    return usage


def _exact_paths(ctx: ProjectContext, kept: str, other: str) -> tuple[Path, Path]:
    paths = [slide_language.current_path_for_bare_id(ctx, i) for i in (kept, other)]
    if kept == other or any(p is None for p in paths):
        raise ValueError("Both copies must still exist.")
    if normalise(paths[0].read_text(encoding="utf-8")) != normalise(paths[1].read_text(encoding="utf-8")):
        raise ValueError("The slides are no longer exact copies. Reopen the Library.")
    return tuple(paths)


def archive_unused_copy(ctx: ProjectContext, kept: str, other: str) -> None:
    """Archive the unused current copy through Housekeeping, keeping pinned history intact."""
    from . import unused_content

    _kept, path = _exact_paths(ctx, kept, other)
    usage = usage_index(ctx)
    if not usage.get(kept):
        raise ValueError("Keep a copy used by a deck or block before archiving its unused twin.")
    if usage.get(other) or path not in unused_content.find_unused_slides(ctx):
        raise ValueError(f"{other} is used by a deck, a block, a translation or the pool.")
    if unused_content.archive_files(ctx, [], [path], logging.getLogger(__name__).info)[1] != 1:
        raise ValueError(f"Could not archive {path.name}; check slides/archive/ for an existing copy.")


def _unpinned_calls(deck: deck_scan.Deck, slide_id: str) -> list[deck_editor.SlideCall]:
    mask = deck_language.masked(deck.text)
    return [c for c in deck_editor.parse_slide_calls(deck)
            if c.id == slide_id and c.version is None and mask[c.call_start] == "\\"]


def replacement_files(ctx: ProjectContext, kept: str, other: str) -> dict[Path, deck_scan.Deck]:
    """Validate an exact-copy replacement and snapshot physical files with unpinned calls."""
    kept_path, other_path = _exact_paths(ctx, kept, other)
    links = slide_language.TranslationLinks(ctx.slides_dir, languages.project_languages(ctx).codes)
    groups = [links.group(p.name[:-len(slide_language.CURRENT_SUFFIX)]) for p in (kept_path, other_path)]
    if not all(g.valid for g in groups):
        raise ValueError("The translation links are ambiguous; repair them before replacing calls.")
    missing = groups[1].members.keys() - groups[0].members.keys()
    if missing:
        raise ValueError(f"{other} has a translation ({', '.join(sorted(missing))}) that {kept} lacks.")
    notes = alt_images.load_slide_notes(ctx)
    if other in notes and notes[other].summary and notes[other] != notes.get(kept):
        raise ValueError(f"{other} has alt-text slide notes that {kept} lacks.")
    for entry in alt_images.load_store(ctx).values():
        use, kept_use = entry.used_on.get(other), entry.used_on.get(kept)
        if use is not None and (kept_use is None or any(
                text != kept_use.takeaways.get(code) for code, text in use.takeaways.items())):
            raise ValueError(f"{other} has alt-text for {entry.image} that {kept} lacks.")
    # Exam Forge remembers user-chosen bank folders in its per-plugin settings.
    # Host.cache_dir() is the other per-plugin storage scope; neither is .slidemage.
    settings = project.config_dir() / "plugins" / "settings" / "exam-forge.json"
    scope = "Checked project plugin data, the Exam Forge cache and remembered bank folders; unregistered external banks cannot be verified."
    folders = [project.cache_dir() / "plugins" / "exam-forge"]
    try:
        choices = json.loads(settings.read_text(encoding="utf-8")).get("bank_folders", {}) if settings.exists() else {}
        folders.extend(Path(value).expanduser() for value in choices.values())
        for folder in folders[1:]:
            if not folder.is_dir():
                raise OSError(f"Remembered bank is unavailable: {folder}")
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"Cannot check Exam Forge links: {exc}. {scope}") from exc
    core = {"library.json", "library.lock", "blocks.lock", "ai-review.json", "ai-review.lock", "ai-before", "claude-hooks",
            "bundled_copies.json", "project.json", "app_settings.json", "compile_passes.json",
            "translation_prompts.json", "draft_prompts.json", "backups", "compat-report.json",
            "compat-report.md", "timing.jsonl"}
    reference = re.compile(rb"(?<![A-Za-z0-9])" + re.escape(other.encode()) + rb"(?![A-Za-z0-9])")
    paths = [p for p in ctx.settings_dir.rglob("*") if p.relative_to(ctx.settings_dir).parts[0] not in core
             and not p.name.startswith("library (conflict")]
    for folder in folders:
        paths.extend(folder.rglob("*.json"))
    for path in sorted(set(paths)):
        try:
            if path.is_file() and reference.search(path.name.encode() + b"\0" + path.read_bytes()):
                raise ValueError(f"{other} is referenced by plugin data in {path}. "
                                 f"SlideMage cannot transfer these links. {scope}")
        except OSError as exc:
            raise ValueError(f"Cannot check plugin links in {path}: {exc}. {scope}") from exc
    files = {}
    for path in call_files(ctx):
        deck = deck_scan.read_deck(path)
        if _unpinned_calls(deck, other):
            files[path] = deck
    return files


def replace_exact_copy(ctx: ProjectContext, kept: str, other: str, files: dict[Path, deck_scan.Deck]) -> None:
    """Retarget approved files only; validate all snapshots before the first write."""
    current = replacement_files(ctx, kept, other)
    calls_by_path = {}
    for path, deck in files.items():
        if path not in current or current[path].text != deck.text:
            raise StaleFileError(f"{path.name} changed on disk -- reopen the replacement dialog.")
        calls = _unpinned_calls(current[path], other)
        for call in calls:
            if not call.editable:
                raise ValueError(f"Cannot replace calls in {path.name}: {call.readonly_reason}")
        calls_by_path[path] = calls
    slug = slide_language.current_id_slug_for_bare_id(ctx, kept)
    edits = {}
    for path in sorted(calls_by_path, key=lambda p: (p.parent != ctx.blocks_dir, str(p))):
        text = current[path].text
        for call in reversed(calls_by_path[path]):
            token = deck_editor.format_call(call.macro, slug, call.version, call.conditions, call.steps)
            text = text[:call.call_start] + token + text[call.call_end:]
        edits[path] = (current[path].text, text)
    write_texts(edits)


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
