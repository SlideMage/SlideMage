# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Image batch outcomes, route disclosure, and results in the Images page and assistant."""
from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QLabel, QMessageBox

from slidemage import alt_draft, alt_images
from slidemage.ai import ai_profile, resolver
from slidemage.ai.ai_profile import IMAGE_DESCRIPTION, Route, TRANSLATION
from fake_routes import FakeProvider
from slidemage.batch_result import CANCELLED, DONE, FAILED, KEPT
from slidemage.ui.kit import kit_qss as q
from slidemage.ui.kit.widgets import Button
from slidemage.ui.pages import image_runs
from selection_make_readable_image_batches_helpers import LF, buttons, click, pump, settled, slide_file, wait_until
from selection_make_readable_image_batches_helpers import fake as fake
from test_images_page_gui import CHART, run_jobs_inline, wait_for
from test_images_page_gui import make_page as make_page

CLOUD = Route("fake_cloud", IMAGE_DESCRIPTION, "fake-1")
LOCAL = Route("fake_local", IMAGE_DESCRIPTION, "fake-2")
CLOUD_NOTE = "fake-1 · sends this image to the cloud"
FIRST, SECOND, THIRD, FOURTH = (f"media/{name}.png" for name in ("first", "second", "third", "fourth"))


GOOD = alt_draft.DraftResult(short="drafted short", long="drafted long", takeaway="take", model="scripted")


class Backend:
    label = "offline-test"

    def __init__(self, results=None, *, provider=None, before=None):
        self.provider = provider
        self.results, self.before, self.attempted = results or {}, before or {}, []

    def reply(self, image, default):
        self.attempted.append(image)
        if image in self.before:
            self.before[image]()
        result = self.results.get(image, default)
        if isinstance(result, Exception):
            raise result
        return result

    def draft(self, _path, context):
        return self.reply(context.image, GOOD)

    def translate(self, entry):
        return self.reply(entry.image, alt_draft.TranslationResult(
            short_de="k", long_de="l", takeaway_de="t", source_hash=alt_images.en_text_hash(entry)))


@pytest.fixture
def stored(ctx, monkeypatch):
    alt_images.save_store(ctx, {image: alt_images.ImageEntry(image=image) for image in (FIRST, SECOND, THIRD, FOURTH)})
    monkeypatch.setattr(alt_draft, "build_context", lambda _ctx, _path, reference: SimpleNamespace(image=reference))
    return [alt_draft.ImageJob(image, Path("x.png"), "one", Path("one.tex")) for image in (FIRST, SECOND, THIRD, FOURTH)]


def edit_store(ctx, image, **fields):
    alt_images.update_store(ctx, lambda entries: [setattr(entries[image], key, value) for key, value in fields.items()] and True)


def test_a_batch_settles_every_image_and_keeps_what_a_person_wrote_meanwhile(ctx, stored):
    backend = Backend(
        {FIRST: GOOD, SECOND: GOOD, THIRD: alt_draft.DraftResult(error="overloaded"), FOURTH: RuntimeError("boom")},
        before={SECOND: lambda: edit_store(ctx, SECOND, long="MY OWN TEXT")})
    seen = []
    summary = alt_draft.run_batch(ctx, stored, backend, on_item_done=lambda image, outcome: seen.append((image, outcome.kind)))
    assert {image: (outcome.kind, outcome.reason) for image, outcome in summary.outcomes.items()} == {
        FIRST: (DONE, ""), SECOND: (KEPT, ""), THIRD: (FAILED, "overloaded"), FOURTH: (FAILED, "boom")}
    assert seen == [(FIRST, DONE), (SECOND, KEPT), (THIRD, FAILED), (FOURTH, FAILED)]
    assert (summary.written, summary.skipped_changed, summary.failed) == (1, 1, 2)
    entries = alt_images.load_store(ctx)
    assert entries[FIRST].long == "drafted long" and entries[SECOND].long == "MY OWN TEXT" and entries[SECOND].short == ""
    assert "you edited or reviewed it" in summary.errors[0]

    backend = Backend({THIRD: GOOD}, before={THIRD: lambda: edit_store(ctx, THIRD, status=alt_images.STATUS_REVIEWED)})
    summary = alt_draft.run_batch(ctx, stored[2:3], backend)
    assert summary.outcomes[THIRD].kind == KEPT and alt_images.load_store(ctx)[THIRD].long == ""


def test_a_request_ended_by_the_stop_is_cancelled_not_failed(ctx, stored):
    stop = threading.Event()
    backend = Backend({FIRST: alt_draft.DraftResult(error="aborted"), SECOND: GOOD},
                       before={FIRST: stop.set})
    summary = alt_draft.run_batch(ctx, stored[:2], backend, should_stop=stop.is_set)
    assert {image: outcome.kind for image, outcome in summary.outcomes.items()} == {FIRST: CANCELLED}
    assert summary.stopped_early and summary.failed == 0 and summary.attempted == 1


def test_a_translation_batch_keeps_german_text_a_person_wrote_meanwhile(ctx):
    entries = {image: alt_images.ImageEntry(image=image, short="s", long=f"long {image}") for image in (FIRST, SECOND, THIRD)}
    alt_images.save_store(ctx, entries)

    backend = Backend({THIRD: alt_draft.TranslationResult(error="no")},
                      before={SECOND: lambda: edit_store(ctx, SECOND, long_de="MEIN TEXT")})
    summary = alt_draft.run_translation_batch(ctx, [FIRST, SECOND, THIRD], backend)
    assert {image: outcome.kind for image, outcome in summary.outcomes.items()} == {FIRST: DONE, SECOND: KEPT, THIRD: FAILED}
    assert alt_images.load_store(ctx)[SECOND].long_de == "MEIN TEXT"


def run_on(monkeypatch, page, route, backend, *images):
    monkeypatch.setattr(image_runs, "picked_route", lambda *_args: route)
    monkeypatch.setattr(resolver, "draft_backend", lambda _ctx, _route: backend)
    monkeypatch.setattr(resolver, "translation_backend", lambda _ctx, _route: backend)
    monkeypatch.setattr(alt_draft, "build_context", lambda _ctx, path, reference: SimpleNamespace(image=reference))
    monkeypatch.setattr(alt_draft, "images_needing_drafts", lambda _ctx, **_kwargs: [
        alt_draft.ImageJob(image, Path("x.png"), "one", page.first.path) for image in images])
    monkeypatch.setattr(alt_draft, "images_needing_translation", lambda _ctx, _language="de": list(images))
    for image in images:
        page.store.setdefault(image, alt_images.ImageEntry(image=image, short="s", long="l"))


def answer(monkeypatch, button=QMessageBox.StandardButton.Ok):
    asked = []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: asked.append((box.text(), box.informativeText())) or button)
    return asked


@pytest.mark.parametrize("route", [CLOUD, LOCAL], ids=["cloud", "local"])
def test_draft_all_asks_with_the_model_and_what_is_sent(make_page, monkeypatch, route):
    page = make_page()
    backend = Backend(provider=FakeProvider())
    run_on(monkeypatch, page, route, backend, FIRST, SECOND)
    asked = answer(monkeypatch, QMessageBox.StandardButton.Cancel)
    page._draft_all()
    [(title, detail)] = asked
    assert title == f"Draft 2 image descriptions in {page.app.project.root.name}?"
    assert detail.startswith(route.model)
    if route == CLOUD:
        assert "sends each image and its slide text to the cloud" in detail
    else:
        assert "cloud" not in detail
    assert not backend.attempted and page._job is None and page.app.slots == ["took", "gave"]


def test_a_batch_keeps_the_route_it_started_on_when_the_switch_moves(make_page, monkeypatch, ctx):
    page = make_page()
    ai_profile.set_mode(ctx, ai_profile.CLOUD)
    page.refresh_model_preferences()
    page.draft_model.setCurrentIndex(page.draft_model.findData("fake-2"))
    assert page.draft_note.text() == "fake-2 · sends this image to the cloud"
    form = page._forms[0]
    assert form.translate_button.text().endswith(" · cloud")
    assert form.save_translate_button.text().endswith(" · cloud")
    release = threading.Event()
    provider = FakeProvider("offline-test")
    provider.abort = release.set
    backend = Backend(provider=provider, before={FIRST: lambda: release.wait(5)})
    built = []
    run_on(monkeypatch, page, CLOUD, backend, FIRST, SECOND)
    monkeypatch.setattr(resolver, "draft_backend", lambda _ctx, route: built.append(route) or backend)
    answer(monkeypatch)
    page._draft_all()
    job = page._job
    assert wait_for(lambda: backend.attempted == [FIRST])
    assert job.route == CLOUD and built == [CLOUD]
    ai_profile.set_mode(ctx, ai_profile.LOCAL)
    page.refresh_model_preferences([], [])
    assert not form.translate_button.text().endswith(" · cloud")
    assert not form.save_translate_button.text().endswith(" · cloud")
    assert wait_for(lambda: "fake-1" in page.job_card.detail.text())
    assert job.route == CLOUD
    [work] = page.running_work()
    assert work.route == "fake-1"
    release.set()
    assert wait_for(lambda: page._job is None)
    assert built == [CLOUD] and backend.attempted == [FIRST, SECOND]           # one backend, built once, for both images
    assert page.results.result.route == CLOUD


# the Images page: the results panel
def rows(view):
    labels = view.scroll.widget().findChildren(QLabel)
    return list(zip([label.text() for label in labels if label.objectName() == q.PANEL_MONO],
                    [label.text() for label in labels if label.objectName() == q.TASK_STATE]))


def test_the_panel_lists_each_image_after_a_run_and_retry_runs_only_the_failed(make_page, monkeypatch):
    page = make_page()
    run_jobs_inline(monkeypatch)
    backend = Backend({SECOND: alt_draft.DraftResult(error="overloaded")}, provider=FakeProvider())
    run_on(monkeypatch, page, CLOUD, backend, FIRST, SECOND, THIRD, FOURTH)

    def type_during_batch():
        page.store[THIRD].long = "MY OWN TEXT"

    def stop_after_current_image():
        page._job.stop_requested = True

    backend.before.update({FIRST: type_during_batch, THIRD: stop_after_current_image})
    answer(monkeypatch)
    page._draft_all()
    view = page.results
    assert not view.isHidden()
    assert view.title.text() == "Image descriptions · partly done" and view.route.text() == "fake-1"
    assert rows(view) == [("first.png", "Drafted · needs review"), ("second.png", "Failed · overloaded"),
                          ("third.png", "You edited it during the run · your text kept"),
                          ("fourth.png", "Cancelled · not sent")]
    assert page.store[THIRD].long == "MY OWN TEXT"
    assert view.result.failed == [SECOND] and view.retry is not None
    # Retry failed: a new batch of the failed image only, on the route active now, asked about again
    backend.before.clear()
    backend.attempted.clear()
    backend.results.clear()
    asked = answer(monkeypatch)
    view.retry.click()
    assert [text for text, _line in asked] == [f"Draft 1 image description in {page.app.project.root.name}?"]
    assert backend.attempted == [SECOND]
    assert rows(view) == [("second.png", "Drafted · needs review")]
    assert view.title.text() == "Image descriptions · done" and view.retry is None
    view.close_button.click()
    assert view.isHidden() and view.result is None


def test_a_draft_over_text_typed_into_the_form_counts_as_kept(make_page, monkeypatch):
    page = make_page()
    run_jobs_inline(monkeypatch)
    run_on(monkeypatch, page, CLOUD, Backend(provider=FakeProvider()), CHART)
    page._forms[0].fields["long"].setPlainText("TYPED, NOT SAVED")
    answer(monkeypatch)
    page._draft_all()
    assert rows(page.results) == [("chart.png", "You edited it during the run · your text kept")]
    assert page._forms[0].fields["long"].toPlainText() == "TYPED, NOT SAVED"
    assert page.results.retry is None and page.results.title.text() == "Image descriptions · done"


def test_translate_all_confirms_cloud_disclosure_and_shows_translation_results(make_page, monkeypatch):
    page = make_page()
    run_jobs_inline(monkeypatch)
    route = Route("fake_cloud", TRANSLATION, "fake-1")
    run_on(monkeypatch, page, route, Backend(provider=FakeProvider()), FIRST)
    asked = answer(monkeypatch)
    page._translate_all()
    [(title, detail)] = asked
    assert title == f"Translate 1 description in {page.app.project.root.name} to German?"
    assert detail.startswith("fake-1 · sends each description to the cloud")
    assert page.results.title.text() == "Image translations · done"
    assert rows(page.results) == [("first.png", "Translated · needs review")]
    assert page.results.retry is None


def test_stop_and_switch_cancels_the_pending_images_and_the_panel_says_so(make_page, monkeypatch):
    page = make_page()
    release = threading.Event()
    provider = FakeProvider("offline-test")
    provider.abort = release.set
    second_started = threading.Event()

    def block_second():
        second_started.set()
        release.wait(5)

    backend = Backend({SECOND: alt_draft.DraftResult(error="aborted")}, provider=provider, before={SECOND: block_second})
    run_on(monkeypatch, page, CLOUD, backend, FIRST, SECOND, THIRD)
    answer(monkeypatch)
    page._draft_all()
    assert wait_for(second_started.is_set)
    assert wait_for(lambda: FIRST in page._job.outcomes)
    [work] = page.running_work()
    assert "1 of 3 done" in work.line and "Pending images are canceled" in work.line
    work.stop()  # Stop and switch
    assert page._job is None
    assert page.results.title.text() == "Image descriptions · partly done"
    assert rows(page.results) == [("first.png", "Drafted · needs review"), ("second.png", "Cancelled · not sent"),
                                  ("third.png", "Cancelled · not sent")]
    assert page.results.retry is None
    assert wait_for(lambda: page.app.slots == ["took", "gave"])


# the window: the side panels and the assistant's image tasks
@pytest.fixture(autouse=True)
def _registered_routes(fake_routes):
    return fake_routes


def with_pictures(fake, **entries):
    env = fake.env
    text = LF + "\n" + "\n".join("\\includegraphics{media/" + name + ".png}" for name in entries)
    slide_file(env).editor.replace_all_text(text)
    alt_images.save_store(env.window.project, {f"media/{name}.png": alt_images.ImageEntry(image=f"media/{name}.png", **fields)
                                               for name, fields in entries.items()})
    fake.monkeypatch.setattr(alt_draft, "draftable_images", lambda _ctx, row, _entries: [(image, Path("x.png")) for image in row.images])
    fake.monkeypatch.setattr(alt_draft, "build_context", lambda _ctx, _path, image: SimpleNamespace(image=image))
    env.window.assistant.header.schedule()


def test_image_actions_and_side_panels_disclose_the_active_route(fake):
    window = fake.env.window
    page, panels = window.images_page, window.side_panels
    with_pictures(fake, a={})
    panels.set_panel("language")
    pump(0.1)
    translate = next(b for b in panels.panels["language"].findChildren(Button) if b.text().startswith("Translate to"))
    assert translate.text().endswith(" · cloud")
    assert page.draft_note.text() == CLOUD_NOTE
    assert "sends the description to the cloud" in page.translate_note.text()
    assert all(button.text().endswith(" · cloud") for button in (page.draft_button, page.draft_all_button,
                                                                page.translate_all_button))

    window.state.set_ai_route(ai_profile.LOCAL)
    assert not translate.text().endswith(" · cloud")
    assert page.draft_all_button.text() == "Draft all…" and page.draft_note.text() == "fake-1"
    panels.set_panel("images")
    pump(0.1)
    redraft = next(b for b in panels.panels["images"].findChildren(Button) if b.text().startswith("Redraft"))
    assert not redraft.text().endswith(" · cloud")
    window.state.set_ai_route(ai_profile.CLOUD, "fake_cloud")
    assert redraft.text().endswith(" · cloud") and page.draft_all_button.text().endswith(" · cloud")


def test_an_image_task_of_the_assistant_ends_in_the_same_panel_and_retry_runs_the_failed(fake, monkeypatch):
    env = fake.env
    area = env.window.assistant
    with_pictures(fake, a={}, b={})
    wait_until(lambda: "Describe images (2)" in buttons(env))
    backend = Backend({"media/b.png": alt_draft.DraftResult(error="overloaded")}, provider=FakeProvider())
    monkeypatch.setattr(fake.routes.cloud, "draft_backend", lambda *_args: backend)
    click(env, "Describe images (2)")
    assert settled(env).endswith(": 1 described, 1 failed (media/b.png: overloaded)")
    view = area.image_results
    assert area._stack.currentWidget() is area._results_page and view.result is area.tasks.result
    assert view.title.text() == "Image descriptions · partly done" and view.route.text() == "fake-1"
    assert rows(view) == [("a.png", "Drafted · needs review"), ("b.png", "Failed · overloaded")]
    assert view.retry.text() == "Retry failed (1)"
    backend.results.clear()
    asked = answer(monkeypatch)
    view.retry.click()
    assert asked[0][0] == f"Draft 1 image description in {env.window.project.root.name}?"
    assert settled(env).endswith(": 1 described")
    assert backend.attempted == ["media/a.png", "media/b.png", "media/b.png"]
    assert view.title.text() == "Image descriptions · done" and view.retry is None
    view.back.click()
    assert area.tasks.result is None and area._stack.currentWidget() is not area._results_page


def test_a_stopped_image_task_shows_its_cancelled_images(fake, monkeypatch):
    env = fake.env
    area = env.window.assistant
    with_pictures(fake, a={}, b={})
    wait_until(lambda: "Describe images (2)" in buttons(env))
    release = threading.Event()
    provider = FakeProvider()
    provider.abort = release.set
    backend = Backend({"media/a.png": alt_draft.DraftResult(error="aborted")},
                      provider=provider, before={"media/a.png": lambda: release.wait(5)})
    monkeypatch.setattr(fake.routes.cloud, "draft_backend", lambda *_args: backend)
    click(env, "Describe images (2)")
    wait_until(lambda: bool(backend.attempted))
    area.task_row.stop_button.click()
    settled(env)
    assert rows(area.image_results) == [("a.png", "Cancelled · not sent"), ("b.png", "Cancelled · not sent")]
    assert area.image_results.retry is None and area.image_results.title.text() == "Image descriptions · partly done"


def test_translating_the_descriptions_ends_in_the_panel_too(fake, monkeypatch):
    env = fake.env
    with_pictures(fake, a=dict(short="A bar chart.", long="Two bars."))
    wait_until(lambda: "Translate image descriptions (1)" in buttons(env))
    monkeypatch.setattr(fake.routes.cloud, "translation_backend", lambda *_args: Backend(provider=FakeProvider()))
    click(env, "Translate image descriptions (1)")
    settled(env)
    view = env.window.assistant.image_results
    assert view.title.text() == "Image translations · done" and rows(view) == [("a.png", "Translated · needs review")]
