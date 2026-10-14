"""The tasks of the assistant card (ui/workspace/terminal/tasks.py, assistant.py and assistant_header.py), with the fake
`claude -p` of tests/fake_claude.py: which tasks the focus and the lint offer, a fix applied into the open buffer, a
translation that creates the partner only on success, the conflicts (typing, a changed source), Stop, the
route's model and effort and the project's German address, the image bubbles (describe, translate the descriptions), the deck bubbles
(counts, two processes at a time, fresh captures, conflicts, duplicate partners, rate and usage limits, Stop, the
summary). The project is a throwaway one, never example/."""
from __future__ import annotations

import json
import sys
import threading

import pytest
from slidemage.project import ProjectContext
from PySide6.QtWidgets import QMessageBox, QPlainTextEdit
from conftest import SLIDE_TEXT
from test_claude_code_gui import env as claude_env, pump, start_view, wait_until  # noqa: F401 -- a fixture
from test_claude_images import ANSWER as IMAGE_ANSWER, GERMAN as GERMAN_IMAGE, add_pictures

from slidemage import alt_draft, alt_images, app_settings, slide_ids, slide_language, slide_versioning
from slidemage.ai import ai_profile, claude_launch, claude_runner, credentials, resolver, translation_style
from slidemage.ai.agent_types import EDIT_AUTO
from slidemage.ui.kit.widgets import Button, ModalSheet
from slidemage.ui.workspace import task_card_model as card_model
from slidemage.ui.workspace.terminal import tasks as tasks_module

pytest.importorskip("PySide6.QtWebEngineWidgets")
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the stand-in for claude is a POSIX script")

SLIDE = "slides/abc-EN-Hello-current.tex"
LF = SLIDE_TEXT.replace("\r\n", "\n")
BROKEN = LF.replace("\t\\end{itemize}\n", "", 1)              # \begin{itemize} is not closed
FIX = {"edits": [{"before": "\t\t\\item Second point\n", "after": "\t\t\\item Second point\n\t\\end{itemize}\n"}]}
SENT = slide_versioning.strip_marker(slide_ids.body_of(LF))   # what a translation request carries
GERMAN = {"body": SENT.replace("Hello", "Hallo").replace("First point", "Erster Punkt")}
GERMAN_NAME = "-DE-"


class Fake:
    """What the fake `claude -p` is told and what it was asked."""

    def __init__(self, env, tmp_path, monkeypatch):
        self.env, self.monkeypatch, self.log = env, monkeypatch, tmp_path / "tasks.jsonl"
        self.renders, self.error = [], ""

    def rendered(self, *args, **kwargs):
        """The stand-in for the preview's render: it compiles unless `error` is set."""
        self.renders.append(args)
        if self.error:
            raise RuntimeError(self.error)
        return b"png"

    def reply(self, *replies):
        self.monkeypatch.setenv("FAKE_CLAUDE_REPLIES", json.dumps(replies))

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []


@pytest.fixture
def ctx(claude_env):  # noqa: F811
    return ProjectContext.at(claude_env.root)


@pytest.fixture
def fake(claude_env, tmp_path, monkeypatch):  # noqa: F811
    start_view(claude_env)                                                  # the route of these tasks: Cloud · Claude Code
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "tasks.jsonl"))   # not the terminal's log
    made = Fake(claude_env, tmp_path, monkeypatch)
    area = claude_env.window.assistant
    area.chat.session.set_mode(EDIT_AUTO)                                  # most of these tests are about the write
    monkeypatch.setattr(area.workspace, "render_preview", made.rendered)  # no LaTeX: Check preview compiles or fails at will
    return made


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


def german_files(env):
    return sorted((env.root / "slides").glob(f"*{GERMAN_NAME}*-current.tex"))


def break_slide(env):
    slide_file(env).editor.replace_all_text(BROKEN)
    wait_until(lambda: "Fix LaTeX errors" in buttons(env))


# -- which bubbles ----------------------------------------------------------------------------------------

def test_the_bubbles_follow_the_focus_and_the_lint(fake):
    env = fake.env
    wait_until(lambda: buttons(env) == ["Translate to German", "Better title"])
    break_slide(env)
    wait_until(lambda: buttons(env) == ["Translate to German", "Fix LaTeX errors", "Better title"])
    slide_file(env).editor.replace_all_text(LF)
    wait_until(lambda: buttons(env) == ["Translate to German", "Better title"])
    env.window.state.set_focused_slide("abd")
    wait_until(lambda: env.window.centre.path.name.startswith("abd") and buttons(env) == ["Translate to German", "Better title"])
    env.window.centre.open_file(env.root / "decks" / "test.tex")      # not a slide
    wait_until(lambda: buttons(env) == [])


def test_a_slide_with_a_partner_is_not_offered_a_translation(fake):
    env = fake.env
    (env.root / SLIDE).write_bytes((SLIDE_TEXT.replace("%%\r\n\r\n", "%%\r\n%% DE translation: abe-DE-Hallo\r\n%%\r\n\r\n", 1)).encode())
    (env.root / "slides" / "abe-DE-Hallo-current.tex").write_bytes(b"%% Translation of: abc-EN-Hello\r\n%%\r\n\r\nx\r\n")
    env.window.centre.source.file_for(env.path).reload()
    env.window.state.set_focused_slide("abd")
    wait_until(lambda: env.window.centre.path.name.startswith("abd"))
    pump(0.6)                                                  # the session has noticed (it polls every 0.4 s)
    env.window.state.set_focused_slide("abc")
    wait_until(lambda: env.window.centre.path == env.path and buttons(env) == ["Better title"])


def test_without_claude_the_header_offers_no_task_and_the_palette_says_why(claude_env, monkeypatch, tmp_path):  # noqa: F811
    env = claude_env
    ai_profile.mark_cloud_seen(env.window.project)
    env.window.state.set_ai_route(ai_profile.CLOUD, ai_profile.CLAUDE_CODE)
    monkeypatch.setattr(claude_launch, "find_claude", lambda: None)
    shown = []
    env.window.toast.show_message = shown.append
    area = env.window.assistant
    area.header.refresh_content()
    assert "Better title" in buttons(env) and area.header.shown == []
    click(env, "Better title")
    card = area.tasks.card
    assert card.phase == card_model.SETUP and card.note == resolver.NO_CLAUDE and not shown and not area.tasks.busy
    assert card_model.state_text(card) == resolver.NO_CLAUDE + " The slide is unchanged."


# -- fixing ---------------------------------------------------------------------------------------------------

def test_a_fix_goes_into_the_open_buffer_and_ctrl_z_takes_it_back(fake):
    env = fake.env
    break_slide(env)
    fake.reply({"answer": FIX})
    click(env, "Fix LaTeX errors")
    area = env.window.assistant
    assert area.tasks.busy and area.header.shown == [] and area._stack.currentWidget() is area.task_card
    assert settled(env).startswith("Applied automatically (Edit automatically is on). Changed 1 line in abc-EN-Hello-current.tex.")
    editor = slide_file(env).editor
    assert editor.text() == LF
    assert env.window.state.mode == "source"                         # the mode stays
    assert buttons(env) == ["Translate to German", "Better title"]
    editor.undo()
    assert editor.text() == BROKEN
    request = fake.calls()[0]["request"]
    assert "(environments)" in request and "<slide>" in request
    assert (env.root / SLIDE).read_bytes() == SLIDE_TEXT.encode()      # nothing was saved


def test_check_preview_renders_the_slide_in_the_view_and_language_being_edited(fake):
    env = fake.env
    env.window.state.set_mode("split")
    pump(0.1)
    break_slide(env)
    fake.reply({"answer": FIX})
    click(env, "Fix LaTeX errors")
    assert "The preview is current." in settled(env) and env.window.state.mode == "split"
    ((target, text, view, language, _timestamp, _cancel),) = fake.renders
    assert target.source_path == env.path and text == LF and (view, language) == ("instructor", "EN")
    assert env.window.assistant.tasks.card.where == "abc · Instructor · EN"


def test_a_slide_that_needs_no_change_says_so(fake):
    env = fake.env
    break_slide(env)
    fake.reply({"answer": {"edits": []}})
    click(env, "Fix LaTeX errors")
    assert settled(env) == "Nothing to change in abc. Nothing was written."
    assert slide_file(env).editor.text() == BROKEN


def test_typing_during_a_fix_is_a_conflict_and_nothing_is_overwritten(fake):
    env = fake.env
    break_slide(env)
    fake.reply({"answer": FIX, "delay": 0.4})
    click(env, "Fix LaTeX errors")
    editor = slide_file(env).editor
    typed = BROKEN + "% typed meanwhile\n"
    editor.replace_all_text(typed)
    assert settled(env) == "abc changed while this task ran. The proposal is kept but not applied."
    assert editor.text() == typed
    card = env.window.assistant.tasks.card
    assert card.phase == card_model.CONFLICT and "Second point" in card.after and fake.renders == []


def test_a_focus_change_during_a_task_does_not_change_its_target(fake):
    env = fake.env
    break_slide(env)
    fake.reply({"answer": FIX, "delay": 0.4})
    click(env, "Fix LaTeX errors")
    env.window.state.set_focused_slide("abd")
    wait_until(lambda: env.window.centre.path.name.startswith("abd"))
    assert "Changed 1 line in abc-EN-Hello-current.tex. The preview is current." in settled(env)
    assert slide_file(env).editor.text() == LF                       # abc, which was the target
    assert env.window.centre.source.file_for(env.window.centre.path).editor.text() == LF.replace("Hello", "Second")


def test_stop_cancels_and_the_late_result_is_dropped(fake, tmp_path):
    env = fake.env
    break_slide(env)
    fake.reply({"answer": FIX, "delay": 5, "marker": str(tmp_path / "late")})
    click(env, "Fix LaTeX errors")
    wait_until(lambda: fake.log.exists())
    next(b for b in env.window.assistant.task_card.findChildren(Button) if b.text() == "Stop").click()
    assert settled(env) == "Stopped. Nothing was changed."
    assert slide_file(env).editor.text() == BROKEN and not (tmp_path / "late").exists()


def test_a_failure_is_reported_as_it_is(fake):
    env = fake.env
    break_slide(env)
    fake.reply({"error": "Not logged in · Please run /login"})
    click(env, "Fix LaTeX errors")
    assert settled(env) == claude_runner.NOT_LOGGED_IN + " The slide is unchanged."
    assert env.window.assistant.tasks.card.phase == card_model.SETUP and env.window.assistant.tasks.card.can_sign_in
    assert slide_file(env).editor.text() == BROKEN


# -- translating --------------------------------------------------------------------------------------------

def test_a_translation_creates_the_partner_after_the_source_and_links_both(ctx, fake):
    env = fake.env
    fake.reply({"answer": GERMAN})
    click(env, "Translate to German")
    status = settled(env)
    (partner,) = german_files(env)
    new_id_slug = partner.name.removesuffix("-current.tex")
    assert status == (f"Applied automatically (Edit automatically is on). Created {new_id_slug}-current.tex. "
                      "It stays linked to the English slide. The preview is current.")
    text = partner.read_bytes().decode()
    assert text.startswith(f"%% Included in decks: test\r\n%%\r\n\r\n%% Translation of: abc-EN-Hello\r\n%%\r\n\r\n")
    assert "Hallo" in text and "Erster Punkt" in text and "\\setSlideVersion" not in text and "\r\n" in text
    deck = (env.root / "decks" / "test.tex").read_text()
    assert f"\\slide{{abc-EN-Hello}}\n\\slide{{{new_id_slug}}}\n\\section{{Main}}" in deck.replace("\r\n", "\n")
    source = slide_file(env).editor.text()                                # linked in the buffer, not saved
    assert f"%% DE translation: {new_id_slug}\n" in source and source != LF
    assert (env.root / SLIDE).read_bytes() == SLIDE_TEXT.encode()
    assert env.window.centre.path == env.path                             # not shown until View DE version
    next(b for b in env.window.assistant.task_card.findChildren(Button) if b.text() == "View DE version").click()
    assert env.window.centre.path == partner
    ((target, *_),) = fake.renders
    assert target.source_path == partner                                  # Check preview rendered the new slide
    link = slide_language.translation_link(ctx, "abc-EN-Hello")                # found although the source is unsaved
    assert link is not None and link.partner == new_id_slug and not any(b.label.startswith("Translate") for b in tasks_module._offers(ctx, 
        tasks_module._focus(env.window), link))
    env.window.centre.open_file(env.path)
    wait_until(lambda: buttons(env) == ["Better title"])
    (call,) = fake.calls()
    assert call["request"].startswith("Translate this slide from English to German.\n"
                                      'Address the audience with "Sie" (formal).\n<slide>\n')
    assert "\\setSlideVersion" not in call["request"] and "Included in decks" not in call["request"]


def test_a_translation_is_called_once_after_the_first_call_of_its_source_the_way_the_source_is(fake):
    env = fake.env
    deck = env.root / "decks" / "test.tex"
    deck.write_bytes(deck.read_bytes().replace(b"\\slide{abc-EN-Hello}\r\n", b"\\conditionalslide[instructor]{abc-EN-Hello}\r\n")
                     .replace(b"\\end{document}", b"\\slide{abc-EN-Hello}\r\n\\end{document}"))
    env.window.reload_decks()
    env.window.state.set_focused_slide("abc")
    wait_until(lambda: "Translate to German" in buttons(env))
    fake.reply({"answer": GERMAN})
    click(env, "Translate to German")
    settled(env)
    (partner,) = german_files(env)
    new_id_slug = partner.name.removesuffix("-current.tex")
    text = deck.read_text().replace("\r\n", "\n")
    assert f"\\conditionalslide[instructor]{{abc-EN-Hello}}\n\\conditionalslide[instructor]{{{new_id_slug}}}\n\\section{{Main}}" in text
    assert text.count(new_id_slug) == 1


def test_the_terminal_translates_through_the_bubble(fake):
    from mcp_client import Client
    from test_claude_code_gui import on_thread

    env = fake.env
    fake.reply({"answer": GERMAN})
    client = Client(env.view.session._server)
    answer = on_thread(lambda: client.text("translate_slide", path=SLIDE))
    assert answer == "SlideMage is translating it (Translate to German); the task card in the assistant shows the proposed slide."
    settled(env)
    (partner,) = german_files(env)
    assert "Hallo" in partner.read_text()
    assert "nothing to translate" in on_thread(lambda: client.text("translate_slide", path=SLIDE))


def test_a_failed_translation_creates_nothing(fake):
    env = fake.env
    deck = (env.root / "decks" / "test.tex").read_bytes()
    fake.reply({"error": "overloaded"}, {"error": "overloaded"})
    click(env, "Translate to German")
    assert settled(env) == "overloaded. Nothing was changed."
    assert german_files(env) == [] and (env.root / "decks" / "test.tex").read_bytes() == deck
    assert slide_file(env).editor.text() == LF


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
    click(env, "Translate to German")
    assert "It is not complete: not added to the deck." in settled(env)
    assert len(german_files(env)) == 1 and deck.read_text().count("\\slide") == 1


def test_the_german_address_and_the_glossary_reach_the_request(ctx, fake):
    env = fake.env
    translation_style.set_de_address(ctx, "du")
    (env.root / ".slidemage" / "glossary.md").write_text("slide = Folie\n", encoding="utf-8")
    fake.reply({"answer": GERMAN})
    click(env, "Translate to German")
    settled(env)
    request = fake.calls()[0]["request"]
    assert 'Address the audience with "du" (informal).' in request and "slide = Folie" in request
    assert json.loads((env.root / ".slidemage" / "project.json").read_text())["de_address"] == "du"


def test_settings_set_the_german_address(ctx, fake):
    from slidemage.ui.dialogs.settings import AiTab

    tab = AiTab(ctx)
    assert tab.address.current() == "Sie"
    tab.address.changed.emit("du")
    assert translation_style.de_address(ctx) == "du"


# -- the model and effort of a task --------------------------------------------------------------------------

def test_the_model_and_effort_of_a_task_are_those_the_route_has_for_its_kind(ctx, fake):
    env = fake.env
    ai_profile.set_model_choice(ctx, ai_profile.CLAUDE_CODE, ai_profile.FIXES, "haiku:low")
    ai_profile.set_model_choice(ctx, ai_profile.CLAUDE_CODE, ai_profile.TRANSLATION, "opus:high")
    break_slide(env)
    fake.reply({"answer": FIX}, {"answer": GERMAN})
    click(env, "Fix LaTeX errors")
    settled(env)
    click(env, "Translate to German")
    settled(env)
    assert [call["argv"][:5] for call in fake.calls()] == [
        ["-p", "--model", "haiku", "--effort", "low"], ["-p", "--model", "opus", "--effort", "high"]]


def test_the_route_is_captured_when_a_task_starts(ctx, fake):
    env = fake.env
    fake.reply({"answer": GERMAN, "delay": 0.3})
    click(env, "Translate to German")
    ai_profile.set_mode(ctx, ai_profile.LOCAL)                     # the switch moves: the running task is not moved with it
    assert settled(env).startswith("Applied automatically") and "Created" in settled(env)
    assert len(fake.calls()) == 1 and len(german_files(env)) == 1


def test_two_clicks_start_one_task(fake):
    env = fake.env
    fake.reply({"answer": GERMAN, "delay": 0.3})
    click(env, "Translate to German")
    env.window.assistant.tasks.start(tasks_module.claude_tasks.TRANSLATE)
    settled(env)
    assert len(fake.calls()) == 1


# -- the other bubbles ------------------------------------------------------------------------------------

PROSE = LF.replace("First point", "This first point explains the main idea of the slide with enough ordinary words")
TEXT_BUBBLES = ["Translate to German", "Proofread", "Make more concise", "Better title", "Add speaker notes"]


def show_text(env, text):
    slide_file(env).editor.replace_all_text(text)
    wait_until(lambda: slide_file(env).editor.text() == text)


def test_the_text_bubbles_need_running_text_a_title_and_no_note_yet(fake):
    env = fake.env
    show_text(env, PROSE)
    wait_until(lambda: buttons(env) == TEXT_BUBBLES)
    show_text(env, PROSE.replace("\\end{standardframe}", "\t\\note{Say it.}\n\\end{standardframe}"))
    wait_until(lambda: buttons(env) == TEXT_BUBBLES[:-1])
    show_text(env, "Plain words without any frame, but enough of them to count as running text here.\n")
    wait_until(lambda: buttons(env) == ["Translate to German", "Proofread", "Make more concise", "Add speaker notes"])
    show_text(env, LF)
    wait_until(lambda: buttons(env) == ["Translate to German", "Better title"])


def test_a_slide_without_a_language_is_not_proofread(ctx, fake):
    env = fake.env
    show_text(env, PROSE)
    wait_until(lambda: "Proofread" in buttons(env))
    assert tasks_module._offers(ctx, tasks_module._focus(env.window), None)[1].label == "Proofread"
    legacy = tasks_module._Focus(env.root / "slides" / "xyz-legacy-current.tex", "xyz-legacy", PROSE)
    assert "Proofread" not in [b.label for b in tasks_module._offers(ctx, legacy, None)]


def test_proofreading_applies_its_edits_into_the_buffer(fake):
    env = fake.env
    show_text(env, PROSE)
    wait_until(lambda: "Proofread" in buttons(env))
    fake.reply({"answer": {"edits": [{"before": "enough ordinary words", "after": "enough ordinary words,"}]}})
    click(env, "Proofread")
    assert "Changed 1 line" in settled(env)
    editor = slide_file(env).editor
    assert "ordinary words," in editor.text()
    editor.undo()
    assert editor.text() == PROSE
    assert "Proofread this English slide" in fake.calls()[0]["request"]


def test_proofreading_text_without_mistakes_says_so(fake):
    env = fake.env
    show_text(env, PROSE)
    wait_until(lambda: "Proofread" in buttons(env))
    fake.reply({"answer": {"edits": []}})
    click(env, "Proofread")
    assert settled(env) == "Nothing to change in abc. Nothing was written." and slide_file(env).editor.text() == PROSE


def test_a_shortened_slide_is_applied_and_one_that_loses_structure_is_refused(fake):
    env = fake.env
    show_text(env, PROSE)
    wait_until(lambda: "Make more concise" in buttons(env))
    lost = PROSE.replace("\t\\end{itemize}\n", "")
    fake.reply({"answer": {"body": lost}})
    click(env, "Make more concise")
    assert settled(env).startswith("Claude's answer was refused: the new text must keep every environment")
    assert slide_file(env).editor.text() == PROSE and len(fake.calls()) == 2          # one repair attempt
    shorter = PROSE.replace(" with enough ordinary words", "")
    fake.reply({"answer": {"body": shorter}})
    click(env, "Make more concise")
    assert "Changed 1 line" in settled(env) and slide_file(env).editor.text() == shorter


def test_a_better_title_replaces_only_the_frame_title(fake):
    env = fake.env
    fake.reply({"answer": {"title": "A better title"}})
    click(env, "Better title")
    assert "Changed 1 line" in settled(env)
    assert slide_file(env).editor.text() == LF.replace("{Hello}", "{A better title}")
    assert "Current title: Hello" in fake.calls()[0]["request"]


def test_a_speaker_note_goes_before_the_frames_end_and_its_bubble_goes(fake):
    env = fake.env
    show_text(env, PROSE)
    wait_until(lambda: "Add speaker notes" in buttons(env))
    fake.reply({"answer": {"note": "Open with the main idea."}})
    click(env, "Add speaker notes")
    assert "Changed 1 line" in settled(env)
    assert slide_file(env).editor.text().endswith("\t\\note{Open with the main idea.}\n\\end{standardframe}\n")
    assert "Add speaker notes" not in buttons(env)


def test_typing_during_a_title_task_is_a_conflict(fake):
    env = fake.env
    fake.reply({"answer": {"title": "A better title"}, "delay": 0.4})
    click(env, "Better title")
    typed = LF + "% typed\n"
    slide_file(env).editor.replace_all_text(typed)
    assert settled(env) == "abc changed while this task ran. The proposal is kept but not applied."
    assert slide_file(env).editor.text() == typed and env.window.assistant.tasks.card.phase == card_model.CONFLICT


def test_the_card_names_what_is_going_on(fake, tmp_path):
    env = fake.env
    fake.reply({"answer": {"title": "T"}, "delay": 1.5})
    click(env, "Better title")
    card = env.window.assistant.tasks.card
    assert card.phase == card_model.GENERATE and card_model.state_text(card).startswith("Looking for a better title for abc.")
    next(b for b in env.window.assistant.task_card.findChildren(Button) if b.text() == "Stop").click()
    settled(env)


# -- updating a translation ----------------------------------------------------------------------------------

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
    fake.partner, fake.german = path, german
    env.window.assistant.header.schedule()
    return fake


def open_partner(env, path):
    env.window.centre.open_file(path)
    wait_until(lambda: env.window.centre.path == path and "Update German translation" in buttons(env))


def test_an_outdated_translation_is_offered_an_update_on_both_slides(outdated):
    env = outdated.env
    wait_until(lambda: "Update German translation" in buttons(env) and "Translate to German" not in buttons(env))
    open_partner(env, outdated.partner)


def test_an_update_goes_into_the_open_translation_and_keeps_its_header(outdated):
    env = outdated.env
    open_partner(env, outdated.partner)
    outdated.reply({"answer": UPDATE_ANSWER})
    click(env, "Update German translation")
    assert f"Updated {GERMAN_ID}-current.tex. It stays linked to the English slide." in settled(env)
    editor = env.window.centre.source.file_for(outdated.partner).editor
    assert editor.text().startswith(GERMAN_HEADER.replace("\r\n", "\n")) and "Erster Punkt!" in editor.text()
    assert "\\setSlideVersion{1-0-0}" in editor.text()
    editor.undo()
    assert "Erster Punkt!" not in editor.text()
    request = outdated.calls()[0]["request"]
    assert request.startswith("Update this German translation to match the current English source.\n"
                              'Address the audience with "Sie" (formal).\n<source>\n')
    source, translation = request.split("<source>\n")[1].split("</source>\n<slide>\n")
    assert "First point" in source and "\\setSlideVersion" not in source and "Included in decks" not in source
    assert translation.startswith("% A note") and "Erster Punkt" in translation and "Translation of" not in translation


def test_an_update_of_a_closed_translation_is_saved_to_its_file(outdated):
    env = outdated.env
    wait_until(lambda: "Update German translation" in buttons(env))
    outdated.reply({"answer": UPDATE_ANSWER})
    click(env, "Update German translation")
    assert f"Updated {GERMAN_ID}-current.tex. It stays linked to the English slide." in settled(env)
    text = outdated.partner.read_bytes().decode()                       # its CRLF line ends are kept
    assert text.startswith(GERMAN_HEADER) and "Erster Punkt!" in text and "\\setSlideVersion{1-0-0}" in text
    assert env.window.centre.path == env.path


def test_a_translation_that_changed_meanwhile_is_not_overwritten(outdated):
    env = outdated.env
    open_partner(env, outdated.partner)
    outdated.reply({"answer": UPDATE_ANSWER, "delay": 0.4})
    click(env, "Update German translation")
    editor = env.window.centre.source.file_for(outdated.partner).editor
    typed = editor.text() + "% getippt\n"
    editor.replace_all_text(typed)
    assert settled(env) == "abe changed while this task ran. The proposal is kept but not applied."
    assert editor.text() == typed and "Erster Punkt!" in env.window.assistant.tasks.card.after


def test_a_translation_that_changed_on_disk_meanwhile_is_not_overwritten(outdated):
    env = outdated.env
    wait_until(lambda: "Update German translation" in buttons(env))
    outdated.reply({"answer": UPDATE_ANSWER, "delay": 0.4})
    click(env, "Update German translation")
    changed = outdated.partner.read_bytes() + b"% getippt\r\n"
    outdated.partner.write_bytes(changed)
    assert settled(env) and env.window.assistant.tasks.card.phase == card_model.CONFLICT and outdated.partner.read_bytes() == changed


# -- images ---------------------------------------------------------------------------------------------------

def with_pictures(fake, **entries):
    """Slide abc with these images (name -> fields of the store entry), in its file, the store and the buffer."""
    slide = add_pictures(fake.monkeypatch, fake.env.root, **entries)
    slide_file(fake.env).editor.replace_all_text(slide.read_bytes().decode().replace("\r\n", "\n"))
    return lambda: alt_images.load_store(ProjectContext.at(fake.env.root))


def test_the_image_bubbles_count_what_is_still_to_do(ctx, fake):
    env = fake.env
    store = with_pictures(fake, a={}, b={}, c=dict(role=alt_images.ROLE_DECORATIVE), d=dict(short="s", long="l"))
    wait_until(lambda: "Describe images (2)" in buttons(env))
    assert "Translate image descriptions (1)" in buttons(env)
    alt_images.update_store(ctx, lambda e: setattr(e["media/a.png"], "long", "now described") or True)
    env.window.assistant.header.schedule()
    assert "Describe images (1)" in buttons(env) and "Translate image descriptions (2)" in buttons(env)
    slide_file(env).editor.replace_all_text(LF)
    wait_until(lambda: buttons(env) == ["Translate to German", "Better title"])
    assert len(store()) == 4


def test_describing_images_stores_drafts_and_shows_them_in_the_panel(ctx, fake):
    env = fake.env
    with_pictures(fake, a={}, b={})
    env.window.side_panels.set_panel("images")
    wait_until(lambda: "Describe images (2)" in buttons(env))
    fake.reply({"answer": IMAGE_ANSWER, "delay": 0.6})
    click(env, "Describe images (2)")
    wait_until(lambda: "Describing images of abc … 1/2" in env.window.assistant.task_row.status.text())
    assert settled(env).startswith("Done in ") and settled(env).endswith(": 2 described")
    store = alt_images.load_store(ctx)
    assert [(e.short, e.drafted_by) for e in store.values()] == [(IMAGE_ANSWER["short"], "Claude haiku")] * 2
    assert all(e.status != alt_images.STATUS_REVIEWED for e in store.values())
    forms = env.window.side_panels.panels["images"]._forms
    assert [form.short_edit.toPlainText() for form in forms] == [IMAGE_ANSWER["short"]] * 2
    assert [call["images"][0]["media_type"] for call in fake.calls()] == ["image/png"] * 2
    assert buttons(env)[-1] == "Translate image descriptions (2)"


def test_stop_ends_the_running_image_process_and_the_rest(ctx, fake, tmp_path):
    env = fake.env
    with_pictures(fake, a={}, b={})
    wait_until(lambda: "Describe images (2)" in buttons(env))
    fake.reply({"answer": IMAGE_ANSWER, "delay": 5, "marker": str(tmp_path / "late")})
    click(env, "Describe images (2)")
    wait_until(lambda: fake.log.exists())
    env.window.assistant.task_row.stop_button.click()
    assert settled(env).startswith("Stopped after ") and settled(env).endswith(": 0 described")
    assert len(fake.calls()) == 1 and not (tmp_path / "late").exists()
    assert not any(e.short for e in alt_images.load_store(ctx).values())


def test_a_failed_image_is_counted_and_the_others_are_kept(ctx, fake):
    env = fake.env
    with_pictures(fake, a={}, b={})
    wait_until(lambda: "Describe images (2)" in buttons(env))
    fake.reply({"answer": IMAGE_ANSWER}, {"error": "overloaded"})
    click(env, "Describe images (2)")
    assert settled(env).endswith(": 1 described, 1 failed (media/b.png: overloaded)")
    assert [e.short for e in alt_images.load_store(ctx).values()] == [IMAGE_ANSWER["short"], ""]


def test_translating_the_descriptions_stores_unreviewed_german_text(ctx, fake):
    env = fake.env
    with_pictures(fake, a=dict(short="A bar chart.", long="Two bars."))
    wait_until(lambda: "Translate image descriptions (1)" in buttons(env))
    assert not any(label.startswith("Describe") for label in buttons(env))
    fake.reply({"answer": GERMAN_IMAGE})
    click(env, "Translate image descriptions (1)")
    assert settled(env).endswith(": 1 translated")
    entry = alt_images.load_store(ctx)["media/a.png"]
    assert (entry.short_de, entry.long_de) == (GERMAN_IMAGE["short_de"], GERMAN_IMAGE["long_de"])
    assert not any(label.startswith("Translate image") for label in buttons(env))


# -- deck batches -------------------------------------------------------------------------------------------

def add_slide(env, word):
    """A third slide, {word} as its frame title, called by the deck after the others."""
    (env.root / "slides" / f"abe-EN-{word}-current.tex").write_bytes(SLIDE_TEXT.replace("Hello", word).encode())
    deck = env.root / "decks" / "test.tex"
    deck.write_bytes(deck.read_bytes().replace(b"\\end{document}", f"\\slide{{abe-EN-{word}}}\r\n\\end{{document}}".encode()))
    env.window.reload_decks()


def deck_scope(env, label="Summarise this deck"):
    env.window.assistant.scope._buttons["deck"].click()
    wait_until(lambda: label in buttons(env))


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


def test_a_deck_without_work_offers_the_summary_and_a_shared_image_counts_once(fake):
    env = fake.env
    with_pictures(fake, a={}, b={})
    abd = env.root / "slides" / "abd-EN-Second-current.tex"
    abd.write_bytes((env.root / SLIDE).read_bytes().replace(b"Hello", b"Second"))    # the same two images
    deck_scope(env, "Describe images (2)")
    assert buttons(env)[-2:] == ["Describe images (2)", "Summarise this deck"]


def test_two_processes_run_at_once_and_each_result_is_applied_on_the_gui_thread_in_turn(fake, monkeypatch):
    env = fake.env
    add_slide(env, "Third")
    applied = []
    real = tasks_module.TaskRunner._apply
    monkeypatch.setattr(tasks_module.TaskRunner, "_apply", lambda self, capture, outcome: applied.append(
        (capture.id_slug, threading.current_thread() is threading.main_thread())) or real(self, capture, outcome))
    fake.reply(*({"when": "{" + word + "}", "answer": german(word), "delay": 1.0} for word in ("Hello", "Second", "Third")))
    deck_scope(env)
    click(env, "Translate missing slides (3)")
    wait_until(lambda: "Translating the deck … " in env.window.assistant.task_row.status.text())
    assert settled(env).startswith("Done in ") and "3 applied" in env.window.assistant.task_row.status.text()
    first, second, third = sorted(call["time"] for call in fake.calls())
    assert second - first < 0.8 and third - first >= 0.9                 # two together; the third waits for one
    assert sorted(slug for slug, _ in applied) == ["abc-EN-Hello", "abd-EN-Second", "abe-EN-Third"]
    assert all(on_gui for _, on_gui in applied)
    created = german_files(env)
    assert len(created) == 3 and len({path.name[:3] for path in created}) == 3          # three distinct ids
    deck = (env.root / "decks" / "test.tex").read_text().replace("\r\n", "\n")
    assert deck.count("\\slide{") == 6 and all(f"\\slide{{{id_slug}}}\n" in deck for id_slug in (
        "abc-EN-Hello", "abd-EN-Second", "abe-EN-Third"))
    assert len(lines(env)) == 3 and env.window.assistant.task_row.result_button.isVisibleTo(env.window.assistant)
    assert env.window.centre.path == env.path                                # no partner was opened


def test_a_slide_edited_before_its_turn_is_captured_as_it_is_then(fake):
    env = fake.env
    add_slide(env, "Third")
    fake.reply(*({"when": "{" + word + "}", "answer": german(word), "delay": 0.8} for word in ("Hello", "Second", "Third")))
    deck_scope(env)
    click(env, "Translate missing slides (3)")
    wait_until(lambda: len(fake.calls()) == 2)
    third = env.root / "slides" / "abe-EN-Third-current.tex"
    third.write_bytes(third.read_bytes().replace(b"First point", b"Freshly typed point"))
    assert settled(env).startswith("Done in ")
    request = next(call["request"] for call in fake.calls() if "{Third}" in call["request"])
    assert "Freshly typed point" in request and len(german_files(env)) == 3


def test_a_slide_edited_during_its_run_is_a_conflict_for_that_slide_only(fake):
    env = fake.env
    fake.reply(*({"when": "{" + word + "}", "answer": german(word), "delay": 0.8} for word in ("Hello", "Second")))
    deck_scope(env)
    click(env, "Translate missing slides (2)")
    wait_until(lambda: len(fake.calls()) == 2)
    slide_file(env).editor.replace_all_text(LF + "% typed meanwhile\n")
    assert settled(env).startswith("Done in ") and "1 applied, 1 failed" in env.window.assistant.task_row.status.text()
    (partner,) = german_files(env)
    assert "-DE-Second-" in partner.name
    assert any(line == f"abc-EN-Hello: {tasks_module.CONFLICT}" for line in lines(env))
    assert (env.root / "decks" / "test.tex").read_text().count("\\slide{") == 3


def test_a_partner_made_meanwhile_is_not_made_again(fake):
    env = fake.env
    fake.reply(*({"when": "{" + word + "}", "answer": german(word), "delay": 0.8} for word in ("Hello", "Second")))
    deck_scope(env)
    click(env, "Translate missing slides (2)")
    wait_until(lambda: len(fake.calls()) == 2)
    (env.root / "slides" / "abf-DE-Zweite-current.tex").write_bytes(
        b"%% Translation of: abd-EN-Second\r\n%%\r\n\r\nHand made\r\n")                  # by the user
    assert settled(env).startswith("Done in ") and "1 applied, 1 failed" in env.window.assistant.task_row.status.text()
    names = [path.name for path in german_files(env)]
    assert len(names) == 2 and "abf-DE-Zweite-current.tex" in names
    assert not any("Zweite" in line or "Second" in line for line in lines(env) if "created" in line)


def test_a_slide_that_got_its_partner_before_its_turn_is_skipped(fake):
    env = fake.env
    add_slide(env, "Third")
    fake.reply(*({"when": "{" + word + "}", "answer": german(word), "delay": 0.6} for word in ("Hello", "Second", "Third")))
    deck_scope(env)
    click(env, "Translate missing slides (3)")
    wait_until(lambda: len(fake.calls()) == 2)
    (env.root / "slides" / "abf-DE-Dritte-current.tex").write_bytes(
        b"%% Translation of: abe-EN-Third\r\n%%\r\n\r\nHand made\r\n")
    assert settled(env).startswith("Done in ") and len(fake.calls()) == 2
    assert "abe-EN-Third: no longer fits" in lines(env) and len(german_files(env)) == 3


def test_a_rate_limit_drops_to_one_worker_and_gives_the_slide_a_second_try(fake):
    env = fake.env
    fake.reply({"when": "{Hello}", "error": "API Error: 429 rate limit exceeded"},
               {"when": "{Second}", "answer": german("Second"), "delay": 1.5}, {"answer": german("Hello")})
    deck_scope(env)
    click(env, "Translate missing slides (2)")
    wait_until(lambda: tasks_module.SLOWED in env.window.assistant.task_row.status.text())
    assert settled(env).startswith("Done in ") and "2 applied" in env.window.assistant.task_row.status.text()
    calls = fake.calls()
    assert len(calls) == 3 and len(german_files(env)) == 2
    assert calls[2]["time"] - calls[1]["time"] >= 1.4 and "{Hello}" in calls[2]["request"]    # alone, after the other


def test_a_second_rate_limit_fails_that_slide_only(fake):
    env = fake.env
    fake.reply({"when": "{Second}", "answer": german("Second")}, {"when": "{Hello}", "error": "overloaded"},
               {"error": "overloaded"})
    deck_scope(env)
    click(env, "Translate missing slides (2)")
    assert settled(env).startswith("Done in ") and "1 applied, 1 failed" in env.window.assistant.task_row.status.text()
    assert "abc-EN-Hello: overloaded" in lines(env) and len(fake.calls()) == 3


def test_a_usage_limit_stops_the_batch(fake, tmp_path):
    env = fake.env
    add_slide(env, "Third")
    fake.reply({"when": "{Hello}", "error": "Claude AI usage limit reached", "delay": 0.7},
               {"when": "{Second}", "answer": german("Second"), "delay": 3, "marker": str(tmp_path / "late")})
    deck_scope(env)
    click(env, "Translate missing slides (3)")
    assert settled(env).startswith("Stopped: Claude AI usage limit reached")
    assert len(fake.calls()) == 2 and not (tmp_path / "late").exists() and german_files(env) == []


def test_stop_ends_both_processes_and_the_queue_but_keeps_what_was_applied(fake, tmp_path):
    env = fake.env
    add_slide(env, "Third")
    fake.reply({"when": "{Hello}", "answer": german("Hello")},
               {"when": "{Second}", "answer": german("Second"), "delay": 5, "marker": str(tmp_path / "late")},
               {"answer": german("Third"), "delay": 5})
    deck_scope(env)
    click(env, "Translate missing slides (3)")
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
    click(env, "Summarise this deck")
    assert settled(env).startswith("Done in ")
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
    fake.reply({"answer": IMAGE_ANSWER, "delay": 0.2})
    click(env, "Describe images (2)")
    wait_until(lambda: "Describing images of the deck" in env.window.assistant.task_row.status.text())
    assert settled(env).endswith(": 2 described") and len(fake.calls()) == 2
    assert all(e.short == IMAGE_ANSWER["short"] for e in alt_images.load_store(ctx).values())


# -- the other routes -------------------------------------------------------------------------------------------

class OfflineProvider:
    """The provider of a Local or API route, as far as a task uses it."""

    def __init__(self, is_local=True):
        self.is_local, self.model, self.label, self.aborted = is_local, "offline", "offline", threading.Event()

    def abort(self):
        self.aborted.set()


def on_route(fake, mode, conn=ai_profile.CLAUDE_CODE):
    ai_profile.set_cloud_conn(fake.env.window.project, conn)
    ai_profile.set_mode(fake.env.window.project, mode)


def test_on_local_a_task_with_no_ollama_path_says_so_and_nothing_runs(ctx, fake):
    env = fake.env
    on_route(fake, ai_profile.LOCAL)
    break_slide(env)
    for label in ("Fix LaTeX errors", "Better title"):
        click(env, label)
        card = env.window.assistant.tasks.card
        assert card.phase == card_model.SETUP and "is not available on Local · Ollama" in card.note
        assert "no other route or model is used" in card_model.state_text(card)
        assert not env.window.assistant.tasks.busy
    assert fake.calls() == [] and slide_file(env).editor.text() == BROKEN
    assert env.window._ollama_task_label is None                                 # the slot was never taken


def test_on_local_a_translation_runs_on_the_translation_model_and_holds_the_ollama_slot(ctx, fake, monkeypatch):
    env = fake.env
    on_route(fake, ai_profile.LOCAL)
    ai_profile.set_model_choice(ctx, ai_profile.LOCAL, ai_profile.TRANSLATION, "translator")
    provider, seen, held = OfflineProvider(), [], []

    def provider_for(_ctx, route):
        seen.append(route)
        return provider

    def translate_body(_ctx, given, body):
        held.append(env.window._ollama_task_label)
        assert given is provider
        return GERMAN["body"], None

    monkeypatch.setattr(tasks_module.resolver, "provider_for", provider_for)
    monkeypatch.setattr(tasks_module.slide_add, "translate_body", translate_body)
    click(env, "Translate to German")
    assert settled(env).startswith("Applied automatically")
    assert len(german_files(env)) == 1 and fake.calls() == []                    # no claude process
    assert [(r.route, r.model) for r in seen] == [("local", "translator")] and held == ["translating a slide"]
    assert env.window._ollama_task_label is None and env.window.assistant.tasks._providers == []


def test_a_translation_on_a_provider_that_fails_or_is_stopped_creates_nothing(ctx, fake, monkeypatch):
    env = fake.env
    on_route(fake, ai_profile.LOCAL)
    ai_profile.set_model_choice(ctx, ai_profile.LOCAL, ai_profile.TRANSLATION, "translator")
    provider = OfflineProvider()
    monkeypatch.setattr(tasks_module.resolver, "provider_for", lambda _ctx, _route: provider)
    monkeypatch.setattr(tasks_module.slide_add, "translate_body", lambda *a: ("", "Ollama is not reachable."))
    click(env, "Translate to German")
    assert settled(env) == "Ollama is not reachable. Nothing was changed." and german_files(env) == []
    assert env.window._ollama_task_label is None

    release = threading.Event()
    monkeypatch.setattr(tasks_module.slide_add, "translate_body", lambda *a: (release.wait(5), ("", "Aborted."))[1])
    click(env, "Translate to German")
    env.window.assistant.tasks.stop()
    assert provider.aborted.is_set()
    release.set()
    assert settled(env) == "Stopped. Nothing was changed." and german_files(env) == []


def test_a_provider_translation_that_breaks_the_slide_is_refused_like_a_claude_answer(ctx, fake, monkeypatch):
    env = fake.env
    on_route(fake, ai_profile.LOCAL)
    ai_profile.set_model_choice(ctx, ai_profile.LOCAL, ai_profile.TRANSLATION, "translator")
    monkeypatch.setattr(tasks_module.resolver, "provider_for", lambda _ctx, _route: OfflineProvider())
    broken = GERMAN["body"].replace("\\end{itemize}", "")
    monkeypatch.setattr(tasks_module.slide_add, "translate_body", lambda *a: (broken, None))
    click(env, "Translate to German")
    assert settled(env).startswith("The translation was refused") and german_files(env) == []


def test_on_local_describing_images_uses_the_vision_model_backend(ctx, fake, monkeypatch):
    env = fake.env
    on_route(fake, ai_profile.LOCAL)
    ai_profile.set_model_choice(ctx, ai_profile.LOCAL, ai_profile.IMAGE_DESCRIPTION, "vision")
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
    click(env, "Describe images (2)")
    assert settled(env).endswith(": 2 described")
    assert [(r.route, r.model) for r in made] == [("local", "vision")] and fake.calls() == []
    assert [e.drafted_by for e in alt_images.load_store(ctx).values()] == ["offline"] * 2
    assert env.window._ollama_task_label is None


def test_a_route_that_is_not_ready_starts_no_task_and_no_other_route_is_used(ctx, fake, monkeypatch):
    env = fake.env
    on_route(fake, ai_profile.LOCAL)
    click(env, "Translate to German")                                            # no Ollama model is chosen
    assert "Choose an Ollama model for translation" in env.window.assistant.tasks.card.note and fake.calls() == []
    credentials.set_api_key(ctx, "")
    on_route(fake, ai_profile.CLOUD, ai_profile.API)                             # no API key: Claude Code does not stand in
    click(env, "Translate to German")
    assert "No Anthropic API key" in env.window.assistant.tasks.card.note and fake.calls() == []
    assert german_files(env) == [] and not env.window.assistant.tasks.busy


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
    click(env, "Translate to German")
    assert settled(env).startswith("Applied automatically") and ai_profile.cloud_seen(ctx)
    assert len(asked) == 2 and "Claude Code" in asked[0]


def test_the_terminal_is_told_why_translate_slide_cannot_run_on_the_route(ctx, fake):
    from mcp_client import Client
    from test_claude_code_gui import on_thread

    env = fake.env
    credentials.set_api_key(ctx, "")
    on_route(fake, ai_profile.CLOUD, ai_profile.API)
    client = Client(env.view.session._server)
    answer = on_thread(lambda: client.text("translate_slide", path=SLIDE))
    assert "No Anthropic API key" in answer and fake.calls() == [] and not env.window.assistant.tasks.busy
