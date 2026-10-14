"""Rewrite selection and Proofread selection (Claude Code reviews plan, step R1): the menu items the Source editor's
context menu shows, and the menu and the form that ask what a rewrite should do. The choices are the labels of
claude_tasks.REWRITE_PRESETS and CUSTOM, which asks for the instruction in a popover (insert_popovers.py). What a choice
starts is the assistant's (`AssistantArea.rewrite_selection`, `proofread_selection`)."""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

from ...ai.claude_tasks import REWRITE_PRESETS
from ..kit.widgets import PopoverMenu

CUSTOM = "Custom…"
REWRITE_CHOICES = (*REWRITE_PRESETS, CUSTOM)
REWRITE, PROOFREAD = "rewrite:", "proofread"      # the prefix of a rewrite item's key, and the proofread item's


def add_menu_items(menu: PopoverMenu, enabled: bool) -> None:
    """The rewrite choices under a "Rewrite selection" heading, then Proofread selection."""
    menu.add_header("Rewrite selection")
    for choice in REWRITE_CHOICES:
        menu.add_item(REWRITE + choice, choice, enabled=enabled)
    menu.add_item(PROOFREAD, "Proofread selection", enabled=enabled)


def rewrite_menu(parent: QWidget) -> PopoverMenu:
    """The choices of a rewrite alone; `triggered` gives the choice."""
    menu = PopoverMenu(parent, min_width=180)
    for choice in REWRITE_CHOICES:
        menu.add_item(choice, choice)
    return menu
