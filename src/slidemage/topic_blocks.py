# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Turn physical slide-call sections into reusable topic blocks."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import deck_editor, deck_language
from .deck_scan import Chapter, Deck, parse_chapters, slugify
from .fileio import StaleFileError, read_text_exact, write_text_exact, write_texts
from .filelock import build_lock
from .project import ProjectContext
from .slide_usage import deck_calls, decks_by
from .tex_source import masked_same_length


def stray_lines(text: str) -> list[tuple[int, str]]:
    """Numbered lines holding anything but slide calls, blank lines and comments."""
    remaining = masked_same_length(text)
    for call in deck_language.calls_in(deck_language.masked(text), []):
        remaining = (remaining[:call.call_start] + re.sub(r"[^\n]", " ", remaining[call.call_start:call.call_end])
                     + remaining[call.call_end:])
    return [(number, line) for number, line in enumerate(remaining.splitlines(), 1) if line.strip()]


def metadata(text: str) -> dict:
    """The managed header lines of a block; a missing line gives an empty value."""
    found = dict(re.findall(r"^%% (SlideMage block|Topics|Description):[^\S\r\n]*([^\r\n]*)", text, re.MULTILINE))
    return {"title": found.get("SlideMage block", "").strip(),
            "topics": [t.strip() for t in found.get("Topics", "").split(",") if t.strip()],
            "description": found.get("Description", "").strip()}


def _calls(text: str) -> list[re.Match]:
    """Validate a call-only body, ignoring comments and spacing between calls."""
    calls = list(deck_editor.SLIDE_CALL_RE.finditer(masked_same_length(text)))
    stray = stray_lines(text)
    if stray:
        raise ValueError("A topic block allows only slide calls, blank lines and comments; "
                         f"found {stray[0][1].strip()!r}.")
    if not calls:
        raise ValueError("This section has no slide calls to make into a block.")
    return calls


def prepare_calls_block(ctx: ProjectContext, tokens: list[str], title: str, newline: str = "\n") -> tuple[Path, str]:
    """Reuse exact call tokens, including pins and conditions, or propose a unique key."""
    title = title.strip()
    if not title or "\n" in title or "\r" in title:
        raise ValueError("Enter a block title on one line.")
    if not tokens:
        raise ValueError("Choose at least one slide for the block.")
    paths = _block_paths(ctx)
    for path in paths:
        if not deck_editor.BLOCK_KEY_RE.fullmatch(path.stem):
            continue
        try:
            text = read_text_exact(path)
            existing = _calls(text)
        except ValueError:
            continue   # plain TeX files and invalid blocks cannot be reused
        if [text[call.start():call.end()] for call in existing] == tokens:
            return path, text
    key = slugify(title)
    used = {path.stem.casefold() for path in paths}
    candidate, suffix = key, 2
    while candidate.casefold() in used:
        candidate, suffix = f"{key}-{suffix}", suffix + 1
    return (ctx.blocks_dir / f"{candidate}.tex",
            f"%% SlideMage block: {title}{newline}" + newline.join(tokens) + newline)


def _replace(body: str, calls: list[re.Match], target: Path) -> str:
    for index, call in reversed(list(enumerate(calls))):
        replacement = f"\\slideblock{{{target.stem}}}" if index == 0 else ""
        body = body[:call.start()] + replacement + body[call.end():]
    return body


def prepare_block(ctx: ProjectContext, deck: Deck, chapter: Chapter, title: str) -> tuple[Path, str, str]:
    """Propose a block and new deck text; comments stay in the deck. No writes."""
    if chapter not in parse_chapters(deck.text):
        raise ValueError("This section changed; reload the deck and retry.")
    if not deck_editor.section_editable(deck.text, chapter):
        raise ValueError("The section heading shares its line with other TeX.")
    start = deck_editor.section_line_span(deck.text, chapter)[1]
    body = deck.text[start:chapter.end]
    calls = _calls(body)
    target, block_text = prepare_calls_block(ctx, [body[c.start():c.end()] for c in calls], title, deck_editor.eol(deck.text))
    body = _replace(body, calls, target)
    return target, block_text, deck.text[:start] + body + deck.text[chapter.end:]


def prepare_run_block(ctx: ProjectContext, occurrences: list[tuple[Deck, list[deck_editor.SlideCall]]],
                      title: str) -> tuple[Path, str, dict[Path, str]]:
    """Propose replacing consecutive, identical calls in several decks. No writes.

    A whole linked block can be one occurrence; its physical reference is kept
    or retargeted to the matching block, without editing the block's calls.
    """
    if not occurrences:
        raise ValueError("Choose a run of slide calls.")
    tokens, spans, decks, linked = None, {}, {}, {}
    for deck, selected in occurrences:
        if not selected or any(not c.editable for c in selected):
            raise ValueError("Use calls on their own lines.")
        if any(c.chapter != selected[0].chapter for c in selected):
            raise ValueError("A shared run cannot cross a section boundary.")
        start, end = selected[0].call_start, selected[-1].call_end
        source = selected[0].source or deck.path
        if source != deck.path:
            body = read_text_exact(source)
            calls = _calls(body)
            if (source.parent != ctx.blocks_dir or not deck_editor.BLOCK_KEY_RE.fullmatch(source.stem)
                    or any(c.source != source or c.call_start != start for c in selected)
                    or [c.index for c in selected] != list(range(len(calls)))
                    or [deck_language.call_text(c) for c in selected] != [deck_language.call_text(c)
                        for c in deck_language.calls_in(deck_language.masked(body), [])]):
                raise ValueError("Unlink the block first to convert part of it.")
            linked[source] = body
            replacements = None  # Replace the physical block reference, not its expanded calls.
        else:
            body = deck.text[start:end]
            calls = _calls(body)
            if (any((c.source or deck.path) != deck.path for c in selected)
                    or [(c.start() + start, c.end() + start) for c in calls]
                    != [(c.call_start, c.call_end) for c in selected]):
                raise ValueError("The run changed; reload the deck and retry.")
            replacements = calls
        current = [body[c.start():c.end()] for c in calls]
        if tokens is not None and current != tokens:
            raise ValueError("The decks' calls do not match exactly (including variants, pins and conditions).")
        tokens = current
        if deck.path in decks and decks[deck.path].text != deck.text:
            raise ValueError("The deck changed; reload and retry.")
        decks[deck.path] = deck
        spans.setdefault(deck.path, []).append((start, end, body, replacements))
    if linked:
        target, block_text = next(iter(linked.items()))
    else:
        target, block_text = prepare_calls_block(ctx, tokens, title, deck_editor.eol(occurrences[0][0].text))
    edits = {}
    for path, runs in spans.items():
        text = decks[path].text
        boundary = len(text)
        for start, end, body, calls in sorted(runs, key=lambda r: r[0], reverse=True):
            if end > boundary:
                raise ValueError("The selected runs overlap.")
            replacement = _replace(body, calls, target) if calls is not None else f"\\slideblock{{{target.stem}}}"
            text = text[:start] + replacement + text[end:]
            boundary = start
        edits[path] = text
    return target, block_text, edits


def _block_paths(ctx):
    paths = sorted(ctx.blocks_dir.glob("*.tex"))
    names = {}
    for path in paths:
        key = path.stem.casefold()
        if key in names:
            raise ValueError(f"Block names collide ignoring case: {names[key].name}, {path.name}. Rename one first.")
        names[key] = path
    return paths


def commit_block(ctx, target: Path, block_text: str, edits=None) -> Path:
    """One commit path for creation and conversion; blocks precede deck writes."""
    _calls(block_text)
    with build_lock(ctx.settings_dir / "blocks.lock"):
        paths = _block_paths(ctx)
        # By name: Windows paths compare ignoring case, so research.tex would pass for Research.tex there.
        if any(p.stem.casefold() == target.stem.casefold() and p.name != target.name for p in paths):
            raise StaleFileError(f"{target.name} now collides with another block -- reload and retry.")
        before = read_text_exact(target) if target.exists() else None
        if before is not None and before != block_text:
            raise StaleFileError(f"{target.name} changed on disk -- reload and retry.")
        write_texts({target: (before, block_text), **(edits or {})})
    return target


def make_block(ctx: ProjectContext, deck: Deck, chapter: Chapter, title: str) -> Path:
    """Create or reuse a block and replace a section's calls. Not undoable."""
    target, block_text, new_text = prepare_block(ctx, deck, chapter, title)
    return commit_block(ctx, target, block_text, {deck.path: (deck.text, new_text)})


def make_run_block(ctx: ProjectContext, occurrences: list[tuple[Deck, list[deck_editor.SlideCall]]],
                   title: str, proposal: tuple[Path, str, dict[Path, str]]) -> Path:
    """Apply an approved proposal, refusing any changed destination or calls. Not undoable."""
    if prepare_run_block(ctx, occurrences, title) != proposal:
        raise StaleFileError("The block proposal changed -- reload and retry.")
    target, block_text, edits = proposal
    before = {deck.path: deck.text for deck, _calls in occurrences}
    return commit_block(ctx, target, block_text, {path: (before[path], text) for path, text in edits.items()})


@dataclass
class TopicBlock:
    path: Path
    title: str
    topics: list[str]
    description: str
    calls: list[deck_editor.SlideCall]
    decks: list[Deck] = field(default_factory=list)


def read_blocks(ctx: ProjectContext, scanned: list | None = None) -> dict[str, TopicBlock]:
    """Physical blocks and the decks that use them (`scanned` is slide_usage.deck_calls)."""
    blocks = {}
    _block_paths(ctx)
    for path in deck_language.block_files(ctx):
        if not deck_editor.BLOCK_KEY_RE.fullmatch(path.stem):
            continue
        text = read_text_exact(path)
        _calls(text)
        meta = metadata(text)
        blocks[path.stem] = TopicBlock(path, meta["title"] or path.stem, meta["topics"], meta["description"],
                                       deck_language.calls_in(deck_language.masked(text), []))
    if blocks:
        users = decks_by(deck_calls(ctx) if scanned is None else scanned, "block")
        for key, block in blocks.items():
            block.decks = users.get(key, [])
    return blocks


def update_metadata(path: Path, field: str, value: str, *, expected: str | None = None) -> None:
    """Change just one managed header line, keeping calls, comments and line endings."""
    if field not in ("SlideMage block", "Topics", "Description") or "\n" in value or "\r" in value:
        raise ValueError("Block metadata must be a single header line.")
    before = read_text_exact(path)
    pattern = re.compile(r"^%% " + re.escape(field) + r":[^\r\n]*", re.MULTILINE)
    meta = metadata(before)
    current = {"SlideMage block": meta["title"] or path.stem, "Topics": ", ".join(meta["topics"]),
               "Description": meta["description"]}[field]
    if expected is not None and current != expected:
        raise StaleFileError(f"{field} changed on disk -- reload the block before editing it.")
    line = f"%% {field}: {value.strip()}"
    after = (pattern.sub(lambda _m: line, before, count=1) if pattern.search(before)
             else line + deck_editor.eol(before) + before)
    if after != before:
        write_text_exact(path, after, expected_text=before)
