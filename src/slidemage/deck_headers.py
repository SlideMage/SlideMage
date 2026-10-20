# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Maintain each slides/*-current.tex file's own "Included in decks: ..."
header comment, from what actually \\slide{}s/\\slidefinal{}s/\\slideversion{}s/
\\omitslide{}s/\\omitslideversion{}s it across every decks/*.tex file.

Extracted from the project-root add_deck_headers.py script (2026-07-23) so
both that script's own `python3 add_deck_headers.py` entry point and
SlideMage's GUI (the deck slide-list editor) can share one
implementation instead of duplicating this regex/logic. add_deck_headers.py
is now a thin wrapper that imports and calls regenerate_headers() below;
see that file for the full history/reasoning this docstring used to carry,
still valid for everything not specific to the module split itself.

Attribution is to whichever decks/*.tex file directly contains the
\\slide{}-family call -- not resolved through \\input{} chains. A wrapper
deck like test.tex/test-student.tex that only \\input{test-slides}s a
shared list of calls (rather than calling \\slide{} itself) contributes no
attribution of its own; the slides it pulls in are already correctly
attributed to "test-slides" directly, since that file is itself picked up
by the decks/*.tex glob below and contains the actual calls.

Only touches the "%% Included in decks: ...\n%%\n" block itself (inserted
right after the leading comment, before the first blank line/real content,
matching every existing slide file's own convention) -- never touches
anything else in a slide file, and never touches slides/*-v<N>-<N>-<N>.tex
version snapshots (those are frozen and not `\\slide{}`-referenced by ID the
same way; a version is loaded via \\slideversion{ID-slug}{N-N-N}, which
still resolves to the *current*-file's own ID for this purpose since the ID
is what's tracked, not the version file itself).

Excludes decks/#workdeck.tex on purpose (formerly decks/*-preview.tex,
retired 2026-07-23 in favor of this single reusable file -- see README.md's
own note): a throwaway scratch compile target for whatever's currently
being fine-tuned, not something a slide's "which real decks include me"
header should list.

Also scans decks/archive/*.tex (SlideMage's archived-deck folder,
2026-07-19): an archived deck still exists and still compiles, just out of
the way, so it should keep showing up in this header rather than silently
vanishing from it the moment it's archived.

Preserves each file's own line-ending convention (CRLF throughout this
project's slides/ and decks/ files) rather than normalizing to bare LF --
read and write both use newline='' so line endings pass through untouched,
and all patterns below tolerate an optional trailing \\r before each \\n.
"""
from __future__ import annotations

import re
import threading
from pathlib import Path

from .fileio import StaleFileError, atomic_write, read_text_exact
from .project import ProjectContext
from .slide_language import TRANSLATION_LANGUAGES

# Serialize header passes within the app. Atomic expected-text writes below also
# protect edits from other writers; after three conflicts leave the file untouched
# for a later pass rather than overwriting a slide that keeps changing.
_LOCK = threading.Lock()

HEADER_RE = re.compile(
    r"%% Included in decks: [^\r\n]*\r?\n%%\r?\n(?:\r?\n)?")


def _deck_display_name(path) -> str:
    return path.stem


def regenerate_headers(ctx: ProjectContext) -> tuple[int, int]:
    """Rescan every decks/*.tex and decks/archive/*.tex file and rewrite
    each slides/*-current.tex file's own header block to match. Returns
    (slide files changed, deck files scanned).

    Serialized via _LOCK -- see its own comment above; safe to call from
    multiple threads."""
    with _LOCK:
        return _regenerate_headers_impl(ctx)


def regenerate_header(ctx: ProjectContext, slide_path: Path) -> bool:
    """Rewrite one slide file's header block to match the decks now; whether the file changed. create_slide calls
    it before it renders the new slide: the header sync after the deck edit then leaves that file alone, instead
    of rewriting it while its preview renders (the Preview drops a render whose file changed meanwhile)."""
    with _LOCK:
        id_to_decks, _deck_paths = _deck_membership(ctx)
        return _rewrite_header(slide_path, sorted(id_to_decks.get(slide_path.name.split("-")[0], [])))


def _regenerate_headers_impl(ctx: ProjectContext) -> tuple[int, int]:
    id_to_decks, deck_paths = _deck_membership(ctx)
    changed = 0
    if ctx.slides_dir.is_dir():
        for slide_path in ctx.slides_dir.glob("*-current.tex"):
            slide_id = slide_path.name.split("-")[0]
            changed += _rewrite_header(slide_path, sorted(id_to_decks.get(slide_id, [])))
    return changed, len(deck_paths)


def _deck_membership(ctx: ProjectContext) -> tuple[dict[str, set[str]], list[Path]]:
    """(slide id -> the names of the decks that include it, the deck files read)."""
    deck_paths = [
        p for directory in ctx.deck_folders if directory.is_dir()
        for p in directory.glob("*.tex")
        if p.name != "#workdeck.tex" and not p.name.startswith(("zzz_", "_"))
    ]

    # id -> sorted list of deck display names that include it
    id_to_decks: dict[str, set[str]] = {}
    for deck_path in deck_paths:
        deck_name = _deck_display_name(deck_path)
        text = read_text_exact(deck_path)
        from types import SimpleNamespace
        from . import deck_editor, deck_language
        calls = deck_editor.parse_slide_calls(SimpleNamespace(text=text, chapters=[]))
        for call in calls:
            id_to_decks.setdefault(call.id, set()).add(deck_name)
        for language in TRANSLATION_LANGUAGES:
            for slot in deck_language.slots(ctx, calls, language):
                id_to_decks.setdefault(slot.call.id, set()).add(deck_name)
    return id_to_decks, deck_paths


def _rewrite_header(slide_path: Path, decks: list[str]) -> bool:
    """Give `slide_path` the header block that lists `decks`; whether the file changed."""
    for _attempt in range(3):
        text = read_text_exact(slide_path)
        eol = "\r\n" if "\r\n" in text else "\n"

        listed = ", ".join(decks) if decks else "(none)"
        new_header = f"%% Included in decks: {listed}{eol}%%{eol}{eol}"

        if HEADER_RE.search(text):
            new_text = HEADER_RE.sub(new_header, text, count=1)
        else:
            # No existing header block -- insert after the leading
            # comment lines (everything up to the first blank line),
            # matching every hand-written slide file's own convention.
            m = re.search(r"\r?\n\r?\n", text)
            insert_at = m.end() if m else 0
            new_text = text[:insert_at] + new_header + text[insert_at:]

        if new_text == text:
            return False
        try:
            atomic_write(slide_path, new_text, expected_text=text)
        except StaleFileError:
            continue                 # re-read the newer body; leave it alone if all retries fail
        return True
    return False
