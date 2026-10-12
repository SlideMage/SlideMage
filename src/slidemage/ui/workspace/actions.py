"""Every action of the workspace window, as a command of the registry (ui/commands.py).

`build_registry()` is called once by the window. A command runs with the window
as its context and says, with the same context, whether it is visible and enabled
now; the top bar's buttons and menus (menus.py), the slide list's context menus
and the palette (palette.py) all show these entries and nothing else.

The ids are the keys the menus have always used (`compile:instructor`,
`deck_settings`, ...), plus `slide:` and `section:` for what acts on the slides
and the section chosen in the list. The group is the palette's heading.

Where the old menu bar's actions went: the "Open Project…", "Settings…" and
"Exit SlideMage" of System, the Decks menu, the housekeeping and info menus are
all commands below, in the groups Deck and Project; "Images" and the archived
decks of the Tabs menu are `images` and `archived_decks`.
"""
from __future__ import annotations

from ...deck_scan import TAG_COURSE, TAG_MANUAL
from ...transcript import STUDENT_VERSIONS
from ..commands import Command, CommandRegistry
from ..text import plural
from .menus import VIEW_LABELS
from .panels import PANELS
from .state import MODES, UI_LANGUAGES, VIEWS

VIEW_AND_BUILD, SLIDE, SECTION, DECK, PROJECT = "View & build", "Slide", "Section", "Deck", "Project"
LANGUAGE_NAMES = {"EN": "English", "DE": "German"}


# -- when a command is available -------------------------------------------------------

def _has_deck(w) -> bool:
    return w.state.deck is not None


def _active_deck(w) -> bool:
    """A deck that is not archived: archived decks only compile and get settings."""
    deck = w.state.deck
    return deck is not None and not deck.archived


def _keeps_group(w) -> bool:
    """The manual is replaced by app updates: its settings and group stay as shipped."""
    deck = w.state.deck
    return deck is not None and deck.group == TAG_MANUAL


def _versioned(w) -> bool:
    deck = w.state.deck
    return deck is not None and deck.supports_version


def _admin_slides_possible(w) -> bool:
    return _active_deck(w) and w.state.deck.group == TAG_COURSE and bool(w.state.deck.course_url)


def _current(is_current: bool) -> str:
    return "current" if is_current else ""


def _slide_targets(w) -> list:
    return w.slide_list.targets()


def _one_slide(w) -> bool:
    return len(_slide_targets(w)) == 1


def _editable_slides(w) -> bool:
    return all(row.call.editable for row in _slide_targets(w))


def _visibility_label(view: str):
    def label(w) -> str:
        rows = _slide_targets(w)
        verb = "Hide" if rows and all(row.call.included_in(view) for row in rows) else "Show"
        return f"{verb} in {VIEW_LABELS[view]}"
    return label


def _remove_label(w) -> str:
    count = len(_slide_targets(w))
    return "Remove from the deck" if count < 2 else f"Remove {count} from the deck"


def _section_enabled(name: str):
    return lambda w: w.slide_list.section_enabled(name)


def _run_slide(name: str):
    return lambda w: w.slide_list.run(name)


def _run_section(name: str):
    return lambda w: w.slide_list.run_section(name)


def _deck(method: str):
    """A window method that takes the current deck."""
    return lambda w: getattr(w, method)(w.state.deck)


def _window(method: str):
    return lambda w: getattr(w, method)()


# -- the registry ----------------------------------------------------------------------

def build_registry() -> CommandRegistry:
    registry = CommandRegistry()

    def add(*args, **kwargs) -> None:
        registry.add(Command(*args, **kwargs))

    # View & build -----------------------------------------------------------------
    for side, label, shortcut in (("left", "slide list", "Ctrl+Alt+["), ("right", "side panel", "Ctrl+Alt+]")):
        add(f"column:{side}",
            lambda w, s=side, text=label: f"{'Show' if getattr(w, s + '_column_hidden') else 'Hide'} {text}",
            VIEW_AND_BUILD, lambda w, s=side: w._toggle_column(s), icon="view_sidebar", shortcut=shortcut)
    for view in VIEWS:
        add(f"view:{view}", f"View as {VIEW_LABELS[view]}", VIEW_AND_BUILD,
            lambda w, v=view: w.state.set_view(v), icon="visibility", meta=lambda w, v=view: _current(w.state.view == v))
    for language in UI_LANGUAGES:
        add(f"language:{language}", f"Show {LANGUAGE_NAMES.get(language, language)} ({language})", VIEW_AND_BUILD,
            lambda w, lang=language: w.state.set_language(lang), icon="translate",
            meta=lambda w, lang=language: _current(w.state.language == lang))
    for mode in MODES:
        add(f"mode:{mode}", f"Show {mode.capitalize()}", VIEW_AND_BUILD,
            lambda w, m=mode: w.state.set_mode(m), icon="tab", meta=lambda w, m=mode: _current(w.state.mode == m))
    for view in VIEWS:
        add(f"compile:{view}", f"Compile PDF · {VIEW_LABELS[view]}", VIEW_AND_BUILD,
            lambda w, v=view: w._compile_current(v), icon="picture_as_pdf", enabled=_has_deck,
            visible=lambda w, v=view: v == VIEWS[0] or _versioned(w))
    add("compile:all", "All views of this deck", VIEW_AND_BUILD, lambda w: w._compile_current("all"),
        enabled=_has_deck)
    add("compile:chapters", "After course, one PDF per chapter", VIEW_AND_BUILD,
        lambda w: w._compile_current("chapters"),
        enabled=lambda w: _has_deck(w) and w.state.deck.has_chapters)
    add("compile:presenter", "Presenter", VIEW_AND_BUILD, lambda w: w._compile_current("presenter"),
        meta="speaker notes", enabled=_has_deck)
    add("compile:slides", "Pages of the selected slides", VIEW_AND_BUILD,
        lambda w: w._compile_slides(list(w.state.selected_or_focused())),
        meta=lambda w: plural(len(w.state.selected_or_focused()), "slide"),
        enabled=lambda w: _has_deck(w) and bool(w.state.selected_or_focused()))
    add("compile:pages", "Pages by number…", VIEW_AND_BUILD, _window("_compile_pages"),
        meta="e.g. 4, 7-10", enabled=_has_deck)
    add("compile:several", "Several decks…", VIEW_AND_BUILD, _window("_compile_several"))
    add("compile:everything", "All decks except archive", VIEW_AND_BUILD, _window("_compile_everything"),
        meta="every view")
    for version in STUDENT_VERSIONS:
        add(f"transcript:{version}", f"Write transcript · {VIEW_LABELS[version]}", VIEW_AND_BUILD,
            lambda w, v=version: w.generate_deck_transcript(w.state.deck, v),
            icon="article", meta="Markdown + HTML", enabled=_has_deck, visible=_versioned)
    add("stop", "Stop compilation", VIEW_AND_BUILD, _window("_stop_compilation"), tone="danger", icon="stop",
        enabled=lambda w: w.compiling)
    add("build_options", "Build options…", VIEW_AND_BUILD, lambda w: w.build_options.exec())
    add("log", "Log", VIEW_AND_BUILD, lambda w: w.log_drawer.toggle(), icon="terminal", shortcut="Ctrl+L")

    # Slide: the focused slide, or the selected ones ---------------------------------------
    for name, label in (("open", "Open source"), ("preview", "Preview"), ("images", "Images")):
        add(f"slide:{name}", label, SLIDE, _run_slide(name), visible=_one_slide)
    for view in VIEWS:
        add(f"slide:visible:{view}", _visibility_label(view), SLIDE, _run_slide(f"visible:{view}"),
            visible=lambda w: bool(_slide_targets(w)), enabled=_editable_slides)
    add("slide:duplicate", "Duplicate slide…", SLIDE, _run_slide("duplicate"), visible=_one_slide)
    add("slide:translate", "Translate slide…", SLIDE, _run_slide("translate"), visible=_one_slide)
    add("slide:before", "Add slide before", SLIDE, _run_slide("before"), visible=_one_slide)
    add("slide:after", "Add slide after", SLIDE, _run_slide("after"), visible=_one_slide)
    add("slide:section_before", "Add section before", SLIDE, _run_slide("section_before"), visible=_one_slide)
    add("slide:remove", _remove_label, SLIDE, _run_slide("remove"), tone="danger",
        visible=lambda w: bool(_slide_targets(w)), enabled=_editable_slides)
    add("slide:clear", "Clear selection", SLIDE, _run_slide("clear"), meta="Esc",
        visible=lambda w: len(_slide_targets(w)) > 1)
    for panel in PANELS:
        add(f"panel:{panel.key}", f"Show {panel.title}", SLIDE, lambda w, key=panel.key: w.side_panels.set_panel(key),
            icon="view_sidebar", visible=lambda w: w.state.focused_slide is not None)

    # Section: the section chosen in the slide list -------------------------------------
    section_chosen = lambda w: w.slide_list.current_section() is not None   # noqa: E731
    for name, label, tone, meta in (
            ("rename", "Rename", "", ""), ("add_slide", "Add slide here", "", ""),
            ("section_before", "Add section before", "", ""), ("section_up", "Move section up", "", ""),
            ("section_down", "Move section down", "", ""),
            ("remove_section", "Remove section", "danger", "keeps its slides")):
        add(f"section:{name}", label, SECTION, _run_section(name), tone=tone, meta=meta,
            visible=section_chosen, enabled=_section_enabled(name))

    # Deck -----------------------------------------------------------------------------
    add("open_pdf", "Open latest PDF", DECK, _deck("_on_open_latest_pdf"), enabled=_active_deck)
    add("deck_settings", "Deck settings…", DECK, _deck("_on_deck_settings"),
        enabled=lambda w: _has_deck(w) and not _keeps_group(w))
    add("admin_slides", "Admin slides…", DECK, _deck("_on_admin_slides"), meta="course page",
        enabled=_admin_slides_possible)
    add("deck_source", "Edit deck source", DECK, _deck("open_deck_source_editor"), enabled=_active_deck)
    add("deck_tags", "Tags…", DECK, _deck("_on_edit_deck_tags"),
        enabled=lambda w: _active_deck(w) and not _keeps_group(w))
    add("duplicate_deck", "Duplicate deck…", DECK, _deck("_on_duplicate_deck"), enabled=_active_deck)
    add("export_pptx", "Export PPTX…", DECK, _deck("_on_export_pptx"), enabled=_active_deck)
    add("archive_deck", "Archive deck…", DECK, _deck("_archive_deck"), tone="danger", enabled=_active_deck)
    add("create_snapshot", "Create deck snapshot…", DECK, _window("_on_create_deck_snapshot"))
    add("add_slide", "Add slide…", DECK, lambda w: w.slide_list.add_slide(), enabled=_has_deck)
    add("import_presentation", "Import PPTX/ODP…", DECK, _window("_on_import_presentation"))
    add("refresh_decks", "Refresh decks", DECK, _window("_on_refresh_decks_clicked"))
    add("archived_decks", "Archived decks…", DECK, lambda w: w.topbar.open_deck_menu(),
        visible=lambda w: any(deck.archived for deck in w.decks))

    # Project --------------------------------------------------------------------------
    add("palette", "Find anything…", PROJECT, lambda w: w.palette.toggle(), icon="search", shortcut="Ctrl+K")
    add("images", "Image descriptions", PROJECT, _window("_toggle_images"), icon="image", meta="every slide with images")
    add("edit_bib", "Edit .bib", PROJECT, _window("_on_edit_bib"))
    add("edit_test_slides", "Edit test-slides.tex", PROJECT, _window("_on_edit_test_slides"))
    add("open_project", "Open project…", PROJECT, _window("_on_open_project"))
    add("settings", "Settings…", PROJECT, _window("_on_open_settings"))
    add("housekeeping", "Housekeeping…", PROJECT, _window("_on_housekeeping"), icon="build",
        meta="pdf, temp files, unused content, previews")
    add("empty_pdf", "Empty pdf folder", PROJECT, _window("_empty_pdf_folder"))
    add("remove_temp", "Remove temp files", PROJECT, _window("_remove_temp_files"))
    add("archive_unused", "Archive unused slides and media files", PROJECT, _window("_on_archive_unused_content"))
    add("update_previews", "Update slide previews", PROJECT, _window("_on_update_previews"))
    add("sync_links", "Reestablish broken translation links", PROJECT, _window("_on_sync_translation_links"))
    add("version_history", "Version history…", PROJECT, _window("_on_open_version_history"))
    add("check_updates", "Check for updates…", PROJECT, _window("_on_check_for_updates"))
    add("project_compat", "Project compatibility…", PROJECT, _window("_on_project_compat"))
    add("exit", "Exit SlideMage", PROJECT, lambda w: w.close())
    return registry
