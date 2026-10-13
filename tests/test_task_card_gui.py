"""The task card (workspace v6, step 4; ui/workspace/task_card.py and task_card_model.py) phase by phase: what it
says, which buttons it offers and what they do, with the stand-in for `claude -p` (fake_claude.py) and a stand-in for
the preview's render (the Check preview step compiles or fails at will). The project is a throwaway one."""
from __future__ import annotations

import sys
import threading

import pytest
from PySide6.QtWidgets import QLabel
from test_claude_code_gui import env as claude_env, pump, wait_until  # noqa: F401 -- a fixture
from test_claude_tasks_gui import BROKEN, FIX, GERMAN, LF, break_slide, buttons, click, ctx, fake, outdated, settled, slide_file  # noqa: F401

from slidemage.ai import claude_runner
from slidemage.ai.agent_types import EDIT_ASK
from slidemage.ui.kit.widgets import Button
from slidemage.ui.workspace import task_card_model as model
from slidemage.ui.workspace.chat.cards import DiffCard

pytest.importorskip("PySide6.QtWebEngineWidgets")
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the stand-in for claude is a POSIX script")

FILE = "abc-EN-Hello-current.tex"
CONFLICT_TEXT = "abc changed while this task ran. The proposal is kept but not applied."


@pytest.fixture
def asked(fake):  # noqa: F811
    """The project is on "Ask before edits": an answer waits in Review."""
    fake.env.window.assistant.chat.session.set_mode(EDIT_ASK)
    return fake


def area(env):
    return env.window.assistant


def card(env):
    return area(env).tasks.card


def shown_buttons(env) -> list[str]:
    layout = area(env).task_card._buttons
    return [layout.itemAt(i).widget().text() for i in range(layout.count())]


def press(env, label: str) -> None:
    layout = area(env).task_card._buttons
    next(layout.itemAt(i).widget() for i in range(layout.count()) if layout.itemAt(i).widget().text() == label).click()


def phase_is(env, phase: str):
    return lambda: card(env) is not None and card(env).phase == phase


def state(env) -> str:
    return area(env).task_card.state.text()


def step_rows(env) -> list[tuple[str, str]]:
    """(label, note) of the steps on show."""
    rows = area(env).task_card._steps
    found = []
    for i in range(rows.count()):
        labels = [w.text() for w in (rows.itemAt(i).layout().itemAt(j).widget() for j in range(1, 3))]
        found.append(tuple(labels))
    return found


def hold(monkeypatch, owner, name):
    """Replace a method by one that keeps its arguments instead of running: returns the list and the original."""
    original, kept = getattr(owner, name), []
    monkeypatch.setattr(owner, name, lambda *args, **kwargs: kept.append((args, kwargs)))
    return kept, original


# -- Generate -------------------------------------------------------------------------------------------------

def test_generate_names_the_task_the_slide_and_the_route_counts_seconds_and_stops(fake):  # noqa: F811
    env = fake.env
    fake.reply({"answer": {"title": "T"}, "delay": 5})
    click(env, "Better title")
    view = area(env).task_card
    assert area(env)._stack.currentWidget() is view and card(env).phase == model.GENERATE
    assert view.title.text() == "Better title" and view.target.text() == "Target: abc · Hello"
    assert view.route.text() == "Claude Code · Haiku · effort medium" and view.route_icon.text() == "cloud"
    assert state(env) == "Looking for a better title for abc. The rest of the slide is kept."
    assert view.state.accessibleName() == "Task status" and view.state.accessibleDescription() == state(env)
    assert shown_buttons(env) == ["Stop"] and view.elapsed.text() == "0 s"
    card(env).t0 -= 7
    area(env).tasks._tick()
    assert view.elapsed.text() == "7 s"                                    # seconds, no percentage
    assert view.steps_toggle.text() == "▸ Steps · 0 of 4 done" and step_rows(env) == []
    view.steps_toggle.click()
    assert view.steps_toggle.text() == "▾ Steps · 0 of 4 done"
    assert step_rows(env) == [("Generate", "now"), ("Review", ""), ("Apply", ""), ("Check preview", "")]
    (work,) = env.window.running_ai_work()                                  # generating is AI work under way
    assert work.stop is not None and "abc" in work.text
    press(env, "Stop")
    wait_until(phase_is(env, model.STOPPED))
    assert state(env) == "Stopped. Nothing was changed." and shown_buttons(env) == ["Run again", "Close"]
    assert step_rows(env)[0] == ("Generate", "stopped") and env.window.running_ai_work() == []
    assert slide_file(env).editor.text() == LF
    press(env, "Close")
    assert card(env) is None and area(env)._stack.currentWidget() is area(env).claude_code


# -- Review, Apply, Check preview, Done -------------------------------------------------------------------------

def test_review_apply_check_preview_done(asked, monkeypatch):
    env = asked.env
    break_slide(env)
    asked.reply({"answer": FIX})
    click(env, "Fix LaTeX errors")
    wait_until(phase_is(env, model.REVIEW))
    view = area(env).task_card
    assert state(env) == f"Proposed change to {FILE}. Nothing is written yet."
    assert shown_buttons(env) == ["Apply", "Reject", "View full diff"]
    primary = view._buttons.itemAt(0).widget()
    assert primary.property("kind") == "primary" and view._buttons.itemAt(1).widget().property("kind") == "secondary"
    (diff,) = view.findChildren(DiffCard)
    assert diff.title == FILE and any("+ " in line.text() for line in diff.findChildren(QLabel))
    assert slide_file(env).editor.text() == BROKEN and asked.renders == []   # nothing is written yet
    assert env.window.running_ai_work() == [] and not area(env).tasks.busy    # waiting for the user is not running
    assert area(env).header.shown == []                                       # no other task meanwhile
    assert step_rows(env) == [] and view.steps_toggle.text() == "▸ Steps · 1 of 4 done"
    press(env, "View full diff")
    assert diff._all_rows

    writes, write = hold(monkeypatch, area(env).tasks, "_write_card")           # keep the card in Apply
    press(env, "Apply")
    assert card(env).phase == model.APPLY and shown_buttons(env) == []
    assert state(env) == f"Writing {FILE}. This step cannot be interrupted."
    (work,) = env.window.running_ai_work()
    assert work.stop is None and "write that has started finishes" in work.line   # Stop and switch waits for it
    gate, render = threading.Event(), asked.rendered
    monkeypatch.setattr(area(env).workspace, "render_preview", lambda *a, **k: gate.wait(5) and render(*a, **k))
    wait_until(lambda: writes)
    write(*writes[0][0])
    wait_until(phase_is(env, model.CHECK))
    assert state(env) == "Changes applied. Rendering abc · Instructor · EN. The old preview is marked as older."
    assert shown_buttons(env) == [] and slide_file(env).editor.text() == LF
    (work,) = env.window.running_ai_work()
    assert work.stop is not None                                                  # a render can be cancelled
    gate.set()
    wait_until(phase_is(env, model.DONE))
    assert state(env) == f"Changed 1 line in {FILE}. The preview is current."
    assert shown_buttons(env) == ["View change", "Undo", "Close"] and env.window.running_ai_work() == []
    view.steps_toggle.click()
    assert view.steps_toggle.text() == "▾ Steps · all done"
    assert step_rows(env) == [("Generate", ""), ("Review", ""), ("Apply", ""), ("Check preview", "")]
    press(env, "View change")
    (diff,) = view.findChildren(DiffCard)
    assert diff.title == FILE
    press(env, "Undo")                                                            # the buffer's own undo
    assert slide_file(env).editor.text() == BROKEN and card(env) is None


def test_reject_changes_nothing(asked):
    env = asked.env
    shown = []
    env.window.toast.show_message = shown.append
    break_slide(env)
    asked.reply({"answer": FIX})
    click(env, "Fix LaTeX errors")
    wait_until(phase_is(env, model.REVIEW))
    press(env, "Reject")
    assert card(env) is None and slide_file(env).editor.text() == BROKEN and shown == ["Rejected. Nothing was changed."]
    assert asked.renders == []


def test_edit_automatically_skips_review(fake):  # noqa: F811
    env = fake.env
    break_slide(env)
    fake.reply({"answer": FIX})
    click(env, "Fix LaTeX errors")
    assert settled(env) == ("Applied automatically (Edit automatically is on). "
                            f"Changed 1 line in {FILE}. The preview is current.")
    assert slide_file(env).editor.text() == LF and len(fake.renders) == 1
    area(env).task_card.steps_toggle.click()
    assert step_rows(env) == [("Generate", ""), ("Review", "skipped · Edit automatically"), ("Apply", ""), ("Check preview", "")]
    assert shown_buttons(env) == ["View change", "Undo", "Close"]


def test_a_task_with_nothing_to_change_ends_without_review_or_undo(asked):
    env = asked.env
    break_slide(env)
    asked.reply({"answer": {"edits": []}})
    click(env, "Fix LaTeX errors")
    wait_until(phase_is(env, model.DONE))
    assert state(env) == "Nothing to change in abc. Nothing was written." and shown_buttons(env) == ["Close"]
    area(env).task_card.steps_toggle.click()
    assert [note for _label, note in step_rows(env)] == ["", "skipped", "skipped", "skipped"]


def test_a_failed_run_ends_the_card_with_the_reason(asked):
    env = asked.env
    break_slide(env)
    asked.reply({"error": "overloaded"})
    click(env, "Fix LaTeX errors")
    wait_until(phase_is(env, model.FAILED))
    assert state(env) == "overloaded. Nothing was changed." and shown_buttons(env) == ["Run again", "Close"]


# -- Conflict --------------------------------------------------------------------------------------------------

def test_a_conflict_keeps_the_proposal_compares_and_runs_again(asked):
    env = asked.env
    break_slide(env)
    asked.reply({"answer": FIX, "delay": 0.4}, {"answer": FIX})
    click(env, "Fix LaTeX errors")
    editor = slide_file(env).editor
    typed = BROKEN + "% typed meanwhile\n"
    editor.replace_all_text(typed)
    wait_until(phase_is(env, model.CONFLICT))
    view = area(env).task_card
    assert state(env) == CONFLICT_TEXT and shown_buttons(env) == ["Compare with current", "Run again", "Dismiss"]
    assert view.findChildren(DiffCard) and editor.text() == typed and asked.renders == []   # kept, not applied
    assert not area(env).tasks.busy
    view.steps_toggle.click()
    assert step_rows(env)[1] == ("Review", "slide changed")
    press(env, "Compare with current")
    (diff,) = view.findChildren(DiffCard)
    assert any("typed meanwhile" in line.text() for line in diff.findChildren(QLabel))
    press(env, "Run again")                                                     # the same task on the same slide
    wait_until(phase_is(env, model.REVIEW))
    assert card(env).title == "Fix LaTeX errors" and len(asked.calls()) == 2
    assert typed.rstrip() in card(env).before


def test_the_slide_changing_while_the_proposal_waits_is_a_conflict_at_apply(asked):
    env = asked.env
    break_slide(env)
    asked.reply({"answer": FIX})
    click(env, "Fix LaTeX errors")
    wait_until(phase_is(env, model.REVIEW))
    typed = BROKEN + "% typed while reviewing\n"
    slide_file(env).editor.replace_all_text(typed)
    press(env, "Apply")
    wait_until(phase_is(env, model.CONFLICT))
    assert slide_file(env).editor.text() == typed and state(env) == CONFLICT_TEXT
    press(env, "Dismiss")
    assert card(env) is None


# -- Preview failed ---------------------------------------------------------------------------------------------

def test_a_failed_preview_keeps_the_change_and_opens_the_source_or_the_log(fake):  # noqa: F811
    env = fake.env
    fake.error = "Render failed for abc.\n! Undefined control sequence.\nl.9 \\SMCod{standardframe}"
    break_slide(env)
    fake.reply({"answer": FIX})
    click(env, "Fix LaTeX errors")
    wait_until(phase_is(env, model.PREVIEW_FAILED))
    assert state(env) == f"Changes applied to {FILE}. The preview failed: Undefined control sequence on line 9. Nothing was rolled back."
    assert shown_buttons(env) == ["Open source", "View log", "Close"] and slide_file(env).editor.text() == LF
    area(env).task_card.steps_toggle.click()
    assert step_rows(env)[3] == ("Check preview", "failed")
    drawer = env.window.compile_display.drawer
    press(env, "View log")
    assert drawer.isVisibleTo(drawer.parentWidget())
    env.window.state.set_mode("preview")
    press(env, "Open source")
    assert env.window.state.mode == "source" and env.window.centre.path == env.path
    press(env, "Close")
    assert card(env) is None


def test_stopping_the_render_ends_the_card_done_without_a_preview(fake, monkeypatch):  # noqa: F811
    env = fake.env
    gate = threading.Event()

    def cancelled(*_args, **_kwargs):
        gate.wait(5)
        raise RuntimeError("Preview cancelled")

    monkeypatch.setattr(area(env).workspace, "render_preview", cancelled)
    break_slide(env)
    fake.reply({"answer": FIX})
    click(env, "Fix LaTeX errors")
    wait_until(phase_is(env, model.CHECK))
    (work,) = env.window.running_ai_work()
    work.stop()                                                                 # Stop and switch
    gate.set()
    wait_until(phase_is(env, model.DONE))
    assert state(env).endswith("The preview was not rendered because the task was stopped.")


# -- Setup needed -----------------------------------------------------------------------------------------------

def test_a_login_failure_asks_for_setup_and_signs_in(fake, monkeypatch):  # noqa: F811
    env = fake.env
    break_slide(env)
    fake.reply({"error": "Not logged in · Please run /login"})
    click(env, "Fix LaTeX errors")
    wait_until(phase_is(env, model.SETUP))
    assert state(env) == claude_runner.NOT_LOGGED_IN + " The slide is unchanged."
    assert shown_buttons(env) == ["Sign in…", "Run again", "Close"]
    area(env).task_card.steps_toggle.click()
    assert step_rows(env)[0] == ("Generate", "setup needed")
    signed = []
    monkeypatch.setattr(area(env).claude_code, "sign_in", lambda: signed.append(True))
    press(env, "Sign in…")
    assert signed == [True] and card(env) is None and area(env)._stack.currentWidget() is area(env).claude_code


def test_run_again_on_a_setup_card_asks_the_route_again(fake, monkeypatch):  # noqa: F811
    env = fake.env
    from slidemage.ai import claude_launch

    real = claude_launch.find_claude
    monkeypatch.setattr(claude_launch, "find_claude", lambda: None)
    break_slide(env)
    click(env, "Fix LaTeX errors")
    assert card(env).phase == model.SETUP and shown_buttons(env) == ["Run again", "Close"] and fake.calls() == []
    monkeypatch.setattr(claude_launch, "find_claude", real)
    fake.reply({"answer": FIX})
    press(env, "Run again")
    assert settled(env).startswith("Applied automatically") and slide_file(env).editor.text() == LF


# -- Undo ---------------------------------------------------------------------------------------------------------

def test_a_translation_has_no_undo_and_views_the_new_slide(fake):  # noqa: F811
    env = fake.env
    fake.reply({"answer": GERMAN})
    click(env, "Translate to German")
    settled(env)
    assert shown_buttons(env) == ["View DE version", "Close"]
    assert card(env).title == "Translate to German" and area(env).task_card.title.text() == "Translate to German"


def test_undo_of_a_closed_translation_goes_back_to_the_backup(outdated):  # noqa: F811
    env = outdated.env
    wait_until(lambda: "Update German translation" in buttons(env))
    before = outdated.partner.read_bytes()
    outdated.reply({"answer": {"body": outdated.german.replace("Erster Punkt", "Erster Punkt!")}})
    click(env, "Update German translation")
    settled(env)
    assert outdated.partner.read_bytes() != before and shown_buttons(env) == ["View change", "Undo", "Close"]
    press(env, "Undo")
    assert outdated.partner.read_bytes() == before and card(env) is None


# -- Back to conversation and the pill ---------------------------------------------------------------------------

def test_back_to_conversation_leaves_a_pill_while_the_proposal_waits(asked):
    env = asked.env
    break_slide(env)
    asked.reply({"answer": FIX})
    click(env, "Fix LaTeX errors")
    wait_until(phase_is(env, model.REVIEW))
    head = area(env).header
    assert not head.pill.isVisibleTo(head)
    area(env).task_card.back.click()
    assert area(env)._stack.currentWidget() is area(env).claude_code
    assert head.pill.isVisibleTo(head) and head.pill.label.full_text() == "Fix LaTeX errors · waiting for review"
    head.pill.clicked.emit()                                                    # Open
    assert area(env)._stack.currentWidget() is area(env).task_card and not head.pill.isVisibleTo(head)
    press(env, "Apply")
    wait_until(phase_is(env, model.DONE))
    area(env).task_card.back.click()                                            # an ended card just goes
    assert card(env) is None and not head.pill.isVisibleTo(head)


def test_a_card_left_while_it_generates_keeps_running_and_shows_where_it_got_to(asked):
    env = asked.env
    asked.reply({"answer": {"title": "T"}, "delay": 0.5})
    click(env, "Better title")
    area(env).task_card.back.click()
    head = area(env).header
    assert head.pill.label.full_text() == "Better title · generating"
    wait_until(phase_is(env, model.REVIEW))
    assert head.pill.label.full_text() == "Better title · waiting for review"
    assert area(env)._stack.currentWidget() is area(env).claude_code             # it does not jump back by itself


def test_the_target_note_says_so_after_moving_to_another_slide(fake):  # noqa: F811
    env = fake.env
    fake.reply({"answer": {"title": "T"}, "delay": 5})
    click(env, "Better title")
    env.window.state.set_focused_slide("abd")
    wait_until(lambda: env.window.centre.path.name.startswith("abd"))
    area(env).task_card.render()
    assert area(env).task_card.target.text() == "Target: abc · Hello (still this slide, though you moved on)"
    area(env).tasks.stop()
    wait_until(phase_is(env, model.STOPPED))


# -- the entry points ---------------------------------------------------------------------------------------------

def test_the_language_panels_translate_opens_the_card(asked):
    env = asked.env
    env.window.side_panels.set_panel("language")
    pump(0.1)
    panel = env.window.side_panels
    asked.reply({"answer": GERMAN})
    next(b for b in panel.findChildren(Button) if b.text() == "Translate to DE").click()
    assert card(env).task is model.claude_tasks.TRANSLATE and area(env)._stack.currentWidget() is area(env).task_card
    wait_until(phase_is(env, model.REVIEW))
    assert state(env) == "Proposed translation of abc into German, as a new slide. Nothing is written yet."
    (diff,) = area(env).task_card.findChildren(DiffCard)
    assert diff.title == f"New DE slide, translated from {FILE}"
    press(env, "Apply")
    wait_until(phase_is(env, model.DONE))
    assert "Created " in state(env) and "It stays linked to the English slide." in state(env)


def test_a_card_in_review_holds_the_other_tasks_back(asked):
    env = asked.env
    break_slide(env)
    asked.reply({"answer": FIX})
    click(env, "Fix LaTeX errors")
    wait_until(phase_is(env, model.REVIEW))
    area(env).task_card.back.click()
    click(env, "Better title")                                                  # asks for the answer first
    assert card(env).phase == model.REVIEW and not card(env).hidden and len(asked.calls()) == 1


# -- the model, without a window -------------------------------------------------------------------------------

def test_the_first_error_of_a_compile_log():
    assert model.first_error("Render failed.\n! Undefined control sequence.\nl.9 \\SMCod{x}") == "Undefined control sequence on line 9"
    assert model.first_error("! Missing } inserted.") == "Missing } inserted"
    assert model.first_error("Preview timed out\nmore") == "Preview timed out" and model.first_error("") == "the render failed"


def test_changed_lines_counts_what_the_change_touches():
    assert model.changed_lines("a\nb\nc\n", "a\nB\nc\n") == 1
    assert model.changed_lines("a\n", "a\nb\nc\n") == 2 and model.changed_lines("a\n", "a\n") == 0
