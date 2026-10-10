"""The Images page (ui/pages/images.py and friends): what its forms save, how a slide is left, and
how a drafting or translating job runs, stops and gives the Ollama slot back."""
from __future__ import annotations

import threading
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QWidget

from slidemage import alt_blocks, alt_draft, alt_images, image_review
from slidemage.ai.providers import OllamaProvider
from slidemage.alt_blocks import SlideRow
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.pages import image_dialogs, image_runs, images
from slidemage.ui.pages.image_jobs import Job
from slidemage.ui.workspace.state import WorkspaceState

CHART = "media/chart.png"


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class FakeApp:
    """What the page asks of the window."""

    def __init__(self) -> None:
        self.theme = ThemeManager()
        self.logged: list[str] = []
        self.slots: list[str] = []          # "took"/"gave" per Ollama slot call
        self.unsaved: set[Path] = set()     # slide files with unsaved edits in the Source view
        self.synced: list[Path] = []
        self.opened: list[Path] = []
        self.centre = SimpleNamespace(is_dirty=lambda path: path in self.unsaved, sync_source=self.synced.append,
                                      slide_text=lambda path: path.read_text(encoding="utf-8"))

    def log(self, line):
        self.logged.append(line)

    def try_start_ollama_task(self, _label, provider=None):
        self.slots.append("took")
        return True

    def end_ollama_task(self, provider=None):
        self.slots.append("gave")

    def open_slide_editor(self, path):
        self.opened.append(path)


@pytest.fixture
def make_page(monkeypatch, qapp, tmp_path):
    """The page over two slides ("one": all `image_refs`, "two": the first) and an in-memory store."""

    def make(image_refs=None):
        image_refs = image_refs or [CHART]
        first = SlideRow(tmp_path / "one-current.tex", "one", "First", list(image_refs))
        second = SlideRow(tmp_path / "two-current.tex", "two", "Second", [image_refs[0]])
        for row in (first, second):
            row.path.write_text("slide text", encoding="utf-8")
        store = {reference: alt_images.ImageEntry(image=reference) for reference in image_refs}
        sync_calls = []
        monkeypatch.setattr(alt_blocks, "scan_slides_raw", lambda: [first, second])
        monkeypatch.setattr(alt_blocks, "resolve_image", lambda _reference: None)
        monkeypatch.setattr(alt_draft, "draftable_images", lambda *_args: [])
        monkeypatch.setattr(alt_images, "sync_store", lambda: (sync_calls.append(True), alt_images.SyncReport())[1])
        monkeypatch.setattr(alt_images, "load_store", lambda: deepcopy(store))
        monkeypatch.setattr(alt_images, "slide_context_hash", lambda _path: "slide-hash")

        def update_store(mutate):
            latest = deepcopy(store)
            changed = mutate(latest)
            if changed:
                store.clear()
                store.update(latest)
            return changed

        monkeypatch.setattr(alt_images, "update_store", update_store)
        monkeypatch.setattr(OllamaProvider, "list_models", lambda self, vision_only=False: [])
        app = FakeApp()
        page = images.ImagesPage(app, WorkspaceState())
        page.reload()
        page.app, page.sync_calls, page.store, page.first, page.second = app, sync_calls, store, first, second
        return page

    return make


def run_jobs_inline(monkeypatch):
    """Jobs run on the calling thread, so that their result arrives at once."""
    monkeypatch.setattr(Job, "start", Job.run)


def choose_provider(monkeypatch, provider=None):
    monkeypatch.setattr(image_runs, "provider_from_combo", lambda *_args: provider or OllamaProvider("offline-test"))


def type_into(page, key, text, index=0):
    page._forms[index].fields[key].setPlainText(text)


# -- the list ------------------------------------------------------------------------------------


def test_the_page_lists_the_slides_with_images_and_shows_the_first(make_page):
    page = make_page()
    assert [view.row.slide_id for view in page.nav.shown] == ["one", "two"]
    assert page._current.row.slide_id == "one" and [form.reference for form in page._forms] == [CHART]
    assert page.nav.summary.text() == "0 reviewed · 0 need re-check · 0 draft · 2 undescribed"
    assert page.review_button.text() == "Save and mark reviewed"


def test_a_slide_with_several_images_says_all_images_on_its_review_button(make_page):
    page = make_page([CHART, "media/second.png"])
    assert len(page._forms) == 2 and page.review_button.text() == "Save and mark all images reviewed"
    page.nav.slide_list.setCurrentRow(1)
    assert len(page._forms) == 1 and page.review_button.text() == "Save and mark reviewed"


def test_the_no_german_filter_lists_slides_whose_image_has_english_but_no_german(make_page):
    page = make_page()
    no_german = [label for label, _ in image_review.FILTERS].index("No German")
    page.nav.set_filter(no_german)
    page._populate(None)
    assert page.nav.shown == []
    assert page.slide_title.text() == "No slide selected"
    page.store[CHART].short = "English text"
    page.reload()
    assert [view.row.slide_id for view in page.nav.shown] == ["one", "two"]
    page.store[CHART].short_de = "Deutscher Text"
    page.reload()
    assert page.nav.shown == []


def test_find_slide_jumps_to_it_whatever_the_filter_shows(make_page, monkeypatch):
    page = make_page()
    page.store[CHART].short, page.store[CHART].long = "s", "l"       # nothing needs attention any more
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


def test_the_order_follows_the_open_deck(make_page, monkeypatch):
    page = make_page()
    assert page._order() == {}                                    # no deck open
    page.state.deck = SimpleNamespace(is_test_deck=False)
    monkeypatch.setattr(image_review, "sort_order", lambda deck: {"two": 0, "one": 1})
    page._populate(None)
    assert [view.row.slide_id for view in page.nav.shown] == ["two", "one"]
    page.nav.orders.set_current("files")
    page._populate(None)
    assert [view.row.slide_id for view in page.nav.shown] == ["one", "two"]


# -- unsaved edits --------------------------------------------------------------------------------


def test_batch_completion_keeps_a_form_with_unsaved_edits(make_page):
    for finish, summary in ((lambda page, s: page._drafted(s), alt_draft.BatchSummary()),
                            (lambda page, s: page._translated(s), alt_draft.TranslationBatchSummary())):
        page = make_page()
        form = page._forms[0]
        type_into(page, "long", "UNSAVED HUMAN EDIT")
        assert page.dirty and page.state.dirty
        finish(page, summary)
        assert page._forms[0] is form and form.fields["long"].toPlainText() == "UNSAVED HUMAN EDIT"
        assert len(page.sync_calls) == 1                           # the rescan waited for the edit
        assert any("unsaved edits" in line for line in page.app.logged)


def test_leaving_the_slide_saves_the_edit_as_a_draft(make_page):
    page = make_page()
    type_into(page, "long", "typed long text")
    type_into(page, "short", "typed short")
    page.nav.slide_list.setCurrentRow(1)
    assert page._current.row.slide_id == "two" and not page.dirty and not page.state.dirty
    saved = page.store[CHART]
    assert (saved.short, saved.long) == ("typed short", "typed long text")
    assert saved.status != alt_images.STATUS_REVIEWED and saved.used_on["one"].reviewed == ""
    assert page.nav.shown[0].state == alt_images.STATE_DRAFT        # the list shows the new state


def test_a_rescan_and_a_deck_switch_save_a_pending_edit_too(make_page):
    page = make_page()
    type_into(page, "short", "first")
    page.reload()
    assert page.store[CHART].short == "first" and not page.dirty
    type_into(page, "short", "second")
    page.state.set_deck(SimpleNamespace(path=Path("other.tex"), name="other", text="", is_test_deck=True))
    assert page.store[CHART].short == "second" and not page.dirty


def test_flush_saves_nothing_without_an_edit(make_page):
    page = make_page()
    page.flush()
    assert page.store[CHART].used_on == {}


def test_save_merges_human_edit_with_worker_updates_across_visible_images(make_page):
    second_ref = "media/second.png"
    page = make_page([CHART, second_ref])
    chart = page.store[CHART]
    chart.short = "worker's latest English short"
    chart.takeaway_default = "worker's latest English takeaway"
    chart.used_on["one"] = alt_images.SlideUse(takeaway="worker's latest slide override",
                                               takeaway_de="worker's latest German override")
    chart.short_de, chart.long_de = "worker short DE", "worker long DE"
    chart.takeaway_default_de = "worker default DE"
    chart.translated_from_hash = alt_images.en_text_hash(chart)
    other = page.store[second_ref]
    other.long, other.drafted_by, other.hint = "worker's latest second-image description", "offline-worker", "latest worker hint"
    other.short_de, other.long_de = "second short DE", "second long DE"
    other.takeaway_default, other.takeaway_default_de = "second EN takeaway", "second DE takeaway"
    other.translated_from_hash = alt_images.en_text_hash(other)

    form = page._forms[0]
    type_into(page, "long", "HUMAN ENGLISH EDIT")
    page._translated(alt_draft.TranslationBatchSummary(written=2))
    assert page._forms[0] is form                                   # the dirty form stayed as it was
    page._save(reviewed=False)

    saved = page.store[CHART]
    assert (saved.long, saved.short) == ("HUMAN ENGLISH EDIT", "worker's latest English short")
    assert saved.takeaway_default == "worker's latest English takeaway"
    assert saved.takeaway_for("one") == "worker's latest slide override"
    assert saved.takeaway_default_de == "worker default DE"
    assert saved.takeaway_for_de("one") == "worker's latest German override"
    assert (saved.short_de, saved.long_de) == ("worker short DE", "worker long DE")
    assert saved.translated_from_hash == alt_images.en_text_hash(chart)
    assert alt_images.translation_state(saved) == alt_images.STATE_STALE
    untouched = page.store[second_ref]
    assert untouched.long == "worker's latest second-image description"
    assert (untouched.drafted_by, untouched.hint) == ("offline-worker", "latest worker hint")
    assert (untouched.short_de, untouched.long_de) == ("second short DE", "second long DE")
    assert (untouched.takeaway_default, untouched.takeaway_default_de) == ("second EN takeaway", "second DE takeaway")
    assert untouched.translated_from_hash == alt_images.en_text_hash(untouched)


def test_set_default_keeps_worker_fields_and_invalidates_stale_human_translation(make_page):
    page = make_page()
    entry = page.store[CHART]
    entry.short, entry.long = "worker's new English short", "worker's new English long"
    entry.short_de, entry.long_de = "worker short DE", "worker long DE"
    entry.translated_from_hash = alt_images.en_text_hash(entry)

    type_into(page, "takeaway", "human's chosen default")
    page._forms[0]._set_default()
    type_into(page, "short_de", "human German edit based on old form")
    page._save(reviewed=False)

    saved = page.store[CHART]
    assert (saved.short, saved.long) == ("worker's new English short", "worker's new English long")
    assert saved.takeaway_default == "human's chosen default" and saved.long_de == "worker long DE"
    assert saved.short_de == "human German edit based on old form"
    assert saved.translated_from_hash == "" and alt_images.translation_state(saved) == alt_images.STATE_STALE


# -- reviewing --------------------------------------------------------------------------------------


def test_review_is_refused_while_an_informative_image_has_no_long_description(make_page, monkeypatch):
    page = make_page()
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warned.append(args[2]))
    type_into(page, "short", "only a short one")
    assert page._save(reviewed=True) is False
    assert CHART in warned[0] and page.store[CHART].short == ""
    page._forms[0].roles.set_current(alt_images.ROLE_DECORATIVE)
    page._forms[0]._on_role(alt_images.ROLE_DECORATIVE)
    assert page._save(reviewed=True) is True and page.store[CHART].role == alt_images.ROLE_DECORATIVE


def test_marking_reviewed_moves_on_to_the_next_slide_the_filter_lists(make_page):
    page = make_page()
    type_into(page, "short", "s")
    type_into(page, "long", "l")
    page._save(reviewed=True)
    # the chart is one shared image: both slides use it, but only slide "one" was stamped
    assert page.store[CHART].used_on["one"].reviewed
    assert [view.row.slide_id for view in page.nav.shown] == ["two"] and page._current.row.slide_id == "two"
    assert not page.dirty


def test_decorative_images_keep_only_the_source_editable(make_page):
    page = make_page()
    form = page._forms[0]
    form.roles.set_current(alt_images.ROLE_DECORATIVE)
    form._on_role(alt_images.ROLE_DECORATIVE)
    assert {key: edit.isEnabled() for key, edit in form.fields.items()} == {
        "short": False, "long": False, "takeaway": False, "source": True,
        "short_de": False, "long_de": False, "takeaway_de": False, "source_de": True}
    assert form.changed and page.dirty


def test_clear_draft_discards_unreviewed_text_only(make_page, monkeypatch):
    page = make_page()
    page.store[CHART].short, page.store[CHART].long, page.store[CHART].drafted_by = "s", "l", "model"
    page.reload()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    page._clear_draft()
    cleared = page.store[CHART]
    assert (cleared.short, cleared.long, cleared.drafted_by) == ("", "", "")
    told = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: told.append(args[2]))
    page._clear_draft()
    assert "unreviewed" in told[0]


# -- the slide's own actions ---------------------------------------------------------------------------


def test_open_in_source_and_transcript_preview_use_the_slide_on_show(make_page, monkeypatch):
    page = make_page()
    page._open_source()
    assert page.app.opened == [page.first.path]
    shown = []
    monkeypatch.setattr(images, "show_transcript_preview", lambda *args: shown.append(args))
    page._preview_transcript()
    app, text, bare, id_slug, view, language = shown[0]
    assert (text, bare, id_slug, language) == ("slide text", "one", "one", "en") and view == page.state.view


# -- drafting and translating: jobs --------------------------------------------------------------------------


class FakeBackend:
    def __init__(self, provider, **_kwargs):
        self.provider, self.label = provider, "offline-test"

    def draft(self, _path, _context):
        return alt_draft.DraftResult(short="drafted short", long="drafted long", takeaway="take", model="offline-test")


def test_draft_slide_runs_one_job_writes_the_draft_and_gives_the_slot_back(make_page, monkeypatch):
    page = make_page()
    run_jobs_inline(monkeypatch)
    choose_provider(monkeypatch)
    monkeypatch.setattr(alt_draft, "ModelBackend", FakeBackend)
    monkeypatch.setattr(alt_draft, "build_context", lambda *_args: None)
    monkeypatch.setattr(alt_draft, "slide_jobs", lambda row, entries: [
        alt_draft.ImageJob(CHART, Path("chart.png"), row.slide_id, row.path)])
    page._draft_slide()
    assert page.app.slots == ["took", "gave"] and page._job is None and page.job_card.isHidden()
    drafted = page.store[CHART]
    assert (drafted.short, drafted.long, drafted.drafted_by) == ("drafted short", "drafted long", "offline-test")
    assert page._forms[0].fields["short"].toPlainText() == "drafted short"      # the untouched form shows it
    assert page.nav.shown[0].state == alt_images.STATE_DRAFT
    assert any(line.startswith("Finished: 1 image(s) drafted") for line in page.app.logged)


def test_draft_slide_tells_when_there_is_nothing_to_draft(make_page, monkeypatch):
    page = make_page()
    told = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: told.append(args[1]))
    page._draft_slide()
    assert told == ["Nothing to draft"] and page.app.slots == []


def test_draft_all_confirms_then_runs_the_queue_and_reports_errors(make_page, monkeypatch):
    page = make_page()
    run_jobs_inline(monkeypatch)
    choose_provider(monkeypatch)
    monkeypatch.setattr(alt_draft, "ModelBackend", FakeBackend)
    monkeypatch.setattr(alt_draft, "build_context", lambda *_args: None)
    queue = [alt_draft.ImageJob(CHART, Path("chart.png"), "one", page.first.path)]
    monkeypatch.setattr(alt_draft, "images_needing_drafts", lambda **_kwargs: queue)
    monkeypatch.setattr(QMessageBox, "exec", lambda box: QMessageBox.StandardButton.Cancel)
    page._draft_all()
    assert page.app.slots == ["took", "gave"] and page.store[CHART].short == ""    # declined: slot given back
    page.app.slots.clear()
    monkeypatch.setattr(QMessageBox, "exec", lambda box: QMessageBox.StandardButton.Ok)
    page._draft_all()
    assert page.app.slots == ["took", "gave"] and page.store[CHART].short == "drafted short"


def test_a_cloud_job_goes_through_the_same_slot_calls(make_page, monkeypatch):
    """The window decides that a cloud provider needs no slot (try_start_ollama_task); the page asks every time."""
    page = make_page()
    run_jobs_inline(monkeypatch)
    cloud = OllamaProvider("offline-test")
    cloud.is_local = False
    choose_provider(monkeypatch, cloud)
    monkeypatch.setattr(alt_draft, "ModelBackend", FakeBackend)
    monkeypatch.setattr(alt_draft, "build_context", lambda *_args: None)
    monkeypatch.setattr(alt_draft, "slide_jobs", lambda row, entries: [
        alt_draft.ImageJob(CHART, Path("chart.png"), row.slide_id, row.path)])
    given = []
    page.app.end_ollama_task = lambda provider=None: given.append(provider)
    page._draft_slide()
    assert given == [cloud]


class SlowBackend:
    """Draft one image after another until told to stop, like a long batch."""

    def __init__(self, provider, **_kwargs):
        self.provider, self.label = provider, "offline-test"
        self.started = threading.Event()

    def draft(self, _path, _context):
        self.started.set()
        time.sleep(0.02)
        return alt_draft.DraftResult(error="no answer")


def window_stand_in() -> QWidget:
    widget = QWidget()
    widget.log = lambda line: None
    return widget


def wait_for(condition, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    return condition()


def test_stop_ends_a_batch_after_the_current_image_and_takes_the_click_back(make_page, monkeypatch):
    page = make_page()
    choose_provider(monkeypatch)
    backend = SlowBackend(OllamaProvider("offline-test"))
    monkeypatch.setattr(alt_draft, "ModelBackend", lambda provider, **kw: backend)
    monkeypatch.setattr(alt_draft, "build_context", lambda *_args: None)
    queue = [alt_draft.ImageJob(f"media/{i}.png", Path("x.png"), "one", page.first.path) for i in range(500)]
    monkeypatch.setattr(alt_draft, "images_needing_drafts", lambda **_kwargs: queue)
    monkeypatch.setattr(QMessageBox, "exec", lambda box: QMessageBox.StandardButton.Ok)
    page._draft_all()
    job = page._job
    assert job is not None and not page.draft_all_button.isEnabled() and not page.job_card.isHidden()
    assert wait_for(backend.started.is_set)
    page._stop_clicked()
    assert job.stop_requested and "Stopping" in page.job_card.stop.text()
    page._stop_clicked()                                            # a second click takes it back
    assert not job.stop_requested and page.job_card.stop.text() == "Stop"
    page._stop_clicked()
    assert wait_for(lambda: page._job is None)
    assert page.app.slots == ["took", "gave"] and page.draft_all_button.isEnabled()
    assert any(line.startswith("Stopped:") for line in page.app.logged)


def test_closing_the_window_stops_a_running_job_and_gives_the_slot_back(make_page, monkeypatch):
    page = make_page()
    release = threading.Event()
    provider = OllamaProvider("offline-test")
    aborted = []
    provider.abort = lambda: (aborted.append(True), release.set())

    def work(job):
        release.wait(5)                                              # a request that only abort ends
        return alt_draft.BatchSummary()

    page.app.try_start_ollama_task("test", provider)
    job = Job("Drafting", provider, work)
    page._start(job, "one image", 5, lambda outcome: None)
    assert job.isRunning()
    page.shutdown()
    assert aborted == [True] and page._job is None
    assert wait_for(job.isFinished) and wait_for(lambda: page.app.slots == ["took", "gave"])


# -- translating one image ----------------------------------------------------------------------------------


def translation_for(entry):
    return alt_draft.TranslationResult(short_de="translated short", long_de="translated long",
                                       takeaway_de="translated takeaway", source_hash=alt_images.en_text_hash(entry))


class FakeTranslator:
    def __init__(self, *_args, **_kwargs):
        self.label = "offline-test"

    def translate(self, entry):
        return translation_for(entry)


def unsaved_draft(monkeypatch):
    monkeypatch.setattr(images.ImagesPage, "_ask_which_english", lambda page: "unsaved")


def test_unsaved_english_translation_stays_current_after_save(make_page, monkeypatch):
    page = make_page()
    type_into(page, "long", "UNSAVED ENGLISH TO TRANSLATE")
    unsaved_draft(monkeypatch)
    run_jobs_inline(monkeypatch)
    choose_provider(monkeypatch)
    monkeypatch.setattr(alt_draft, "ModelTranslationBackend", FakeTranslator)
    form = page._forms[0]
    page._translate_image(form, False)
    assert "matches the current English text" in form.translation_state.text()
    assert page.app.slots == ["took", "gave"]
    translated_hash = form.provenance["source_hash"]
    page._save(reviewed=False)
    saved = page.store[CHART]
    assert saved.long == "UNSAVED ENGLISH TO TRANSLATE" and saved.translated_from_hash == translated_hash
    assert alt_images.translation_state(saved) == alt_images.STATE_REVIEWED


def test_translation_completion_keeps_newer_english_and_human_german_stale(make_page, monkeypatch):
    page = make_page()
    type_into(page, "long", "ENGLISH AT REQUEST TIME")
    unsaved_draft(monkeypatch)
    started = []
    monkeypatch.setattr(Job, "start", lambda job: started.append(job))
    choose_provider(monkeypatch)
    monkeypatch.setattr(alt_draft, "ModelTranslationBackend", FakeTranslator)
    form = page._forms[0]
    page._translate_image(form, False)
    asked = alt_images.ImageEntry(image=CHART, long="ENGLISH AT REQUEST TIME")
    type_into(page, "long", "NEWER ENGLISH AFTER REQUEST")
    type_into(page, "short_de", "HUMAN GERMAN EDIT DURING REQUEST")
    page._on_job_result(started[0], translation_for(asked))
    assert form.fields["short_de"].toPlainText() == "HUMAN GERMAN EDIT DURING REQUEST"
    page._save(reviewed=False)
    saved = page.store[CHART]
    assert saved.long == "NEWER ENGLISH AFTER REQUEST" and saved.short_de == "HUMAN GERMAN EDIT DURING REQUEST"
    assert saved.translated_from_hash == "" and alt_images.translation_state(saved) == alt_images.STATE_STALE


def test_edit_after_translation_completion_invalidates_saved_provenance(make_page, monkeypatch):
    page = make_page()
    type_into(page, "long", "UNSAVED ENGLISH TO TRANSLATE")
    unsaved_draft(monkeypatch)
    run_jobs_inline(monkeypatch)
    choose_provider(monkeypatch)
    monkeypatch.setattr(alt_draft, "ModelTranslationBackend", FakeTranslator)
    page._translate_image(page._forms[0], False)
    type_into(page, "long_de", "HUMAN GERMAN EDIT AFTER TRANSLATION")
    page._save(reviewed=False)
    saved = page.store[CHART]
    assert saved.long_de == "HUMAN GERMAN EDIT AFTER TRANSLATION" and saved.translated_from_hash == ""
    assert alt_images.translation_state(saved) == alt_images.STATE_STALE


def test_individual_translation_keeps_fields_typed_after_request(make_page):
    page = make_page()
    form = page._forms[0]
    form.begin_translation(form.english())
    type_into(page, "long_de", "NEW HUMAN GERMAN TEXT")
    form.end_translation(alt_draft.TranslationResult(short_de="translated short", long_de="translated long",
                                                     takeaway_de="translated takeaway"))
    assert form.fields["short_de"].toPlainText() == "translated short"
    assert form.fields["long_de"].toPlainText() == "NEW HUMAN GERMAN TEXT"
    assert form.fields["takeaway_de"].toPlainText() == "translated takeaway"


def test_save_then_translate_translates_what_was_just_saved(make_page, monkeypatch):
    page = make_page()
    type_into(page, "long", "ENGLISH TO SAVE FIRST")
    run_jobs_inline(monkeypatch)
    choose_provider(monkeypatch)
    sent = []

    class Translator(FakeTranslator):
        def translate(self, entry):
            sent.append(entry.long)
            return super().translate(entry)

    monkeypatch.setattr(alt_draft, "ModelTranslationBackend", Translator)
    page._translate_image(page._forms[0], True)
    assert page.store[CHART].long == "ENGLISH TO SAVE FIRST" and sent == ["ENGLISH TO SAVE FIRST"]
    assert page._forms[0].fields["long_de"].toPlainText() == "translated long"


def test_a_failed_translation_says_so_and_frees_the_form(make_page, monkeypatch):
    page = make_page()
    run_jobs_inline(monkeypatch)
    choose_provider(monkeypatch)
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warned.append(args[2]))

    class Failing(FakeTranslator):
        def translate(self, entry):
            raise RuntimeError("model unreachable")

    monkeypatch.setattr(alt_draft, "ModelTranslationBackend", Failing)
    form = page._forms[0]
    page._translate_image(form, False)
    assert warned == ["model unreachable"] and not form.translating and page._job is None
    assert form.translate_button.text() == "Translate" and form.translate_button.isEnabled()


def test_switching_slides_during_a_translation_asks_first(make_page, monkeypatch):
    page = make_page()
    monkeypatch.setattr(Job, "start", lambda job: None)
    choose_provider(monkeypatch)
    monkeypatch.setattr(alt_draft, "ModelTranslationBackend", FakeTranslator)
    page._translate_image(page._forms[0], False)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    page.nav.slide_list.setCurrentRow(1)
    assert page._current.row.slide_id == "one" and page.nav.current_row() == 0
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    page.nav.slide_list.setCurrentRow(1)
    assert page._current.row.slide_id == "two"


def test_stop_on_a_single_translation_aborts_it_at_once(make_page, monkeypatch):
    page = make_page()
    release = threading.Event()
    provider = OllamaProvider("offline-test")
    provider.abort = release.set
    choose_provider(monkeypatch, provider)

    class Waiting(FakeTranslator):
        def translate(self, entry):
            release.wait(5)
            return alt_draft.TranslationResult(error="aborted")

    monkeypatch.setattr(alt_draft, "ModelTranslationBackend", Waiting)
    form = page._forms[0]
    page._translate_image(form, False)
    assert form.translating and page.job_card.single
    page._stop_clicked()
    assert not form.translating and page._job is None
    assert wait_for(lambda: page.app.slots == ["took", "gave"])


# -- replacing an image -------------------------------------------------------------------------------------


class FakeReplaceSheet:
    others_checked = True

    def __init__(self, parent, reference, others):
        self.source, self.new_name = Path("picked.png"), "chart-new.png"
        self.on_others = SimpleNamespace(isChecked=lambda: self.others_checked)

    def exec(self):
        return 1


def test_replace_image_repoints_clean_slides_and_refuses_one_with_unsaved_edits(make_page, monkeypatch, tmp_path):
    page = make_page()
    page.store[CHART].short = "described"
    page.store[CHART].used_on = {"one": alt_images.SlideUse(), "two": alt_images.SlideUse()}
    page.first.path.write_text(f"\\includegraphics{{{CHART}}}", encoding="utf-8")
    page.second.path.write_text(f"\\includegraphics{{{CHART}}}", encoding="utf-8")
    page.app.unsaved = {page.second.path}
    page.reload()
    monkeypatch.setattr(image_review, "PROJECT_ROOT", tmp_path)
    (tmp_path / "picked.png").write_bytes(b"png")
    monkeypatch.setattr(FakeReplaceSheet, "__init__", lambda self, parent, reference, others: (
        setattr(self, "source", tmp_path / "picked.png"), setattr(self, "new_name", "chart-new.png"),
        setattr(self, "on_others", SimpleNamespace(isChecked=lambda: True)), setattr(self, "others", others)) and None)
    monkeypatch.setattr(images, "ReplaceImageSheet", FakeReplaceSheet)
    warned, asked = [], []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warned.append(args[2]))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: asked.append(args[2]))
    page._replace_image(page._forms[0])
    assert (tmp_path / "media" / "chart-new.png").read_bytes() == b"png"
    assert "media/chart-new.png" in page.first.path.read_text(encoding="utf-8")
    assert CHART in page.second.path.read_text(encoding="utf-8")                  # unsaved buffer: left alone
    assert "unsaved edits" in warned[0] and "two" in warned[0]
    assert page.app.synced == [page.first.path]                                   # a clean buffer is re-read
    assert asked == [] and CHART in page.store                                    # still used on slide two: kept


def test_replace_image_offers_to_delete_the_orphaned_description(make_page, monkeypatch, tmp_path):
    page = make_page()
    page.store[CHART].short = "described"
    page.store[CHART].used_on = {"one": alt_images.SlideUse()}
    page.first.path.write_text(f"\\includegraphics{{{CHART}}}", encoding="utf-8")
    page.reload()
    monkeypatch.setattr(image_review, "PROJECT_ROOT", tmp_path)
    (tmp_path / "picked.png").write_bytes(b"png")

    class Sheet(FakeReplaceSheet):
        def __init__(self, parent, reference, others):
            self.source, self.new_name = tmp_path / "picked.png", "chart-new.png"
            self.on_others = SimpleNamespace(isChecked=lambda: False)

    monkeypatch.setattr(images, "ReplaceImageSheet", Sheet)
    deleted = []
    monkeypatch.setattr(alt_images, "delete_entry", lambda image: deleted.append(image))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    page._replace_image(page._forms[0])
    assert deleted == [CHART]


def test_the_replace_sheet_validates_the_name_and_warns_before_overwriting(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(image_review, "PROJECT_ROOT", tmp_path)
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "taken.png").write_bytes(b"x")
    sheet = image_dialogs.ReplaceImageSheet(None, "media/chart-old.png", ["2bb", "3cc"])
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
    assert "already exists" in sheet.problem.text() and sheet.replace_button.isEnabled()


# -- tuning the prompt --------------------------------------------------------------------------------------


def test_closing_the_tuning_sheet_stops_a_running_draft_and_hands_the_slot_back(qapp, monkeypatch, tmp_path):
    release = threading.Event()
    provider = OllamaProvider("offline-test")
    provider.abort = release.set

    class Backend:
        def __init__(self, provider, **_kwargs):
            pass

        def draft(self, _path, _context):
            release.wait(5)
            return alt_draft.DraftResult(error="aborted")

    monkeypatch.setattr(image_dialogs.alt_draft, "ModelBackend", Backend)
    monkeypatch.setattr(alt_blocks, "resolve_image", lambda _reference: None)
    over = []
    app = window_stand_in()
    context = alt_draft.SlideContext(slide_id="one", title="T", body="", source="", image="chart.png")
    sheet = image_dialogs.PromptTuningSheet(app, CHART, tmp_path / "chart.png", context, provider, "", lambda: over.append(True))
    sheet._draft()
    job = sheet._job
    assert job.isRunning() and not sheet.draft_button.isEnabled() and not sheet.accept_button.isEnabled()
    sheet.reject()
    assert wait_for(job.isFinished) and over == [True]


def test_a_tuned_draft_can_be_accepted_with_its_hint(qapp, monkeypatch, tmp_path):
    provider = OllamaProvider("offline-test")

    class Backend:
        def __init__(self, provider, **kwargs):
            self.system_prompt = kwargs["system_prompt"]

        def draft(self, _path, context):
            return alt_draft.DraftResult(short=f"short with {context.hint}", long="long", takeaway="t", model="m",
                                         role_suggestion="informative")

    monkeypatch.setattr(image_dialogs.alt_draft, "ModelBackend", Backend)
    monkeypatch.setattr(Job, "start", Job.run)
    monkeypatch.setattr(alt_blocks, "resolve_image", lambda _reference: None)
    over = []
    context = alt_draft.SlideContext(slide_id="one", title="T", body="", source="", image="chart.png")
    window = window_stand_in()
    sheet = image_dialogs.PromptTuningSheet(window, CHART, tmp_path / "chart.png",
                                            context, provider, "old hint", lambda: over.append(True))
    sheet.hint_edit.setPlainText("the y-axis maximum is 6800")
    sheet._draft()
    assert sheet.accept_button.isEnabled() and sheet.result_draft.short == "short with the y-axis maximum is 6800"
    assert "SHORT" in sheet.output.toPlainText() and sheet.hint == "the y-axis maximum is 6800"
    sheet.accept()
    assert over == [True]
