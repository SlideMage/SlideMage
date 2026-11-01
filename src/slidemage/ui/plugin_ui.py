# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The window's side of the plugin host (plugins/host.py HostUi): the widgets a plugin builds with, its messages and
Deck settings, and the plugins' commands as commands of the registry.

Plugins are activated before the window exists, so HOST_UI finds the window lazily: the window registers itself when
it is built. A plugin's code is never trusted to behave: whatever it raises while a command runs or a menu asks
whether it is enabled is logged and shown as a message, never allowed to reach the event loop.
"""
from __future__ import annotations

import logging
import weakref
from collections.abc import Callable
from typing import Any

import shiboken6
from PySide6.QtCore import Signal

from ..plugin_api import Focus
from ..plugins import session
from ..plugins.host import deck_snapshot
from ..plugins.registry import set_box_refresher
from .commands import Command, CommandRegistry
from .kit.widgets import Field, Page, caption
from .workspace.panels.plugin_box import box_key

log = logging.getLogger(__name__)


DIRTY_SHEET_MESSAGE = "Save or discard the changes on the other tabs first."


class PluginPage(Page):
    """A kit Page for a plugin's tab or box: `body` to fill, and `changed` for the plugin to emit when its state
    changed (a deck settings tab's footer button asks `enabled` again then)."""

    changed = Signal()


class WindowHostUi:
    def __init__(self) -> None:
        self._window: weakref.ref | None = None
        self._sheets: list[weakref.ref] = []        # the open Deck settings sheets
        self._plugin_windows: list[weakref.ref] = []        # what plugins made with Host.Window
        self._theme_listeners: list[Callable[[bool], None]] = []    # plugins subscribe before the window exists

    def attach(self, window: Any) -> None:
        self._window = weakref.ref(window)
        set_box_refresher(self.refresh_sidebar_box)
        window.theme.add_listener(lambda: self._theme_changed(window.theme.dark))

    def add_theme_listener(self, listener: Callable[[bool], None]) -> Callable[[], None]:
        self._theme_listeners.append(listener)
        return lambda: self._theme_listeners.remove(listener) if listener in self._theme_listeners else None

    def _theme_changed(self, dark: bool) -> None:
        for listener in list(self._theme_listeners):
            listener(dark)

    def dark(self) -> bool | None:
        """Whether the window is dark; None before there is a window."""
        window = self.window
        return window.theme.dark if window is not None else None

    def track_plugin_window(self, window: Any) -> None:
        self._plugin_windows = [r for r in self._plugin_windows if r() is not None] + [weakref.ref(window)]

    def close_plugin_windows(self) -> bool:
        """Ask the open plugin windows to close, before SlideMage does: a window left open would keep the process
        running after the main window closed. False when one refuses, for its unsaved work; the others are closed."""
        closed = True
        for window in (r() for r in self._plugin_windows):
            if window is None or not shiboken6.isValid(window) or not window.isVisible():
                continue
            try:
                closed = window.close() and closed
            except Exception as exc:        # a plugin's bug must not keep SlideMage open, nor reach the event loop
                say_error(f"Closing the window {window.windowTitle()!r} failed", exc)
                window.hide()
        return closed

    def refresh_sidebar_box(self, plugin_id: str, key: str) -> None:
        """Build the box `key` of the plugin again (Host.refresh_sidebar_box); nothing without a window."""
        window = self.window
        panels = getattr(window, "side_panels", None) if window is not None else None
        if panels is not None:
            panels.refresh_box(box_key(plugin_id, key))

    @property
    def window(self) -> Any:
        return self._window() if self._window is not None else None

    # -- HostUi

    def Page(self) -> PluginPage:
        return PluginPage()

    def Field(self, label: str, widget: Any) -> Field:
        return Field(label, widget)

    def caption(self, text: str, tone: str = "") -> Any:
        return caption(text, tone)

    def show_message(self, text: str, error: bool = False) -> None:
        window = self.window
        if window is None:
            log.log(logging.ERROR if error else logging.INFO, "%s", text)
        else:
            window.toast.show_message(text, error=error, timeout_ms=6000 if error else None)

    def try_start_route_task(self, route_id: str, label: str, owner: object) -> bool:
        window = self.window
        if window is None:
            raise RuntimeError("no window")
        return window.try_start_route_task(route_id, label, owner)

    def end_route_task(self, route_id: str, owner: object) -> None:
        window = self.window
        if window is not None:
            window.end_route_task(route_id, owner)

    def model_choices_changed(self, route_id: str) -> None:
        window = self.window
        if window is not None:
            window.model_choices_changed.emit(route_id)

    def terminal_tokens(self) -> Any:
        """The design tokens the embedded terminal is coloured with."""
        window = self.window
        if window is None:
            raise RuntimeError("no window")
        return window.theme.tokens

    def focus(self) -> Focus:
        """What the user is looking at: the deck, the slide the editor shows, and the assistant's scope."""
        window = self.window
        if window is None:
            return Focus(None, None, "slide")
        deck = window.state.deck
        slide = window.centre.path
        scope = "deck" if window.assistant.scope.current() == "deck" else "slide"
        return Focus(deck.path if deck is not None and not deck.is_test_deck else None,
                     slide if slide is not None and slide.parent.name == "slides" else None, scope)

    # -- plugin deck edits and the Deck settings sheet: while the sheet has unsaved core changes a plugin may not
    # write the deck (plugin_api.EditRefusedError); an edit made while it is clean is taken over by the sheet.

    def register_sheet(self, sheet: Any) -> None:
        self._sheets = [r for r in self._sheets if r() is not None] + [weakref.ref(sheet)]

    def unregister_sheet(self, sheet: Any) -> None:
        self._sheets = [r for r in self._sheets if r() not in (None, sheet)]

    def _sheets_of(self, path: Any) -> list[Any]:
        return [s for s in (r() for r in self._sheets) if s is not None and s.deck.path == path]

    def deck_edit_blocker(self, path: Any) -> str | None:
        return DIRTY_SHEET_MESSAGE if any(s.dirty() for s in self._sheets_of(path)) else None

    def after_deck_edit(self, path: Any, summary: str, previous_text: str) -> None:
        """What a core deck edit runs (window.after_deck_edit: rescan, views, headers, Undo with previous_text), then
        the open sheets of the deck read the rescanned deck."""
        window = self.window
        if window is None:
            return
        window.after_deck_edit(path, summary, previous_text=previous_text)
        core = next((d for d in window.decks if d.path == path), None)
        if core is not None:
            for sheet in self._sheets_of(path):
                sheet.refresh_from_deck(core)

    def open_slide(self, path: Any) -> None:
        """The slide file at `path` in the Source view, a frozen version too (the window's open_slide_editor)."""
        window = self.window
        if window is None:
            raise RuntimeError("no window")
        window.open_slide_editor(path)

    def open_deck_settings(self, deck: Any, tab: str | None = None) -> None:
        """The Deck settings sheet of the deck with `deck`'s file, on the tab with that title (else the first)."""
        from .workspace import deck_actions

        window = self.window
        if window is None:
            raise RuntimeError("no window")
        core = next((d for d in window.decks if d.path == deck.path), None)
        if core is None:
            raise ValueError(f"{deck.name} is not a deck of this project")
        deck_actions.on_deck_settings(window, core, tab if tab is not None else 0)


HOST_UI = WindowHostUi()


def say_error(what: str, exc: BaseException) -> None:
    """Log that plugin code failed and show it."""
    log.error("%s", what, exc_info=exc)
    HOST_UI.show_message(f"{what}: {exc}", error=True)


def _snapshot(window: Any):
    deck = window.state.deck
    return deck_snapshot(deck) if deck is not None else None


def _command(plugin, entry) -> Command:
    def run(window: Any) -> None:
        try:
            entry.run(_snapshot(window))
        except Exception as exc:        # a plugin's bug is a message, not a crash
            say_error(f"{plugin.manifest.name}: {entry.title} failed", exc)

    def enabled(window: Any) -> bool:
        try:
            return bool(entry.enabled(_snapshot(window)))
        except Exception:
            log.exception("enabled() of %s raised; counted as False", entry.id)
            return False

    return Command(entry.id, entry.title, plugin.manifest.name, run, icon="extension", enabled=enabled)


def add_commands(registry: CommandRegistry) -> None:
    """Every loaded plugin's commands, in the palette under the plugin's name."""
    for plugin in session.active():
        for entry in plugin.contributions.commands:
            try:
                registry.add(_command(plugin, entry))
            except ValueError:
                log.exception("command %s of %s not added", entry.id, plugin.id)
