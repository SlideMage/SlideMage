# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Task card phases and actions on scripted routes."""
from __future__ import annotations

import threading

import pytest
from PySide6.QtWidgets import QLabel
from test_tasks_gui import pump, wait_until
from test_tasks_gui import BROKEN, FIX, GERMAN, GERMAN_HEADER, LF, UPDATE_ANSWER, break_slide, buttons, click
from test_tasks_gui import ctx, fake, outdated, settled, slide_file  # noqa: F401

from slidemage.ai.agent_types import EDIT_ASK
from slidemage.ui.kit.widgets import Button
from slidemage.ui.workspace import task_card_model as model
from slidemage.ui.workspace.chat.cards import DiffCard


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
    steps = area(env).task_card._steps
    rows = [steps.itemAt(i).layout() for i in range(steps.count())]
    return [(row.itemAt(1).widget().text(), row.itemAt(2).widget().text()) for row in rows]


def start_fix(fake, *replies):  # noqa: F811
    env = fake.env
    break_slide(env)
    fake.reply(*(replies or ({"answer": FIX},)))
    click(env, "Fix LaTeX errors")
    return env


def test_generate_shows_progress_and_stop_cancels_the_runner(fake):  # noqa: F811
    env = fake.env
    late = env.root / "late"
    fake.reply({"answer": {"title": "T"}, "delay": 5, "marker": str(late)})
    click(env, "Better title")
    wait_until(lambda: fake.calls())
    view = area(env).task_card
    assert area(env)._stack.currentWidget() is view and card(env).phase == model.GENERATE
    assert view.title.text() == "Better title" and "abc" in view.target.text() and view.route.text() == "fake-1"
    assert view.state.accessibleDescription() == state(env)
    card(env).t0 -= 7
    area(env).tasks._tick()
    assert view.elapsed.text().endswith(" s")
    view.steps_toggle.click()
    assert step_rows(env)[0] == ("Generate", "now")
    (work,) = env.window.running_ai_work()
    assert work.stop is not None and "abc" in work.text
    press(env, "Stop")
    wait_until(phase_is(env, model.STOPPED))
    assert shown_buttons(env) == ["Run again", "Close"] and env.window.running_ai_work() == []
    assert slide_file(env).editor.text() == LF and not late.exists()
    press(env, "Close")
    assert card(env) is None


def test_review_apply_check_preview_done(asked, monkeypatch):
    env = start_fix(asked)
    wait_until(phase_is(env, model.REVIEW))
    view = area(env).task_card
    assert shown_buttons(env) == ["Apply", "Reject", "View full diff", "Compare rendered"]
    (diff,) = view.findChildren(DiffCard)
    assert diff.title == FILE and any("+ " in line.text() for line in diff.findChildren(QLabel))
    assert slide_file(env).editor.text() == BROKEN and asked.renders == []
    assert env.window.running_ai_work() == [] and not area(env).tasks.busy
    press(env, "View full diff")
    assert diff._all_rows

    writes, write = [], area(env).tasks._write_card
    monkeypatch.setattr(area(env).tasks, "_write_card", lambda *args: writes.append(args))
    press(env, "Apply")
    assert card(env).phase == model.APPLY and shown_buttons(env) == []
    (work,) = env.window.running_ai_work()
    assert work.stop is None
    gate, render = threading.Event(), asked.rendered
    monkeypatch.setattr(area(env).workspace, "render_preview", lambda *a, **k: gate.wait(5) and render(*a, **k))
    wait_until(lambda: writes)
    write(*writes[0])
    wait_until(phase_is(env, model.CHECK))
    assert "The old preview is marked as older." in state(env)
    assert shown_buttons(env) == [] and slide_file(env).editor.text() == LF
    (work,) = env.window.running_ai_work()
    assert work.stop is not None                                                  # a render can be cancelled
    gate.set()
    wait_until(phase_is(env, model.DONE))
    assert state(env) == f"Changed 1 line in {FILE}. The preview is current."
    assert shown_buttons(env) == ["View change", "Undo", "Compare rendered", "Close"] and env.window.running_ai_work() == []
    press(env, "View change")
    assert view.findChildren(DiffCard)
    press(env, "Undo")
    assert slide_file(env).editor.text() == BROKEN and card(env) is None


def test_reject_changes_nothing(asked):
    shown = []
    asked.env.window.toast.show_message = shown.append
    env = start_fix(asked)
    wait_until(phase_is(env, model.REVIEW))
    press(env, "Reject")
    assert card(env) is None and slide_file(env).editor.text() == BROKEN and shown == ["Rejected. Nothing was changed."]
    assert asked.renders == []


def test_a_task_with_nothing_to_change_ends_without_review_or_undo(asked):
    env = start_fix(asked, {"answer": {"edits": []}})
    wait_until(phase_is(env, model.DONE))
    assert state(env) == "Nothing to change in abc. Nothing was written." and shown_buttons(env) == ["Close"]
    area(env).task_card.steps_toggle.click()
    assert [note for _label, note in step_rows(env)] == ["", "skipped", "skipped", "skipped"]


def test_a_conflict_keeps_the_proposal_compares_and_runs_again(asked):
    env = start_fix(asked, {"answer": FIX, "delay": 0.4}, {"answer": FIX})
    editor = slide_file(env).editor
    typed = BROKEN + "% typed meanwhile\n"
    editor.replace_all_text(typed)
    wait_until(phase_is(env, model.CONFLICT))
    view = area(env).task_card
    assert state(env) == CONFLICT_TEXT and shown_buttons(env) == ["Compare with current", "Compare rendered", "Run again", "Dismiss"]
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
    typed += "% typed while reviewing\n"
    editor.replace_all_text(typed)
    press(env, "Apply")
    wait_until(phase_is(env, model.CONFLICT))
    assert editor.text() == typed and state(env) == CONFLICT_TEXT and asked.renders == []
    press(env, "Dismiss")
    assert card(env) is None


def test_a_failed_preview_keeps_the_change_and_opens_the_source_or_the_log(fake):  # noqa: F811
    env = fake.env
    fake.error = "Render failed for abc.\n! Undefined control sequence.\nl.9 \\SMCod{standardframe}"
    break_slide(env)
    fake.reply({"answer": FIX})
    click(env, "Fix LaTeX errors")
    wait_until(phase_is(env, model.PREVIEW_FAILED))
    assert state(env) == f"Changes applied to {FILE}. The preview failed: Undefined control sequence on line 9. Nothing was rolled back."
    assert shown_buttons(env) == ["Source", "View log", "Close"] and slide_file(env).editor.text() == LF
    area(env).task_card.steps_toggle.click()
    assert step_rows(env)[3] == ("Check preview", "failed")
    drawer = env.window.compile_display.drawer
    press(env, "View log")
    assert drawer.isVisibleTo(drawer.parentWidget())
    env.window.state.set_mode("preview")
    press(env, "Source")
    assert env.window.state.mode == "source" and env.window.centre.path == env.path
    press(env, "Close")
    assert card(env) is None


def test_stopping_the_render_ends_the_card_done_without_a_preview(fake, monkeypatch):  # noqa: F811
    env = fake.env
    gate = threading.Event()

    def cancelled(*_args, **_kwargs):
        gate.wait(5)
        raise RuntimeError("Preview canceled")

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


def test_run_again_on_a_setup_card_asks_the_route_again(fake):  # noqa: F811
    env = fake.env
    fake.route.problem_text = "Route unavailable."
    break_slide(env)
    click(env, "Fix LaTeX errors")
    assert card(env).phase == model.SETUP and shown_buttons(env) == ["Run again", "Close"] and fake.calls() == []
    fake.route.problem_text = ""
    fake.reply({"answer": FIX})
    press(env, "Run again")
    assert settled(env).startswith("Applied automatically") and slide_file(env).editor.text() == LF


def test_undo_of_a_closed_translation_goes_back_to_the_backup(outdated):  # noqa: F811
    env = outdated.env
    wait_until(lambda: "Update German translation" in buttons(env))
    before = outdated.partner.read_bytes()
    outdated.reply({"answer": UPDATE_ANSWER})
    click(env, "Update German translation")
    assert "It stays linked to the English slide." in settled(env)
    written = outdated.partner.read_bytes().decode()
    assert written.startswith(GERMAN_HEADER) and "\\setSlideVersion{1-0-0+}" in written and "Erster Punkt!" in written
    assert env.window.centre.path == env.path and "Undo" in shown_buttons(env)
    press(env, "Undo")
    assert outdated.partner.read_bytes() == before and card(env) is None


def test_hidden_card_keeps_running_and_holds_other_tasks_until_reviewed(asked):
    env = start_fix(asked, {"answer": FIX, "delay": 0.4})
    head = area(env).header
    area(env).task_card.back.click()
    assert head.pill.isVisibleTo(head) and "generating" in head.pill.label.full_text()
    wait_until(phase_is(env, model.REVIEW))
    assert "waiting for review" in head.pill.label.full_text()
    assert area(env)._stack.currentWidget() is area(env).surface_for("fake_cloud")
    head.pill.clicked.emit()
    assert not head.pill.isVisibleTo(head)
    area(env).task_card.back.click()
    click(env, "Better title")
    assert area(env)._stack.currentWidget() is area(env).task_card and not card(env).hidden
    assert card(env).phase == model.REVIEW and len(asked.calls()) == 1
    press(env, "Apply")
    wait_until(phase_is(env, model.DONE))
    area(env).task_card.back.click()
    assert card(env) is None and not head.pill.isVisibleTo(head)


def test_the_language_panels_translate_opens_the_card(asked):
    env = asked.env
    env.window.side_panels.set_panel("language")
    pump(0.1)
    panel = env.window.side_panels
    asked.reply({"answer": GERMAN})
    next(b for b in panel.findChildren(Button) if b.text() == "Translate to German · cloud").click()
    assert card(env).task is model.ai_tasks.TRANSLATE and area(env)._stack.currentWidget() is area(env).task_card
    wait_until(phase_is(env, model.REVIEW))
    assert state(env) == "Proposed translation of abc into German, as a new slide. Nothing is written yet."
    (diff,) = area(env).task_card.findChildren(DiffCard)
    assert diff.title == f"New DE slide, translated from {FILE}"
    press(env, "Apply")
    wait_until(phase_is(env, model.DONE))
    assert "Created " in state(env) and "It stays linked to the English slide." in state(env)
    assert shown_buttons(env) == ["View DE version", "Close"]


def test_the_first_error_of_a_compile_log():
    assert model.first_error("Render failed.\n! Undefined control sequence.\nl.9 \\SMCod{x}") == "Undefined control sequence on line 9"
    assert model.first_error("! Missing } inserted.") == "Missing } inserted"
    assert model.first_error("Preview timed out\nmore") == "Preview timed out" and model.first_error("") == "the render failed"
