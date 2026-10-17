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
decks of the Tabs menu are `images` and `archived_decks`. `images` is also the way out of the Images page, and the AI
switch's moves and setup are the group AI.
"""
from __future__ import annotations

from ... import ai_review
from ...deck_scan import TAG_COURSE, TAG_MANUAL
from ...transcript import STUDENT_VERSIONS
from ..commands import Command, CommandRegistry
from ..text import plural
from . import compare_rendered, compile_actions, deck_actions, maintenance
from .menus import VIEW_LABELS
from .panels import PANELS
from ...ai import ai_profile
from ...ai.claude_scope import DECK as DECK_SCOPE, SLIDE as SLIDE_SCOPE
from .selection_tasks import REWRITE_CHOICES
from .terminal.tasks import DECK_TASKS, SLIDE_TASKS, selection_of
from .state import MODES, UI_LANGUAGES, VIEWS

VIEW_AND_BUILD, SLIDE, SECTION, DECK, PROJECT = "View & build", "Slide", "Section", "Deck", "Project"
AI = "AI"
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


def _offered(w, scope: str, task):
    """The bubble of `task` the assistant offers for `scope` now, or None."""
    return next((bubble for bubble in w.assistant.header.offers(scope) if bubble.task is task), None)


def _current(is_current: bool) -> str:
    return "current" if is_current else ""


def _slide_targets(w) -> list:
    return w.slide_list.targets()


def _review_paths(w) -> list:
    rows = _slide_targets(w)
    if len(rows) > 1 or (rows and rows[0].matches(w.state.focused_slide)):
        return [w.project.slides_dir / row.call.source_filename for row in rows]
    path = w.centre.path
    return [path] if path is not None else []


def _last_edit_path(w):
    """The slide "Compare rendered with last AI edit" acts on: the focused one, when an earlier text is kept for it."""
    paths = _review_paths(w)
    return paths[0] if len(paths) == 1 and ai_review.last_before(w.project, paths[0]) is not None else None


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
            lambda w, v=view: compile_actions.compile_current(w, v), icon="picture_as_pdf", enabled=_has_deck,
            visible=lambda w, v=view: v == VIEWS[0] or _versioned(w))
    add("compile:all", "All views of this deck", VIEW_AND_BUILD, lambda w: compile_actions.compile_current(w, "all"),
        enabled=_has_deck)
    add("compile:chapters", "After course, one PDF per chapter", VIEW_AND_BUILD,
        lambda w: compile_actions.compile_current(w, "chapters"),
        enabled=lambda w: _has_deck(w) and w.state.deck.has_chapters)
    add("compile:presenter", "Presenter", VIEW_AND_BUILD, lambda w: compile_actions.compile_current(w, "presenter"),
        meta="speaker notes", enabled=_has_deck)
    add("compile:slides", "Pages of the selected slides", VIEW_AND_BUILD,
        lambda w: compile_actions.compile_slides(w, list(w.state.selected_or_focused())),
        meta=lambda w: plural(len(w.state.selected_or_focused()), "slide"),
        enabled=lambda w: _has_deck(w) and bool(w.state.selected_or_focused()))
    add("compile:pages", "Pages by number…", VIEW_AND_BUILD, compile_actions.compile_pages,
        meta="e.g. 4, 7-10", enabled=_has_deck)
    add("compile:several", "Several decks…", VIEW_AND_BUILD, compile_actions.compile_several)
    add("compile:everything", "All decks except archive", VIEW_AND_BUILD, compile_actions.compile_everything,
        meta="every view")
    for version in STUDENT_VERSIONS:
        add(f"transcript:{version}", f"Write transcript · {VIEW_LABELS[version]}", VIEW_AND_BUILD,
            lambda w, v=version: deck_actions.generate_deck_transcript(w, w.state.deck, v),
            icon="article", meta="Markdown + HTML", enabled=_has_deck, visible=_versioned)
    add("stop", "Stop compilation", VIEW_AND_BUILD, compile_actions.ask_to_stop, tone="danger", icon="stop",
        enabled=lambda w: w.compiling)
    add("build_options", "Build options…", VIEW_AND_BUILD, lambda w: w.build_options.exec())
    add("log", "Log", VIEW_AND_BUILD, lambda w: w.compile_display.drawer.toggle(), icon="terminal", shortcut="Ctrl+L")

    # Slide: the focused slide, or the selected ones ---------------------------------------
    for name, label in (("open", "Open source"), ("preview", "Preview"), ("images", "Images")):
        add(f"slide:{name}", label, SLIDE, _run_slide(name), visible=_one_slide)
    add("slide:reviewed", "Mark reviewed", SLIDE, lambda w: w.slide_list.mark_reviewed(_review_paths(w)),
        visible=lambda w: bool(_review_paths(w)),
        enabled=lambda w: any(ai_review.is_unreviewed(w.project, p) for p in _review_paths(w)))
    add("slide:compare", "Compare rendered with last AI edit", SLIDE,
        lambda w: compare_rendered.compare_with_last_edit(w, _last_edit_path(w)),
        visible=lambda w: _last_edit_path(w) is not None)
    add("slide:readability", "Check readability of this slide", SLIDE,
        lambda w: w.assistant.check_readability(SLIDE_SCOPE), icon="visibility", meta="no AI",
        enabled=lambda w: w.assistant.header.can_check(SLIDE_SCOPE))
    add("slide:readable", "Make this slide readable", SLIDE, lambda w: w.assistant.make_readable(), icon="auto_fix_high",
        meta="checks it first", enabled=lambda w: w.assistant.header.can_check(SLIDE_SCOPE))
    # The tasks on the text selected in the Source view: there for every slide, enabled with a selection to work on.
    selected = lambda w: selection_of(w) is not None     # noqa: E731
    add("selection:rewrite", "Rewrite selection…", SLIDE, lambda w: w.assistant.rewrite_selection(), icon="edit_note",
        meta="choose how", shortcut="Ctrl+Shift+R", enabled=selected)
    for choice in REWRITE_CHOICES:
        add(f"selection:rewrite:{choice}", f"Rewrite selection · {choice}", SLIDE,
            lambda w, c=choice: w.assistant.rewrite_selection(c), icon="edit_note", meta="selected text", enabled=selected)
    add("selection:proofread", "Proofread selection", SLIDE, lambda w: w.assistant.proofread_selection(), icon="spellcheck",
        meta="selected text", enabled=selected)
    add("slides:unreviewed", "List not reviewed slides", SLIDE,
        lambda w: w.slide_list.review_filter.setChecked(True), enabled=_has_deck)
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
    add("open_pdf", "Open latest PDF", DECK, lambda w: deck_actions.on_open_latest_pdf(w, w.state.deck), enabled=_active_deck)
    add("deck_settings", "Deck settings…", DECK, lambda w: deck_actions.on_deck_settings(w, w.state.deck),
        enabled=lambda w: _has_deck(w) and not _keeps_group(w))
    add("admin_slides", "Admin slides…", DECK, lambda w: deck_actions.on_admin_slides(w, w.state.deck), meta="course page",
        enabled=_admin_slides_possible)
    add("deck_source", "Edit deck source", DECK, _deck("open_deck_source_editor"), enabled=_active_deck)
    add("deck_tags", "Tags…", DECK, lambda w: deck_actions.on_edit_deck_tags(w, w.state.deck),
        enabled=lambda w: _active_deck(w) and not _keeps_group(w))
    add("new_deck", "New deck…", DECK, deck_actions.on_new_deck)
    add("duplicate_deck", "Duplicate deck…", DECK, lambda w: deck_actions.on_duplicate_deck(w, w.state.deck), enabled=_active_deck)
    add("export_pptx", "Export PPTX…", DECK, lambda w: compile_actions.export_pptx(w, w.state.deck), enabled=_active_deck)
    add("archive_deck", "Archive deck…", DECK, lambda w: deck_actions.archive_deck(w, w.state.deck), tone="danger", enabled=_active_deck)
    add("create_snapshot", "Create deck snapshot…", DECK, deck_actions.on_create_deck_snapshot)
    add("rerender_deck_previews", "Rerender all previews for this deck", DECK, compile_actions.rerender_deck_previews,
        enabled=_has_deck)
    add("update_deck_versions", "Update version of all changed slides…", DECK,
        lambda w: w.centre.update_deck_versions(), enabled=_has_deck)
    add("deck:readability", "Check readability of this deck", DECK,
        lambda w: w.assistant.check_readability(DECK_SCOPE), icon="visibility", meta="no AI", enabled=_has_deck)
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
    add("housekeeping", "Housekeeping…", PROJECT, maintenance.on_housekeeping, icon="build",
        meta="pdf, temp files, unused content, previews")
    add("empty_pdf", "Empty pdf folder", PROJECT, maintenance.empty_pdf_folder)
    add("remove_temp", "Remove temp files", PROJECT, maintenance.remove_temp_files)
    add("archive_unused", "Archive unused slides and media files", PROJECT, maintenance.on_archive_unused_content)
    add("update_previews", "Update slide previews", PROJECT, compile_actions.update_previews)
    add("sync_links", "Reestablish broken translation links", PROJECT, maintenance.on_sync_translation_links)
    add("version_history", "Version history…", PROJECT, maintenance.on_open_version_history)
    add("check_updates", "Check for updates…", PROJECT, maintenance.on_check_for_updates)
    add("project_compat", "Project compatibility…", PROJECT, maintenance.on_project_compat)
    add("exit", "Exit SlideMage", PROJECT, lambda w: w.close())

    # AI: the switch of the top bar, through its request flow (popovers included) ---------------
    for mode, label, icon in ((ai_profile.LOCAL, "Use Local AI", "computer"), (ai_profile.CLOUD, "Use Cloud AI", "cloud")):
        add(f"ai:{mode}", label, AI, lambda w, m=mode: w.ai_route.request(m), icon=icon,
            meta=lambda w, m=mode: _current(w.state.ai_mode == m))
    add("ai:setup", "AI setup…", AI, lambda w: w.ai_route.open_setup(), icon="tune",
        meta="models per task, cloud connection, project setting")
    # The tasks that fit the slide or the deck now, as the assistant header offers them (two of them there):
    # a task the route cannot run says why instead of running.
    for scope, scope_meta, tasks in ((SLIDE_SCOPE, "this slide", SLIDE_TASKS), (DECK_SCOPE, "the deck", DECK_TASKS)):
        for task in tasks:
            add(f"task:{scope}:{task.name}", lambda w, sc=scope, t=task: getattr(_offered(w, sc, t), "label", t.name), AI,
                lambda w, sc=scope, t=task: w.assistant.run_task(_offered(w, sc, t)), icon="auto_fix_high",
                meta=scope_meta, visible=lambda w, sc=scope, t=task: _offered(w, sc, t) is not None)
    return registry
