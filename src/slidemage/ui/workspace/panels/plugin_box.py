# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""A plugin's compact sidebar box as a side panel: an entry of the picker under "Plugins", offered only while the
plugin's `when(deck)` says so for the open deck, showing the widget its `build(deck)` returns.

The box is rebuilt when the open deck, or its text, differs from what it was built for, when it is chosen again,
when the plugin says its data changed (refresh_sidebar_box), and when the calendar date changes (the side panels
call invalidate()); a failing when() or build() is logged and counts as "not offered" / shows an error line, never
a crash.
"""
from __future__ import annotations

import logging

from ....plugins.host import deck_snapshot
from ...kit import kit_qss as q
from ...kit.widgets import clear_layout
from .base import SidePanel, text

log = logging.getLogger(__name__)


def box_key(plugin_id: str, key: str) -> str:
    """The side panels' key of a plugin's box."""
    return f"plugin:{plugin_id}:{key}"


class PluginBoxPanel(SidePanel):
    plugin = True

    def __init__(self, app, state, actions, plugin, box) -> None:
        self.key = box_key(plugin.id, box.key)
        self.title = box.title
        self.plugin_id, self.plugin_name, self.box = plugin.id, plugin.manifest.name, box
        super().__init__(app, state, actions)
        self._built_for: tuple | None = None

    def _snapshot(self):
        deck = self.state.deck
        return deck_snapshot(deck) if deck is not None else None

    def offered(self) -> bool:
        snapshot = self._snapshot()
        if snapshot is None:
            return False
        try:
            return bool(self.box.when(snapshot))
        except Exception:
            log.exception("when() of the box %r of %s raised; not offered", self.box.key, self.plugin_id)
            return False

    def invalidate(self) -> None:
        """Build again at the next refresh (the box was chosen again, its data changed, or the date did)."""
        self._built_for = None

    def refresh(self) -> None:
        deck = self.state.deck
        built_for = (deck.path, deck.text) if deck is not None else None
        if built_for is not None and built_for == self._built_for:
            return
        clear_layout(self.body)
        self._built_for = built_for
        snapshot = self._snapshot()
        if snapshot is None:
            return
        try:
            self.body.addWidget(self.box.build(snapshot))
        except Exception as exc:
            log.exception("box %r of %s failed", self.box.key, self.plugin_id)
            self.body.addWidget(text(f"{self.plugin_name} could not build this box: {exc}", q.DETAILS_LABEL))
