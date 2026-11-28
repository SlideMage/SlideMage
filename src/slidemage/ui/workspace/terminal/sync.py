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

The timer's scans run on a thread of their own (2026-11-16): on a synced project folder one scan took 1 to 4 s, and
on the GUI thread, once a second, that froze the window again and again while the terminal ran. The result comes
back to the GUI thread, which compares and acts as before. `start()` (the baseline) and `poll()` (the last look on
`stop()`, and callers that want the answer now) still scan on the spot.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ....ai import project_watch
from ...background import run_in_background
from ...polling import PollTimer
from ..source_file import SAME

POLL_MS = 1000
STRUCTURE_FOLDERS = ("slides", "decks", "blocks")


def _text(path: Path) -> str | None:
    try:
        with open(path, encoding="utf-8", newline="") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


class ExternalEditWatch(QObject):
    """The generic watch: polls the project's text files (ai/project_watch.py) and hands each change to
    `on_change(changes)`. This is the host service (Host.watch_external_edits, plugin_api.EditWatch); DiskSync below
    is what the window does with the changes of the Claude Code session."""

    _scanned = Signal(int, object)      # the generation a background scan was started in, its Scan

    def __init__(self, root: Path, on_change: Callable[[project_watch.Changes], None],
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.root, self._on_change = root, on_change
        self._known: project_watch.Scan = {}
        self._generation = 0            # bumped by every scan on the spot: an older background scan is dropped
        self._scanning = False          # a background scan is out: the timer starts no second one
        self._timer = PollTimer(self, POLL_MS)      # paused while minimized: the next look is at once on return
        self._timer.timeout.connect(self._poll_in_background)
        self._scanned.connect(self._on_scanned)

    def start(self) -> None:
        if not self._timer.isActive():
            self._generation += 1
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
        """Scan now, on this thread, and hand over what changed."""
        self._generation += 1
        self._take(project_watch.scan(self.root))

    def _take(self, now: project_watch.Scan) -> None:
        changes = project_watch.diff(self._known, now)
        if changes:
            self._on_change(changes)
        self._known = now           # only once the caller took the changes in: a failure is tried again

    def _poll_in_background(self) -> None:
        if self._scanning:
            return                  # the last scan is still running (a slow drive): skip this tick
        self._scanning = True
        generation, root = self._generation, self.root

        def done(now, _error) -> None:
            self._scanned.emit(generation, now)     # an error: now is None, the next tick tries again

        run_in_background(lambda: project_watch.scan(root), done, parent=self)

    def _on_scanned(self, generation: int, now) -> None:
        self._scanning = False
        if now is None or generation != self._generation or not self._timer.isActive():
            return                  # failed, or a scan on the spot (or stop) came in between
        self._take(now)

    def __enter__(self) -> ExternalEditWatch:
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()


class DiskSync(ExternalEditWatch):
    def __init__(self, window, root: Path, parent: QObject | None = None) -> None:
        super().__init__(root, lambda changes: self._apply(changes), parent)
        self.window = window

    def _apply(self, changes: project_watch.Changes) -> None:
        window = self.window
        decks = {deck.path: deck for deck in window.decks}
        structural = any(p.relative_to(self.root).parts[0] in STRUCTURE_FOLDERS
                         for p in (*changes.added, *changes.removed) if p.suffix == ".tex")
        review_changed = window.project.ai_review_path in (*changes.added, *changes.modified, *changes.removed)
        if review_changed:
            window.refresh_ai_review()
        edited_decks, refresh = [], False
        for path in (*changes.modified, *changes.added, *changes.removed):
            if path == window.project.ai_review_path:
                continue
            if path.parent == window.project.blocks_dir:
                window.centre.disk_changed(path)
                edited_decks.append(path)
                continue
            outcome = window.centre.disk_changed(path)
            if outcome == SAME:
                continue
            if outcome is None:
                window.centre.file_written(path)    # the Preview renders the shown slide, as after a chat edit
            deck = decks.get(path)
            if deck is None:
                refresh = True
            elif _text(path) != deck.text:
                edited_decks.append(deck.path)
        for deck in edited_decks:
            window.after_deck_edit(deck, f"Claude Code changed {deck.name}")
        if edited_decks:
            return                              # after_deck_edit rescans and redraws everything
        if structural:
            window.reload_decks()
        elif refresh:
            window.slide_list.rebuild()
            window.side_panels.refresh()
