# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Duplicate deck…: the copy is in the deck switcher at once and carries the group chosen for it."""
from __future__ import annotations

import shutil

from conftest import EXAMPLE, build_window, qapp as qapp  # noqa: F401 -- a fixture
from slidemage import deck_scan
from slidemage.fileio import read_text_exact
from slidemage.deck_scan import TAG_WORK
from slidemage.project import ProjectContext
from slidemage.ui.workspace import deck_actions, menus


class _Sheet:
    def __init__(self, name, group):
        self.name, self.group = name, group

    def exec(self):
        return True


def _duplicate(monkeypatch, tmp_path, group):
    root = tmp_path / "proj"
    shutil.copytree(EXAMPLE, root)
    ctx = ProjectContext.at(root)
    window = build_window(monkeypatch, ctx)
    source = next(d for d in window.decks if d.name == "slidemage-manual")
    monkeypatch.setattr(deck_actions, "DeckGroupSheet", lambda *a, **k: _Sheet("manual-copy", group))
    deck_actions.on_duplicate_deck(window, source)
    return window, source, root / "decks" / "manual-copy.tex"


def test_the_copy_is_in_the_deck_switcher_at_once_with_the_group_chosen(qapp, monkeypatch, tmp_path):
    window, source, dest = _duplicate(monkeypatch, tmp_path, TAG_WORK)
    assert dest.is_file()
    copy = next((d for d in window.decks if d.path == dest), None)
    assert copy is not None and copy.group == TAG_WORK
    assert TAG_WORK in deck_scan.find_decktags(read_text_exact(dest)).group(1)
    menu = menus.build_deck_menu(window.topbar, window.topbar._decks, window.state.deck)
    assert menus.deck_key(copy) in [e[1] for e in menu._entries if e[0] == "item"]
