"""The main window: top bar (deck switcher, view, language, Compile, Images, the
⋮ menu), the hosted pages and where the old deck table's and menu bar's
actions went."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QInputDialog, QLabel, QMessageBox

from slidemage import app_settings
from slidemage.compiler import CompileJob, order_jobs
from slidemage.deck_scan import Chapter, Deck
from slidemage.ui.kit.widgets import PopoverMenu
from slidemage.ui.workspace import window as window_module
from slidemage.ui.workspace.menus import (
    build_compile_menu,
    build_deck_menu,
    build_more_menu,
    deck_key,
)

from conftest import build_window


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def make_deck(name, tags=(), *, archived=False, versions=True, chapters=()):
    return Deck(
        name=name, path=Path(f"decks/{'archive/' if archived else ''}{name}.tex"), archived=archived,
        text="", supports_version=versions, uses_biblatex=False, preamble_end=0,
        chapters=list(chapters), output_folders={}, tags=list(tags))


CHAPTER = Chapter(order=1, title="One", slug="One", start=0, end=0)
COURSE = make_deck("course", ["course"], chapters=[CHAPTER])
WORK = make_deck("#workdeck", ["work"], versions=False)
MANUAL = make_deck("slidemage-manual", ["manual"])
TEST = make_deck("test-all", ["test"])
OLD = make_deck("old-course", ["course"], archived=True)


@pytest.fixture
def window(qapp, monkeypatch):
    """A window over a fixed set of decks, without building deck editors."""
    monkeypatch.setattr(window_module, "scan_decks", lambda: [WORK, COURSE, MANUAL, TEST, OLD])
    return build_window(monkeypatch)


def entries(menu):
    """(key, text, enabled) of a menu's items, and its headers as ("", text, True)."""
    return [(e[1], e[2], e[6]) if e[0] == "item" else ("", e[1], True)
            for e in menu._entries if e[0] != "sep"]


def items(menu):
    return {key: enabled for key, _text, enabled in entries(menu) if key}


# -- the deck switcher ---------------------------------------------------------

def test_deck_switcher_groups_decks_and_lists_archived_ones_in_its_footer(qapp):
    menu = build_deck_menu(None, [OLD, TEST, MANUAL, COURSE, WORK], COURSE)
    assert entries(menu) == [
        (deck_key(WORK), "#workdeck", True),                        # the work deck stands alone
        ("", "Course decks", True), (deck_key(COURSE), "course", True),
        ("", "SlideMage manual", True), (deck_key(MANUAL), "slidemage-manual", True),
        ("", "Test decks", True), (deck_key(TEST), "test-all", True),
        ("", "Archived decks (1)", True), (deck_key(OLD), "old-course", True),
    ]
    assert menu._entries[2][4] == "check"                          # the open deck is ticked


def test_no_archived_section_without_archived_decks(qapp):
    menu = build_deck_menu(None, [WORK], WORK)
    assert [text for _key, text, _on in entries(menu)] == ["#workdeck"]


def test_window_opens_the_first_active_deck_then_the_one_left_open(window, monkeypatch):
    assert window.state.deck is WORK                                # first active deck
    window.topbar._on_deck_picked(deck_key(MANUAL))
    assert app_settings.get(window_module.LAST_DECK_KEY) == "slidemage-manual"
    again = build_window(monkeypatch)
    assert again.state.deck.name == "slidemage-manual"


def test_picking_a_deck_updates_the_state_the_label_and_the_page(window):
    window.topbar._on_deck_picked(deck_key(TEST))
    assert window.state.deck is TEST
    assert window.topbar._deck_button._name.text() == "test-all"
    assert "test deck" in window.placeholder.text()                 # it has no slide list
    assert window.stack.currentWidget() is window.placeholder


class FakeEditor(QLabel):
    """Stands in for the deck editor tab, which builds a row for every slide."""

    def __init__(self, _app, deck):
        super().__init__(deck.name)

    def reload(self, deck):
        pass


def test_deck_editor_pages_are_kept_per_deck_and_dropped_with_the_deck(qapp, monkeypatch):
    decks = [WORK, COURSE]
    monkeypatch.setattr(window_module, "scan_decks", lambda: decks)
    monkeypatch.setattr(window_module, "DeckEditorTab", FakeEditor)
    window = build_window(monkeypatch, with_deck_editor=True)
    first = window._deck_editor_tabs[WORK.path]
    window.state.set_deck(COURSE)
    assert window.stack.currentWidget() is window._deck_editor_tabs[COURSE.path]
    window.state.set_deck(WORK)
    assert window.stack.currentWidget() is first                    # not rebuilt
    decks[:] = [WORK]                                               # course archived or removed
    window.reload_decks()
    assert list(window._deck_editor_tabs) == [WORK.path]


def test_reload_follows_an_archived_deck_and_falls_back_when_it_is_gone(window, monkeypatch):
    window.state.set_deck(COURSE)
    archived = make_deck("course", ["course"], archived=True)
    monkeypatch.setattr(window_module, "scan_decks", lambda: [WORK, archived])
    window.reload_decks()
    assert window.state.deck is archived
    monkeypatch.setattr(window_module, "scan_decks", lambda: [WORK])
    window.reload_decks()
    assert window.state.deck is WORK


def test_a_project_without_decks_shows_a_placeholder(qapp, monkeypatch):
    monkeypatch.setattr(window_module, "scan_decks", lambda: [])
    window = build_window(monkeypatch)
    assert window.state.deck is None
    assert "no decks" in window.placeholder.text()
    assert window.topbar._deck_button._name.text() == "No deck"
    assert not window.topbar._compile.isEnabled()


# -- view, language, compile label ----------------------------------------------

def test_view_and_language_controls_drive_the_state_and_follow_it(window):
    bar = window.topbar
    window.state.set_deck(COURSE)
    bar._views._buttons["during-course"].click()
    bar._languages._buttons["DE"].click()
    assert (window.state.view, window.state.language) == ("during-course", "DE")
    assert bar._strip.property("tone") == "during"
    window.state.set_view("after-course")                           # e.g. restored for another deck
    window.state.set_language("EN")
    assert bar._views.current() == "after-course" and bar._languages.current() == "EN"
    assert bar._strip.property("tone") == "after"


def test_compile_label_names_the_view_unless_the_deck_has_no_versions(window):
    window.state.set_deck(COURSE)
    assert window.topbar._compile.text() == "Compile PDF · Instructor"
    window.state.set_view("during-course")
    assert window.topbar._compile.text() == "Compile PDF · During"
    window.state.set_view("after-course")
    assert window.topbar._compile.text() == "Compile PDF · After"
    window.state.set_deck(WORK)
    assert window.topbar._compile.text() == "Compile PDF"


def test_the_view_comes_back_with_the_deck(window):
    window.state.set_deck(COURSE)
    window.state.set_view("after-course")
    window.state.set_deck(MANUAL)
    assert window.topbar._views.current() == "instructor"
    window.state.set_deck(COURSE)
    assert window.topbar._views.current() == "after-course"
    assert window.topbar._compile.text() == "Compile PDF · After"


# -- compile -------------------------------------------------------------------

def compiled(window, monkeypatch):
    jobs: list = []
    monkeypatch.setattr(window, "_compile_jobs", lambda batch: jobs.append(batch))
    return jobs


def describe(job: CompileJob):
    return (job.deck.name, job.version, job.chapter.order if job.chapter else None,
            job.presenter, job.pages)


def test_compile_button_compiles_the_current_view_of_the_current_deck(window, monkeypatch):
    jobs = compiled(window, monkeypatch)
    window.state.set_deck(COURSE)
    window.topbar._compile._main.click()
    window.state.set_view("after-course")
    window.topbar._compile._main.click()
    window.state.set_deck(WORK)                                     # no versions: one plain job
    window.topbar._compile._main.click()
    assert [[describe(j) for j in batch] for batch in jobs] == [
        [("course", "instructor", None, False, None)],
        [("course", "after-course", None, False, None)],
        [("#workdeck", None, None, False, None)],
    ]


def test_compile_menu_entries_compile_the_other_pdfs(window, monkeypatch):
    jobs = compiled(window, monkeypatch)
    window.state.set_deck(COURSE)
    for key in ("compile:during-course", "compile:chapters", "compile:presenter"):
        window.topbar.command.emit(key)
    assert [[describe(j) for j in batch] for batch in jobs] == [
        [("course", "during-course", None, False, None)],
        [("course", "after-course", 1, False, None)],
        [("course", "instructor", None, True, None)],
    ]


def test_selected_pages_compile_the_current_view(window, monkeypatch):
    jobs = compiled(window, monkeypatch)
    window.state.set_deck(COURSE)
    window.state.set_view("during-course")
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("4, 7-9", True))
    window.topbar.command.emit("compile:pages")
    assert [describe(j) for j in jobs[0]] == [("course", "during-course", None, False, [4, 7, 8, 9])]
    told: list = []
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("4, x", True))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: told.append(a[2]))
    window.topbar.command.emit("compile:pages")
    assert len(jobs) == 1 and told                                    # refused with a message


def test_compile_menu_offers_only_what_the_deck_can_do(qapp):
    full = items(build_compile_menu(None, COURSE, compiling=False))
    assert list(full) == [
        "compile:instructor", "compile:during-course", "compile:after-course", "compile:all",
        "compile:chapters", "compile:presenter", "compile:several", "compile:pages", "transcript:during-course", "transcript:after-course",
        "stop", "build_options"]
    assert full["compile:chapters"] and not full["stop"]
    plain = items(build_compile_menu(None, make_deck("plain", versions=False), compiling=False))
    assert list(plain) == ["compile:instructor", "compile:all", "compile:chapters",
                           "compile:presenter", "compile:several", "compile:pages", "stop", "build_options"]
    assert not plain["compile:chapters"]                              # no \section chapters
    assert items(build_compile_menu(None, COURSE, compiling=True))["stop"]


def test_stop_follows_the_compile_state(window):
    window.state.set_deck(COURSE)
    assert not items(window.topbar._compile_menu)["stop"]
    window.topbar.set_compiling(True)
    assert items(window.topbar._compile_menu)["stop"]


def test_transcript_entries_write_the_current_decks_transcript(window, monkeypatch):
    window.state.set_deck(COURSE)
    made: list = []
    monkeypatch.setattr(window, "generate_deck_transcript", lambda deck, version: made.append((deck, version)))
    window.topbar.command.emit("transcript:after-course")
    assert made == [(COURSE, "after-course")]


def test_log_lines_keep_working_after_the_decks_are_reloaded(window):
    window.reload_decks()
    for line in ("==== Compiling a -> a ====", "==== PASS: a -> pdf ====", "==== Done: 1 passed ===="):
        window._log(line)
    assert window.status_label.text() == "Done: 1 passed"


# -- Images and the pages ----------------------------------------------------------

def test_images_button_toggles_the_images_page(window, monkeypatch):
    monkeypatch.setattr(window.transcript_tab, "ensure_loaded", lambda: None)
    bar = window.topbar
    assert bar._images.text() == "Images"
    bar._images.click()
    assert window.stack.currentWidget() is window.transcript_tab and bar._images.text() == "Close images"
    bar._images.click()
    assert window.stack.currentWidget() is window.placeholder and bar._images.text() == "Images"


def test_a_slide_editor_opens_in_the_centre_and_closing_returns_to_the_deck(window, tmp_path):
    path = tmp_path / "abc-EN-Test-current.tex"
    path.write_text("\\slide{abc-EN-Test}\nBODY\n", encoding="utf-8", newline="")
    window.open_slide_editor(path)
    tab = window._slide_source_tabs[path]
    assert window.stack.currentWidget() is tab
    assert window.topbar._save.text() == "Saved"
    tab.widget.insertPlainText("x")
    assert window.topbar._save.text() == "Unsaved changes"
    tab._set_dirty(False)
    tab.widget.document().setModified(False)
    window.close_slide_editor_tab(tab)
    assert window.stack.currentWidget() is window._home()
    assert path not in window._slide_source_tabs and window.topbar._save.text() == "Saved"


def test_opening_a_slide_focuses_it(window, monkeypatch):
    from slidemage import slide_ids

    monkeypatch.setattr(window_module, "SLIDES_DIR", slide_ids.SLIDES_DIR)
    slide = next(iter(slide_ids.SLIDES_DIR.glob("*-current.tex")))
    window.open_slide_editor(slide)
    assert window.state.focused_slide == slide.name.split("-", 1)[0]


# -- the ⋮ menu: nothing of the old deck table and menu bar is lost --------------------

OLD_MENU_BAR = [
    "Open Project…", "Preferences…", "Exit SlideMage",                        # System
    "Create deck snapshot…", "Import PPTX/ODP…",                              # Decks
    "Edit .bib", "Edit test-slides.tex",                                      # Tabs (Archived decks and
    "Empty pdf folder", "Remove temp files",                                  #  Images moved to the
    "Archive unused slides and media files",                                  #  switcher and the button)
    "Update slide previews", "Reestablish broken translation links",          # Housekeeping
    "Version history…", "Check for updates…", "Project compatibility…",       # Info
]
OLD_DECK_ROW = ["Open latest PDF", "Deck settings…", "Edit deck source", "Duplicate deck…",
                "Tags…", "Export PPTX…", "Archive deck…", "Refresh decks"]


def test_every_former_menu_bar_and_deck_row_action_is_in_the_more_menu(qapp):
    labels = [text.lower() for _key, text, _on in entries(build_more_menu(None, COURSE)) if text]
    for wanted in OLD_MENU_BAR + OLD_DECK_ROW:
        assert wanted.lower() in labels, wanted
    assert "go to slide…" in labels and "search slide text…" in labels   # the old corner search


def test_every_menu_key_has_a_command(window):
    keys = {key for menu in (build_more_menu(None, COURSE), build_compile_menu(None, COURSE, False))
            for key in items(menu)}
    prefixed = ("compile:", "transcript:")
    assert [k for k in keys if k not in window._commands and not k.startswith(prefixed)] == []


def test_a_deck_command_runs_with_the_current_deck(window):
    window.state.set_deck(COURSE)
    seen: list = []
    window._commands["duplicate_deck"] = window._for_deck(seen.append)
    window.topbar.command.emit("duplicate_deck")
    assert seen == [COURSE]


@pytest.mark.parametrize("deck, disabled", [
    (COURSE, []),
    (MANUAL, ["deck_settings", "deck_tags"]),              # the manual keeps its settings and group
    (OLD, ["open_pdf", "deck_source", "deck_tags", "duplicate_deck", "export_pptx", "archive_deck"]),
    (None, ["open_pdf", "deck_settings", "deck_source", "deck_tags", "duplicate_deck", "export_pptx",
            "archive_deck"]),
])
def test_deck_actions_are_disabled_where_the_old_row_had_no_such_button(qapp, deck, disabled):
    enabled = items(build_more_menu(None, deck))
    deck_keys = ["open_pdf", "deck_settings", "deck_source", "deck_tags", "duplicate_deck",
                 "export_pptx", "archive_deck"]
    assert [key for key in deck_keys if not enabled[key]] == disabled


def test_the_more_button_opens_the_menu_and_forwards_the_choice(window):
    seen: list = []
    window.topbar.command.connect(seen.append)
    window.topbar._more.click()
    menu = window.topbar.findChildren(PopoverMenu)[-1]
    assert menu.isVisible()
    menu._on_activated("refresh_decks")
    assert seen == ["refresh_decks"] and not menu.isVisible()


def test_go_to_slide_opens_an_existing_slide_and_refuses_an_unknown_one(window, monkeypatch):
    from slidemage import slide_ids

    told: list = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: told.append(a[2]))
    window._on_slide_search_activated("zzz-EN-No-Such-Slide")
    assert told and not window._slide_source_tabs

    id_slug = slide_ids.list_id_slugs()[0]
    window._on_slide_search_activated(id_slug)
    assert [p.name for p in window._slide_source_tabs] == [f"{id_slug}-current.tex"]
    assert window.stack.currentWidget() is next(iter(window._slide_source_tabs.values()))


def test_all_views_compiles_every_view_the_deck_has(window, monkeypatch):
    jobs = compiled(window, monkeypatch)
    window.state.set_deck(COURSE)
    window.topbar.command.emit("compile:all")
    window.state.set_deck(WORK)
    window.topbar.command.emit("compile:all")
    assert [[describe(j)[:2] for j in batch] for batch in jobs] == [
        [("course", "instructor"), ("course", "during-course"), ("course", "after-course")],
        [("#workdeck", None)],
    ]


def open_several(window, monkeypatch, ticks=(), *, accept=True, select_all=False, clear=False):
    """Runs Compile -> Several decks… with `ticks` ((deck name, kind) pairs) ticked."""
    from slidemage.ui.workspace import compile_jobs

    seen: dict = {}

    def fake_exec(sheet):
        seen["sheet"] = sheet
        if select_all:
            sheet._set_all(True)
        if clear:
            sheet._set_all(False)
        for key in ticks:
            sheet.boxes[key].setChecked(True)
        return accept

    monkeypatch.setattr(compile_jobs.MultiCompileSheet, "exec", fake_exec)
    window.topbar.command.emit("compile:several")
    return seen["sheet"]


def test_several_decks_queue_all_ticked_pdfs_in_the_usual_order(window, monkeypatch):
    jobs = compiled(window, monkeypatch)
    open_several(window, monkeypatch, [
        ("slidemage-manual", "during-course"), ("course", "instructor"), ("#workdeck", "instructor"),
        ("course", "chapters"), ("course", "presenter")])
    assert len(jobs) == 1                      # one run for all decks
    ordered = order_jobs(jobs[0])              # what _compile_jobs does: version by version
    assert [(j.deck.name, j.version, j.presenter, j.chapter is not None) for j in ordered] == [
        ("course", "instructor", True, False), ("#workdeck", None, False, False),
        ("course", "instructor", False, False), ("slidemage-manual", "during-course", False, False),
        ("course", "after-course", False, True)]


def test_the_sheet_offers_what_the_old_table_did(window, monkeypatch):
    sheet = open_several(window, monkeypatch, accept=False)
    offered = {name: sorted(kind for n, kind in sheet.boxes if n == name)
               for name in ("course", "#workdeck")}
    assert "old-course" not in {n for n, _k in sheet.boxes}          # archived decks excluded
    assert offered["#workdeck"] == ["instructor", "presenter"]       # no versions, no chapters
    assert "chapters" in offered["course"] and "transcript:after-course" in offered["course"]


def test_select_all_and_clear_and_cancel(window, monkeypatch):
    jobs = compiled(window, monkeypatch)
    monkeypatch.setattr(window, "generate_deck_transcript", lambda *a, **k: True)
    sheet = open_several(window, monkeypatch, select_all=True, clear=True)
    assert not any(box.isChecked() for box in sheet.boxes.values()) and jobs == []
    open_several(window, monkeypatch, [("course", "instructor")], accept=False)
    assert jobs == []                                                 # cancelled
    sheet = open_several(window, monkeypatch, select_all=True)
    assert all(box.isChecked() for box in sheet.boxes.values()) and len(jobs[0]) > 4


def test_several_decks_write_the_ticked_transcripts_quietly(window, monkeypatch):
    jobs = compiled(window, monkeypatch)
    made: list = []
    monkeypatch.setattr(window, "generate_deck_transcript",
                        lambda deck, version, quiet=False: made.append((deck.name, version, quiet)) or True)
    open_several(window, monkeypatch, [("course", "transcript:after-course"),
                                       ("slidemage-manual", "transcript:during-course")])
    assert jobs == []
    assert made == [("course", "after-course", True), ("slidemage-manual", "during-course", True)]
    assert "2 of 2 transcript(s)" in window.log_text.toPlainText()
