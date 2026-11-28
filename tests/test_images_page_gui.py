# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Images page navigation, editing, and background jobs."""
from __future__ import annotations

import threading
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QWidget

from slidemage import alt_archive, alt_blocks, alt_draft, alt_images, image_review
from slidemage.ai import ai_profile, resolver
from slidemage.ai.ai_profile import IMAGE_DESCRIPTION, Route
from fake_routes import FakeProvider
from slidemage.alt_blocks import SlideRow
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.pages import image_dialogs, image_runs, images
from slidemage.ui.pages.image_jobs import Job
from slidemage.ui.workspace.state import WorkspaceState
from slidemage.project import ProjectContext

CHART = "media/chart.png"


class FakeApp:
    def __init__(self, project) -> None:
        self.project = project
        self.theme = ThemeManager()
        self.slots: list[str] = []
        self.routes = []
        self.unsaved: set[Path] = set()     # slide files with unsaved edits in the Source view
        self.synced: list[Path] = []
        self.opened: list[Path] = []
        self.centre = SimpleNamespace(unsaved=lambda path: path in self.unsaved, sync_source=self.synced.append,
                                      slide_text=lambda path: path.read_text(encoding="utf-8"))

    def log(self, _line):
        pass

    def acquire_route_task(self, route_id, label):
        from slidemage.plugins.host import _RouteTaskLease
        self.slots.append("took")
        self.routes.append(route_id)
        return _RouteTaskLease(lambda: self.slots.append("gave"))

    def open_slide_editor(self, path):
        self.opened.append(path)


@pytest.fixture
def make_page(monkeypatch, qapp, tmp_path, ctx, fake_routes):
    """The page over two slides ("one": all `image_refs`, "two": the first) and an in-memory store."""

    def make(image_refs=None):
        image_refs = image_refs or [CHART]
        first = SlideRow(tmp_path / "one-current.tex", "one", "First", list(image_refs))
        second = SlideRow(tmp_path / "two-current.tex", "two", "Second", [image_refs[0]])
        for row in (first, second):
            row.path.write_text("slide text", encoding="utf-8")
        store = {reference: alt_images.ImageEntry(image=reference) for reference in image_refs}
        monkeypatch.setattr(alt_blocks, "scan_slides_raw", lambda _ctx: [first, second])
        monkeypatch.setattr(alt_blocks, "resolve_image", lambda _ctx, _reference: None)
        monkeypatch.setattr(alt_draft, "draftable_images", lambda _ctx, *_args: [])
        monkeypatch.setattr(alt_images, "sync_store", lambda _ctx: alt_images.SyncReport())
        monkeypatch.setattr(alt_images, "load_store", lambda _ctx: deepcopy(store))
        monkeypatch.setattr(alt_images, "slide_context_hash", lambda _path: "slide-hash")

        def update_store(_ctx, mutate):
            latest = deepcopy(store)
            changed = mutate(latest)
            if changed:
                store.clear()
                store.update(latest)
            return changed

        monkeypatch.setattr(alt_images, "update_store", update_store)
        app = FakeApp(ctx)
        page = images.ImagesPage(app, WorkspaceState(ctx), app.centre)
        page.reload()
        page.store, page.first, page.second = store, first, second
        return page

    return make


def run_jobs_inline(monkeypatch):
    monkeypatch.setattr(Job, "start", Job.run)


def choose_provider(monkeypatch, provider=None):
    provider = provider or FakeProvider("offline-test")
    monkeypatch.setattr(image_runs, "picked_route", lambda *_args: Route("fake_local", IMAGE_DESCRIPTION, "offline-test"))
    monkeypatch.setattr(resolver, "provider_for", lambda _ctx, _route: provider)


def type_into(page, key, text):
    page._forms[0].fields[key].setPlainText(text)


# the list

def test_images_page_minimum_width_fits_with_full_action_labels(make_page, qapp):
    from slidemage.ui.kit.fonts import load_fonts

    page = make_page([CHART, "media/second.png"])
    load_fonts()
    page.app.theme.apply()
    page.show()
    page.resize(700, 640)
    qapp.processEvents()
    assert page.minimumSizeHint().width() <= 700
    for button in (page.draft_button, page.clear_button, page.save_button, page.review_button):
        assert button.isVisible() and button.width() >= button.minimumSizeHint().width()
    scrollbar = page.scroll.horizontalScrollBar()
    assert scrollbar.isVisible() and scrollbar.maximum() > 0
    page.hide()


def test_find_slide_jumps_to_it_whatever_the_filter_shows(make_page, monkeypatch):
    page = make_page()
    page.store[CHART].short, page.store[CHART].long = "s", "l"
    page.store[CHART].status = alt_images.STATUS_REVIEWED
    page.nav.set_filter(0)
    page.reload()
    page.show_slide("two-second")
    assert image_review.FILTERS[page.nav.filter_index][0] == "All slides with images"
    assert page._current.row.slide_id == "two"
    told = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: told.append(args[2]))
    page.show_slide("zzz")
    assert "No slide matching" in told[0] and page._current.row.slide_id == "two"


# unsaved edits

def test_leaving_rescanning_and_switching_decks_save_pending_drafts(make_page):
    page = make_page()
    assert [view.row for view in page.nav.shown] == [page.first, page.second]
    assert page._current.row == page.first
    page.flush()
    assert page.store[CHART].used_on == {}
    type_into(page, "short", "typed short")
    type_into(page, "long", "typed long text")
    page.nav.slide_list.setCurrentRow(1)
    assert page._current.row == page.second and not page.dirty and not page.state.dirty
    saved = page.store[CHART]
    assert (saved.short, saved.long) == ("typed short", "typed long text")
    assert saved.status != alt_images.STATUS_REVIEWED and saved.used_on["one"].reviewed == ""
    assert page.nav.shown[0].state == alt_images.STATE_DRAFT

    type_into(page, "short", "rescanned")
    page.reload()
    assert page.store[CHART].short == "rescanned" and not page.dirty
    type_into(page, "short", "switched")
    page.state.set_deck(SimpleNamespace(path=Path("other.tex"), name="other", text="", is_test_deck=True))
    assert page.store[CHART].short == "switched" and not page.dirty


def test_save_merges_human_edit_with_worker_updates_across_visible_images(make_page, monkeypatch):
    second_ref = "media/second.png"
    page = make_page([CHART, second_ref])
    chart = alt_images.ImageEntry(
        CHART, short="worker short", takeaway_default="worker takeaway",
        used_on={"one": alt_images.SlideUse(takeaway="worker override", takeaway_de="worker override DE")},
        short_de="worker short DE", long_de="worker long DE", takeaway_default_de="worker default DE")
    other = alt_images.ImageEntry(
        second_ref, long="worker description", drafted_by="offline-worker", hint="worker hint",
        short_de="second short DE", long_de="second long DE",
        takeaway_default="second EN takeaway", takeaway_default_de="second DE takeaway")
    for worker_entry in (chart, other):
        worker_entry.translated_from_hash = alt_images.en_text_hash(worker_entry)
        page.store[worker_entry.image] = worker_entry

    form = page._forms[0]
    type_into(page, "long", "HUMAN ENGLISH EDIT")

    assert page.dirty and page.state.dirty
    monkeypatch.setattr(page, "reload", lambda *_args: pytest.fail("batch completion reloaded an edited form"))
    page._drafted(alt_draft.BatchSummary())
    page._translated(alt_draft.TranslationBatchSummary(written=2))
    assert page._forms[0] is form
    assert form.fields["long"].toPlainText() == "HUMAN ENGLISH EDIT"
    assert form.fields["short"].toPlainText() == "" and form.saved_english()[0] == chart.short
    page._save(reviewed=False)

    saved = page.store[CHART]
    assert saved.long == "HUMAN ENGLISH EDIT" and saved.short == chart.short
    assert saved.takeaway_default == chart.takeaway_default
    assert saved.takeaway_for("one") == chart.takeaway_for("one")
    assert saved.takeaway_in("one", "de") == chart.takeaway_in("one", "de")
    assert saved.texts["de"] == chart.texts["de"]
    assert alt_images.translation_state(saved) == alt_images.STATE_STALE
    untouched = page.store[second_ref]
    assert untouched.texts == other.texts
    assert (untouched.drafted_by, untouched.hint) == (other.drafted_by, other.hint)


def test_set_default_keeps_worker_fields_and_invalidates_stale_human_translation(make_page):
    page = make_page()
    entry = page.store[CHART]
    entry.short, entry.long = "worker's new English short", "worker's new English long"
    entry.short_de, entry.long_de = "worker short DE", "worker long DE"
    entry.translated_from_hash = alt_images.en_text_hash(entry)

    type_into(page, "takeaway", "human's chosen default")
    page._forms[0]._set_default()
    type_into(page, "short_tr", "human German edit based on old form")
    page._save(reviewed=False)

    saved = page.store[CHART]
    assert (saved.short, saved.long) == ("worker's new English short", "worker's new English long")
    assert saved.takeaway_default == "human's chosen default" and saved.long_de == "worker long DE"
    assert saved.short_de == "human German edit based on old form"
    assert saved.translated_from_hash == "" and alt_images.translation_state(saved) == alt_images.STATE_STALE


# reviewing

def test_review_is_refused_while_an_informative_image_has_no_long_description(make_page, monkeypatch):
    page = make_page()
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warned.append(args[2]))
    type_into(page, "short", "only a short one")
    assert page._save(reviewed=True) is False
    assert CHART in warned[0] and page.store[CHART].short == ""
    form = page._forms[0]
    form.roles.set_current(alt_images.ROLE_DECORATIVE)
    form._on_role(alt_images.ROLE_DECORATIVE)
    assert {key for key, edit in form.fields.items() if edit.isEnabled()} == {"source", "source_tr"}
    assert form.changed and page.dirty
    assert page._save(reviewed=True) and page.store[CHART].role == alt_images.ROLE_DECORATIVE
    assert page.store[CHART].used_on["one"].reviewed and not page.dirty
    assert [view.row for view in page.nav.shown] == [page.second] and page._current.row == page.second


def test_set_as_default_needs_a_takeaway_on_an_informative_image(make_page):
    page = make_page()
    form = page._forms[0]
    assert not form.default_button.isEnabled()
    type_into(page, "takeaway", "why it is here")
    assert form.default_button.isEnabled()
    form.roles.set_current(alt_images.ROLE_DECORATIVE)
    form._on_role(alt_images.ROLE_DECORATIVE)
    assert not form.default_button.isEnabled()
    form.roles.set_current(alt_images.ROLE_INFORMATIVE)
    form._on_role(alt_images.ROLE_INFORMATIVE)
    type_into(page, "takeaway", "")
    form._set_default()
    assert page.store[CHART].takeaway_default == ""


def test_translate_requires_english_text_and_a_model(make_page):
    page = make_page()
    form = page._forms[0]
    page.translate_model.setEnabled(True)
    page._update_buttons()
    assert not form.translate_button.isEnabled() and not form.save_translate_button.isEnabled()
    type_into(page, "takeaway", "Sales rise")
    assert form.translate_button.isEnabled() and form.save_translate_button.isEnabled()
    page.translate_model.setEnabled(False)
    page._update_buttons()
    assert not form.translate_button.isEnabled() and not form.save_translate_button.isEnabled()


def test_clear_draft_discards_unreviewed_text_only(make_page, monkeypatch):
    page = make_page()
    page.store[CHART].short, page.store[CHART].long, page.store[CHART].drafted_by = "s", "l", "model"
    page.reload()
    type_into(page, "short", "typed on top of the draft")
    assert page.dirty
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    page._clear_draft()
    cleared = page.store[CHART]
    assert (cleared.short, cleared.long, cleared.drafted_by) == ("", "", "")
    assert page._forms[0].fields["short"].toPlainText() == "" and not page.dirty
    page.flush()
    assert page.store[CHART].short == ""  # pending edits must not recreate the draft
    told = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: told.append(args[2]))
    page._clear_draft()
    assert "unreviewed" in told[0]


# the slide's own actions

def test_open_in_source_and_transcript_preview_use_the_slide_on_show(make_page, monkeypatch):
    page = make_page()
    page._open_source()
    assert page.app.opened == [page.first.path]
    shown = []
    monkeypatch.setattr(images, "show_transcript_preview", lambda *args: shown.append(args))
    page._preview_transcript()
    app, text, bare, id_slug, view, language = shown[0]
    assert (text, bare, id_slug, language) == ("slide text", "one", "one", "en") and view == page.state.view


# drafting and translating: jobs

class FakeBackend:
    def __init__(self, _ctx, provider, **_kwargs):
        self.provider, self.label = provider, "offline-test"

    def draft(self, _path, _context):
        return alt_draft.DraftResult(short="drafted short", long="drafted long", takeaway="take", model="offline-test")


def test_draft_slide_tells_when_empty_then_saves_a_draft_and_releases_the_route(make_page, monkeypatch):
    page = make_page()
    told = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: told.append(args[1]))
    page._draft_slide()
    assert told == ["Nothing to draft"] and page.app.slots == []

    run_jobs_inline(monkeypatch)
    route = Route("fake_cloud", IMAGE_DESCRIPTION, "offline-test")
    backend = FakeBackend(None, FakeProvider("offline-test"))
    monkeypatch.setattr(page, "_draft_backend", lambda: (route, backend))
    monkeypatch.setattr(alt_draft, "build_context", lambda _ctx, *_args: None)
    monkeypatch.setattr(alt_draft, "slide_jobs", lambda _ctx, row, entries: [
        alt_draft.ImageJob(CHART, Path("chart.png"), row.slide_id, row.path)])
    page._draft_slide()
    assert page.app.slots == ["took", "gave"] and page.app.routes == [route.route]
    assert page._job is None and page.job_card.isHidden()
    drafted = page.store[CHART]
    assert (drafted.short, drafted.long, drafted.drafted_by) == ("drafted short", "drafted long", "offline-test")
    assert page._forms[0].fields["short"].toPlainText() == drafted.short
    assert page.nav.shown[0].state == alt_images.STATE_DRAFT


def wait_for(condition, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    return condition()


def test_stop_ends_a_batch_after_the_current_image_and_takes_the_click_back(make_page, monkeypatch):
    second = "media/second.png"
    page = make_page([CHART, second])
    started, release = threading.Event(), threading.Event()

    class Backend(FakeBackend):
        def draft(self, _path, _context):
            started.set()
            release.wait(5)
            return super().draft(_path, _context)

    choose_provider(monkeypatch)
    monkeypatch.setattr(alt_draft, "ModelBackend", Backend)
    monkeypatch.setattr(alt_draft, "build_context", lambda _ctx, *_args: None)
    queue = [alt_draft.ImageJob(ref, Path("x.png"), "one", page.first.path) for ref in (CHART, second)]
    monkeypatch.setattr(alt_draft, "images_needing_drafts", lambda _ctx, **_kwargs: queue)
    monkeypatch.setattr(QMessageBox, "exec", lambda box: QMessageBox.StandardButton.Ok)
    page._draft_all()
    job = page._job
    assert job is not None and not page.draft_all_button.isEnabled() and not page.job_card.isHidden()
    assert wait_for(started.is_set)
    page._stop_clicked()
    assert job.stop_requested and "Stopping" in page.job_card.stop.text()
    page._stop_clicked()
    assert not job.stop_requested and page.job_card.stop.text() == "Stop"
    page._stop_clicked()
    release.set()
    assert wait_for(lambda: page._job is None)
    assert page.store[CHART].short and not page.store[second].short
    assert page.app.slots == ["took", "gave"] and page.draft_all_button.isEnabled()


def test_closing_the_window_stops_a_running_job_and_gives_the_slot_back(make_page):
    page = make_page()
    release = threading.Event()
    provider = FakeProvider("offline-test")
    aborted = []
    provider.abort = lambda: (aborted.append(True), release.set())

    def work(job):
        release.wait(5)
        return alt_draft.BatchSummary()

    lease = page.app.acquire_route_task("fake_local", "test")
    job = Job("Drafting", provider, work, Route("fake_local", IMAGE_DESCRIPTION, "offline-test"))
    page._start(job, "one image", 5, lambda outcome: None, lease)
    assert job.isRunning()
    job.position = (3, 5)
    [running] = page.running_work()
    assert (running.text, running.route, running.local) == ("Drafting · 2 of 5 done", "offline-test", True)
    assert running.stop == page._abort_job
    page.shutdown()
    assert page.running_work() == []
    assert aborted == [True] and page._job is None
    assert wait_for(job.isFinished) and wait_for(lambda: page.app.slots == ["took", "gave"])


# translating one image

def translated(entry):
    return alt_draft.TranslationResult(short_de="translated short", long_de="translated long",
                                       takeaway_de="translated takeaway", source_hash=alt_images.en_text_hash(entry))


def use_translator(monkeypatch, translate=translated, provider=None):
    choose_provider(monkeypatch, provider)
    monkeypatch.setattr(alt_draft, "ModelTranslationBackend", lambda _ctx, provider, **_kwargs:
                        SimpleNamespace(translate=translate, label="offline-test", provider=provider))


def unsaved_draft(monkeypatch):
    monkeypatch.setattr(images.ImagesPage, "_ask_which_english", lambda page: "unsaved")


@pytest.mark.parametrize("edited", [False, True], ids=["current", "german-edit-after-completion"])
def test_unsaved_english_translation_tracks_edits_after_completion(make_page, monkeypatch, edited):
    page = make_page()
    type_into(page, "long", "UNSAVED ENGLISH TO TRANSLATE")
    unsaved_draft(monkeypatch)
    run_jobs_inline(monkeypatch)
    use_translator(monkeypatch)
    form = page._forms[0]
    page._translate_image(form, False)
    assert "matches the current English text" in form.translation_state.text()
    assert page.app.slots == ["took", "gave"]
    translated_hash = form.provenance["source_hash"]
    if edited:
        type_into(page, "long_tr", "HUMAN GERMAN EDIT AFTER TRANSLATION")
    page._save(reviewed=False)
    saved = page.store[CHART]
    assert saved.long == "UNSAVED ENGLISH TO TRANSLATE"
    if edited:
        assert saved.long_de == "HUMAN GERMAN EDIT AFTER TRANSLATION" and saved.translated_from_hash == ""
        assert alt_images.translation_state(saved) == alt_images.STATE_STALE
    else:
        assert saved.translated_from_hash == translated_hash
        assert alt_images.translation_state(saved) == alt_images.STATE_REVIEWED


def test_translation_completion_keeps_newer_english_and_human_german_stale(make_page, monkeypatch):
    page = make_page()
    type_into(page, "long", "ENGLISH AT REQUEST TIME")
    unsaved_draft(monkeypatch)
    form = start_translation(page, monkeypatch)
    type_into(page, "long", "NEWER ENGLISH AFTER REQUEST")
    type_into(page, "short_tr", "HUMAN GERMAN EDIT DURING REQUEST")
    page._job.run()
    assert form.fields["short_tr"].toPlainText() == "HUMAN GERMAN EDIT DURING REQUEST"
    assert form.fields["long_tr"].toPlainText() == "translated long"
    assert form.fields["takeaway_tr"].toPlainText() == "translated takeaway"
    page._save(reviewed=False)
    saved = page.store[CHART]
    assert saved.long == "NEWER ENGLISH AFTER REQUEST" and saved.short_de == "HUMAN GERMAN EDIT DURING REQUEST"
    assert saved.translated_from_hash == "" and alt_images.translation_state(saved) == alt_images.STATE_STALE


def test_save_then_translate_translates_what_was_just_saved(make_page, monkeypatch):
    page = make_page()
    type_into(page, "long", "ENGLISH TO SAVE FIRST")
    run_jobs_inline(monkeypatch)
    sent = []

    def translate(entry):
        sent.append(entry.long)
        return translated(entry)

    use_translator(monkeypatch, translate)
    page._translate_image(page._forms[0], True)
    assert page.store[CHART].long == "ENGLISH TO SAVE FIRST" and sent == ["ENGLISH TO SAVE FIRST"]
    assert page._forms[0].fields["long_tr"].toPlainText() == "translated long"


def test_a_failed_translation_says_so_and_frees_the_form(make_page, monkeypatch):
    page = make_page()
    run_jobs_inline(monkeypatch)
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warned.append(args[2]))

    def unreachable(_entry):
        raise RuntimeError("model unreachable")

    use_translator(monkeypatch, unreachable)
    form = page._forms[0]
    type_into(page, "short", "A chart")
    unsaved_draft(monkeypatch)
    page._translate_image(form, False)
    assert warned == ["model unreachable"] and not form.translating and page._job is None
    assert form.translate_button.text() == "Translate" and form.translate_button.isEnabled()


def test_switching_slides_during_a_translation_asks_and_restores_selection(make_page, qapp, monkeypatch):
    page = make_page()
    form = start_translation(page, monkeypatch)
    page.resize(1100, 700)
    page.show()
    qapp.processEvents()
    replies = iter((QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: next(replies))
    click_row(page, 1)
    qapp.processEvents()
    slide_list = page.nav.slide_list
    assert page._current.row == page.first and page._forms == [form]
    assert slide_list.currentRow() == 0
    assert [slide_list.row(item) for item in slide_list.selectedItems()] == [0]
    click_row(page, 1)
    qapp.processEvents()
    assert page._current.row == page.second
    page.hide()


def start_translation(page, monkeypatch):
    monkeypatch.setattr(Job, "start", lambda job: None)
    use_translator(monkeypatch)
    page._translate_image(page._forms[0], False)
    return page._forms[0]


def test_a_reviewed_save_during_a_translation_is_not_undone_by_a_draft_save(make_page, monkeypatch):
    page = make_page()
    page.nav.set_filter(image_review.FILTER_ALL)
    page._populate(page._current_path())
    form = start_translation(page, monkeypatch)
    type_into(page, "short", "a short description")
    type_into(page, "long", "a long description")
    assert page._save(reviewed=True) and not page.dirty
    assert page.store[CHART].status == alt_images.STATUS_REVIEWED
    page.flush()
    assert page.store[CHART].status == alt_images.STATUS_REVIEWED and form.translating


def test_filter_order_and_deck_keep_translation_but_find_and_rescan_ask(make_page, monkeypatch):
    page = make_page()
    shown = page._current
    form = start_translation(page, monkeypatch)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: pytest.fail("asked although the slide stays"))
    page.nav._on_filter(str(image_review.FILTER_ALL))

    monkeypatch.setattr(image_review, "sort_order", lambda deck: {"two": 0, "one": 1})
    page.state.set_deck(SimpleNamespace(path=Path("deck.tex"), name="deck", text="", is_test_deck=False))
    page.nav.orders.set_current("files")
    page.nav.orders.changed.emit("files")
    assert page.nav.slide_list.currentRow() == 0
    page.nav.orders.set_current("deck")
    page.nav.orders.changed.emit("deck")
    assert [view.row.slide_id for view in page.nav.shown] == ["two", "one"]
    assert page.nav.slide_list.currentRow() == 1
    assert page._current is shown and page._forms == [form] and page._translation_in_flight()

    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    page.show_slide("two")
    page._on_rescan()
    assert page._current is shown and page._forms == [form]
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    page.show_slide("two")
    assert page._current.row == page.second


def test_stop_on_a_single_translation_aborts_it_at_once(make_page, monkeypatch):
    page = make_page()
    release = threading.Event()
    provider = FakeProvider("offline-test")
    provider.abort = release.set
    def translate(_entry):
        release.wait(5)
        return alt_draft.TranslationResult(error="aborted")

    use_translator(monkeypatch, translate, provider)
    form = page._forms[0]
    page._translate_image(form, False)
    assert form.translating and page.job_card.single
    page._stop_clicked()
    assert not form.translating and page._job is None
    assert wait_for(lambda: page.app.slots == ["took", "gave"])


# replacing an image

def pick_replacement(monkeypatch, tmp_path, *, on_others):
    source = tmp_path / "picked.png"
    source.write_bytes(b"png")
    sheet = SimpleNamespace(source=source, new_name="chart-new.png", exec=lambda: 1,
                            on_others=SimpleNamespace(isChecked=lambda: on_others))
    monkeypatch.setattr(images, "ReplaceImageSheet", lambda *_args: sheet)


def test_replace_image_repoints_clean_slides_and_refuses_one_with_unsaved_edits(make_page, monkeypatch, tmp_path):
    page = make_page()
    page.store[CHART].short = "described"
    page.store[CHART].used_on = {"one": alt_images.SlideUse(), "two": alt_images.SlideUse()}
    page.first.path.write_text(f"\\includegraphics{{{CHART}}}", encoding="utf-8")
    page.second.path.write_text(f"\\includegraphics{{{CHART}}}", encoding="utf-8")
    page.app.unsaved = {page.second.path}
    page.reload()
    pick_replacement(monkeypatch, tmp_path, on_others=True)
    warned, asked = [], []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warned.append(args[2]))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: asked.append(args[2]))
    page._replace_image(page._forms[0])
    assert (tmp_path / "media" / "chart-new.png").read_bytes() == b"png"
    assert "media/chart-new.png" in page.first.path.read_text(encoding="utf-8")
    assert CHART in page.second.path.read_text(encoding="utf-8")
    assert "could not be saved" in warned[0] and "two" in warned[0]
    assert page.app.synced == [page.first.path]
    assert asked == [] and CHART in page.store


def test_replace_image_offers_to_delete_the_orphaned_description(make_page, monkeypatch, tmp_path):
    page = make_page()
    page.store[CHART].short = "described"
    page.store[CHART].used_on = {"one": alt_images.SlideUse()}
    page.first.path.write_text(f"\\includegraphics{{{CHART}}}", encoding="utf-8")
    page.reload()
    pick_replacement(monkeypatch, tmp_path, on_others=False)
    deleted = []
    monkeypatch.setattr(alt_archive, "archive_images",
                        lambda _ctx, images, reason=None, **_kw: deleted.extend(images))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    page._replace_image(page._forms[0])
    assert deleted == [CHART]


def test_the_replace_sheet_validates_the_name_and_refuses_to_overwrite(qapp, monkeypatch, tmp_path):
    ctx = ProjectContext.at(tmp_path)
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "taken.png").write_bytes(b"x")
    sheet = image_dialogs.ReplaceImageSheet(None, ctx, "media/chart-old.png", ["2bb", "3cc"])
    assert not sheet.replace_button.isEnabled() and not sheet.on_others.isHidden()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(tmp_path / "new.JPG"), ""))
    sheet._choose()
    assert sheet.name_edit.text() == "chart-old" and sheet.new_name == "chart-old.jpg" and sheet.replace_button.isEnabled()
    sheet.name_edit.setText("a/b")
    sheet._validate()
    assert "path separators" in sheet.problem.text() and not sheet.replace_button.isEnabled()
    sheet.name_edit.setText("taken")
    sheet.extension.setText(".png")
    sheet._validate()
    assert "already exists" in sheet.problem.text() and not sheet.replace_button.isEnabled()
    # the suggestion is a free name even when the old file has the same stem and suffix
    (tmp_path / "media" / "chart-old.jpg").write_bytes(b"x")
    (tmp_path / "media" / "chart-old-2.jpg").write_bytes(b"x")
    sheet.name_edit.setText("")
    sheet._choose()
    assert sheet.new_name == "chart-old-3.jpg" and sheet.replace_button.isEnabled()


# tuning the prompt

def tuning_sheet(ctx, tmp_path, provider, monkeypatch):
    monkeypatch.setattr(alt_blocks, "resolve_image", lambda _ctx, _reference: None)
    window = QWidget()
    window.project = ctx
    window.log = lambda line: None
    context = alt_draft.SlideContext(slide_id="one", title="T", body="", source="", image="chart.png")
    finished = []
    sheet = image_dialogs.PromptTuningSheet(
        window, CHART, tmp_path / "chart.png", context, provider, "old hint", lambda: finished.append(True))
    return window, sheet, finished


def test_closing_the_tuning_sheet_stops_a_running_draft_and_hands_the_slot_back(ctx, qapp, monkeypatch, tmp_path):
    release = threading.Event()
    provider = FakeProvider("offline-test")
    provider.abort = release.set

    def draft(_path, _context):
        release.wait(5)
        return alt_draft.DraftResult(error="aborted")

    monkeypatch.setattr(alt_draft, "ModelBackend", lambda *_args, **_kwargs: SimpleNamespace(draft=draft))
    window, sheet, over = tuning_sheet(ctx, tmp_path, provider, monkeypatch)
    sheet._draft()
    job = sheet._job
    assert job.isRunning() and not sheet.draft_button.isEnabled() and not sheet.accept_button.isEnabled()
    sheet.reject()
    assert wait_for(job.isFinished) and over == [True]


def test_a_tuned_draft_can_be_accepted_with_its_hint(ctx, qapp, monkeypatch, tmp_path):
    provider = FakeProvider("offline-test")

    def draft(_path, context):
        return alt_draft.DraftResult(short=f"short with {context.hint}", long="long", takeaway="t", model="m",
                                     role_suggestion="informative")

    monkeypatch.setattr(alt_draft, "ModelBackend", lambda *_args, **_kwargs: SimpleNamespace(draft=draft))
    run_jobs_inline(monkeypatch)
    window, sheet, over = tuning_sheet(ctx, tmp_path, provider, monkeypatch)
    sheet.hint_edit.setPlainText("the y-axis maximum is 6800")
    sheet._draft()
    assert sheet.accept_button.isEnabled() and sheet.result_draft.short == "short with the y-axis maximum is 6800"
    assert "SHORT" in sheet.output.toPlainText() and sheet.hint == "the y-axis maximum is 6800"
    sheet.accept()
    assert over == [True]


# navigation during translation

def click_row(page, row):
    slide_list = page.nav.slide_list
    QTest.mouseClick(slide_list.viewport(), Qt.MouseButton.LeftButton,
                     pos=slide_list.visualItemRect(slide_list.item(row)).center())


def test_a_show_filter_that_drops_the_slide_asks_during_a_translation_and_no_restores_it(make_page, monkeypatch):
    page = make_page()
    shown, form = page._current, page._forms[0]
    page._translating = form
    reviewed = next(i for i, (label, _) in enumerate(image_review.FILTERS) if label == "Reviewed")
    answers = iter((QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: next(answers))
    page.nav._on_filter(str(reviewed))
    assert page.nav.filter_index == 0 and len(page.nav.shown) == 2
    assert page._current is shown and page._forms[0] is form

    page.nav._on_filter(str(reviewed))
    assert page.nav.filter_index == reviewed and page.nav.shown == []


# route availability

def test_image_actions_use_the_selected_route_and_refuse_missing_backends(make_page, ctx, fake_routes, monkeypatch):
    page = make_page()
    cloud = fake_routes.cloud
    ai_profile.set_mode(ctx, ai_profile.CLOUD)
    ai_profile.mark_cloud_seen(ctx)
    page.refresh_model_preferences()
    drafting_route, drafting = page._draft_backend()
    translating_route, translating = page._translation_backend("the text")
    assert drafting_route.route == translating_route.route == cloud.id
    assert drafting.provider in cloud.providers and translating.provider in cloud.providers

    told = []
    monkeypatch.setattr(QMessageBox, "critical", lambda _p, _t, text: told.append(text))
    cloud.problem_text = "The fake route is unavailable."
    page.refresh_model_preferences()
    page._translate_all()
    assert told.pop() == "The fake route is unavailable." and page._job is None

    cloud.problem_text = ""
    monkeypatch.setattr(cloud, "provider", lambda *_args: None)
    page.refresh_model_preferences()
    page._tune(page._forms[0])
    assert len(told) == 1 and "not available on Cloud · Fake cloud" in told[0]
    assert page.app.slots == []


def test_the_language_switch_follows_the_projects_languages(make_page, ctx):
    from slidemage import languages
    page = make_page()
    assert [button.text() for button in page.languages.buttons()] == ["EN", "DE"]
    languages.set_project_languages(ctx, "en", ["de", "fr"])
    page.state.refresh_languages()
    assert [button.text() for button in page.languages.buttons()] == ["EN", "DE", "FR"]
    page._set_language("fr")
    assert page._forms and all(form.second == "fr" for form in page._forms)
    languages.set_project_languages(ctx, "en", ["de"])
    page.state.refresh_languages()
    assert [button.text() for button in page.languages.buttons()] == ["EN", "DE"]
    assert page._language == "en" and all(form.second == "de" for form in page._forms)

