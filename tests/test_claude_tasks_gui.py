"""The bubbles of the Claude Code tab (ui/workspace/terminal/tasks.py and view.py), with the fake `claude -p` of
tests/fake_claude.py: which bubbles the focus and the lint offer, a fix applied into the open buffer, a
translation that creates the partner only on success, the conflicts (typing, a changed source), Stop, the
picker and the project's German address. The project is a throwaway one, never example/."""
from __future__ import annotations

import json
import sys

import pytest
from conftest import SLIDE_TEXT
from test_claude_code_gui import env as claude_env, pump, start_view, wait_until  # noqa: F401 -- a fixture

from slidemage import slide_ids, slide_language, slide_versioning
from slidemage.ai import claude_launch, claude_runner, translation_style
from slidemage.ui import layout_settings
from slidemage.ui.kit.widgets import PopoverMenu
from slidemage.ui.workspace import render_check
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

    def reply(self, *replies):
        self.monkeypatch.setenv("FAKE_CLAUDE_REPLIES", json.dumps(replies))

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]


@pytest.fixture
def fake(claude_env, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(translation_style, "PROJECT_ROOT", claude_env.root)
    start_view(claude_env)
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "tasks.jsonl"))   # not the terminal's log
    return Fake(claude_env, tmp_path, monkeypatch)


def slide_file(env):
    return env.window.centre.source.file_for(env.path)


def bubble_buttons(env):
    row = env.view._bubble_row
    return [row.itemAt(i).widget() for i in range(len(env.view._bubbles))]


def buttons(env):
    return [bubble.label for bubble in env.view._bubbles]


def click(env, label):
    next(b for b in bubble_buttons(env) if b.text() == label).click()


def settled(env):
    wait_until(lambda: not env.view.tasks.busy)
    pump(0.05)
    return env.view.task_status.text()


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


def test_without_claude_there_are_no_bubbles(claude_env, monkeypatch):  # noqa: F811
    env = claude_env
    monkeypatch.setattr(claude_launch, "find_claude", lambda: None)
    env.window.assistant.show_view(1)
    pump(0.2)
    assert env.view.tasks is None and env.view._bubbles == []


# -- fixing ---------------------------------------------------------------------------------------------------

def test_a_fix_goes_into_the_open_buffer_and_ctrl_z_takes_it_back(fake, monkeypatch):
    env = fake.env
    rendered = []
    monkeypatch.setattr(env.window.centre.preview, "render_buffer", lambda: rendered.append(True))
    monkeypatch.setattr(render_check, "confirm_render", lambda *a, **k: pytest.fail("a dialog opened"))
    break_slide(env)
    fake.reply({"answer": FIX})
    click(env, "Fix LaTeX errors")
    assert env.view.tasks.busy and env.view._bubbles == [] and env.view.stop_button.isVisibleTo(env.view)
    assert settled(env).startswith("Done in ")
    editor = slide_file(env).editor
    assert editor.text() == LF and rendered == []                    # Source mode: the mode stays, nothing renders
    assert env.window.state.mode == "source"
    assert not env.view.stop_button.isVisibleTo(env.view) and buttons(env) == ["Translate to German", "Better title"]
    editor.undo()
    assert editor.text() == BROKEN
    request = fake.calls()[0]["request"]
    assert "(environments)" in request and "<slide>" in request
    assert (env.root / SLIDE).read_bytes() == SLIDE_TEXT.encode()      # nothing was saved


def test_a_fix_renders_the_buffer_only_when_the_preview_is_showing(fake, monkeypatch):
    env = fake.env
    rendered = []
    monkeypatch.setattr(env.window.centre.preview, "render_buffer", lambda: rendered.append(True))
    monkeypatch.setattr(render_check, "confirm_render", lambda *a, **k: pytest.fail("a dialog opened"))
    env.window.state.set_mode("split")
    pump(0.1)
    break_slide(env)
    fake.reply({"answer": FIX})
    click(env, "Fix LaTeX errors")
    assert settled(env).startswith("Done in ") and rendered == [True] and env.window.state.mode == "split"


def test_a_slide_that_needs_no_change_says_so(fake):
    env = fake.env
    break_slide(env)
    fake.reply({"answer": {"edits": []}})
    click(env, "Fix LaTeX errors")
    assert settled(env) == "Nothing to change"
    assert slide_file(env).editor.text() == BROKEN


def test_typing_during_a_fix_is_a_conflict_and_nothing_is_overwritten(fake):
    env = fake.env
    break_slide(env)
    fake.reply({"answer": FIX, "delay": 0.4})
    click(env, "Fix LaTeX errors")
    editor = slide_file(env).editor
    typed = BROKEN + "% typed meanwhile\n"
    editor.replace_all_text(typed)
    assert settled(env) == tasks_module.CONFLICT
    assert editor.text() == typed
    assert env.view.result_button.isVisibleTo(env.view) and "Second point" in env.view.tasks.unapplied


def test_a_focus_change_during_a_task_does_not_change_its_target(fake):
    env = fake.env
    break_slide(env)
    fake.reply({"answer": FIX, "delay": 0.4})
    click(env, "Fix LaTeX errors")
    env.window.state.set_focused_slide("abd")
    wait_until(lambda: env.window.centre.path.name.startswith("abd"))
    assert settled(env).startswith("Done in ")
    assert slide_file(env).editor.text() == LF                       # abc, which was the target
    assert env.window.centre.source.file_for(env.window.centre.path).editor.text() == LF.replace("Hello", "Second")


def test_stop_cancels_and_the_late_result_is_dropped(fake, tmp_path):
    env = fake.env
    break_slide(env)
    fake.reply({"answer": FIX, "delay": 5, "marker": str(tmp_path / "late")})
    click(env, "Fix LaTeX errors")
    wait_until(lambda: fake.log.exists())
    env.view.stop_button.click()
    assert settled(env) == "Cancelled"
    assert slide_file(env).editor.text() == BROKEN and not (tmp_path / "late").exists()


def test_a_failure_is_reported_as_it_is(fake):
    env = fake.env
    break_slide(env)
    fake.reply({"error": "Not logged in · Please run /login"})
    click(env, "Fix LaTeX errors")
    assert settled(env) == claude_runner.NOT_LOGGED_IN
    assert slide_file(env).editor.text() == BROKEN


# -- translating --------------------------------------------------------------------------------------------

def test_a_translation_creates_the_partner_after_the_source_and_links_both(fake):
    env = fake.env
    fake.reply({"answer": GERMAN})
    click(env, "Translate to German")
    status = settled(env)
    (partner,) = german_files(env)
    new_id_slug = partner.name.removesuffix("-current.tex")
    assert status == f"Done in {status.split()[2]} s: {new_id_slug} created"
    text = partner.read_bytes().decode()
    assert text.startswith(f"%% Included in decks: (none)\r\n%%\r\n%% Translation of: abc-EN-Hello\r\n%%\r\n\r\n")
    assert "Hallo" in text and "Erster Punkt" in text and "\\setSlideVersion" not in text and "\r\n" in text
    deck = (env.root / "decks" / "test.tex").read_text()
    assert f"\\slide{{abc-EN-Hello}}\n\\slide{{{new_id_slug}}}\n\\section{{Main}}" in deck.replace("\r\n", "\n")
    source = slide_file(env).editor.text()                                # linked in the buffer, not saved
    assert f"%% DE translation: {new_id_slug}\n" in source and source != LF
    assert (env.root / SLIDE).read_bytes() == SLIDE_TEXT.encode()
    assert env.window.centre.path == partner                              # shown
    link = slide_language.translation_link("abc-EN-Hello")                # found although the source is unsaved
    assert link is not None and link.partner == new_id_slug and not any(b.label.startswith("Translate") for b in tasks_module._offers(
        tasks_module._focus(env.window), link))
    env.window.centre.open_file(env.path)
    wait_until(lambda: buttons(env) == ["Better title"])
    (call,) = fake.calls()
    assert call["request"].startswith("Translate this slide from English to German.\n"
                                      'Address the audience with "Sie" (formal).\n<slide>\n')
    assert "\\setSlideVersion" not in call["request"] and "Included in decks" not in call["request"]


def test_a_failed_translation_creates_nothing(fake):
    env = fake.env
    deck = (env.root / "decks" / "test.tex").read_bytes()
    fake.reply({"error": "overloaded"}, {"error": "overloaded"})
    click(env, "Translate to German")
    assert settled(env) == "overloaded"
    assert german_files(env) == [] and (env.root / "decks" / "test.tex").read_bytes() == deck
    assert slide_file(env).editor.text() == LF


def test_a_source_that_changed_meanwhile_gets_no_partner(fake):
    env = fake.env
    fake.reply({"answer": GERMAN, "delay": 0.4})
    click(env, "Translate to German")
    typed = LF + "% typed meanwhile\n"
    slide_file(env).editor.replace_all_text(typed)
    assert settled(env) == tasks_module.CONFLICT
    assert german_files(env) == [] and slide_file(env).editor.text() == typed
    assert "Hallo" in env.view.tasks.unapplied and env.view.result_button.isVisibleTo(env.view)
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
    assert settled(env).endswith("created, not added to the deck")
    assert len(german_files(env)) == 1 and deck.read_text().count("\\slide") == 1


def test_the_german_address_and_the_glossary_reach_the_request(fake):
    env = fake.env
    translation_style.set_de_address("du")
    (env.root / ".slidemage" / "glossary.md").write_text("slide = Folie\n", encoding="utf-8")
    fake.reply({"answer": GERMAN})
    click(env, "Translate to German")
    settled(env)
    request = fake.calls()[0]["request"]
    assert 'Address the audience with "du" (informal).' in request and "slide = Folie" in request
    assert json.loads((env.root / ".slidemage" / "project.json").read_text())["de_address"] == "du"


def test_settings_set_the_german_address(fake):
    from slidemage.ui.dialogs.settings import ModelsTab

    tab = ModelsTab()
    assert tab.address.current() == "Sie"
    tab.address.changed.emit("du")
    assert translation_style.de_address() == "du"


# -- the picker -----------------------------------------------------------------------------------------------

def test_the_picked_model_and_effort_reach_claude_and_are_remembered(fake):
    env = fake.env
    assert env.view.picker.text().startswith("Sonnet · medium")
    env.view._on_picked("claude_task_model:haiku")
    env.view._on_picked("claude_task_effort:low")
    assert env.view.picker.text().startswith("Haiku · low")
    break_slide(env)
    fake.reply({"answer": FIX})
    click(env, "Fix LaTeX errors")
    settled(env)
    assert fake.calls()[0]["argv"][:5] == ["-p", "--model", "haiku", "--effort", "low"]
    assert layout_settings.get("claude_task_model") == "haiku"
    assert env.view._remembered("claude_task_model", claude_runner.MODELS, claude_runner.MODEL) == "haiku"
    layout_settings.set("claude_task_effort", "extreme")                      # an unknown value is not taken
    assert env.view._remembered("claude_task_effort", claude_runner.EFFORTS, claude_runner.EFFORT) == "medium"


def test_two_clicks_start_one_task(fake):
    env = fake.env
    fake.reply({"answer": GERMAN, "delay": 0.3})
    click(env, "Translate to German")
    env.view.tasks.start(tasks_module.claude_tasks.TRANSLATE, "sonnet", "medium")
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


def test_a_slide_without_a_language_is_not_proofread(fake):
    env = fake.env
    show_text(env, PROSE)
    wait_until(lambda: "Proofread" in buttons(env))
    assert tasks_module._offers(tasks_module._focus(env.window), None)[1].label == "Proofread"
    legacy = tasks_module._Focus(env.root / "slides" / "xyz-legacy-current.tex", "xyz-legacy", PROSE)
    assert "Proofread" not in [b.label for b in tasks_module._offers(legacy, None)]


def test_proofreading_applies_its_edits_into_the_buffer(fake):
    env = fake.env
    show_text(env, PROSE)
    wait_until(lambda: "Proofread" in buttons(env))
    fake.reply({"answer": {"edits": [{"before": "enough ordinary words", "after": "enough ordinary words,"}]}})
    click(env, "Proofread")
    assert settled(env).startswith("Done in ")
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
    assert settled(env) == "Nothing to change" and slide_file(env).editor.text() == PROSE


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
    assert settled(env).startswith("Done in ") and slide_file(env).editor.text() == shorter


def test_a_better_title_replaces_only_the_frame_title(fake):
    env = fake.env
    fake.reply({"answer": {"title": "A better title"}})
    click(env, "Better title")
    assert settled(env).startswith("Done in ")
    assert slide_file(env).editor.text() == LF.replace("{Hello}", "{A better title}")
    assert "Current title: Hello" in fake.calls()[0]["request"]


def test_a_speaker_note_goes_before_the_frames_end_and_its_bubble_goes(fake):
    env = fake.env
    show_text(env, PROSE)
    wait_until(lambda: "Add speaker notes" in buttons(env))
    fake.reply({"answer": {"note": "Open with the main idea."}})
    click(env, "Add speaker notes")
    assert settled(env).startswith("Done in ")
    assert slide_file(env).editor.text().endswith("\t\\note{Open with the main idea.}\n\\end{standardframe}\n")
    assert "Add speaker notes" not in buttons(env)


def test_typing_during_a_title_task_is_a_conflict(fake):
    env = fake.env
    fake.reply({"answer": {"title": "A better title"}, "delay": 0.4})
    click(env, "Better title")
    typed = LF + "% typed\n"
    slide_file(env).editor.replace_all_text(typed)
    assert settled(env) == tasks_module.CONFLICT
    assert slide_file(env).editor.text() == typed and env.view.tasks.unapplied.startswith("A better title") is False


def test_the_status_names_what_is_done(fake, tmp_path):
    env = fake.env
    fake.reply({"answer": {"title": "T"}, "delay": 1.5})
    click(env, "Better title")
    assert env.view.task_status.text().startswith("Retitling abc … ")
    env.view.stop_button.click()
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
    env.view._refresh_bubbles()
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
    assert settled(env).endswith(f": {GERMAN_ID} updated")
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
    assert settled(env).endswith(f": {GERMAN_ID} updated")
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
    assert settled(env) == tasks_module.CONFLICT
    assert editor.text() == typed and "Erster Punkt!" in env.view.tasks.unapplied


def test_a_translation_that_changed_on_disk_meanwhile_is_not_overwritten(outdated):
    env = outdated.env
    wait_until(lambda: "Update German translation" in buttons(env))
    outdated.reply({"answer": UPDATE_ANSWER, "delay": 0.4})
    click(env, "Update German translation")
    changed = outdated.partner.read_bytes() + b"% getippt\r\n"
    outdated.partner.write_bytes(changed)
    assert settled(env) == tasks_module.CONFLICT and outdated.partner.read_bytes() == changed


# -- more than fits ---------------------------------------------------------------------------------------

def test_bubbles_that_do_not_fit_go_under_more(fake, monkeypatch):
    env = fake.env
    show_text(env, PROSE)
    wait_until(lambda: buttons(env) == TEXT_BUBBLES)
    view = env.view
    monkeypatch.setattr(view, "width", lambda: 5000)
    view._fit()
    assert not view.more.isVisibleTo(view) and all(b.isVisibleTo(view) for b in bubble_buttons(env))
    monkeypatch.setattr(view, "width", lambda: 330)
    view._fit()
    shown = [b for b in bubble_buttons(env) if b.isVisibleTo(view)]
    assert 0 < len(shown) < len(TEXT_BUBBLES) and view.more.isVisibleTo(view)
    assert [b.text() for b in shown] == TEXT_BUBBLES[:len(shown)]
    view._open_more()
    (menu,) = [m for m in view.findChildren(PopoverMenu) if m.isVisible()]
    assert [entry[2] for entry in menu._entries] == TEXT_BUBBLES[len(shown):]
    fake.reply({"answer": {"title": "T"}, "delay": 0.2})
    menu._on_activated(str(TEXT_BUBBLES.index("Better title")))
    assert view.tasks.busy
    settled(env)
