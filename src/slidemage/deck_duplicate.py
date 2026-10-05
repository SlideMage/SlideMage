"""Duplicate a deck's .tex file under a new name.

No content rewriting needed, unlike archive.py's own archive_deck(): a
deck's name (Deck.name, deck_scan.py) is derived purely from its filename
stem, never embedded in the .tex content itself, so a plain byte-for-byte
copy under a new filename is already a fully working, independent deck.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Optional

from . import compile_passes
from .deck_scan import Deck

# Characters Windows itself refuses in a filename -- a deck name here is
# free text typed into a dialog, not picked from a fixed pattern (e.g. a
# slide id), so it needs its own validation rather than reusing slide_ids.py's.
_INVALID_CHARS_RE = re.compile(r'[<>:"/\\|?*]')


def is_valid_deck_name(name: str, directory: Path) -> Optional[str]:
    """None if `name` is usable as a new deck's filename stem inside
    `directory`, else a human-readable reason it isn't -- call this before
    duplicate_deck() to show the reason directly in the UI rather than
    letting an OSError/ValueError surface from deeper down."""
    name = name.strip()
    if not name:
        return "Name can't be empty."
    if _INVALID_CHARS_RE.search(name):
        return 'Name can\'t contain any of: < > : " / \\ | ? *'
    if (directory / f"{name}.tex").exists():
        return f"{name}.tex already exists."
    return None


def duplicate_deck(deck: Deck, new_name: str) -> Path:
    """Copy deck.path to <same directory>/<new_name>.tex, verbatim.
    Raises ValueError if new_name isn't valid (see is_valid_deck_name) --
    always call that first to show the reason directly in the UI; this
    re-checks it defensively rather than trusting the caller blindly."""
    new_name = new_name.strip()
    reason = is_valid_deck_name(new_name, deck.path.parent)
    if reason is not None:
        raise ValueError(reason)
    dest = deck.path.parent / f"{new_name}.tex"
    shutil.copy2(str(deck.path), str(dest))
    compile_passes.copy_counts(deck.name, new_name)   # same content, same passes
    return dest
