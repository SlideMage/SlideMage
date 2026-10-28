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
from typing import Any

from PySide6.QtCore import Signal

from ..plugin_api import Focus
from ..plugins import session
from ..plugins.host import deck_snapshot
from .commands import Command, CommandRegistry
from .kit.widgets import Field, Page, caption

log = logging.getLogger(__name__)


class PluginPage(Page):
    """A kit Page for a plugin's tab or box: `body` to fill, and `changed` for the plugin to emit when its state
    changed (a deck settings tab's footer button asks `enabled` again then)."""

    changed = Signal()


class WindowHostUi:
    def __init__(self) -> None:
        self._window: weakref.ref | None = None

    def attach(self, window: Any) -> None:
        self._window = weakref.ref(window)

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
