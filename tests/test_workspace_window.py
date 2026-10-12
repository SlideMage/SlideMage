"""The main window: top bar (deck switcher, view, language, Compile, Images, the
⋮ menu), the hosted pages and where the old deck table's and menu bar's
actions went."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QInputDialog, QMessageBox

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

from conftest import build_window, command_context, qapp as qapp


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
    assert window.topbar._deck_button.text() == "test-all"
    assert "test deck" in window.centre.preview._page.message       # it has no slide list
    assert window.stack.currentWidget() is window.centre


def test_the_slide_list_follows_the_deck_and_the_stack_starts_on_the_hint(qapp, monkeypatch):
    decks = [WORK, COURSE]
    monkeypatch.setattr(window_module, "scan_decks", lambda: decks)
    window = build_window(monkeypatch)
    assert window.slide_list.deck is WORK
    assert window.stack.currentWidget() is window.centre
    assert "Double-click" in window.centre.preview._page.message
    window.state.set_deck(COURSE)
    assert window.slide_list.deck is COURSE
    decks[:] = [WORK]                                               # course archived or removed
    window.reload_decks()
    assert window.slide_list.deck is WORK


def test_reload_follows_an_archived_deck_and_falls_back_when_it_is_gone(window, monkeypatch):
    window.state.set_deck(COURSE)
    archived = make_deck("course", ["course"], archived=True)
    monkeypatch.setattr(window_module, "scan_decks", lambda: [WORK, archived])
    window.reload_decks()
    assert window.state.deck is archived
    monkeypatch.setattr(window_module, "scan_decks", lambda: [WORK])
    window.reload_decks()
    assert window.state.deck is WORK


def test_a_project_without_decks_shows_a_placeholder_and_offers_the_manual_where_it_can_be_added(qapp, monkeypatch):
    monkeypatch.setattr(window_module, "scan_decks", lambda: [])
    window = build_window(monkeypatch)
    assert window.state.deck is None
    assert "no decks" in window.centre.preview._page.message
    assert window.topbar._deck_button.text() == "No deck"
    assert not window.topbar._compile.isEnabled()
    assert window.body.currentWidget() is window.no_decks
    added = []
    monkeypatch.setattr(window, "can_add_manual", lambda: True)
    monkeypatch.setattr(window, "_on_add_manual", lambda: added.append(1))
    window.no_decks.refresh()
    assert window.no_decks.manual.isEnabled()
    window.no_decks.manual.clicked.emit()
    assert added == [1]
    monkeypatch.setattr(window, "can_add_manual", lambda: False)
    window.no_decks.refresh()
    assert not window.no_decks.manual.isEnabled()
    monkeypatch.setattr(window_module, "scan_decks", lambda: [WORK])
    window.reload_decks()
    assert window.body.currentWidget() is not window.no_decks    # decks again: the workspace is back


# -- view, language, compile label ----------------------------------------------

def test_view_and_language_controls_drive_the_state_and_follow_it(window):
    bar = window.topbar
    window.state.set_deck(COURSE)
    bar._views._buttons["during-course"].click()
    bar._languages._buttons["DE"].click()
    assert (window.state.view, window.state.language) == ("during-course", "DE")
    window.state.set_view("after-course")                           # e.g. restored for another deck
    window.state.set_language("EN")
    assert bar._views.current() == "after-course" and bar._languages.current() == "EN"


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
    full = items(build_compile_menu(None, command_context(COURSE)))
    assert list(full) == [
        "compile:instructor", "compile:during-course", "compile:after-course", "compile:all",
        "compile:chapters", "compile:presenter", "compile:slides", "compile:pages", "compile:several",
        "compile:everything", "transcript:during-course", "transcript:after-course", "stop", "build_options"]
    assert full["compile:chapters"] and not full["stop"] and not full["compile:slides"]   # no slide selected
    assert items(build_compile_menu(None, command_context(COURSE, selected=('aaa', 'bbb'))))["compile:slides"]
    plain = items(build_compile_menu(None, command_context(make_deck("plain", versions=False))))
    assert list(plain) == ["compile:instructor", "compile:all", "compile:chapters", "compile:presenter",
                           "compile:slides", "compile:pages", "compile:several", "compile:everything",
                           "stop", "build_options"]
    assert not plain["compile:chapters"]                              # no \section chapters
    assert items(build_compile_menu(None, command_context(COURSE, compiling=True)))["stop"]


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
    assert window.log_drawer.text.toPlainText().splitlines()[-1] == "==== Done: 1 passed ===="


# -- Images and the pages ----------------------------------------------------------

def test_centre_stack_size_hints_follow_the_shown_page(window, monkeypatch, qapp):
    monkeypatch.setattr(window.images_page, "ensure_loaded", lambda: None)
    window.state.set_mode("preview")
    window.show()
    qapp.processEvents()
    assert window.centre.minimumSizeHint().width() <= 400
    assert window.images_page.minimumSizeHint().width() <= 700
    assert window.images_page.minimumSizeHint().width() > window.centre.minimumSizeHint().width()
    for page in (window.centre, window.images_page, window.centre):
        window.stack.setCurrentWidget(page)
        qapp.processEvents()
        assert window.stack.minimumSizeHint() == page.minimumSizeHint()
        assert window.stack.sizeHint() == page.sizeHint()


def test_images_button_toggles_the_images_page(window, monkeypatch):
    monkeypatch.setattr(window.images_page, "ensure_loaded", lambda: None)
    window.state.set_mode("source")
    window.show()
    bar = window.topbar
    assert window.slide_list.isVisible() and window.side_panels.isVisible()
    assert bar._images.text() == "Images"
    bar._images.click()
    assert window.stack.currentWidget() is window.images_page and bar._images.text() == "Close images"
    assert not window.slide_list.isVisible() and not window.side_panels.isVisible()
    bar._images.click()
    assert window.stack.currentWidget() is window.centre and bar._images.text() == "Images"
    assert window.slide_list.isVisible() and window.side_panels.isVisible()
    window._toggle_images()
    window.images_page.closed.emit()
    assert window.stack.currentWidget() is window.centre
    assert window.slide_list.isVisible() and window.side_panels.isVisible()
    window._toggle_images()
    bar._modes.changed.emit(window.state.mode)  # clicking the mode that is already set also leaves Images
    assert window.stack.currentWidget() is window.centre


def test_a_slide_editor_opens_in_the_centre_and_unsaved_edits_show_in_the_top_bar(window, tmp_path, monkeypatch):
    redraws = []
    monkeypatch.setattr(window.slide_list, "rebuild", lambda: redraws.append(True))
    path = tmp_path / "abc-EN-Test-current.tex"
    path.write_text("\\slide{abc-EN-Test}\nBODY\n", encoding="utf-8", newline="")
    window.open_slide_editor(path)
    file = window.centre.source.current
    assert window.stack.currentWidget() is window.centre and window.state.mode == "source"
    assert file.path == path and window.topbar._save.text() == "Saved"
    file.editor.insertPlainText("x")
    assert window.topbar._save.text() == "Unsaved changes" and window.state.dirty
    assert redraws == []                                          # still being edited
    file.editor.mark_saved()
    assert window.topbar._save.text() == "Saved" and not window.state.dirty
    assert redraws


def test_opening_a_slide_focuses_it(window):
    from slidemage import slide_ids

    slide = next(iter(slide_ids.SLIDES_DIR.glob("*-current.tex")))
    window.open_slide_editor(slide)
    assert window.state.focused_slide == slide.name.split("-", 1)[0]


# -- the slide list in the window ----------------------------------------------------

def test_an_edit_rescans_and_the_slide_list_keeps_what_it_takes_to_undo_it(window, monkeypatch):
    rescans = []
    monkeypatch.setattr(window, "_regenerate_headers_bg", lambda: None)
    monkeypatch.setattr(window, "resync_deck", rescans.append)
    window.after_deck_edit(WORK.path, "Removed x", previous_text="the text before")
    assert rescans == [WORK.path]
    assert window.slide_list._undo[WORK.path] == ["the text before"]
    assert not window.slide_list.toast.isHidden()
    window.after_deck_edit(WORK.path, "Undid last change")        # an undo has nothing to undo itself
    assert window.slide_list._undo[WORK.path] == ["the text before"]


def test_the_slide_lists_slides_are_compiled_as_the_frames_they_have_in_the_last_pdf(window, monkeypatch):
    seen, warned = [], []
    monkeypatch.setattr(window, "_compile_current", lambda kind, pages=None: seen.append((kind, pages)))
    monkeypatch.setattr(window_module.QMessageBox, "warning", lambda *a: warned.append(a[2]))
    monkeypatch.setattr(window_module.QMessageBox, "information", lambda *a: warned.append(a[2]))
    asked = []
    from slidemage import partial_compile
    monkeypatch.setattr(partial_compile, "frames_for_slides",
                        lambda job, ids: asked.append(ids) or [4, 7])
    window.state.set_view("during-course")
    window._compile_slides(["1ab", "1cd"])
    assert asked == [["1ab", "1cd"]] and seen == [("during-course", [4, 7])]
    monkeypatch.setattr(partial_compile, "frames_for_slides", lambda job, ids: [])
    window._compile_slides(["1ab"])
    assert "None of these slides" in warned[-1] and len(seen) == 1
    def refuse(job, ids):
        raise partial_compile.PartialError("compile the whole deck once")
    monkeypatch.setattr(partial_compile, "frames_for_slides", refuse)
    window._compile_slides(["1ab"])
    assert warned[-1] == "compile the whole deck once" and len(seen) == 1


# -- the ⋮ menu: nothing of the old deck table and menu bar is lost --------------------

def test_a_deck_command_runs_with_the_current_deck(window, monkeypatch):
    window.state.set_deck(COURSE)
    seen: list = []
    monkeypatch.setattr(window, "_on_duplicate_deck", seen.append)
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
    enabled = items(build_more_menu(None, command_context(deck)))
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


# -- the centre column in the window ---------------------------------------------------

def test_the_mode_switch_of_the_top_bar_drives_the_state_and_follows_it(window):
    bar = window.topbar
    assert bar._modes.isEnabled() and bar._modes.current() == "preview"
    bar._modes._buttons["source"].click()
    assert window.state.mode == "source" and window.centre.source.isVisibleTo(window.centre)
    window.state.set_mode("details")
    assert bar._modes.current() == "details" and window.centre.details.isVisibleTo(window.centre)


def test_a_saved_deck_source_goes_through_the_deck_edit_pipeline(window, tmp_path, monkeypatch):
    from slidemage.ui.workspace import source_file

    path = tmp_path / "course.tex"
    path.write_text("\\begin{document}\n\\end{document}\n", encoding="utf-8")
    deck = make_deck("course", ["course"])
    deck.path = path
    edits = []
    monkeypatch.setattr(window, "after_deck_edit", lambda *args, **kwargs: edits.append((args, kwargs)))
    monkeypatch.setattr(source_file, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(source_file.slide_source, "BACKUPS_DIR", tmp_path / ".backups")
    window.open_deck_source_editor(deck)
    window.centre.source.current.editor.insertPlainText("% hand edit\n")
    assert window.centre.source.save()
    assert edits == [((path, "Edited course's source directly"),
                      {"previous_text": "\\begin{document}\n\\end{document}\n"})]


def test_the_bib_is_sorted_when_it_is_opened_and_when_it_is_left(window, tmp_path, monkeypatch):
    from slidemage import bibliography

    bib = tmp_path / "Slidemaster.bib"
    bib.write_text("@book{a, title={A}}\n", encoding="utf-8")
    monkeypatch.setattr(bibliography, "DEFAULT_BIB", bib)
    sorted_ = []
    monkeypatch.setattr(bibliography, "sort_entries", lambda: sorted_.append(True))
    window._on_edit_bib()
    assert sorted_ == [True] and window.centre.source.current.path == bib
    window._on_edit_bib()                                   # already open: nothing to sort under it
    assert sorted_ == [True]
    window.centre.source.show_path(None)                    # leaving the clean buffer closes it
    assert sorted_ == [True, True]


def test_leaving_the_images_page_saves_a_pending_edit_and_opening_a_slide_leaves_it(window, monkeypatch):
    monkeypatch.setattr(window.images_page, "ensure_loaded", lambda: None)
    flushed = []
    monkeypatch.setattr(window.images_page, "flush", lambda: flushed.append(True))
    window._toggle_images()
    assert flushed == []
    window._toggle_images()
    assert flushed == [True]
    window._toggle_images()
    window.open_slide_editor(Path(__file__))          # the Source view replaces the page
    assert window.stack.currentWidget() is window.centre and flushed == [True, True]


def test_the_slide_lists_images_entry_lands_on_that_slides_images(window, monkeypatch):
    monkeypatch.setattr(window.images_page, "ensure_loaded", lambda: None)
    shown = []
    monkeypatch.setattr(window.images_page, "show_slide", shown.append)
    window.open_images_for_slide("1an-EN-Slide-Versions")
    assert window.stack.currentWidget() is window.images_page and shown == ["1an-EN-Slide-Versions"]


def test_closing_asks_about_unsaved_image_edits_and_stops_the_page_s_job(window, monkeypatch):
    page, saved, stopped = window.images_page, [], []
    page.dirty = True                                  # what a form with a pending edit sets
    monkeypatch.setattr(page, "flush", lambda: (saved.append(True), setattr(page, "dirty", False)))
    monkeypatch.setattr(page, "shutdown", lambda: stopped.append(True))
    asked = []

    def answer(choice):
        def question(_parent, _title, text, *_args):
            asked.append(text)
            return choice
        return question

    monkeypatch.setattr(QMessageBox, "question", answer(QMessageBox.StandardButton.Cancel))
    assert window._resolve_dirty_edits() is False and saved == []
    assert len(asked) == 1
    monkeypatch.setattr(QMessageBox, "question", answer(QMessageBox.StandardButton.No))
    assert window._resolve_dirty_edits() is True and saved == []        # discarded: closing goes on
    monkeypatch.setattr(QMessageBox, "question", answer(QMessageBox.StandardButton.Yes))
    assert window._resolve_dirty_edits() is True and saved == [True]
    window.close()
    assert stopped == [True]                                           # no worker thread outlives the window


def test_theme_and_tab_width_changes_reach_the_open_editors(window, tmp_path, monkeypatch):
    path = tmp_path / "abc-EN-Test-current.tex"
    path.write_text("\\slide{abc-EN-Test}\nBODY\n", encoding="utf-8", newline="")
    window.open_slide_editor(path)
    editor = window.centre.source.current.editor
    repainted = []
    monkeypatch.setattr(editor, "refresh_colors", lambda: repainted.append(True))
    monkeypatch.setattr(window.theme, "set_dark", lambda dark: None)     # no app-wide restyle here
    window.set_dark_mode(True)
    assert repainted == [True]
    before = editor.tabStopDistance()
    window.set_tab_width_chars(4)
    assert editor.tabStopDistance() == pytest.approx(before * 2)
    assert app_settings.get("tab_width_chars") == 4


def test_the_build_options_footer_timestamp_is_the_states(window):
    box = window.build_options.footer_timestamp_checkbox
    assert not box.isChecked() and not window.state.footer_timestamp
    box.setChecked(True)
    assert window.state.footer_timestamp


def test_closing_asks_about_a_pending_side_panel_edit_too(window, monkeypatch):
    saved = []
    panel = window.side_panels.panels["transcript"]
    monkeypatch.setattr(panel, "flush", lambda: saved.append(True))
    panel.set_dirty(True)
    assert window.state.dirty                  # a panel's pending edit is an unsaved edit of the workspace
    asked = []

    def answer(_parent, _title, text, *_args):
        asked.append(text)
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "question", answer)
    assert window._resolve_dirty_edits() is False
    assert len(asked) == 1 and saved == []
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    assert window._resolve_dirty_edits() is True and saved == [True]


def test_closing_the_window_aborts_and_joins_a_running_ai_check(window, tmp_path, monkeypatch):
    import threading

    from slidemage.ai.providers import OllamaProvider
    from slidemage.syntax_check import SyntaxCheckResult
    from slidemage.ui.workspace import ai_fix

    path = tmp_path / "abc-EN-Test-current.tex"
    path.write_text("\\slide{abc-EN-Test}\nBODY\n", encoding="utf-8", newline="")
    held, aborted = threading.Event(), threading.Event()

    class Checker:
        def __init__(self, provider):
            pass

        def check(self, text):
            held.wait(10)
            return SyntaxCheckResult(model="m", error="Aborted.", cancelled=True)

        def abort(self):
            aborted.set()
            held.set()

    monkeypatch.setattr(OllamaProvider, "list_models", lambda self, vision_only=False: ["m"])
    monkeypatch.setattr(ai_fix, "provider_from_combo", lambda *a: type("P", (), {"label": "m", "is_local": True})())
    monkeypatch.setattr(ai_fix.syntax_check, "SyntaxChecker", Checker)
    window.open_slide_editor(path)
    file = window.centre.source.current
    file.ask_ai_button.click()
    worker = file.fix_panel._worker
    assert worker is not None and worker.isRunning() and window._ollama_task_label == "checking syntax"
    window.state.set_mode("preview")           # the file is kept only because its check runs
    window.centre.source.show_path(None)
    assert file.keep_open

    assert window.close() is True
    assert aborted.is_set() and worker.isFinished()
    assert window._ollama_task_label is None and not file.fix_panel.running


def test_the_right_column_hosts_the_side_panels_and_is_refreshed_with_the_decks(window, monkeypatch):
    panels = window.side_panels
    refreshed = []
    monkeypatch.setattr(panels, "refresh", lambda: refreshed.append(True))
    window.reload_decks()                      # a rescan is no state change, so the window tells the panels
    window._on_dirty_changed(False)            # and a save changes the slide's versions
    window.centre.versions_changed.emit()
    assert len(refreshed) == 3


def test_the_right_column_is_resizable_and_its_width_is_remembered(qapp, monkeypatch):
    from slidemage.ui.workspace import side_panels

    first = build_window(monkeypatch)
    first.resize(2400, 800)
    first.show()
    first.set_right_column_width(520)
    first.splitter.splitterMoved.emit(0, 2)                                 # what a drag of the handle sends
    assert first.side_panels.width() == 520 and app_settings.get(side_panels.WIDTH_SETTING) == 520
    second = build_window(monkeypatch)
    second.resize(2400, 800)
    second.show()
    assert second.side_panels.width() == 520
