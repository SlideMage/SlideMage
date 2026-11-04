# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The workspace's shared state (UI_REDESIGN_PLAN.md, step 3).

One object that the top bar, the slide list, the centre column and the side
panels all read and write, instead of reaching into each other: the current
deck, the focused slide, the view being edited (Instructor / During-course /
After-course), the language on show (one of the project's), the selected slides, what the centre shows
(Preview / Split / Source / Details) and whether any source has unsaved edits.
The AI route (the assistant's Local | Cloud switch and the cloud connection) lives in ai/ai_profile.py; the state
only mirrors it for the Qt side and tells everything that shows a model, a picker or a conversation when the route
changed. Each field has a setter and one signal; a setter that would not change the
value does nothing, so listeners can connect without guarding against loops.

The view and the centre's mode are remembered per deck in the project's app
settings (app_settings.py, the same JSON file as the other UI preferences),
so reopening a deck brings back the view you left it in. The language follows the deck (content languages plan,
2.3): opening a deck, or a change of its \\decklanguage, sets it to the deck's language, and picking another one is
a short look at the translations, kept until the next deck switch.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal

from ... import app_settings, deck_outline, deck_settings, languages
from ...ai import ai_profile
from ...deck_editor import VIEW_INSTRUCTOR, VIEWS
from ...deck_scan import Deck
from ...project import ProjectContext

MODES = ("preview", "split", "source", "details")

SETTLE_MS = 150   # the focus must rest this long before the side panels and the assistant's offers are worked out afresh

# {deck path: {"view": ..., "mode": ...}} in app_settings.json; a "language" from an older version is dropped.
SETTINGS_KEY = "workspace_decks"


class WorkspaceState(QObject):
    deck_changed = Signal(object)            # Deck | None
    focused_slide_changed = Signal(object)   # bare slide id | None
    view_changed = Signal(str)
    language_changed = Signal(str)
    languages_changed = Signal(object)       # tuple of the switch's codes, as languages()
    selection_changed = Signal(object)       # tuple of bare slide ids
    mode_changed = Signal(str)
    dirty_changed = Signal(bool)
    lint_errors_changed = Signal(int)
    ai_route_changed = Signal(str)           # the route of new AI work: a route id (ai_profile.OLLAMA, CLAUDE_CODE, ANTHROPIC_API or a plugin's)

    def __init__(self, project: ProjectContext, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.deck: Optional[Deck] = None
        self.focused_slide: Optional[str] = None
        self.focused_occurrence: tuple | None = None
        # The deck as the slide list last resolved it (deck_outline.Outline), for the centre, the side panels and the
        # Preview to read instead of resolving it again; the list sets it, and a write to a slide file drops it.
        self.outline: Optional[deck_outline.Outline] = None
        self.view = VIEW_INSTRUCTOR
        self.language = self.languages()[0]
        self.selection: tuple[str, ...] = ()
        self.mode = MODES[0]
        # set_mode() remembers the mode for the deck only while this says True: CentreColumn narrows it to "the
        # slide tab is on show" (centre-tabs.md, step 3), so a file tab's own mode (D2), shown through `mode` too,
        # is never remembered as the deck's.
        self.remember_mode: Callable[[], bool] = lambda: True
        self.dirty = False   # some source or side panel has unsaved edits
        self._dirty_by: dict[str, bool] = {}
        self.lint_errors = 0   # errors the static check finds in the source being edited

    def set_deck(self, deck: Optional[Deck]) -> bool:
        """Switch decks: the view and language come back from the settings
        and the focus and selection start empty. A fresh scan of the deck
        already open (same file) only replaces the stored object, so that
        readers see the new text; it is not a switch and emits nothing.
        Returns whether it was a switch."""
        if deck is not None and self.deck is not None and deck.path == self.deck.path:
            before = self._deck_language(self.deck)
            self.deck = deck
            if self._deck_language(deck) != before:     # its settings changed its language: the switch follows
                self.refresh_languages()
                self._show_language(self._deck_language(deck))
            return False
        before = (self.focused_slide, self.selection, self.view, self.language, self.mode)
        shown = self.languages()
        self.deck = deck
        remembered = self._remembered(deck)
        self._forget_language(deck, remembered)
        self.focused_slide, self.selection = None, ()
        self.focused_occurrence = None
        self.view = remembered["view"] if remembered.get("view") in VIEWS else VIEW_INSTRUCTOR
        self.language = self._deck_language(deck) or self.languages()[0]
        self.mode = remembered["mode"] if remembered.get("mode") in MODES else MODES[0]
        self.deck_changed.emit(deck)
        if self.languages() != shown:
            self.languages_changed.emit(self.languages())
        if before[0] is not None:
            self.focused_slide_changed.emit(None)
        if before[1]:
            self.selection_changed.emit(())
        if before[2] != self.view:
            self.view_changed.emit(self.view)
        if before[3] != self.language:
            self.language_changed.emit(self.language)
        if before[4] != self.mode:
            self.mode_changed.emit(self.mode)
        return True

    def languages(self) -> tuple[str, ...]:
        """The codes of the language switch: the project's languages, main first, and the deck's own after them when
        it is not one of them."""
        codes = languages.project_languages(self.project).codes
        own = self._deck_language(self.deck)
        return codes if own is None or own in codes else (*codes, own)

    def refresh_languages(self) -> None:
        """The project's languages changed (Settings → Languages): the switch is built again, and a language no
        longer on it gives way to the deck's."""
        self.languages_changed.emit(self.languages())
        if self.language not in self.languages():
            self._show_language(self._deck_language(self.deck) or self.languages()[0])

    def current_outline(self) -> Optional[deck_outline.Outline]:
        """`outline` when it describes the deck, view and language on show, else None (resolve afresh)."""
        outline, deck = self.outline, self.deck
        return outline if outline is not None and deck is not None and outline.matches(
            self.project, deck, self.language, self.view) else None

    def drop_outline(self) -> None:
        """A slide file was written: the title and translation links in `outline` may be older than the file, so
        readers resolve afresh until the list rebuilds (which the write is followed by)."""
        self.outline = None

    def set_focused_slide(self, slide_id: Optional[str], *, occurrence_key: tuple | None = None) -> None:
        if slide_id != self.focused_slide or occurrence_key != self.focused_occurrence:
            self.focused_slide = slide_id
            self.focused_occurrence = occurrence_key
            self.focused_slide_changed.emit(slide_id)

    def set_view(self, view: str) -> None:
        if view in VIEWS and view != self.view:
            self.view = view
            self._remember("view", view)
            self.view_changed.emit(view)

    def set_language(self, language: str) -> None:
        """A look at the slides in `language`, until the next deck switch (it is not remembered)."""
        if language in self.languages():
            self._show_language(language)

    def _show_language(self, language: str) -> None:
        if language != self.language:
            self.language = language
            self.language_changed.emit(language)

    def set_mode(self, mode: str) -> None:
        if mode in MODES and mode != self.mode:
            self.mode = mode
            if self.remember_mode():
                self._remember("mode", mode)
            self.mode_changed.emit(mode)

    def set_dirty(self, dirty: bool, source: str = "source") -> None:
        """`source` says who has unsaved edits (the Source view, the side panels); the state is
        dirty while any of them is."""
        self._dirty_by[source] = dirty
        dirty = any(self._dirty_by.values())
        if dirty != self.dirty:
            self.dirty = dirty
            self.dirty_changed.emit(dirty)

    def set_lint_errors(self, count: int) -> None:
        if count != self.lint_errors:
            self.lint_errors = count
            self.lint_errors_changed.emit(count)

    @property
    def ai_mode(self) -> str:
        """The switch: ai_profile.LOCAL or ai_profile.CLOUD (the project's setting until the user moved it)."""
        return ai_profile.mode(self.project)

    @property
    def ai_route(self) -> str:
        """Where new AI work goes: the local route, or the cloud connection (a route id)."""
        return ai_profile.active_route(self.project)

    def set_ai_route(self, mode: str, conn: str | None = None) -> bool:
        """Move the switch to `mode` and/or the cloud connection to `conn`; every model label and picker follows
        `ai_route_changed`. The callers that ask the user first are in ai_route.py. Whether the route changed."""
        before = self.ai_route
        if conn is not None:
            ai_profile.set_cloud_conn(self.project, conn)
        ai_profile.set_mode(self.project, mode)
        if self.ai_route == before:
            return False
        self.ai_route_changed.emit(self.ai_route)
        return True

    def selected_or_focused(self) -> tuple[str, ...]:
        """The selected slides, else the focused one."""
        return self.selection or ((self.focused_slide,) if self.focused_slide else ())

    def set_selection(self, slide_ids: tuple[str, ...]) -> None:
        slide_ids = tuple(slide_ids)
        if slide_ids != self.selection:
            self.selection = slide_ids
            self.selection_changed.emit(slide_ids)

    # -- per-deck memory -------------------------------------------------

    def _remembered(self, deck: Optional[Deck]) -> dict:
        if deck is None:
            return {}
        return app_settings.get(self.project, SETTINGS_KEY, {}).get(str(deck.path), {})

    def _deck_language(self, deck: Optional[Deck]) -> Optional[str]:
        """The deck's own \\decklanguage, upper case; the main language for a deck that sets none, None without a
        deck."""
        if deck is None:
            return None
        return deck_settings.read_settings(deck.text).language.upper() or languages.project_languages(self.project).codes[0]

    def _forget_language(self, deck: Optional[Deck], remembered: dict) -> None:
        """Drop the language an older version remembered for the deck: the switch follows the deck now."""
        if deck is None or "language" not in remembered:
            return
        saved = app_settings.get(self.project, SETTINGS_KEY, {})
        saved.get(str(deck.path), {}).pop("language", None)
        app_settings.set(self.project, SETTINGS_KEY, saved)

    def _remember(self, field: str, value: str) -> None:
        if self.deck is None:
            return
        saved = app_settings.get(self.project, SETTINGS_KEY, {})
        saved.setdefault(str(self.deck.path), {})[field] = value
        app_settings.set(self.project, SETTINGS_KEY, saved)
