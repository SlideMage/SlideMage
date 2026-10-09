"""The top bar's menus: deck switcher, Compile caret menu and the ⋮ menu.

Each builder returns a PopoverMenu whose item keys are the command names the
window dispatches (window.py, `WorkspaceWindow._commands`). This module holds
the menus' content and when an entry is available, and nothing else. It is
also the answer to "where did the old deck-table button / menu-bar action go":
the old menu bar's System, Decks, Tabs, Housekeeping and Info menus became
the sections of the ⋮ menu, and the deck table's per-deck buttons became its
"This deck" section. The command registry of step 8 replaces these lists.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QWidget

from ...deck_scan import GROUP_ORDER, TAG_COURSE, TAG_MANUAL, TAG_RESEARCH, TAG_TEST, TAG_WORK, Deck
from ...transcript import STUDENT_VERSIONS
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


def build_compile_menu(parent: QWidget, deck: Optional[Deck], compiling: bool) -> PopoverMenu:
    """Every PDF the old deck table could ask for (its version, per-chapter
    and Presenter checkboxes), the transcripts of its Create Transcript
    button, the Pages field, Stop creation and the options row of the old
    toolbar. Entries a deck cannot use are disabled instead of hidden."""
    menu = PopoverMenu(parent, min_width=300)
    menu.add_header("PDF")
    shown = VIEWS if deck is not None and deck.supports_version else VIEWS[:1]
    for view in shown:
        menu.add_item(f"compile:{view}", VIEW_LABELS[view], enabled=deck is not None)
    menu.add_item("compile:all", "All views of this deck", enabled=deck is not None)
    menu.add_item("compile:chapters", "After course, one PDF per chapter",
                  enabled=deck is not None and deck.has_chapters)
    menu.add_item("compile:presenter", "Presenter", meta="speaker notes", enabled=deck is not None)
    menu.add_item("compile:several", "Several decks…")
    menu.add_item("compile:pages", "Selected pages…", meta="e.g. 4, 7-10", enabled=deck is not None)
    if deck is not None and deck.supports_version:
        menu.add_header("Accessible transcript · Markdown + HTML")
        for version in STUDENT_VERSIONS:
            menu.add_item(f"transcript:{version}", VIEW_LABELS[version])
    menu.add_separator()
    menu.add_item("stop", "Stop compilation", tone="danger", enabled=compiling)
    menu.add_item("build_options", "Build options…")
    return menu


def build_more_menu(parent: QWidget, deck: Optional[Deck]) -> PopoverMenu:
    menu = PopoverMenu(parent, min_width=260)
    has_deck = deck is not None
    # The manual is replaced by app updates: its settings and group stay as shipped.
    keeps_group = has_deck and deck.group == TAG_MANUAL
    active = has_deck and not deck.archived   # archived decks only compile and get settings
    menu.add_header("This deck")
    menu.add_item("open_pdf", "Open latest PDF", enabled=active)
    menu.add_item("deck_settings", "Deck settings…", enabled=has_deck and not keeps_group)
    menu.add_item("admin_slides", "Admin slides…", meta="course page",
                  enabled=active and deck.group == TAG_COURSE and bool(deck.course_url))
    menu.add_item("deck_source", "Edit deck source", enabled=active)
    menu.add_item("deck_tags", "Tags…", enabled=active and not keeps_group)
    menu.add_item("duplicate_deck", "Duplicate deck…", enabled=active)
    menu.add_item("export_pptx", "Export PPTX…", enabled=active)
    menu.add_item("archive_deck", "Archive deck…", tone="danger", enabled=active)
    menu.add_header("Decks")
    menu.add_item("create_snapshot", "Create deck snapshot…")
    menu.add_item("import_presentation", "Import PPTX/ODP…")
    menu.add_item("refresh_decks", "Refresh decks")
    menu.add_header("Project")
    menu.add_item("go_to_slide", "Go to slide…")
    menu.add_item("search_text", "Search slide text…", meta="Ctrl+Shift+F")
    menu.add_item("edit_bib", "Edit .bib")
    menu.add_item("edit_test_slides", "Edit test-slides.tex")
    menu.add_item("open_project", "Open project…")
    menu.add_item("preferences", "Preferences…")
    menu.add_header("Housekeeping")
    menu.add_item("empty_pdf", "Empty pdf folder")
    menu.add_item("remove_temp", "Remove temp files")
    menu.add_item("archive_unused", "Archive unused slides and media files")
    menu.add_item("update_previews", "Update slide previews")
    menu.add_item("sync_links", "Reestablish broken translation links")
    menu.add_header("Info")
    menu.add_item("version_history", "Version history…")
    menu.add_item("check_updates", "Check for updates…")
    menu.add_item("project_compat", "Project compatibility…")
    menu.add_separator()
    menu.add_item("exit", "Exit SlideMage")
    return menu
