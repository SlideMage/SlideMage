# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Workspace command registration, shortcuts and menu wiring."""
from __future__ import annotations

import pytest
from PySide6.QtGui import QShortcut
from PySide6.QtWidgets import QWidget

from conftest import command_context, filled_menu, menu_actions, menu_bar_ids
from slidemage.ui.commands import Command, CommandRegistry
from slidemage.ui.workspace.actions import build_registry
from slidemage.ui.workspace.menus import build_compile_menu


def test_commands_are_found_by_id_and_an_id_is_used_once():
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


def test_label_and_metadata_use_context_with_a_shortcut_fallback():
    command = Command("x", lambda ctx: f"Label {ctx}", "G", lambda ctx: None, meta=lambda ctx: f"meta {ctx}",
                      shortcut="Ctrl+L")
    assert command.title(3) == "Label 3" and command.info(3) == "meta 3"
    plain = Command("y", "Y", "G", lambda ctx: None, shortcut="Ctrl+L")
    assert "L" in plain.info(None)


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


PALETTE_ONLY = {"switch_deck", "compile:mode", "compile:slides", "compile:everything", "add_slide", "deck_tags",
                "slide:open_tab", "empty_pdf", "remove_temp", "archive_unused", "update_previews", "sync_links"}


def test_every_command_a_menu_lists_exists_and_every_command_is_in_a_menu_or_the_palette(qapp):
    registry = build_registry()
    listed = set(menu_bar_ids())
    assert [i for i in listed if i not in registry] == []
    assert {c.id for c in registry} - listed == PALETTE_ONLY
    assert [c.id for c in registry if c.shortcut == "Ctrl+,"] == ["deck_settings"]
    context = command_context()
    assert {k for k in (e[1] for e in build_compile_menu(None, context)._entries if e[0] == "item")
            if not k.startswith("submenu:")} <= {c.id for c in registry}


def test_menu_entries_reflect_command_availability_and_shortcuts(qapp):
    context = command_context()   # no deck
    deck = menu_actions(filled_menu(context, "Deck"))
    assert not deck["archive_deck"].isEnabled()
    assert "deck_settings" in deck and "log" not in deck
    assert menu_actions(filled_menu(context, "Present"))["present"].text().endswith("\tF5")
    assert menu_actions(filled_menu(context, "Project"))["housekeeping"].isEnabled()


def test_every_command_has_a_hover_text_and_the_menus_show_it(qapp):
    from slidemage.ui.workspace.command_tips import TIPS

    registry = build_registry()
    assert [c.id for c in registry if not c.tip] == []
    assert [key for key in TIPS if key not in registry] == []        # no text for a command that is gone
    context = command_context()
    menu = filled_menu(context, "Deck")
    assert menu.toolTipsVisible()
    assert menu_actions(menu)["deck_settings"].toolTip() == registry["deck_settings"].tip
    compile_menu = build_compile_menu(None, context)
    assert all(e[9] for e in compile_menu._entries if e[0] == "item" and not e[1].startswith("submenu:"))
