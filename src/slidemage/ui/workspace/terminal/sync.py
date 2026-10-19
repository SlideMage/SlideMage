# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Keeping SlideMage's views in step with what Claude Code does to the project's files (UI redesign step
10c). While the terminal runs, a timer compares a cheap scan of the project's text files (ai/project_watch.py)
with the last one, and for each change decides what the window shows:

* a file open in the Source view: a clean buffer is reloaded; one with unsaved edits is left alone and the
  editor shows the conflict notice (Reload from disk / Keep my edits) -- source_file.py;
* a deck's .tex: the usual deck-edit sequence (header sync, rescan, slide list), unless the deck on record
  already is what is on disk (an edit SlideMage made itself);
* slides added or removed: a rescan; any other changed file: the slide list and panels are refreshed
  (lint dots, previews, versions).
A file SlideMage saved itself shows as unchanged against its buffer, so the poll does not act on it.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QTimer

from ....ai import project_watch
from ..source_file import SAME

POLL_MS = 1000
STRUCTURE_FOLDERS = ("slides", "decks")


def _text(path: Path) -> str | None:
    try:
        with open(path, encoding="utf-8", newline="") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


class DiskSync(QObject):
    def __init__(self, window, root: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.window, self.root = window, root
        self._known: project_watch.Scan = {}
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self.poll)

    def start(self) -> None:
        self._known = project_watch.scan(self.root)
        self._timer.start()

    def stop(self, *, last_look: bool = True) -> None:
        """Stop watching. While it ran, one last look at what changed since the last poll (the process may
        have written a file in its final second), unless the window is closing (`last_look` False)."""
        if self._timer.isActive():
            if last_look:
                self.poll()
            self._timer.stop()

    def poll(self) -> None:
        now = project_watch.scan(self.root)
        changes = project_watch.diff(self._known, now)
        if changes:
            self._apply(changes)
        self._known = now           # only once the window took the changes in: a failure is tried again

    def _apply(self, changes: project_watch.Changes) -> None:
        window = self.window
        decks = {deck.path: deck for deck in window.decks}
        structural = any(p.relative_to(self.root).parts[0] in STRUCTURE_FOLDERS
                         for p in (*changes.added, *changes.removed) if p.suffix == ".tex")
        review_changed = window.project.ai_review_path in (*changes.added, *changes.modified, *changes.removed)
        if review_changed:
            window.refresh_ai_review()
        edited_decks, refresh, shown = [], False, False
        for path in (*changes.modified, *changes.added):
            if path == window.project.ai_review_path:
                continue
            outcome = window.centre.disk_changed(path)
            if outcome == SAME:
                continue
            if outcome is None and path == window.centre.path:
                shown = True                    # the Preview shows this slide and must say it is older now
            deck = decks.get(path)
            if deck is None:
                refresh = True
            elif _text(path) != deck.text:
                edited_decks.append(deck)
        for deck in edited_decks:
            window.after_deck_edit(deck.path, f"Claude Code changed {deck.path.name}")
        if edited_decks:
            return                              # after_deck_edit rescans and redraws everything
        if structural:
            window.reload_decks()
        elif refresh:
            window.slide_list.rebuild()
            window.side_panels.refresh()
        if shown:
            window.centre.refresh()
