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

from ..plugins import session
from ..plugins.host import deck_snapshot
from ..plugins.registry import set_box_refresher
from .commands import Command, CommandRegistry
from .kit.widgets import Field, Page, caption
from .workspace.panels.plugin_box import box_key

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
        set_box_refresher(self.refresh_sidebar_box)

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

    def after_deck_edit(self, path: Any, summary: str, previous_text: str) -> None:
        """What a core deck edit runs (window.after_deck_edit: rescan, views, headers, Undo with previous_text)."""
        window = self.window
        if window is not None:
            window.after_deck_edit(path, summary, previous_text=previous_text)

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
