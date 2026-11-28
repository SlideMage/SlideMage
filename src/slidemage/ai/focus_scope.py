# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Scope rules shared by AI agents and plugin tools."""
from __future__ import annotations

from pathlib import Path

SLIDE, DECK = "slide", "deck"
GUARDED_FOLDERS = ("slides", "decks")


def slide_focus(root: Path, path: Path | None) -> Path | None:
    """The focused file if it is a project slide, else None."""
    if path is None:
        return None
    try:
        relative = (root / path).resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return None
    return root / relative if relative.startswith("slides/") and relative.endswith(".tex") else None


def scope_problem(scope: str | None, root: Path, focus: str | Path | None, path: Path) -> str | None:
    """Why an edit of `path` is outside the scope, or None."""
    if scope != SLIDE or path.suffix != ".tex":
        return None
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return None
    focused = focus
    if isinstance(focus, Path):
        try:
            focused = (root / focus).resolve().relative_to(root.resolve()).as_posix()
        except (OSError, ValueError):
            focused = None
    if relative.split("/", 1)[0] not in GUARDED_FOLDERS or relative == focused:
        return None
    return (f"SlideMage scope is Slide ({focused or 'no slide in focus'}): {relative} is outside it. "
            "Leave it alone, or call switch_to_deck_mode (the user is asked).")


def deck_problem(scope: str | None) -> str | None:
    """Why adding a slide (a change of the deck) is refused in the scope, or None."""
    if scope != SLIDE:
        return None
    return ("SlideMage scope is Slide: adding a slide changes the deck, which is outside it. "
            "Call switch_to_deck_mode (the user is asked).")
