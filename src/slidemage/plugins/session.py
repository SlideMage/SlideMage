# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The plugins loaded in this process.

ui/app.main loads them once, before the window exists; the window, the menus and the sheets read them from here
instead of being handed the list through every constructor. Empty (no plugins) until set_loaded() is called, which
is also how the tests install a fixture plugin.
"""
from __future__ import annotations

from .loader import LoadedPlugin

_loaded: list[LoadedPlugin] = []


def loaded() -> list[LoadedPlugin]:
    """Every discovered plugin with its state; only those in state "loaded" contribute anything."""
    return _loaded


def active() -> list[LoadedPlugin]:
    """The plugins that loaded and so contribute commands, tabs and boxes."""
    return [p for p in _loaded if p.state == "loaded"]


def set_loaded(plugins: list[LoadedPlugin]) -> None:
    global _loaded
    _loaded = list(plugins)
