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

from .deck_scan import ARCHIVE_DIR, DECKS_DIR, PROJECT_ROOT

# regenerate_headers() does a read-modify-write over every slides/*-current
# .tex file; the GUI runs it on a background thread per edit (see gui.py's
# after_deck_edit), and two edits close enough together would otherwise run
# two of these concurrently and unsynchronized -- confirmed directly
# (2026-07-23) to actually corrupt files this way: thread B can open() a
# file for read in the gap between thread A's open(path, "w") (which
# truncates immediately, before any write() call) and A's actual write,
# reading a near-empty file, then dutifully writing that near-empty
# content back once its own turn comes, permanently losing everything but
# the header block. This lock serializes every call (across threads
# within one process -- SlideMage is single-process/single-instance)
# so a second call simply waits for the first to finish rather than
# racing it.
_LOCK = threading.Lock()

DECKS_GLOBS = [DECKS_DIR, ARCHIVE_DIR]
SLIDES_DIR = PROJECT_ROOT / "slides"

SLIDE_CALL_RE = re.compile(
    r"\\(?:slide|slidefinal|slideversion|omitslide|omitslideversion|conditionalslide|slidestep)"
    r"(?:\[[^\]]*\])?\{([^-}]+)-[^}]*\}")
HEADER_RE = re.compile(
    r"%% Included in decks: [^\r\n]*\r?\n%%\r?\n(?:\r?\n)?")


def _deck_display_name(path) -> str:
    return path.stem


def regenerate_headers() -> tuple[int, int]:
    """Rescan every decks/*.tex and decks/archive/*.tex file and rewrite
    each slides/*-current.tex file's own header block to match. Returns
    (slide files changed, deck files scanned).

    Serialized via _LOCK -- see its own comment above; safe to call from
    multiple threads."""
    with _LOCK:
        return _regenerate_headers_impl()


def _regenerate_headers_impl() -> tuple[int, int]:
    deck_paths = [
        p for directory in DECKS_GLOBS if directory.is_dir()
        for p in directory.glob("*.tex")
        if p.name != "#workdeck.tex" and not p.name.startswith(("zzz_", "_"))
    ]

    # id -> sorted list of deck display names that include it
    id_to_decks: dict[str, set[str]] = {}
    for deck_path in deck_paths:
        deck_name = _deck_display_name(deck_path)
        with open(deck_path, encoding="utf-8", newline="") as f:
            text = f.read()
        for slide_id in set(SLIDE_CALL_RE.findall(text)):
            id_to_decks.setdefault(slide_id, set()).add(deck_name)

    changed = 0
    if SLIDES_DIR.is_dir():
        for slide_path in SLIDES_DIR.glob("*-current.tex"):
            slide_id = slide_path.name.split("-")[0]
            decks = sorted(id_to_decks.get(slide_id, []))

            with open(slide_path, encoding="utf-8", newline="") as f:
                text = f.read()
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

            if new_text != text:
                with open(slide_path, "w", encoding="utf-8", newline="") as f:
                    f.write(new_text)
                changed += 1

    return changed, len(deck_paths)
