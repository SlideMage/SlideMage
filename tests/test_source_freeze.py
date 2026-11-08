# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Editing a deck's source: deleting the line of the focused slide, and the autosave that follows."""
from __future__ import annotations

import shutil
import sys

from slidemage.project import ProjectContext

from conftest import EXAMPLE, build_window


def test_deleting_the_include_line_of_the_focused_slide_and_autosaving_keeps_the_source_open(qapp, monkeypatch, tmp_path):
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *args: errors.append(args))
    root = tmp_path / "example"
    shutil.copytree(EXAMPLE, root)
    window = build_window(monkeypatch, ProjectContext.at(root))
    window.reload_decks()
    deck = next(d for d in window.decks if d.name == "slidemage-manual")
    window.state.set_deck(deck)
    window.reload_decks()
    window.state.set_mode("source")
    item = next(i for i in window.slide_list.tree.slide_items() if window.slide_list.tree.data_of(i).call.id == "1ym")
    window.slide_list.tree.setCurrentItem(item)
    qapp.processEvents()
    assert window.state.focused_slide == "1ym"
    window.open_deck_source_editor(window.state.deck)
    source = window.centre.source.current
    assert source.path == deck.path
    text = source.editor.text()
    line = "\t\\slide{1ym-EN-Framework-Project-App}\n"
    assert line in text
    source.editor.replace_all_text(text.replace(line, ""))
    assert source.dirty
    assert source.write_now()
    qapp.processEvents()
    assert not errors, errors
    assert window.centre.source.file_for(deck.path) is source
    assert window.centre.source.current is source


def test_a_deck_source_waits_10_s_for_its_autosave_and_other_files_keep_the_short_delay(qapp, monkeypatch, tmp_path):
    from slidemage.ui.workspace import source_file

    assert source_file.DECK_AUTOSAVE_DELAY_MS == 10_000
    root = tmp_path / "example"
    shutil.copytree(EXAMPLE, root)
    window = build_window(monkeypatch, ProjectContext.at(root))
    window.reload_decks()
    deck = next(d for d in window.decks if d.name == "slidemage-manual")
    window.open_deck_source_editor(deck)
    source = window.centre.source.current
    source.editor.insertPlainText("% a\n")
    assert source._autosave_timer.isActive() and source._autosave_timer.interval() == 10_000
    window._on_edit_bib()
    bib = window.centre.source.current
    assert bib.path == window.project.bibliography_path
    bib.editor.insertPlainText("% a\n")
    assert bib._autosave_timer.interval() == source_file.AUTOSAVE_DELAY_MS
    window.centre.close_tab(window.centre.tabs.tab_for(deck.path))      # closing the tab writes it at once
    assert "% a\n" in deck.path.read_text(encoding="utf-8")
