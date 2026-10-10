"""The top bar's menus: deck switcher, Compile caret menu and the ⋮ menu, and the
helper the slide list's context menus use too.

A menu here is only a layout, which commands in which sections; the labels, the
shortcuts and when an entry is available come from the command registry
(actions.py). The item keys are command ids, which `WorkspaceWindow.run_command`
runs. The old menu bar's System, Decks, Tabs, Housekeeping and Info menus became
the sections of the ⋮ menu, and the deck table's per-deck buttons its "This deck"
section.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Optional

from PySide6.QtWidgets import QWidget

from ...deck_scan import GROUP_ORDER, TAG_COURSE, TAG_MANUAL, TAG_RESEARCH, TAG_TEST, TAG_WORK, Deck
from ...transcript import STUDENT_VERSIONS
from ..commands import Context
from ..kit.widgets import PopoverMenu
from .state import VIEWS

VIEW_LABELS = {
    "instructor": "Instructor",
    "during-course": "During course",
    "after-course": "After course",
}

# Deck switcher sections in GROUP_ORDER; the work deck stands on its own, unlabelled.
GROUP_HEADINGS = {
    TAG_WORK: None,
    TAG_COURSE: "Course decks",
    TAG_RESEARCH: "Research presentations",
    TAG_MANUAL: "SlideMage manual",
    TAG_TEST: "Test decks",
}


def deck_key(deck: Deck) -> str:
    return str(deck.path)


def build_deck_menu(parent: QWidget, decks: list[Deck], current: Optional[Deck]) -> PopoverMenu:
    """Active decks by group, then the archived decks in a footer section."""
    menu = PopoverMenu(parent, min_width=300)
    active = [d for d in decks if not d.archived]
    for tag in GROUP_ORDER:
        group = [d for d in active if d.group == tag]
        if not group:
            continue
        if GROUP_HEADINGS[tag]:
            menu.add_header(GROUP_HEADINGS[tag])
        for deck in group:
            _add_deck(menu, deck, current)
    archived = [d for d in decks if d.archived]
    if archived:
        menu.add_separator()
        menu.add_header(f"Archived decks ({len(archived)})")
        for deck in archived:
            _add_deck(menu, deck, current)
    return menu


def _add_deck(menu: PopoverMenu, deck: Deck, current: Optional[Deck]) -> None:
    is_current = current is not None and deck.path == current.path
    menu.add_item(deck_key(deck), deck.name, icon="check" if is_current else "")


def add_commands(menu: PopoverMenu, ctx: Context, ids: Iterable[str], header: str = "") -> None:
    """The visible commands `ids` as items (disabled where they are not available now),
    under `header` if any of them is shown."""
    commands = [c for c in (ctx.commands[i] for i in ids) if c.visible(ctx)]
    if commands and header:
        menu.add_header(header)
    for command in commands:
        menu.add_item(command.id, command.title(ctx), meta=command.info(ctx), tone=command.tone,
                      enabled=command.enabled(ctx))


def build_compile_menu(parent: QWidget, ctx: Context) -> PopoverMenu:
    """Every PDF the old deck table could ask for (its version, per-chapter and Presenter
    checkboxes), the transcripts of its Create Transcript button, the Pages field, Stop creation
    and the options row of the old toolbar; the pages of the selected slides; and every active
    deck at once. Entries a deck cannot use are disabled instead of hidden."""
    menu = PopoverMenu(parent, min_width=300)
    add_commands(menu, ctx, [f"compile:{view}" for view in VIEWS] + [
        "compile:all", "compile:chapters", "compile:presenter", "compile:slides", "compile:pages",
        "compile:several", "compile:everything"], "PDF")
    add_commands(menu, ctx, [f"transcript:{version}" for version in STUDENT_VERSIONS],
                 "Accessible transcript")
    menu.add_separator()
    add_commands(menu, ctx, ["stop", "build_options"])
    return menu


# The ⋮ menu: (header, command ids).
MORE_SECTIONS = (
    ("This deck", ("open_pdf", "deck_settings", "admin_slides", "deck_source", "deck_tags", "duplicate_deck",
                   "export_pptx", "archive_deck")),
    ("Decks", ("create_snapshot", "import_presentation", "refresh_decks")),
    ("Project", ("palette", "log", "edit_bib", "edit_test_slides", "open_project", "preferences")),
    ("Housekeeping", ("empty_pdf", "remove_temp", "archive_unused", "update_previews", "sync_links")),
    ("Info", ("version_history", "check_updates", "project_compat")),
)


def build_more_menu(parent: QWidget, ctx: Context) -> PopoverMenu:
    menu = PopoverMenu(parent, min_width=260)
    for header, ids in MORE_SECTIONS:
        add_commands(menu, ctx, ids, header)
    menu.add_separator()
    add_commands(menu, ctx, ["exit"])
    return menu
