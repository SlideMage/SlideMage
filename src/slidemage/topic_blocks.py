# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Turn physical slide-call sections into reusable topic blocks."""
from __future__ import annotations

import re
from pathlib import Path

from . import deck_editor
from .deck_scan import Chapter, Deck, parse_chapters, slugify
from .fileio import StaleFileError, read_text_exact, write_text_exact
from .project import ProjectContext
from .tex_source import masked_same_length


def _calls(text: str) -> list[re.Match]:
    """Validate a call-only body, ignoring comments and spacing between calls."""
    masked = masked_same_length(text)
    calls = list(deck_editor.SLIDE_CALL_RE.finditer(masked))
    remaining = deck_editor.SLIDE_CALL_RE.sub("", masked)
    if remaining.strip():
        found = next(line.strip() for line in remaining.splitlines() if line.strip())
        raise ValueError("A topic block allows only slide calls, blank lines and comments; "
                         f"found {found!r}.")
    if not calls:
        raise ValueError("This section has no slide calls to make into a block.")
    return calls


def prepare_block(ctx: ProjectContext, deck: Deck, chapter: Chapter, title: str) -> tuple[Path, str, str]:
    """Return the block path, its proposed text, and the new deck text, without writing.

    Reuse a valid block with exactly the same call tokens (including pins and
    conditions), ignoring comments and spacing between calls. Section comments
    stay in the deck; new blocks contain the calls and their title header.
    """
    title = title.strip()
    if not title or "\n" in title or "\r" in title:
        raise ValueError("Enter a block title on one line.")
    if chapter not in parse_chapters(deck.text):
        raise ValueError("This section changed; reload the deck and retry.")
    if not deck_editor.section_editable(deck.text, chapter):
        raise ValueError("The section heading shares its line with other TeX.")
    start = deck_editor.section_line_span(deck.text, chapter)[1]
    body = deck.text[start:chapter.end]
    calls = _calls(body)
    tokens = [call.group() for call in calls]
    paths = sorted(ctx.blocks_dir.glob("*.tex"))
    target = None
    for path in paths:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", path.stem):
            continue
        try:
            existing = _calls(read_text_exact(path))
        except ValueError:
            continue   # plain TeX files and invalid blocks cannot be reused
        if [call.group() for call in existing] == tokens:
            target = path
            break
    if target is None:
        key = slugify(title)
        used = {path.stem.casefold() for path in paths}
        candidate, suffix = key, 2
        while candidate.casefold() in used:
            candidate, suffix = f"{key}-{suffix}", suffix + 1
        target = ctx.blocks_dir / f"{candidate}.tex"
    newline = deck_editor.eol(deck.text)
    block_text = f"%% SlideMage block: {title}{newline}" + newline.join(
        body[call.start():call.end()] for call in calls) + newline
    for index, call in reversed(list(enumerate(calls))):
        replacement = f"\\slideblock{{{target.stem}}}" if index == 0 else ""
        body = body[:call.start()] + replacement + body[call.end():]
    return target, block_text, deck.text[:start] + body + deck.text[chapter.end:]


def make_block(ctx: ProjectContext, deck: Deck, chapter: Chapter, title: str) -> Path:
    """Create or reuse a block and replace a section's calls. Not undoable."""
    target, block_text, new_text = prepare_block(ctx, deck, chapter, title)
    if read_text_exact(deck.path) != deck.text:
        raise StaleFileError(f"{deck.path.name} changed on disk -- reload and retry.")
    created = not target.exists()
    if created:
        target.parent.mkdir(exist_ok=True)
        write_text_exact(target, block_text)
    try:
        deck_editor.apply(deck.path, deck.text, lambda _text: new_text)
    except (OSError, StaleFileError):
        if created and read_text_exact(target) == block_text:
            target.unlink()
        raise
    return target
