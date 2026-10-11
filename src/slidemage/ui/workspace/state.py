"""The workspace's shared state (UI_REDESIGN_PLAN.md, step 3).

One object that the top bar, the slide list, the centre column and the side
panels all read and write, instead of reaching into each other: the current
deck, the focused slide, the view being edited (Instructor / During-course /
After-course), the language being edited (EN / DE), the selected slides, what the centre shows
(Preview / Split / Source / Details) and whether any source has unsaved edits.
Each field has a setter and one signal; a setter that would not change the
value does nothing, so listeners can connect without guarding against loops.

The view, the language and the centre's mode are remembered per deck in the project's app
settings (app_settings.py, the same JSON file as the other UI preferences),
so reopening a deck brings back the view you left it in.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, Signal

from ... import app_settings, deck_settings
from ...deck_scan import Deck
from ...slide_language import LANGUAGES
from ...transcript import VERSION_AFTER, VERSION_DURING, VERSION_INSTRUCTOR

VIEWS = (VERSION_INSTRUCTOR, VERSION_DURING, VERSION_AFTER)
MODES = ("preview", "split", "source", "details")
# "mult" marks a slide that is the same in every language: not a language to edit in.
UI_LANGUAGES = tuple(lang for lang in LANGUAGES if lang != "mult")

# {deck path: {"view": ..., "language": ..., "mode": ...}} in app_settings.json.
SETTINGS_KEY = "workspace_decks"


class WorkspaceState(QObject):
    deck_changed = Signal(object)            # Deck | None
    focused_slide_changed = Signal(object)   # bare slide id | None
    view_changed = Signal(str)
    language_changed = Signal(str)
    footer_timestamp_changed = Signal(bool)
    selection_changed = Signal(object)       # tuple of bare slide ids
    mode_changed = Signal(str)
    dirty_changed = Signal(bool)
    lint_errors_changed = Signal(int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.deck: Optional[Deck] = None
        self.focused_slide: Optional[str] = None
        self.view = VERSION_INSTRUCTOR
        self.language = UI_LANGUAGES[0]
        self.selection: tuple[str, ...] = ()
        self.mode = MODES[0]
        self.dirty = False   # some source or side panel has unsaved edits
        self._dirty_by: dict[str, bool] = {}
        # The Build options' "Include footer timestamp", which the Preview renders with too.
        # Read when a render starts, so it has no signal.
        self.footer_timestamp = False
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
        self.view = remembered["view"] if remembered.get("view") in VIEWS else VERSION_INSTRUCTOR
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

    def set_footer_timestamp(self, enabled: bool) -> None:
        if self.footer_timestamp != enabled:
            self.footer_timestamp = enabled
            self.footer_timestamp_changed.emit(enabled)

    def selected_or_focused(self) -> tuple[str, ...]:
        """The selected slides, else the focused one."""
        return self.selection or ((self.focused_slide,) if self.focused_slide else ())

    def set_selection(self, slide_ids: tuple[str, ...]) -> None:
        slide_ids = tuple(slide_ids)
        if slide_ids != self.selection:
            self.selection = slide_ids
            self.selection_changed.emit(slide_ids)

    # -- per-deck memory -------------------------------------------------

    @staticmethod
    def _remembered(deck: Optional[Deck]) -> dict:
        if deck is None:
            return {}
        return app_settings.get(SETTINGS_KEY, {}).get(str(deck.path), {})

    @staticmethod
    def _deck_language(deck: Optional[Deck]) -> str:
        """The deck's own \\decklanguage while nothing was chosen yet."""
        code = deck_settings.read_settings(deck.text).language.upper() if deck else ""
        return code if code in UI_LANGUAGES else UI_LANGUAGES[0]

    def _remember(self, field: str, value: str) -> None:
        if self.deck is None:
            return
        saved = app_settings.get(SETTINGS_KEY, {})
        saved.setdefault(str(self.deck.path), {})[field] = value
        app_settings.set(SETTINGS_KEY, saved)
