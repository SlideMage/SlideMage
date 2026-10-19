# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Image batches on a route (workspace v6 handoff, section 5): what the route in use shows on the buttons that send
content, the question before a batch, the route a batch captures, and the results panel with Retry failed: for the
Images page, for "Stop and switch" and for the assistant's image tasks. The pipeline's own part, what became of each
image (alt_draft's outcomes, an edit made during the run kept), is tested here too."""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest
from PySide6.QtWidgets import QLabel, QMessageBox

from slidemage import alt_draft, alt_images
from slidemage.ai import ai_profile, resolver
from slidemage.ai.ai_profile import CLAUDE_CODE, IMAGE_DESCRIPTION, LOCAL, TRANSLATION, Route
from slidemage.ai.providers import OllamaProvider
from slidemage.batch_result import (
    CANCELLED, DONE, DRAFT, FAILED, KEPT, TRANSLATE, BatchResult, ItemOutcome, display_name)
from slidemage.ui.kit import kit_qss as q
from slidemage.ui.kit.widgets import Button
from slidemage.ui.pages import image_results, image_runs
from test_images_page_gui import CHART, make_page, run_jobs_inline, wait_for  # noqa: F401 -- make_page is a fixture

HAIKU = Route(CLAUDE_CODE, IMAGE_DESCRIPTION, "haiku", "medium")
QWEN = Route(LOCAL, IMAGE_DESCRIPTION, "qwen3-vl:32b")
CLOUD_NOTE = "Claude Code · Haiku · effort medium · sends this image to the cloud"
FIRST, SECOND, THIRD, FOURTH = (f"media/{name}.png" for name in ("first", "second", "third", "fourth"))


# -- the model: titles, summary, labels, the question ---------------------------------------------------------------

def result_of(kind=DRAFT, route=QWEN, **kinds):
    """A result with one image per outcome kind given: first=DONE, ..."""
    return BatchResult(kind, route, tuple((f"media/{name}.png", ItemOutcome(outcome, "overloaded" if outcome == FAILED else ""))
                                          for name, outcome in kinds.items()))


def test_a_result_says_what_became_of_each_image():
    result = result_of(a=DONE, b=KEPT, c=FAILED, d=CANCELLED, e=DONE)
    assert result.title == "Image descriptions · partly done" and result.failed == ["media/c.png"]
    assert result.summary == ("2 drafted · 1 kept as you edited it · 1 failed · 1 cancelled. Each finished item was saved "
                              "as it completed; nothing is rolled back. Retry runs only the failed ones, as a new run "
                              "on the current route.")
    assert [result.label(outcome) for _image, outcome in result.items] == [
        "Drafted · needs review", "You edited it during the run · your text kept", "Failed · overloaded",
        "Cancelled · not sent", "Drafted · needs review"]
    assert result.label(ItemOutcome(FAILED)) == "Failed · the model returned no description"


def test_a_result_without_failures_is_done_and_offers_no_retry():
    result = result_of(TRANSLATE, a=DONE, b=KEPT)
    assert result.title == "Image translations · done" and result.failed == []
    assert result.summary == "1 translated · 1 kept as you edited it. Each finished item was saved as it completed; nothing is rolled back."
    assert result.label(ItemOutcome(DONE)) == "Translated · needs review"
    assert result_of(a=DONE, b=CANCELLED).title == "Image descriptions · partly done"


def test_the_images_a_run_did_not_reach_are_cancelled():
    result = BatchResult.of(DRAFT, QWEN, [FIRST, SECOND, THIRD], {FIRST: ItemOutcome(DONE)})
    assert [outcome.kind for _image, outcome in result.items] == [DONE, CANCELLED, CANCELLED]
    assert display_name(FIRST) == "first.png" and display_name("tikz:abc") == "tikz:abc"


def test_the_question_names_the_model_and_what_is_sent():
    assert image_results.question(DRAFT, 4, "slidemage-manual", HAIKU) == (
        "Draft 4 image descriptions in slidemage-manual?",
        "Claude Code · Haiku · effort medium · sends each image and its slide text to the cloud · 10–60 s per image.")
    assert image_results.question(DRAFT, 1, "manual", QWEN) == (
        "Draft 1 image description in manual?", "qwen3-vl:32b · Ollama · expect this to take hours.")
    assert image_results.question(TRANSLATE, 3, "manual", Route(CLAUDE_CODE, TRANSLATION, "haiku", "medium")) == (
        "Translate 3 descriptions in manual to German?",
        "Claude Code · Haiku · effort medium · sends each description to the cloud · a few seconds per image.")
    assert image_results.question(TRANSLATE, 3, "manual", Route(LOCAL, TRANSLATION, "hy-mt")) == (
        "Translate 3 descriptions in manual to German?", "hy-mt · Ollama.")


# -- the pipeline: outcomes, an edit during the run is kept -------------------------------------------------------------

class Scripted:
    """A backend that answers per image as `answers` says (a DraftResult, or an exception to raise) and may do
    something before it does (`before[image]()`: a person editing the store while the model works)."""

    label = "scripted"
    provider = None

    def __init__(self, answers, before=None):
        self.answers, self.before = answers, before or {}

    def draft(self, _path, context):
        image = context
        if image in self.before:
            self.before[image]()
        answer = self.answers[image]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def translate(self, entry):
        if entry.image in self.before:
            self.before[entry.image]()
        answer = self.answers[entry.image]
        if isinstance(answer, Exception):
            raise answer
        return answer


GOOD = alt_draft.DraftResult(short="drafted short", long="drafted long", takeaway="take", model="scripted")


@pytest.fixture
def stored(ctx, monkeypatch):
    """A store of four undescribed images and a drafting queue over them (the context of an image is its name)."""
    alt_images.save_store(ctx, {image: alt_images.ImageEntry(image=image) for image in (FIRST, SECOND, THIRD, FOURTH)})
    monkeypatch.setattr(alt_draft, "build_context", lambda _ctx, _path, reference: reference)
    return [alt_draft.ImageJob(image, Path("x.png"), "one", Path("one.tex")) for image in (FIRST, SECOND, THIRD, FOURTH)]


def edit_store(ctx, image, **fields):
    alt_images.update_store(ctx, lambda entries: [setattr(entries[image], key, value) for key, value in fields.items()] and True)


def test_a_batch_settles_every_image_and_keeps_what_a_person_wrote_meanwhile(ctx, stored):
    backend = Scripted(
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


def test_a_description_reviewed_during_the_run_is_kept_too(ctx, stored):
    backend = Scripted({FIRST: GOOD}, before={FIRST: lambda: edit_store(ctx, FIRST, status=alt_images.STATUS_REVIEWED)})
    summary = alt_draft.run_batch(ctx, stored[:1], backend)
    assert summary.outcomes[FIRST].kind == KEPT and alt_images.load_store(ctx)[FIRST].long == ""


def test_a_request_ended_by_the_stop_is_cancelled_not_failed(ctx, stored):
    stop = threading.Event()
    backend = Scripted({FIRST: alt_draft.DraftResult(error="aborted"), SECOND: GOOD},
                       before={FIRST: stop.set})
    summary = alt_draft.run_batch(ctx, stored[:2], backend, should_stop=stop.is_set)
    assert {image: outcome.kind for image, outcome in summary.outcomes.items()} == {FIRST: CANCELLED}
    assert summary.stopped_early and summary.failed == 0 and summary.attempted == 1


def test_a_translation_batch_keeps_german_text_a_person_wrote_meanwhile(ctx):
    entries = {image: alt_images.ImageEntry(image=image, short="s", long=f"long {image}") for image in (FIRST, SECOND, THIRD)}
    alt_images.save_store(ctx, entries)

    def translation(image):
        return alt_draft.TranslationResult(short_de="k", long_de="l", takeaway_de="t",
                                           source_hash=alt_images.en_text_hash(entries[image]))

    backend = Scripted({FIRST: translation(FIRST), SECOND: translation(SECOND), THIRD: alt_draft.TranslationResult(error="no")},
                       before={SECOND: lambda: edit_store(ctx, SECOND, long_de="MEIN TEXT")})
    summary = alt_draft.run_translation_batch(ctx, [FIRST, SECOND, THIRD], backend)
    assert {image: outcome.kind for image, outcome in summary.outcomes.items()} == {FIRST: DONE, SECOND: KEPT, THIRD: FAILED}
    assert alt_images.load_store(ctx)[SECOND].long_de == "MEIN TEXT"


# -- the Images page: the route on its buttons -------------------------------------------------------------------------

def texts(page):
    return (page.draft_button.text(), page.draft_all_button.text(), page.translate_all_button.text(),
            page._forms[0].translate_button.text(), page._forms[0].save_translate_button.text())


def test_the_note_and_the_buttons_follow_the_route_in_use(make_page, ctx):  # noqa: F811
    page = make_page()
    page.refresh_model_preferences(["qwen3:8b"], ["qwen3-vl:32b"])
    assert page.draft_note.text() == "qwen3-vl:32b · Ollama"
    assert page.translate_note.text() == "qwen3:8b · Ollama"
    assert texts(page) == ("Draft this slide", "Draft all…", "Translate all…", "Translate", "Save, then translate")
    ai_profile.set_mode(ctx, ai_profile.CLOUD)                            # what the AI switch does, then the window's refresh
    page.refresh_model_preferences(["qwen3:8b"], ["qwen3-vl:32b"])
    assert page.draft_note.text() == CLOUD_NOTE
    assert page.translate_note.text() == "Claude Code · Haiku · effort medium · sends the description to the cloud"
    assert texts(page) == ("Draft this slide · cloud", "Draft all… · cloud", "Translate all… · cloud", "Translate · cloud",
                           "Save, then translate · cloud")
    ai_profile.set_mode(ctx, ai_profile.LOCAL)
    page.refresh_model_preferences(["qwen3:8b"], ["qwen3-vl:32b"])
    assert page.draft_note.text() == "qwen3-vl:32b · Ollama" and texts(page)[0] == "Draft this slide"


def test_the_note_follows_the_picker(make_page, ctx):  # noqa: F811
    page = make_page()
    ai_profile.set_mode(ctx, ai_profile.CLOUD)
    page.refresh_model_preferences([], [])
    page.draft_model.setCurrentIndex(page.draft_model.findData("sonnet:high"))
    assert page.draft_note.text() == "Claude Code · Sonnet · effort high · sends this image to the cloud"


# -- the Images page: the question, the captured route, the progress ---------------------------------------------------

class Backend:
    """Describes every image, or blocks in `draft` until released; the page's job holds `provider`."""

    def __init__(self, provider, results=None, block=None):
        self.provider, self.label, self.results = provider, "offline-test", results or {}
        self.block, self.drafted = block, []

    def draft(self, _path, context):
        self.drafted.append(context.image)
        if self.block is not None:
            self.block.wait(5)
        return self.results.get(context.image, GOOD)

    def translate(self, entry):
        self.drafted.append(entry.image)
        return self.results.get(entry.image, alt_draft.TranslationResult(
            short_de="k", long_de="l", takeaway_de="t", source_hash=alt_images.en_text_hash(entry)))


def jobs_for(page, *images):
    return [alt_draft.ImageJob(image, Path("x.png"), "one", page.first.path) for image in images]


def run_on(monkeypatch, page, route, backend, *images):
    """The page's batch over `images` runs on `route` with `backend`; images_needing_drafts and _translation say so."""
    monkeypatch.setattr(image_runs, "picked_route", lambda *_args: route)
    monkeypatch.setattr(resolver, "draft_backend", lambda _ctx, _route: backend)
    monkeypatch.setattr(resolver, "translation_backend", lambda _ctx, _route: backend)
    monkeypatch.setattr(alt_draft, "build_context", lambda _ctx, path, reference: SimpleContext(reference))
    monkeypatch.setattr(alt_draft, "images_needing_drafts", lambda _ctx, **_kwargs: jobs_for(page, *images))
    monkeypatch.setattr(alt_draft, "images_needing_translation", lambda _ctx: list(images))
    for image in images:
        page.store.setdefault(image, alt_images.ImageEntry(image=image, short="s", long="l"))


class SimpleContext:
    def __init__(self, image):
        self.image = image


def answer(monkeypatch, button=QMessageBox.StandardButton.Ok):
    """The question box is answered `button`; what it asked is in the list that is returned."""
    asked = []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: asked.append((box.text(), box.informativeText())) or button)
    return asked


@pytest.mark.parametrize(("route", "text", "line"), [
    (HAIKU, "Draft 2 image descriptions in {root}?",
     "Claude Code · Haiku · effort medium · sends each image and its slide text to the cloud · 10–60 s per image."),
    (QWEN, "Draft 2 image descriptions in {root}?", "qwen3-vl:32b · Ollama · expect this to take hours."),
], ids=["cloud", "local"])
def test_draft_all_asks_with_the_model_and_what_is_sent(make_page, monkeypatch, route, text, line):  # noqa: F811
    page = make_page()
    run_on(monkeypatch, page, route, Backend(OllamaProvider("offline-test")), FIRST, SECOND)
    asked = answer(monkeypatch, QMessageBox.StandardButton.Cancel)
    page._draft_all()
    assert asked[0][0] == text.format(root=page.app.project.root.name) and asked[0][1].startswith(line)
    assert page._job is None and page.app.slots == ["took", "gave"]


def test_translate_all_asks_with_the_model_and_what_is_sent(make_page, monkeypatch):  # noqa: F811
    page = make_page()
    route = Route(CLAUDE_CODE, TRANSLATION, "haiku", "medium")
    run_on(monkeypatch, page, route, Backend(OllamaProvider("offline-test")), FIRST, SECOND, THIRD)
    asked = answer(monkeypatch, QMessageBox.StandardButton.Cancel)
    page._translate_all()
    assert asked[0][0] == f"Translate 3 descriptions in {page.app.project.root.name} to German?"
    assert asked[0][1].startswith("Claude Code · Haiku · effort medium · sends each description to the cloud")


def test_a_batch_keeps_the_route_it_started_on_when_the_switch_moves(make_page, monkeypatch, ctx):  # noqa: F811
    page = make_page()
    release = threading.Event()
    provider = OllamaProvider("offline-test")
    provider.abort = release.set
    backend = Backend(provider, block=release)
    built = []
    run_on(monkeypatch, page, HAIKU, backend, FIRST, SECOND)
    monkeypatch.setattr(resolver, "draft_backend", lambda _ctx, route: built.append(route) or backend)
    answer(monkeypatch)
    page._draft_all()
    job = page._job
    assert wait_for(lambda: backend.drafted == [FIRST])
    assert job.route == HAIKU and built == [HAIKU]
    ai_profile.set_mode(ctx, ai_profile.CLOUD)
    ai_profile.set_mode(ctx, ai_profile.LOCAL)                              # the switch moves under the running batch
    page.refresh_model_preferences([], [])
    assert wait_for(lambda: page.job_card.detail.text() == "Image 1 of 2 · first.png · Claude Code · Haiku · effort medium")
    assert job.route == HAIKU
    [work] = page.running_work()
    assert work.text == "Drafting image descriptions · 0 of 2 done" and work.route == "Claude Code · Haiku · effort medium"
    release.set()
    assert wait_for(lambda: page._job is None)
    assert built == [HAIKU] and backend.drafted == [FIRST, SECOND]           # one backend, built once, for both images
    assert page.results.result.route == HAIKU


# -- the Images page: the results panel -----------------------------------------------------------------------------

def rows(view):
    """(image, what became of it) per row of the results panel."""
    labels = view.scroll.widget().findChildren(QLabel)
    return list(zip([label.text() for label in labels if label.objectName() == q.PANEL_MONO],
                    [label.text() for label in labels if label.objectName() == q.TASK_STATE]))


def test_the_panel_lists_each_image_after_a_run_and_retry_runs_only_the_failed(make_page, monkeypatch):  # noqa: F811
    page = make_page()
    run_jobs_inline(monkeypatch)
    backend = Backend(OllamaProvider("offline-test"), {SECOND: alt_draft.DraftResult(error="overloaded")})
    run_on(monkeypatch, page, HAIKU, backend, FIRST, SECOND, THIRD, FOURTH)
    original = backend.draft

    def draft(path, context):
        if context.image == FIRST:               # a person writes the third image's text while the model works
            page.store[THIRD].long = "MY OWN TEXT"
        if context.image == THIRD:               # ... and the run is stopped on the third image
            page._job.stop_requested = True
        return original(path, context)

    backend.draft = draft
    answer(monkeypatch)
    page._draft_all()
    view = page.results
    assert not view.isHidden()
    assert view.title.text() == "Image descriptions · partly done" and view.route.text() == "Claude Code · Haiku · effort medium"
    assert rows(view) == [("first.png", "Drafted · needs review"), ("second.png", "Failed · overloaded"),
                          ("third.png", "You edited it during the run · your text kept"),
                          ("fourth.png", "Cancelled · not sent")]
    assert page.store[THIRD].long == "MY OWN TEXT"
    assert view.summary.text().startswith("1 drafted · 1 kept as you edited it · 1 failed · 1 cancelled. Each finished item")
    assert view.retry.text() == "Retry failed (1)"
    # Retry failed: a new batch of the failed image only, on the route active now, asked about again
    backend.draft = original
    backend.drafted.clear()
    backend.results.clear()                      # the model answers this time
    asked = answer(monkeypatch)
    view.retry.click()
    assert [text for text, _line in asked] == [f"Draft 1 image description in {page.app.project.root.name}?"]
    assert backend.drafted == [SECOND]
    assert rows(view) == [("second.png", "Drafted · needs review")]
    assert view.title.text() == "Image descriptions · done" and view.retry is None
    view.close_button.click()
    assert view.isHidden() and view.result is None


def test_a_draft_over_text_typed_into_the_form_counts_as_kept(make_page, monkeypatch):  # noqa: F811
    page = make_page()
    run_jobs_inline(monkeypatch)
    run_on(monkeypatch, page, HAIKU, Backend(OllamaProvider("offline-test")), CHART)
    page._forms[0].fields["long"].setPlainText("TYPED, NOT SAVED")
    answer(monkeypatch)
    page._draft_all()
    assert rows(page.results) == [("chart.png", "You edited it during the run · your text kept")]
    assert page._forms[0].fields["long"].toPlainText() == "TYPED, NOT SAVED"
    assert page.results.retry is None and page.results.title.text() == "Image descriptions · done"


def test_a_translation_batch_has_its_own_title_and_labels(make_page, monkeypatch):  # noqa: F811
    page = make_page()
    run_jobs_inline(monkeypatch)
    run_on(monkeypatch, page, Route(CLAUDE_CODE, TRANSLATION, "haiku", "medium"), Backend(OllamaProvider("offline-test")),
           FIRST, SECOND)
    answer(monkeypatch)
    page._translate_all()
    assert page.results.title.text() == "Image translations · done"
    assert [label for _name, label in rows(page.results)] == ["Translated · needs review"] * 2
    assert page.results.summary.text().startswith("2 translated. Each finished item")


def test_stop_and_switch_cancels_the_pending_images_and_the_panel_says_so(make_page, monkeypatch):  # noqa: F811
    page = make_page()
    release = threading.Event()
    provider = OllamaProvider("offline-test")
    provider.abort = release.set
    backend = Backend(provider, block=None)
    run_on(monkeypatch, page, HAIKU, backend, FIRST, SECOND, THIRD)
    second_started = threading.Event()
    original = backend.draft

    def draft(path, context):
        if context.image == SECOND:
            second_started.set()
            release.wait(5)                                              # a request that only the abort ends
            return alt_draft.DraftResult(error="aborted")
        return original(path, context)

    backend.draft = draft
    answer(monkeypatch)
    page._draft_all()
    assert wait_for(second_started.is_set)
    assert wait_for(lambda: FIRST in page._job.outcomes)
    [work] = page.running_work()
    assert work.line == ("Drafting image descriptions · 1 of 3 done · Claude Code · Haiku · effort medium. "
                         "Pending images are cancelled, not moved to the other route")
    work.stop()                                                           # "Stop and switch"
    assert page._job is None
    assert page.results.title.text() == "Image descriptions · partly done"
    assert rows(page.results) == [("first.png", "Drafted · needs review"), ("second.png", "Cancelled · not sent"),
                                  ("third.png", "Cancelled · not sent")]
    assert page.results.retry is None                                    # cancelled is not failed: nothing to retry
    assert wait_for(lambda: page.app.slots == ["took", "gave"])


# -- the window: the side panels and the assistant's image tasks -------------------------------------------------------

pytest.importorskip("PySide6.QtWebEngineWidgets")
from test_claude_code_gui import env as claude_env  # noqa: E402,F401 -- a fixture
from test_claude_images import ANSWER as IMAGE_ANSWER, GERMAN as GERMAN_IMAGE  # noqa: E402
from test_claude_tasks_gui import buttons, click, fake, pump, settled, wait_until, with_pictures  # noqa: E402,F401

windows_only = pytest.mark.skipif(sys.platform == "win32", reason="the stand-in for claude is a POSIX script")


@windows_only
def test_the_side_panels_say_cloud_while_the_switch_is_on_cloud(fake):  # noqa: F811
    env = fake.env
    panels = env.window.side_panels
    with_pictures(fake, a={})
    panels.set_panel("language")
    pump(0.1)
    translate = next(b for b in panels.panels["language"].findChildren(Button) if b.text().startswith("Translate to"))
    assert translate.text() == "Translate to DE · cloud"
    env.window.state.set_ai_route(ai_profile.LOCAL)
    assert translate.text() == "Translate to DE"
    panels.set_panel("images")
    pump(0.1)
    redraft = [b for b in panels.panels["images"].findChildren(Button) if b.text().startswith("Redraft")]
    assert [b.text() for b in redraft] == ["Redraft…"]
    env.window.state.set_ai_route(ai_profile.CLOUD, CLAUDE_CODE)           # the open panel follows the switch, no rebuild
    assert [b.text() for b in redraft] == ["Redraft… · cloud"]


@windows_only
def test_the_images_page_of_the_window_follows_the_switch(fake):  # noqa: F811
    window = fake.env.window
    page = window.images_page
    window.state.set_ai_route(ai_profile.LOCAL)
    assert page.draft_all_button.text() == "Draft all…" and page.draft_note.text().endswith("· Ollama")
    window.state.set_ai_route(ai_profile.CLOUD, CLAUDE_CODE)
    assert page.draft_all_button.text() == "Draft all… · cloud" and page.draft_note.text() == CLOUD_NOTE


@windows_only
def test_an_image_task_of_the_assistant_ends_in_the_same_panel_and_retry_runs_the_failed(fake, monkeypatch):  # noqa: F811
    env = fake.env
    area = env.window.assistant
    with_pictures(fake, a={}, b={})
    wait_until(lambda: "Describe images (2)" in buttons(env))
    fake.reply({"answer": IMAGE_ANSWER}, {"error": "overloaded"}, {"answer": IMAGE_ANSWER})
    click(env, "Describe images (2)")
    assert settled(env).endswith(": 1 described, 1 failed (media/b.png: overloaded)")
    view = area.image_results
    assert area._stack.currentWidget() is area._results_page and view.result is area.tasks.result
    assert view.title.text() == "Image descriptions · partly done" and view.route.text() == "Claude Code · Haiku · effort medium"
    assert rows(view) == [("a.png", "Drafted · needs review"), ("b.png", "Failed · overloaded")]
    assert view.retry.text() == "Retry failed (1)"
    asked = answer(monkeypatch)
    view.retry.click()
    assert asked[0][0] == f"Draft 1 image description in {env.window.project.root.name}?"
    assert settled(env).endswith(": 1 described")
    assert [call["images"][0]["media_type"] for call in fake.calls()] == ["image/png"] * 3 and len(fake.calls()) == 3
    assert view.title.text() == "Image descriptions · done" and view.retry is None
    view.back.click()                                                    # Back to conversation
    assert area.tasks.result is None and area._stack.currentWidget() is not area._results_page


@windows_only
def test_a_stopped_image_task_shows_its_cancelled_images(fake, tmp_path):  # noqa: F811
    env = fake.env
    area = env.window.assistant
    with_pictures(fake, a={}, b={})
    wait_until(lambda: "Describe images (2)" in buttons(env))
    fake.reply({"answer": IMAGE_ANSWER, "delay": 5, "marker": str(tmp_path / "late")})
    click(env, "Describe images (2)")
    wait_until(lambda: fake.log.exists())
    area.task_row.stop_button.click()
    settled(env)
    assert rows(area.image_results) == [("a.png", "Cancelled · not sent"), ("b.png", "Cancelled · not sent")]
    assert area.image_results.retry is None and area.image_results.title.text() == "Image descriptions · partly done"
    click(env, "Describe images (2)")                                    # a new task clears the panel
    assert area.tasks.result is None
    area.tasks.stop()
    settled(env)


@windows_only
def test_translating_the_descriptions_ends_in_the_panel_too(fake):  # noqa: F811
    env = fake.env
    with_pictures(fake, a=dict(short="A bar chart.", long="Two bars."))
    wait_until(lambda: "Translate image descriptions (1)" in buttons(env))
    fake.reply({"answer": GERMAN_IMAGE})
    click(env, "Translate image descriptions (1)")
    settled(env)
    view = env.window.assistant.image_results
    assert view.title.text() == "Image translations · done" and rows(view) == [("a.png", "Translated · needs review")]
