# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Rewrite selection and Proofread selection (Claude Code reviews plan, step R1): the menu items the Source editor's
context menu shows, and the menu and the form that ask what a rewrite should do. The choices are the labels of
ai_tasks.REWRITE_PRESETS and CUSTOM, which asks for the instruction in a popover (insert_popovers.py). What a choice
starts is the assistant's (`AssistantArea.rewrite_selection`, `proofread_selection`)."""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

from ...ai.tasks import REWRITE_PRESETS
from ..kit.widgets import PopoverMenu

CUSTOM = "Custom…"
REWRITE_CHOICES = (*REWRITE_PRESETS, CUSTOM)
# The hover texts of the rewrite choices.
REWRITE_TIPS = {**REWRITE_PRESETS, CUSTOM: "Tell the AI how to rewrite the selected text."}
REWRITE, PROOFREAD = "rewrite:", "proofread"      # the prefix of a rewrite item's key, and the proofread item's


def add_menu_items(menu: PopoverMenu, enabled: bool) -> None:
    """The rewrite choices under a "Rewrite selection" heading, then Proofread selection."""
    menu.add_header("Rewrite selection")
    for choice in REWRITE_CHOICES:
        menu.add_item(REWRITE + choice, choice, enabled=enabled, tip=REWRITE_TIPS.get(choice, ""))
    menu.add_item(PROOFREAD, "Proofread selection", enabled=enabled,
                  tip="Let the AI correct spelling and grammar in the selected text")


def rewrite_menu(parent: QWidget) -> PopoverMenu:
    """The choices of a rewrite alone; `triggered` gives the choice."""
    menu = PopoverMenu(parent, min_width=180)
    for choice in REWRITE_CHOICES:
        menu.add_item(choice, choice, tip=REWRITE_TIPS.get(choice, ""))
    return menu
