"""The scope of the embedded Claude Code (the Slide / Deck switch above its terminal): what
the user is looking at and how far a request may reach.

The window writes the focus to a small JSON file (`publish`), named in the child's environment; the
UserPromptSubmit hook turns it into a short context block that opens every prompt (`prompt_context`), so
Claude Code starts at the right file without exploring, and the PreToolUse hook refuses an edit of another
slide or deck while the scope is Slide (`edit_problem`). No Qt.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

FOCUS_ENV = "SLIDEMAGE_FOCUS_FILE"
SLIDE, DECK = "slide", "deck"
GUARDED_FOLDERS = ("slides", "decks")


def publish(file: Path, scope: str, root: Path, slide_id: str | None, slide_path: Path | None,
            deck: Path | None, view: str, language: str, dirty: bool) -> None:
    """Write the focus atomically (the hook may read at any time). `slide_path` is the file the editor
    shows: kept only if it is a slide (slides/*.tex)."""
    def rel(path: Path | None) -> str | None:
        if path is None:
            return None
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except (OSError, ValueError):
            return None

    slide = rel(slide_path)
    if slide is not None and not (slide.startswith("slides/") and slide.endswith(".tex")):
        slide, dirty = None, False
    data = {"scope": scope, "slide_id": slide_id, "slide": slide, "deck": rel(deck),
            "view": view, "language": language, "dirty": dirty}
    temporary = file.with_name(file.name + ".tmp")
    temporary.write_text(json.dumps(data), encoding="utf-8")
    os.replace(temporary, file)


def load(file: str | os.PathLike | None) -> dict | None:
    if not file:
        return None
    try:
        data = json.loads(Path(file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def prompt_context(data: dict) -> str:
    """The block put before the user's prompt."""
    slide, deck = data.get("slide"), data.get("deck")
    where = (f"deck {deck}, viewed as {data.get('view')}, language {data.get('language')}" if deck
             else "no deck open")
    if data.get("scope") == DECK:
        focus = f"; the slide in focus is {slide}" if slide else ""
        return (f"[SlideMage scope: WHOLE DECK] {where}{focus}. The request may concern any slide of this deck. "
                "list_slides gives the outline; open only the slides the request needs, do not scan the project.")
    if not slide:
        return ("[SlideMage scope: THIS SLIDE] No slide is in focus, so there is nothing to work on yet. "
                "Ask the user to select a slide in SlideMage, or to switch the scope to Deck.")
    unsaved = (" It has unsaved edits in the editor: read it with read_buffer, not Read." if data.get("dirty")
               else "")
    return (f"[SlideMage scope: THIS SLIDE] The request is about {slide} ({where}).{unsaved} "
            "Use only this file: do not read, search or edit other slides, decks or folders, and do not explore "
            "the project (no Glob, Grep, ls, find or other shell exploration); the file's own text and read_guide "
            "are enough. Go straight to it: you need no get_focus. If the request needs something outside this "
            "slide, say so in one sentence and let the user switch the scope to Deck.")


def edit_problem(data: dict | None, root: Path, path: Path) -> str | None:
    """Why an edit of `path` is refused in the scope Slide, or None."""
    if not data or data.get("scope") != SLIDE or path.suffix != ".tex":
        return None
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return None
    if relative.split("/", 1)[0] not in GUARDED_FOLDERS or relative == data.get("slide"):
        return None
    focused = data.get("slide")
    return (f"SlideMage scope is Slide ({focused or 'no slide in focus'}): {relative} is outside it. "
            "Leave it alone, or ask the user to switch the scope to Deck.")
