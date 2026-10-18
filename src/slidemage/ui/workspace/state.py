"""The workspace's shared state (UI_REDESIGN_PLAN.md, step 3).

One object that the top bar, the slide list, the centre column and the side
panels all read and write, instead of reaching into each other: the current
deck, the focused slide, the view being edited (Instructor / During-course /
After-course), the language being edited (EN / DE), the selected slides, what the centre shows
(Preview / Split / Source / Details) and whether any source has unsaved edits.
The AI route (the top bar's Local | Cloud switch and the cloud connection) lives in ai/ai_profile.py; the state
only mirrors it for the Qt side and tells everything that shows a model, a picker or a conversation when the route
changed. Each field has a setter and one signal; a setter that would not change the
value does nothing, so listeners can connect without guarding against loops.

The view, the language and the centre's mode are remembered per deck in the project's app
settings (app_settings.py, the same JSON file as the other UI preferences),
so reopening a deck brings back the view you left it in.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, Signal

from ... import app_settings, deck_settings
from ...ai import ai_profile
from ...deck_editor import VIEW_INSTRUCTOR, VIEWS
from ...deck_scan import Deck
from ...project import ProjectContext
from ...slide_language import TRANSLATION_LANGUAGES

MODES = ("preview", "split", "source", "details")
# "mult" marks a slide that is the same in every language: not a language to edit in.
UI_LANGUAGES = TRANSLATION_LANGUAGES

# {deck path: {"view": ..., "language": ..., "mode": ...}} in app_settings.json.
SETTINGS_KEY = "workspace_decks"


class WorkspaceState(QObject):
    deck_changed = Signal(object)            # Deck | None
    focused_slide_changed = Signal(object)   # bare slide id | None
    view_changed = Signal(str)
    language_changed = Signal(str)
    selection_changed = Signal(object)       # tuple of bare slide ids
    mode_changed = Signal(str)
    dirty_changed = Signal(bool)
    lint_errors_changed = Signal(int)
    ai_route_changed = Signal(str)           # the route of new AI work: ai_profile's LOCAL, CLAUDE_CODE or API

    def __init__(self, project: ProjectContext, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.deck: Optional[Deck] = None
        self.focused_slide: Optional[str] = None
        self.view = VIEW_INSTRUCTOR
        self.language = UI_LANGUAGES[0]
        self.selection: tuple[str, ...] = ()
        self.mode = MODES[0]
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
            self.deck = deck
            return False
        before = (self.focused_slide, self.selection, self.view, self.language, self.mode)
        self.deck = deck
        remembered = self._remembered(deck)
        self.focused_slide, self.selection = None, ()
        self.view = remembered["view"] if remembered.get("view") in VIEWS else VIEW_INSTRUCTOR
        self.language = remembered["language"] if remembered.get("language") in UI_LANGUAGES \
            else self._deck_language(deck)
        self.mode = remembered["mode"] if remembered.get("mode") in MODES else MODES[0]
        self.deck_changed.emit(deck)
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

    def set_focused_slide(self, slide_id: Optional[str]) -> None:
        if slide_id != self.focused_slide:
            self.focused_slide = slide_id
            self.focused_slide_changed.emit(slide_id)

    def set_view(self, view: str) -> None:
        if view in VIEWS and view != self.view:
            self.view = view
            self._remember("view", view)
            self.view_changed.emit(view)

    def set_language(self, language: str) -> None:
        if language in UI_LANGUAGES and language != self.language:
            self.language = language
            self._remember("language", language)
            self.language_changed.emit(language)

    def set_mode(self, mode: str) -> None:
        if mode in MODES and mode != self.mode:
            self.mode = mode
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
        """Where new AI work goes: ai_profile.LOCAL, or the cloud connection (CLAUDE_CODE or API)."""
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

    @staticmethod
    def _deck_language(deck: Optional[Deck]) -> str:
        """The deck's own \\decklanguage while nothing was chosen yet."""
        code = deck_settings.read_settings(deck.text).language.upper() if deck else ""
        return code if code in UI_LANGUAGES else UI_LANGUAGES[0]

    def _remember(self, field: str, value: str) -> None:
        if self.deck is None:
            return
        saved = app_settings.get(self.project, SETTINGS_KEY, {})
        saved.setdefault(str(self.deck.path), {})[field] = value
        app_settings.set(self.project, SETTINGS_KEY, saved)
