# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import shutil

from conftest import EXAMPLE, build_window, qapp as qapp  # noqa: F401 -- a fixture
from slidemage import deck_scan
from slidemage.fileio import read_text_exact
from slidemage.deck_scan import TAG_WORK
from slidemage.project import ProjectContext
from slidemage.ui.workspace import deck_actions, menus


class _Sheet:
    def __init__(self, name, groups):
        self.name, self.chosen_groups = name, tuple(groups)

    def exec(self):
        return True


def test_the_copy_opens_and_appears_in_the_switcher(qapp, monkeypatch, tmp_path):
    root = tmp_path / "proj"
    shutil.copytree(EXAMPLE, root)
    ctx = ProjectContext.at(root)
    window = build_window(monkeypatch, ctx)
    source = next(d for d in window.decks if d.name == "slidemage-manual")
    monkeypatch.setattr(deck_actions, "DeckGroupSheet", lambda *a, **k: _Sheet("manual-copy", [TAG_WORK, "research"]))
    deck_actions.on_duplicate_deck(window, source)
    dest = root / "decks" / "manual-copy.tex"
    copy = window.state.deck
    assert copy is not None and copy.path == dest
    assert copy.groups == ("work", "research")
    assert deck_scan.find_decktags(read_text_exact(dest)).group(1) == "work,research"
    menu = menus.build_deck_menu(window.topbar, window.topbar._decks, copy)
    assert [entry[1] for entry in menu._entries if entry[0] == "item"].count(menus.deck_key(copy)) == 2
