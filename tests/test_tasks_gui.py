# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Assistant tasks on scripted routes, including image jobs and deck batches."""
from __future__ import annotations

import threading
import time
from functools import partial
from types import SimpleNamespace

import pytest
from slidemage.project import ProjectContext
from PySide6.QtWidgets import QMessageBox, QPlainTextEdit
from conftest import SLIDE_TEXT, build_window, wait_until as _wait_until
from fake_chat import FakeChatSurface, FakeTaskRunner
from slidemage.deck_scan import scan_decks

from slidemage.slide_source import read_slide_source
from slidemage import alt_draft, alt_images, app_settings, slide_ids, slide_language, slide_versioning
from slidemage.ai import ai_profile, translation_style
from slidemage.ai.task_result import CANCELLED, FAILED, Outcome
from slidemage.ai.agent_types import EDIT_AUTO
from slidemage.ui.kit.widgets import Button, ModalSheet
from slidemage.ui.workspace import task_card_model as card_model
from slidemage.ui.workspace import task_bubbles as tasks_module
from assistant_accessibility_helpers import pump


SLIDE = "slides/abc-EN-Hello-current.tex"
LF = SLIDE_TEXT.replace("\r\n", "\n")
BROKEN = LF.replace("\t\\end{itemize}\n", "", 1)              # \begin{itemize} is not closed
FIX = {"edits": [{"before": "\t\t\\item Second point\n", "after": "\t\t\\item Second point\n\t\\end{itemize}\n"}]}
SENT = slide_versioning.strip_marker(slide_ids.body_of(LF))   # what a translation request carries
GERMAN = {"body": SENT.replace("Hello", "Hallo").replace("First point", "Erster Punkt")}
GERMAN_NAME = "-DE-"


wait_until = partial(_wait_until, seconds=20)


IMAGE_ANSWER = {"short": "A bar chart.", "long": "Two bars: A is higher than B.",
                "takeaway": "A beats B.", "role_suggestion": "informative"}
GERMAN_IMAGE = {"short_de": "Ein Balkendiagramm.", "long_de": "Zwei Balken.", "takeaway_de": "A schlägt B."}


def add_pictures(root, **entries):
    ctx = ProjectContext.at(root)
    (root / "media").mkdir(exist_ok=True)
    slide = root / SLIDE
    entries_by_path = {f"media/{name}.png": alt_images.ImageEntry(image=f"media/{name}.png", **fields)
                       for name, fields in entries.items()}
    for image in entries_by_path:
        (root / image).write_bytes(b"fake image")
    includes = b"".join(f"\t\\includegraphics{{{image}}}\r\n".encode() for image in entries_by_path)
    slide.write_bytes(slide.read_bytes().replace(b"\\end{standardframe}", includes + b"\\end{standardframe}"))
    alt_images.update_store(ctx, lambda store: store.update(entries_by_path) or True)
    return slide


class Fake:
    """Script a route runner and image backends, recording captured work."""

    def __init__(self, env, route):
        self.env, self.route = env, route
        self.renders, self.error, self.records, self.steps = [], "", [], []
        self.lock = threading.Lock()
        self.runner = FakeTaskRunner(env.window.project, self.run)
        route.runner = self.runner
        route.draft_backend = lambda _ctx, _route, cancel: self.backend(cancel)
        route.translation_backend = lambda _ctx, _route, cancel: self.backend(cancel)

    def rendered(self, *args, **kwargs):
        self.renders.append(args)
        if self.error:
            raise RuntimeError(self.error)
        return b"png"

    def reply(self, *replies):
        with self.lock:
            self.steps = list(replies)

    def calls(self):
        with self.lock:
            return list(self.records)

    def next_step(self, request, cancel):
        with self.lock:
            self.records.append({"request": request, "time": time.monotonic()})
            index = next((i for i, step in enumerate(self.steps) if step.get("when") and step["when"] in request), None)
            if index is None:
                index = next((i for i, step in enumerate(self.steps) if not step.get("when")), 0)
            step = self.steps[index]
            if len(self.steps) > 1:
                self.steps.pop(index)
        if gate := step.get("gate"):
            assert gate.wait(5), "Timed out waiting for the test to release the worker"
        if cancel.wait(step.get("delay", 0)):
            return None
        if marker := step.get("marker"):
            from pathlib import Path
            Path(marker).touch()
        return step

    def run(self, _task, _captured, request, cancel, _span):
        step = self.next_step(request, cancel)
        if step is None:
            return Outcome(CANCELLED)
        return Outcome(FAILED, message=step["error"]) if "error" in step else step["answer"]

    def backend(self, cancel):
        fake = self

        class Backend:
            label = "Fake route"

            def draft(self, path, context):
                step = fake.next_step(str(path), cancel)
                if step is None:
                    return alt_draft.DraftResult(error="Cancelled")
                if "error" in step:
                    return alt_draft.DraftResult(error=step["error"])
                return alt_draft.DraftResult(**step["answer"], model=self.label)

            def translate(self, entry):
                step = fake.next_step(entry.image, cancel)
                if step is None:
                    return alt_draft.TranslationResult(error="Cancelled")
                if "error" in step:
                    return alt_draft.TranslationResult(error=step["error"])
                return alt_draft.TranslationResult(**step["answer"], model=self.label,
                                                   source_hash=alt_images.en_text_hash(entry))

        return Backend()


@pytest.fixture
def ctx(root):
    return ProjectContext.at(root)


@pytest.fixture
def fake(qapp, root, ctx, monkeypatch, fake_routes):
    fake_routes.cloud.surface_factory = FakeChatSurface
    ai_profile.mark_cloud_seen(ctx)
    ai_profile.set_mode(ctx, ai_profile.CLOUD)
    window = build_window(monkeypatch, ctx)
    window.show()
    window.state.set_mode("source")
    window.state.set_deck(next(d for d in scan_decks(ctx) if d.name == "test"))
    window.state.set_focused_slide("abc")
    env = SimpleNamespace(root=root, path=root / SLIDE, window=window)
    wait_until(lambda: window.centre.path == env.path)
    window.centre.source.file_for(env.path)
    pump(0.1)
    made = Fake(env, fake_routes.cloud)
    window.assistant.refresh_models()
    window.assistant.chat.session.set_mode(EDIT_AUTO)
    monkeypatch.setattr(window.assistant.workspace, "render_preview", made.rendered)
    yield made
    window.assistant.shutdown()


def slide_file(env):
    return env.window.centre.source.file_for(env.path)


def buttons(env):
    """Every task that fits the scope now (the header shows the two most relevant of them)."""
    area = env.window.assistant
    return [bubble.label for bubble in area.header.offers(area.scope.current())]


def click(env, label):
    """Run the task of that label, as the header's button or the palette's command does."""
    area = env.window.assistant
    area.run_task(next(b for b in area.header.offers(area.scope.current()) if b.label == label))


def settled(env):
    wait_until(lambda: not env.window.assistant.tasks.busy)
    pump(0.05)
    card = env.window.assistant.tasks.card
    return card_model.state_text(card) if card else env.window.assistant.task_row.status.text()


def run_task(env, label):
    click(env, label)
    return settled(env)


def german_files(env):
    return sorted((env.root / "slides").glob(f"*{GERMAN_NAME}*-current.tex"))


def break_slide(env):
    slide_file(env).editor.replace_all_text(BROKEN)
    wait_until(lambda: "Fix LaTeX errors" in buttons(env))


# -- which bubbles


# -- fixing

def test_fix_applies_to_the_buffer_and_checks_the_active_preview(fake):
    env = fake.env
    env.window.state.set_mode("split")
    pump(0.1)
    break_slide(env)
    fake.reply({"answer": FIX})
    assert "The preview is current." in run_task(env, "Fix LaTeX errors") and env.window.state.mode == "split"
    ((target, text, view, language, _cancel),) = fake.renders
    assert target.source_path == env.path and text == LF and (view, language) == ("instructor", "EN")
    editor = slide_file(env).editor
    assert editor.text() == LF and env.path.read_bytes() == SLIDE_TEXT.encode()
    wait_until(lambda: buttons(env) == ["Translate to German", "Better title"])
    editor.undo()
    assert editor.text() == BROKEN and "(environments)" in fake.calls()[0]["request"]
    env.window.centre.open_file(env.root / "decks/test.tex")
    wait_until(lambda: buttons(env) == [])


@pytest.mark.parametrize("label, before, answer, proposed", [
    ("Fix LaTeX errors", BROKEN, FIX, "Second point"),
    ("Better title", LF, {"title": "A better title"}, "A better title"),
], ids=["fix", "title"])
def test_typing_during_a_task_keeps_the_proposal_without_overwriting(fake, label, before, answer, proposed):
    env = fake.env
    if before == BROKEN:
        break_slide(env)
    fake.reply({"answer": answer, "delay": 0.4})
    click(env, label)
    editor = slide_file(env).editor
    typed = before + "% typed meanwhile\n"
    editor.replace_all_text(typed)
    assert "The proposal is kept but not applied." in settled(env)
    card = env.window.assistant.tasks.card
    assert card.phase == card_model.CONFLICT and proposed in card.after
    assert editor.text() == typed and fake.renders == []


def test_a_focus_change_during_a_task_does_not_change_its_target(fake):
    env = fake.env
    break_slide(env)
    fake.reply({"answer": FIX, "delay": 0.4})
    click(env, "Fix LaTeX errors")
    env.window.state.set_focused_slide("abd")
    wait_until(lambda: env.window.centre.path.name.startswith("abd"))
    env.window.assistant.task_card.render()
    assert "still this slide" in env.window.assistant.task_card.target.text()
    assert "Changed 1 line in abc-EN-Hello-current.tex" in settled(env)
    assert slide_versioning.without_plus(read_slide_source(env.path)[0]) == LF
    assert env.window.centre.source.file_for(env.window.centre.path).editor.text() == LF.replace("Hello", "Second")


# -- translating

def test_translation_preserves_the_source_call_and_links_both_slides(ctx, fake):
    from slidemage.ui.dialogs.settings_languages import LanguagesSection

    env = fake.env
    # Keep the backlink unsaved when leaving the slide, so the partner does not become outdated.
    env.window.set_autosave(False)
    deck = env.root / "decks/test.tex"
    deck.write_bytes(deck.read_bytes().replace(b"\\slide{abc-EN-Hello}\r\n",
                                              b"\\conditionalslide[instructor]{abc-EN-Hello}\r\n")
                     .replace(b"\\end{document}", b"\\slide{abc-EN-Hello}\r\n\\end{document}"))
    env.window.reload_decks()
    wait_until(lambda: "Translate to German" in buttons(env))
    settings = LanguagesSection(SimpleNamespace(project=ctx))
    settings.address.changed.emit("informal")
    assert translation_style.de_address(ctx) == "du"
    (env.root / ".slidemage/glossary.md").write_text("slide = Folie\n", encoding="utf-8")

    original_deck = deck.read_bytes()
    fake.reply({"error": "overloaded"})
    assert "overloaded" in run_task(env, "Translate to German")
    assert german_files(env) == [] and deck.read_bytes() == original_deck
    assert slide_file(env).editor.text() == LF

    fake.reply({"answer": GERMAN})
    status = run_task(env, "Translate to German")
    (partner,) = german_files(env)
    slug = partner.name.removesuffix("-current.tex")
    assert f"Created {partner.name}" in status and "The preview is current." in status
    # The deck edit syncs the new file's header on a separate thread.
    wait_until(lambda: partner.read_bytes().startswith(b"%% Included in decks: test\r\n"))
    text = partner.read_bytes().decode()
    assert "%% Translation of: abc-EN-Hello\r\n" in text
    assert "Hallo" in text and "Erster Punkt" in text and "\\setSlideVersion" not in text
    calls = deck.read_text()
    assert f"\\conditionalslide[instructor]{{abc-EN-Hello}}\n\\conditionalslide[instructor]{{{slug}}}\n" in calls
    assert calls.count(slug) == 1
    source = slide_file(env).editor.text()
    assert f"%% DE translation: {slug}\n" in source and env.window.centre.path == env.path
    next(b for b in env.window.assistant.task_card.findChildren(Button) if b.text() == "View DE version").click()
    assert env.window.centre.path == partner
    ((target, *_),) = fake.renders
    assert target.source_path == partner
    assert slide_language.translation_group(ctx, "abc-EN-Hello")[0].partner == slug
    env.window.centre.open_file(env.path)
    env.window.assistant.header.schedule()
    wait_until(lambda: env.window.centre.path == env.path and buttons(env) == ["Better title"])
    assert env.path.read_bytes() == SLIDE_TEXT.encode() and slide_file(env).editor.text() == source
    request = fake.calls()[-1]["request"]
    assert "from English to German" in request and "Address the audience informally." in request
    assert "slide = Folie\n<slide>\n" in request and "\\setSlideVersion" not in request and "Included in decks" not in request


def test_a_source_that_changed_meanwhile_gets_no_partner(fake):
    env = fake.env
    fake.reply({"answer": GERMAN, "delay": 0.4})
    click(env, "Translate to German")
    typed = LF + "% typed meanwhile\n"
    slide_file(env).editor.replace_all_text(typed)
    assert settled(env) == "abc changed while this task ran. The proposal is kept but not applied."
    assert german_files(env) == [] and slide_file(env).editor.text() == typed
    assert "Hallo" in env.window.assistant.tasks.card.after
    assert (env.root / "decks" / "test.tex").read_text().count("\\slide") == 2


def test_a_slide_that_is_not_in_the_deck_still_gets_its_translation(fake):
    env = fake.env
    deck = env.root / "decks" / "test.tex"
    deck.write_bytes(deck.read_bytes().replace(b"\\slide{abd-EN-Second}\r\n", b""))
    env.window.reload_decks()
    env.window.state.set_focused_slide("abd")
    wait_until(lambda: env.window.centre.path.name.startswith("abd") and "Translate to German" in buttons(env))
    fake.reply({"answer": GERMAN})
    assert "Deck insertion is pending." in run_task(env, "Translate to German")
    partner, = german_files(env)
    assert deck.read_text().count("\\slide") == 1
    deck.write_bytes(deck.read_bytes().replace(b"\\end{document}", b"\\slide{abd-EN-Second}\r\n\\end{document}"))
    next(b for b in env.window.assistant.task_card.findChildren(Button) if b.text() == "Retry insertion").click()
    assert german_files(env) == [partner]
    id_slug = partner.name.removesuffix("-current.tex")
    assert f"\\slide{{abd-EN-Second}}\n\\slide{{{id_slug}}}" in deck.read_text()
    assert not env.window.assistant.tasks.card.insertion_problem


def test_buffer_backlink_is_pending_if_the_buffer_changes_after_the_commit(fake, monkeypatch):
    env = fake.env
    env.window.set_autosave(False)
    workspace = env.window.assistant.workspace
    apply = workspace.apply_to_buffer
    raw = env.path.read_bytes()
    typed = LF + "% unsaved earlier edit\n"
    slide_file(env).editor.replace_all_text(typed)

    def type_after_commit(path, before, after):
        partner, = german_files(env)
        assert partner.name.removesuffix("-current.tex") in (env.root / "decks/test.tex").read_text()
        slide_file(env).editor.replace_all_text(typed + "% newer edit\n")
        return apply(path, before, after)

    monkeypatch.setattr(workspace, "apply_to_buffer", type_after_commit)
    fake.reply({"answer": GERMAN})
    status = run_task(env, "Translate to German")
    assert "Created " in status and "backlink in abc-EN-Hello-current.tex is pending" in status
    assert slide_file(env).editor.text() == typed + "% newer edit\n"
    assert env.path.read_bytes() == raw


# -- the model of a task

def test_two_clicks_start_one_task_and_switching_routes_leaves_it_running(ctx, fake, fake_routes):
    env = fake.env
    ai_profile.set_model_choice(ctx, fake.route.id, ai_profile.TRANSLATION, "fake-2")
    fake.reply({"answer": GERMAN, "delay": 0.3})
    click(env, "Translate to German")
    tasks = env.window.assistant.tasks
    tasks.start(tasks_module.ai_tasks.TRANSLATE)
    assert (tasks.card.route.route, tasks.card.route.model) == (fake.route.id, "fake-2")
    ai_profile.set_mode(ctx, ai_profile.LOCAL)
    assert "Created" in settled(env)
    assert len(fake.calls()) == len(german_files(env)) == 1 and fake_routes.local.providers == []


def test_prompt_route_fills_one_prompt_per_task_and_never_runs_or_queues_it(fake):
    env, filled = fake.env, []
    area = env.window.assistant
    surface = area.surface_for(fake.route.id)
    surface.fill_prompt = lambda text: filled.append(text) or True

    def task_prompt(_ctx, _route, name, slide, language, **kw):
        if name not in ("translate", "summarise"):
            return None
        if slide:
            return f"{name} @{slide.name} into {kw['language_name']} ({language})"
        deck = kw["deck_path"]
        return f"{name} {deck.name} {kw['language_name']}" if deck else ""

    fake.route.task_prompt = task_prompt
    fake.route.problem_text = "The terminal is all there is."
    assert area.tasks.refusal(tasks_module.ai_tasks.TRANSLATE) == ""
    assert area.tasks.refusal(tasks_module.ai_tasks.PROOFREAD)
    click(env, "Translate to German")
    surface.fill_prompt = lambda text: False
    click(env, "Translate to German")
    assert "wait until its input box is back" in area.task_row.status.text()
    surface.fill_prompt = lambda text: filled.append(text) or True
    deck_scope(env)
    click(env, "Translate missing slides (2)")
    click(env, "Summarise this deck")
    assert filled == ["translate @abc-EN-Hello-current.tex into German (DE)", "translate test.tex German", "summarise test.tex "]
    assert fake.calls() == [] and area.tasks.card is None and not area.tasks.busy


# -- the other bubbles

PROSE = LF.replace("First point", "This first point explains the main idea of the slide with enough ordinary words")
TEXT_BUBBLES = ["Translate to German", "Proofread", "Make more concise", "Better title", "Add speaker notes"]


@pytest.fixture
def prose(fake):
    slide_file(fake.env).editor.replace_all_text(PROSE)
    wait_until(lambda: buttons(fake.env) == TEXT_BUBBLES)
    return fake


def test_a_slide_without_a_language_is_not_proofread(ctx, prose):
    env = prose.env
    legacy = tasks_module._Focus(env.root / "slides" / "xyz-legacy-current.tex", "xyz-legacy", PROSE, PROSE)
    assert "Proofread" not in [b.label for b in tasks_module._offers(ctx, legacy, [])]


def test_proofreading_applies_edits_and_leaves_clean_text_alone(prose):
    env = prose.env
    prose.reply({"answer": {"edits": [{"before": "enough ordinary words", "after": "enough ordinary words,"}]}})
    assert "Changed 1 line" in run_task(env, "Proofread")
    editor = slide_file(env).editor
    assert editor.text() == PROSE.replace("ordinary words", "ordinary words,")
    assert "Proofread this English slide" in prose.calls()[0]["request"]
    editor.undo()
    prose.reply({"answer": {"edits": []}})
    assert "Nothing to change" in run_task(env, "Proofread") and editor.text() == PROSE


def test_a_shortened_slide_is_applied_and_one_that_loses_structure_is_refused(prose):
    env = prose.env
    lost = PROSE.replace("\t\\end{itemize}\n", "")
    prose.reply({"answer": {"body": lost}})
    assert run_task(env, "Make more concise").startswith("Fake route's answer was refused: the new text must keep every environment")
    assert slide_file(env).editor.text() == PROSE and len(prose.calls()) == 1
    shorter = PROSE.replace(" with enough ordinary words", "")
    prose.reply({"answer": {"body": shorter}})
    assert "Changed 1 line" in run_task(env, "Make more concise") and slide_file(env).editor.text() == shorter


def test_a_speaker_note_goes_before_the_frames_end_and_its_bubble_goes(prose):
    env = prose.env
    prose.reply({"answer": {"note": "Open with the main idea."}})
    assert "Changed 1 line" in run_task(env, "Add speaker notes")
    assert slide_file(env).editor.text().endswith("\t\\note{Open with the main idea.}\n\\end{standardframe}\n")
    assert "Add speaker notes" not in buttons(env)
    editor = slide_file(env).editor
    editor.replace_all_text("Plain words without any frame, but enough of them to count as running text here.\n")
    wait_until(lambda: "Proofread" in buttons(env) and "Better title" not in buttons(env))
    editor.replace_all_text(LF)
    wait_until(lambda: buttons(env) == ["Translate to German", "Better title"])
    prose.reply({"answer": {"title": "A better title"}, "delay": 0.3})
    click(env, "Better title")
    assert card_model.state_text(env.window.assistant.tasks.card).startswith("Looking for a better title for abc.")
    assert "Changed 1 line" in settled(env)
    assert editor.text() == LF.replace("{Hello}", "{A better title}")


# -- updating a translation

GERMAN_ID = "abe-DE-Hallo"
GERMAN_HEADER = "%% Included in decks: (none)\r\n%%\r\n%% Translation of: abc-EN-Hello\r\n%%\r\n\r\n"
UPDATE_ANSWER = {"body": slide_versioning.set_marker(GERMAN["body"], (1, 0, 0)).replace("Erster Punkt", "Erster Punkt!")}


@pytest.fixture
def outdated(fake):
    """A German partner of abc whose source was saved (a backup is the sign) after the partner was written."""
    env = fake.env
    path = env.root / "slides" / f"{GERMAN_ID}-current.tex"
    german = slide_versioning.set_marker(GERMAN["body"], (1, 0, 0))
    path.write_bytes((GERMAN_HEADER + german.replace("\n", "\r\n")).encode())
    backup = env.root / "slides" / ".backups" / "abc-EN-Hello-current.tex" / "29990101-000000.tex"
    backup.parent.mkdir(parents=True)
    backup.write_text("x")
    fake.partner = path
    env.window.assistant.header.schedule()
    return fake


def open_partner(env, path):
    env.window.centre.open_file(path)
    wait_until(lambda: env.window.centre.path == path and "Update German translation" in buttons(env))


def test_an_update_goes_into_the_open_translation_and_keeps_its_header(outdated):
    env = outdated.env
    wait_until(lambda: "Update German translation" in buttons(env) and "Translate to German" not in buttons(env))
    open_partner(env, outdated.partner)
    outdated.reply({"answer": UPDATE_ANSWER})
    assert f"Updated {GERMAN_ID}-current.tex. It stays linked to the English slide." in run_task(env, "Update German translation")
    editor = env.window.centre.source.file_for(outdated.partner).editor
    assert editor.text().startswith(GERMAN_HEADER.replace("\r\n", "\n")) and "Erster Punkt!" in editor.text()
    assert "\\setSlideVersion{1-0-0}" in editor.text()
    editor.undo()
    assert "Erster Punkt!" not in editor.text()
    request = outdated.calls()[0]["request"]
    source, translation = request.split("<source>\n")[1].split("</source>\n<slide>\n")
    assert "First point" in source and "\\setSlideVersion" not in source and "Included in decks" not in source
    assert translation.startswith("% A note") and "Erster Punkt" in translation and "Translation of" not in translation


@pytest.mark.parametrize("in_buffer", [True, False], ids=["buffer", "disk"])
def test_a_translation_changed_during_update_is_not_overwritten(outdated, in_buffer):
    env = outdated.env
    path = outdated.partner
    wait_until(lambda: "Update German translation" in buttons(env))
    if in_buffer:
        open_partner(env, path)
        editor = env.window.centre.source.file_for(path).editor
    original = path.read_bytes()
    outdated.reply({"answer": UPDATE_ANSWER, "delay": 0.4})
    click(env, "Update German translation")
    if in_buffer:
        typed = editor.text() + "% getippt\n"
        editor.replace_all_text(typed)
    else:
        path.write_bytes(original + b"% getippt\r\n")
    settled(env)
    card = env.window.assistant.tasks.card
    assert card.phase == card_model.CONFLICT and "Erster Punkt!" in card.after
    if in_buffer:
        assert editor.text() == typed and path.read_bytes() == original
    else:
        assert path.read_bytes() == original + b"% getippt\r\n"


# -- images

def with_pictures(fake, **entries):
    slide = add_pictures(fake.env.root, **entries)
    slide_file(fake.env).editor.replace_all_text(slide.read_text(encoding="utf-8"))


def test_image_bubbles_count_unfinished_work_and_disappear_after_translation(ctx, fake):
    env = fake.env
    with_pictures(fake, a={}, b={}, c=dict(role=alt_images.ROLE_DECORATIVE), d=dict(short="s", long="l"))
    wait_until(lambda: "Describe images (2)" in buttons(env))
    assert "Translate image descriptions (1)" in buttons(env)
    alt_images.update_store(ctx, lambda e: setattr(e["media/a.png"], "long", "now described") or True)
    env.window.assistant.header.schedule()
    assert "Describe images (1)" in buttons(env) and "Translate image descriptions (2)" in buttons(env)
    fake.reply({"answer": GERMAN_IMAGE})
    assert run_task(env, "Translate image descriptions (2)").endswith(": 2 translated")
    store = alt_images.load_store(ctx)
    for name in ("a", "d"):
        entry = store[f"media/{name}.png"]
        assert (entry.short_de, entry.long_de) == (GERMAN_IMAGE["short_de"], GERMAN_IMAGE["long_de"])
    assert "Describe images (1)" in buttons(env) and not any(b.startswith("Translate image") for b in buttons(env))


def test_stop_ends_the_running_image_task_and_the_rest(ctx, fake, tmp_path):
    env = fake.env
    with_pictures(fake, a={}, b={})
    wait_until(lambda: "Describe images (2)" in buttons(env))
    fake.reply({"answer": IMAGE_ANSWER, "delay": 5, "marker": str(tmp_path / "late")})
    click(env, "Describe images (2)")
    wait_until(lambda: fake.calls())
    env.window.assistant.task_row.stop_button.click()
    assert settled(env).startswith("Stopped after ") and settled(env).endswith(": 0 described")
    assert len(fake.calls()) == 1 and not (tmp_path / "late").exists()
    assert not any(e.short for e in alt_images.load_store(ctx).values())


def test_image_batch_keeps_successful_drafts_and_shows_them_in_the_panel(ctx, fake):
    env = fake.env
    with_pictures(fake, a={}, b={})
    env.window.side_panels.set_panel("images")
    wait_until(lambda: "Describe images (2)" in buttons(env))
    fake.reply({"answer": IMAGE_ANSWER}, {"error": "overloaded"})
    assert run_task(env, "Describe images (2)").endswith(": 1 described, 1 failed (media/b.png: overloaded)")
    draft, failed = alt_images.load_store(ctx).values()
    assert draft.short == IMAGE_ANSWER["short"] and draft.drafted_by == "Fake route"
    assert draft.status != alt_images.STATUS_REVIEWED and not failed.short
    forms = env.window.side_panels.panels["images"]._forms
    assert IMAGE_ANSWER["short"] in [form.short_edit.toPlainText() for form in forms]


# -- deck batches

def add_slide(env, word):
    """A third slide, {word} as its frame title, called by the deck after the others."""
    (env.root / "slides" / f"abe-EN-{word}-current.tex").write_bytes(SLIDE_TEXT.replace("Hello", word).encode())
    deck = env.root / "decks" / "test.tex"
    deck.write_bytes(deck.read_bytes().replace(b"\\end{document}", f"\\slide{{abe-EN-{word}}}\r\n\\end{{document}}".encode()))
    env.window.reload_decks()


def deck_scope(env, label="Summarise this deck"):
    env.window.assistant.scope._buttons["deck"].click()
    wait_until(lambda: label in buttons(env))


def start_translation_batch(env, count):
    deck_scope(env)
    click(env, f"Translate missing slides ({count})")


def german(word):
    """The answer of the fake for the slide whose frame title is `word`."""
    return {"body": SENT.replace("Hello", word).replace("First point", f"Erster {word}")}


def lines(env):
    return env.window.assistant.tasks.report.splitlines()


def test_the_deck_bubbles_follow_the_scope_and_count_each_slide_once(fake):
    env = fake.env
    assert buttons(env) == ["Translate to German", "Better title"]
    deck_scope(env)
    assert buttons(env) == ["Translate missing slides (2)", "Summarise this deck"]
    deck = env.root / "decks" / "test.tex"
    deck.write_bytes(deck.read_bytes().replace(b"\\end{document}", b"\\slide{abc-EN-Hello}\r\n\\end{document}"))
    env.window.reload_decks()
    slide_file(env).editor.replace_all_text(BROKEN)
    wait_until(lambda: "Fix LaTeX errors (1 slides)" in buttons(env))
    assert buttons(env) == ["Translate missing slides (2)", "Fix LaTeX errors (1 slides)", "Summarise this deck"]
    env.window.assistant.scope._buttons["slide"].click()
    wait_until(lambda: buttons(env) == ["Translate to German", "Fix LaTeX errors", "Better title"])


def test_batch_captures_queued_edits_and_applies_parallel_results_on_the_gui_thread(fake, monkeypatch):
    env = fake.env
    add_slide(env, "Third")
    applied = []
    real = tasks_module.TaskRunner._apply

    def apply(runner, capture, outcome):
        applied.append((capture.id_slug, threading.current_thread() is threading.main_thread()))
        return real(runner, capture, outcome)

    monkeypatch.setattr(tasks_module.TaskRunner, "_apply", apply)
    gate = threading.Event()
    fake.reply({"when": "{Hello}", "answer": german("Hello"), "gate": gate},
               {"when": "{Second}", "answer": german("Second"), "gate": gate},
               {"answer": german("Third")})
    start_translation_batch(env, 3)
    try:
        wait_until(lambda: len(fake.calls()) == 2)
        assert all("{Third}" not in call["request"] for call in fake.calls())
        third = env.root / "slides/abe-EN-Third-current.tex"
        third.write_bytes(third.read_bytes().replace(b"First point", b"Freshly typed point"))
    finally:
        gate.set()
    assert "3 applied" in settled(env)
    assert "Freshly typed point" in fake.calls()[2]["request"]
    assert sorted(applied) == [("abc-EN-Hello", True), ("abd-EN-Second", True), ("abe-EN-Third", True)]
    assert len({path.name[:3] for path in german_files(env)}) == 3
    deck = (env.root / "decks/test.tex").read_text()
    assert deck.count("\\slide{") == 6 and len(lines(env)) == 3 and env.window.centre.path == env.path


def test_a_translation_batch_retries_only_insertions_into_a_previously_dirty_deck(fake, monkeypatch):
    env = fake.env
    window = env.window
    deck = env.root / "decks/test.tex"
    original = deck.read_bytes()
    fake.reply(*({"when": "{" + word + "}", "answer": german(word)} for word in ("Hello", "Second")))
    with monkeypatch.context() as dirty:
        dirty.setattr(window.centre, "is_dirty", lambda path: path == deck)
        start_translation_batch(env, 2)
        assert "2 applied" in settled(env)
    assert deck.read_bytes() == original
    registered = sorted(german_files(env))
    assert len(registered) == 2
    row = window.assistant.task_row
    assert row.retry_button.isVisibleTo(window.assistant)
    row.retry_button.click()
    assert sorted(german_files(env)) == registered and len(fake.calls()) == 2
    assert all(path.name.removesuffix("-current.tex") in deck.read_text() for path in registered)
    assert not row.retry_button.isVisibleTo(window.assistant)


def test_a_slide_edited_during_its_run_is_a_conflict_for_that_slide_only(fake):
    env = fake.env
    fake.reply(*({"when": "{" + word + "}", "answer": german(word), "delay": 0.8} for word in ("Hello", "Second")))
    start_translation_batch(env, 2)
    wait_until(lambda: len(fake.calls()) == 2)
    slide_file(env).editor.replace_all_text(LF + "% typed meanwhile\n")
    assert settled(env).startswith("Done in ") and "1 applied, 1 failed" in env.window.assistant.task_row.status.text()
    (partner,) = german_files(env)
    assert "-DE-Second-" in partner.name
    assert any(line == f"abc-EN-Hello: {tasks_module.CONFLICT}" for line in lines(env))
    assert (env.root / "decks" / "test.tex").read_text().count("\\slide{") == 3


def test_partners_created_during_a_batch_are_neither_retranslated_nor_overwritten(fake):
    env = fake.env
    add_slide(env, "Third")
    gate = threading.Event()
    fake.reply({"when": "{Hello}", "answer": german("Hello"), "gate": gate},
               {"when": "{Second}", "answer": german("Second"), "gate": gate},
               {"answer": german("Third")})
    manual = {}
    start_translation_batch(env, 3)
    try:
        wait_until(lambda: len(fake.calls()) == 2)
        for filename, source in (("abf-DE-Zweite", "abd-EN-Second"), ("abg-DE-Dritte", "abe-EN-Third")):
            path = env.root / "slides" / f"{filename}-current.tex"
            manual[path] = f"%% Translation of: {source}\r\n%%\r\n\r\nHand made\r\n".encode()
            path.write_bytes(manual[path])
    finally:
        gate.set()
    assert "1 applied, 1 failed" in settled(env)
    assert "abe-EN-Third: no longer fits" in lines(env) and len(fake.calls()) == 2
    assert len(german_files(env)) == 3
    # Deck sync can add its generated membership header to the existing partners.
    for path, text in manual.items():
        assert path.read_bytes().replace(b"%% Included in decks: test\r\n%%\r\n\r\n", b"", 1) == text


def test_a_rate_limit_drops_to_one_worker_and_gives_the_slide_a_second_try(fake):
    env = fake.env
    fake.reply({"when": "{Hello}", "error": "API Error: 429 rate limit exceeded"},
               {"when": "{Second}", "answer": german("Second"), "delay": 1.5}, {"answer": german("Hello")})
    start_translation_batch(env, 2)
    wait_until(lambda: tasks_module.SLOWED in env.window.assistant.task_row.status.text())
    assert settled(env).startswith("Done in ") and "2 applied" in env.window.assistant.task_row.status.text()
    calls = fake.calls()
    assert len(calls) == 3 and len(german_files(env)) == 2
    assert calls[2]["time"] - calls[1]["time"] >= 1.4 and "{Hello}" in calls[2]["request"]    # alone, after the other


def test_a_second_rate_limit_fails_that_slide_only(fake):
    env = fake.env
    fake.reply({"when": "{Second}", "answer": german("Second")}, {"when": "{Hello}", "error": "overloaded"},
               {"error": "overloaded"})
    start_translation_batch(env, 2)
    assert settled(env).startswith("Done in ") and "1 applied, 1 failed" in env.window.assistant.task_row.status.text()
    assert "abc-EN-Hello: overloaded" in lines(env) and len(fake.calls()) == 3


def test_a_usage_limit_stops_the_batch(fake, tmp_path):
    env = fake.env
    add_slide(env, "Third")
    fake.reply({"when": "{Hello}", "error": "Claude AI usage limit reached", "delay": 0.7},
               {"when": "{Second}", "answer": german("Second"), "delay": 3, "marker": str(tmp_path / "late")})
    start_translation_batch(env, 3)
    assert settled(env).startswith("Stopped: Claude AI usage limit reached")
    assert len(fake.calls()) == 2 and not (tmp_path / "late").exists() and german_files(env) == []


def test_stop_ends_both_tasks_and_the_queue_but_keeps_what_was_applied(fake, tmp_path):
    env = fake.env
    add_slide(env, "Third")
    fake.reply({"when": "{Hello}", "answer": german("Hello")},
               {"when": "{Second}", "answer": german("Second"), "delay": 5, "marker": str(tmp_path / "late")},
               {"answer": german("Third"), "delay": 5})
    start_translation_batch(env, 3)
    wait_until(lambda: len(german_files(env)) == 1)                       # abc is done, abe has started
    wait_until(lambda: len(fake.calls()) == 3)
    env.window.assistant.task_row.stop_button.click()
    assert settled(env).startswith("Stopped after ") and "1 applied" in env.window.assistant.task_row.status.text()
    assert len(german_files(env)) == 1 and not (tmp_path / "late").exists() and len(fake.calls()) == 3


def test_the_summary_is_shown_in_a_sheet_and_nothing_is_written(fake, monkeypatch):
    env = fake.env
    shown = []
    monkeypatch.setattr(ModalSheet, "exec", lambda sheet: shown.append(
        (sheet.findChild(QPlainTextEdit).toPlainText(), [b.text() for b in sheet.findChildren(type(env.window.assistant.task_row.stop_button))])))
    before = {path: path.read_bytes() for path in (env.root / "slides").iterdir()} | {
        env.root / "decks" / "test.tex": (env.root / "decks" / "test.tex").read_bytes()}
    fake.reply({"answer": {"summary": "Two slides: Hello and Second."}})
    deck_scope(env)
    assert run_task(env, "Summarise this deck").startswith("Done in ")
    assert shown[0][0] == "Two slides: Hello and Second." and "Copy" in shown[0][1]
    request = fake.calls()[0]["request"]
    assert request.startswith("Summarise this deck.\n<slide>\n") and request.count("<slide>") == 2
    assert "Included in decks" not in request and "{Hello}" in request and "{Second}" in request
    assert before == {path: path.read_bytes() for path in before} and slide_file(env).editor.text() == LF


def test_describing_the_decks_images_runs_over_every_image_once(ctx, fake):
    env = fake.env
    with_pictures(fake, a={}, b={})
    abd = env.root / "slides" / "abd-EN-Second-current.tex"
    abd.write_bytes((env.root / SLIDE).read_bytes().replace(b"Hello", b"Second"))
    deck_scope(env, "Describe images (2)")
    assert buttons(env)[-2:] == ["Describe images (2)", "Summarise this deck"]
    fake.reply({"answer": IMAGE_ANSWER, "delay": 0.2})
    click(env, "Describe images (2)")
    wait_until(lambda: "Describing images of the deck" in env.window.assistant.task_row.status.text())
    assert settled(env).endswith(": 2 described") and len(fake.calls()) == 2
    assert all(e.short == IMAGE_ANSWER["short"] for e in alt_images.load_store(ctx).values())


def test_the_first_cloud_task_of_a_project_asks_once(ctx, fake, monkeypatch):
    env = fake.env
    app_settings.save(ctx, {})                                                   # the project has not used the cloud yet
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: asked.append(args[2]) or QMessageBox.StandardButton.No)
    fake.reply({"answer": GERMAN})
    click(env, "Translate to German")
    card = env.window.assistant.tasks.card
    assert card.phase == card_model.STOPPED and card_model.state_text(card) == "Nothing was sent: using the cloud was not confirmed."
    assert fake.calls() == []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: asked.append(args[2]) or QMessageBox.StandardButton.Yes)
    assert run_task(env, "Translate to German").startswith("Applied automatically") and ai_profile.cloud_seen(ctx)
    assert len(asked) == 2 and "fake-1" in asked[0]


def test_unavailable_route_refuses_the_task_without_falling_back(fake, fake_routes):
    env = fake.env
    fake.route.problem_text = "Route unavailable."
    fake_routes.local.runner = FakeTaskRunner(env.window.project, GERMAN)
    env.window.assistant.header.refresh_content()
    assert "Translate to German" in buttons(env) and env.window.assistant.header.shown == []
    click(env, "Translate to German")
    card = env.window.assistant.tasks.card
    assert card.phase == card_model.SETUP and "Route unavailable." in card.note
    assert not fake.calls() and not fake_routes.local.runner.calls and not german_files(env)


class OfflineProvider:
    """The provider of a Local or API route, as far as a task uses it."""

    is_local = True
    model = label = "offline"

    def __init__(self):
        self.aborted = threading.Event()

    def abort(self):
        self.aborted.set()


def local_model(ctx, kind):
    ai_profile.set_mode(ctx, ai_profile.LOCAL)
    ai_profile.set_model_choice(ctx, "fake_local", kind, "fake-2")


def test_on_local_a_translation_runs_on_the_translation_model_and_holds_the_route_slot(ctx, fake, monkeypatch):
    env = fake.env
    local_model(ctx, ai_profile.TRANSLATION)
    provider, seen, held = OfflineProvider(), [], []

    def provider_for(_ctx, route):
        seen.append(route)
        return provider

    def translate_body(_ctx, given, body):
        held.append((env.window._route_tasks.get("fake_local") or (None,))[0])
        assert given is provider
        return GERMAN["body"], None

    monkeypatch.setattr(tasks_module.resolver, "provider_for", provider_for)
    monkeypatch.setattr(tasks_module.slide_add, "translate_body", translate_body)
    assert run_task(env, "Translate to German").startswith("Applied automatically")
    assert len(german_files(env)) == 1 and fake.calls() == []                    # no cloud runner
    assert [(r.route, r.model) for r in seen] == [("fake_local", "fake-2")] and held == ["translating a slide"]
    assert "fake_local" not in env.window._route_tasks and env.window.assistant.tasks._providers == []


def test_failed_refused_and_cancelled_provider_translations_create_nothing(ctx, fake, monkeypatch):
    env = fake.env
    local_model(ctx, ai_profile.TRANSLATION)
    provider = OfflineProvider()
    monkeypatch.setattr(tasks_module.resolver, "provider_for", lambda _ctx, _route: provider)
    broken = GERMAN["body"].replace("\\end{itemize}", "")
    for result, message in ((("", "Provider is not reachable."), "Provider is not reachable."),
                            ((broken, None), "The translation was refused")):
        monkeypatch.setattr(tasks_module.slide_add, "translate_body", lambda *a: result)
        assert run_task(env, "Translate to German").startswith(message) and german_files(env) == []
        assert "fake_local" not in env.window._route_tasks

    release = threading.Event()
    monkeypatch.setattr(tasks_module.slide_add, "translate_body", lambda *a: (release.wait(5), ("", "Aborted."))[1])
    click(env, "Translate to German")
    env.window.assistant.tasks.stop()
    assert provider.aborted.is_set()
    release.set()
    assert settled(env) == "Stopped. Nothing was changed." and german_files(env) == []


def test_on_local_describing_images_uses_the_vision_model_backend(ctx, fake, monkeypatch):
    env = fake.env
    local_model(ctx, ai_profile.IMAGE_DESCRIPTION)
    with_pictures(fake, a={}, b={})
    wait_until(lambda: "Describe images (2)" in buttons(env))
    provider = OfflineProvider()

    class Backend:
        label = "offline"

        def __init__(self):
            self.provider = provider

        def draft(self, _path, _context):
            return alt_draft.DraftResult(short="s", long="l", takeaway="t", model="offline")

    made = []
    monkeypatch.setattr(tasks_module.resolver, "draft_backend", lambda _ctx, route: made.append(route) or Backend())
    assert run_task(env, "Describe images (2)").endswith(": 2 described")
    assert [(r.route, r.model) for r in made] == [("fake_local", "fake-2")] and fake.calls() == []
    assert [e.drafted_by for e in alt_images.load_store(ctx).values()] == ["offline"] * 2
    assert "fake_local" not in env.window._route_tasks


def test_route_without_task_runner_refuses_unsupported_tasks(ctx, fake, fake_routes):
    env = fake.env
    ai_profile.set_mode(ctx, ai_profile.LOCAL)
    break_slide(env)
    click(env, "Fix LaTeX errors")
    card = env.window.assistant.tasks.card
    assert card.phase == card_model.SETUP and "not available on Local · Fake local" in card.note
    assert "no other route or model is used" in card_model.state_text(card)
    assert not env.window.assistant.tasks.busy
    assert not fake.calls() and not fake_routes.local.providers and slide_file(env).editor.text() == BROKEN
    assert "fake_local" not in env.window._route_tasks
