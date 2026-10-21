# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The action registry (ui/commands.py), the commands of the workspace window (actions.py) and
the menus built from them."""
from __future__ import annotations

import pytest
from PySide6.QtGui import QShortcut
from PySide6.QtWidgets import QWidget

from conftest import command_context
from slidemage.ui.commands import Command, CommandRegistry
from slidemage.ui.workspace.actions import build_registry
from slidemage.ui.workspace.menus import MORE_COLUMNS, MORE_FOOTER, build_compile_menu, build_more_menu


# -- the registry ---------------------------------------------------------------------

def test_commands_are_found_by_id_and_an_id_is_used_once(ctx):
    registry = CommandRegistry()
    registry.add(Command("a", "A", "First", lambda ctx: None))
    registry.add(Command("b", "B", "Second", lambda ctx: None))
    registry.add(Command("c", "C", "First", lambda ctx: None))
    assert "a" in registry and "z" not in registry and registry["b"].label == "B"
    with pytest.raises(ValueError):
        registry.add(Command("a", "again", "First", lambda ctx: None))


def test_a_command_runs_only_while_it_is_visible_and_enabled():
    ran = []
    registry = CommandRegistry()
    registry.add(Command("go", "Go", "G", ran.append, enabled=lambda ctx: ctx == "on", visible=lambda ctx: ctx != "hidden"))
    assert not registry.run("go", "off") and not registry.run("go", "hidden")
    assert registry.run("go", "on") and ran == ["on"]


def test_label_and_metadata_may_depend_on_the_context_and_the_shortcut_is_the_fallback_meta(ctx, qapp):
    command = Command("x", lambda ctx: f"Label {ctx}", "G", lambda ctx: None, meta=lambda ctx: f"meta {ctx}",
                      shortcut="Ctrl+L")
    assert command.title(3) == "Label 3" and command.info(3) == "meta 3"
    plain = Command("y", "Y", "G", lambda ctx: None, shortcut="Ctrl+L")
    assert "L" in plain.info(None) and Command("z", "Z", "G", lambda ctx: None).info(None) == ""


def test_shortcuts_are_bound_to_the_window_and_run_the_command(qapp):
    ran = []
    registry = CommandRegistry()
    registry.add(Command("k", "K", "G", ran.append, shortcut="Ctrl+K"))
    registry.add(Command("plain", "Plain", "G", ran.append))
    window = QWidget()
    registry.bind_shortcuts(window)
    shortcuts = window.findChildren(QShortcut)
    assert [s.key().toString() for s in shortcuts] == ["Ctrl+K"]
    shortcuts[0].activated.emit()
    assert ran == [window]
    window.deleteLater()


# -- what the old menu bar had -----------------------------------------------------------

# The old menu bar's entries (before step 3) and the command each became.
OLD_MENU_BAR = {
    "Open Project…": "open_project", "Settings…": "settings", "Exit SlideMage": "exit",                 # System
    "Create deck snapshot…": "create_snapshot", "Import PPTX/ODP…": "import_presentation",                   # Decks
    "Archived decks": "archived_decks", "Images": "images", "Edit .bib": "edit_bib",                          # Tabs
    "Edit test-slides.tex": "edit_test_slides",
    "Empty pdf folder": "empty_pdf", "Remove temp files": "remove_temp",                                      # Housekeeping
    "Archive unused slides and media files": "archive_unused", "Update slide previews": "update_previews",
    "Reestablish broken translation links": "sync_links",
    "Version history…": "version_history", "Check for updates…": "check_updates",                             # Info
    "Project compatibility…": "project_compat",
}
OLD_DECK_ROW = {
    "Open latest PDF": "open_pdf", "Deck settings…": "deck_settings", "Edit deck source": "deck_source",
    "Duplicate deck…": "duplicate_deck", "Tags…": "deck_tags", "Export PPTX…": "export_pptx",
    "Archive deck…": "archive_deck", "Refresh decks": "refresh_decks", "Admin slides…": "admin_slides",
}


def test_every_action_of_the_former_menu_bar_and_deck_row_is_in_the_registry():
    registry = build_registry()
    missing = [label for label, command_id in {**OLD_MENU_BAR, **OLD_DECK_ROW}.items() if command_id not in registry]
    assert missing == []
    context = command_context()
    for command in registry:
        if not callable(command.label):
            assert command.title(context)


def test_every_command_a_menu_lists_exists_and_every_command_is_in_a_menu_or_the_palette(qapp):
    registry = build_registry()
    listed = {i for sections in MORE_COLUMNS for _header, ids in sections for i in ids} | set(MORE_FOOTER)
    assert [i for i in listed if i not in registry] == []
    context = command_context()
    assert {k for menu in (build_more_menu(None, context), build_compile_menu(None, context))
            for k in (e[1] for e in menu._entries if e[0] == "item")} <= {c.id for c in registry}


# -- the menus come from the registry ------------------------------------------------------

def test_a_menu_entry_shows_the_commands_label_tone_shortcut_and_availability(qapp):
    context = command_context()   # no deck
    entries = {e[1]: e for e in build_more_menu(None, context)._entries if e[0] == "item"}
    archive = entries["archive_deck"]
    assert (archive[2], archive[5], archive[6]) == ("Archive deck…", "danger", False)
    assert entries["present"][3] == "F5" and "deck_settings" in entries and "log" not in entries
    assert entries["housekeeping"][6]


def test_deck_settings_has_the_preferences_shortcut_and_no_other_command_uses_it(qapp):
    registry = build_registry()
    assert registry["deck_settings"].shortcut == "Ctrl+,"
    assert [c.id for c in registry if c.shortcut == "Ctrl+,"] == ["deck_settings"]

