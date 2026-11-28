# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Make readable through the header, task card, findings panel and palette on scripted routes."""
from __future__ import annotations

import json

import pytest
from PySide6.QtWidgets import QLabel
from selection_make_readable_image_batches_helpers import (LF, buttons, card, phase_is, settled, shown_buttons,
                                                        slide_file, state, wait_until)
from selection_make_readable_image_batches_helpers import ctx as ctx, fake as fake
from selection_make_readable_image_batches_helpers import click, pump


from slidemage import readability
from slidemage.ai import ai_profile, tasks as ai_tasks
from slidemage.ai.agent_types import EDIT_ASK
from slidemage.ui.kit.widgets import Button
from slidemage.ui.workspace import task_card_model as model
from slidemage.ui.workspace.readability_panel import TEMPLATE_HINT, ReadabilityPanel
from slidemage.ui.workspace import task_bubbles as tasks_module


FILE = "abc-EN-Hello-current.tex"
BIGGER = LF.replace("\\begin{itemize}", "\\begin{itemize}\\small", 1)       # a proposal that passes the checks


def finding(cls="body", severity="error", measured=2.8, threshold=3.3, rule="text_size", unit="% of slide height",
            template_level=False):
    return readability.Finding("abc", 1, rule, cls, severity, measured, threshold, "min" if rule != "clipped" else "max", unit,
                               (0.1, 0.3, 0.9, 0.6), "First point", "Enlarge it.", file=FILE, template_level=template_level)


def report_of(*findings, slide_id="abc"):
    return readability.Report([readability.SlideReport(slide_id, 1, FILE, list(findings), height_pt=272.0)])


BEFORE = (finding(), finding("figure text", "error", 2.0, 2.6), finding("image", "warning", 20.0, 25.0, "image_size", "% of the slide area"))
TEMPLATE = finding("citation", "error", 1.25, 2.2, template_level=True)


class Measure:

    def __init__(self, *answers):
        self.answers, self.texts = list(answers), []

    def __call__(self, _ctx, target, text, view, language, cancel, **kwargs):
        self.texts.append(text)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def measure(fake, monkeypatch):  # noqa: F811
    made = Measure(report_of())
    monkeypatch.setattr(tasks_module.readability_check, "check_slide", made)
    return made


def know(env, *findings, text=LF) -> None:
    env.window.readability_known.remember_slide(env.path, text, report_of(*findings))
    env.window.assistant.header.schedule()
    wait_until(lambda: ("Make readable" in buttons(env)) == any(f.severity == "error" and not f.template_level for f in findings))


def propose(fake, body=BIGGER, **answer):
    fake.reply({"answer": {"body": body, **answer}})
    click(fake.env, "Make readable")


def requests(made) -> list[str]:
    return [call["request"] for call in made.calls()]


def findings_of(request: str) -> list[dict]:
    return json.loads(request.split("Findings (JSON):\n")[1].split("\n<slide>")[0])["findings"]


def test_header_and_panel_use_findings_only_for_the_measured_text(fake, measure, monkeypatch):  # noqa: F811
    env = fake.env
    header = env.window.assistant.header
    header.schedule()
    pump(0.2)
    assert measure.texts == [] and "Make readable" not in buttons(env)
    know(env, BEFORE[-1])
    know(env, TEMPLATE)

    measure.answers = [report_of(*BEFORE, TEMPLATE)]
    check = env.window.assistant.readability
    check.check_slide()
    wait_until(lambda: check.panel.report is not None)
    assert env.window.readability_known.fixable(env.path, LF) == list(BEFORE)
    wait_until(lambda: "Make readable" in buttons(env))
    assert "Make readable" in [button.label for button in header.shown]
    editor = slide_file(env).editor
    editor.replace_all_text(LF + "% edited\n")
    wait_until(lambda: "Make readable" not in buttons(env))
    area = env.window.assistant
    slide, = check.panel.report.slides
    toasts = []
    monkeypatch.setattr(env.window.toast, "show_message", toasts.append)
    area.readability_panel.make_readable_clicked.emit(slide)
    assert toasts == ["The slide changed since it was checked: check it again."] and card(env) is None

    editor.replace_all_text(LF)
    wait_until(lambda: "Make readable" in buttons(env))
    measure.answers = [report_of()]
    fake.reply({"answer": {"body": BIGGER}})
    area.readability_panel.make_readable_clicked.emit(slide)
    assert card(env).task is ai_tasks.READABLE
    settled(env)
    assert editor.text() == BIGGER



def test_review_measures_the_proposal_on_the_selected_local_route_before_applying(ctx, fake, measure):
    env = fake.env
    area = env.window.assistant
    area.chat.session.set_mode(EDIT_ASK)
    route = fake.routes.local.id
    ai_profile.set_mode(ctx, ai_profile.LOCAL)
    ai_profile.set_model_choice(ctx, route, ai_profile.FIXES, "fake-2")
    know(env, *BEFORE, TEMPLATE)
    measure.answers = [report_of(finding("image", "warning", 24.0, 25.0, "image_size", "% of the slide area"), TEMPLATE)]
    propose(fake, note="Split the table.")
    wait_until(phase_is(env, model.REVIEW))
    assert (card(env).route.route, card(env).route.model) == (route, "fake-2")
    assert card(env).task is ai_tasks.READABLE
    assert "0 errors, 1 warning (was 2 errors, 1 warning)" in state(env)
    assert "Split the table." in state(env)
    request, = requests(fake)
    assert "The typeset page is 272 pt high." in request and request.endswith(f"<slide>\n{LF}\n</slide>")
    assert [(f["cls"], f["severity"]) for f in findings_of(request)] == [
        ("body", "error"), ("figure text", "error"), ("image", "warning")]
    assert measure.texts == [BIGGER] and slide_file(env).editor.text() == LF
    assert area.tasks.compare_texts() == (env.path, LF, BIGGER)

    area.tasks.apply()
    wait_until(phase_is(env, model.DONE))
    assert slide_file(env).editor.text() == BIGGER and len(fake.renders) == 1
    assert measure.texts == [BIGGER]
    assert "Now readable: Body text, Text in a figure" in state(env)
    assert "image (24 % of the slide area, needs ≥ 25)" in state(env)
    assert {"Undo", "Compare rendered"} <= set(shown_buttons(env))


def test_run_again_uses_remaining_findings_after_overflow_and_finishes_when_clean(fake, measure):  # noqa: F811
    env = fake.env
    know(env, *BEFORE)
    clipped = finding("body", "error", 6.0, 0, "clipped", "pt beyond the page")
    left = finding("figure text", "error", 2.4, 2.6)
    measure.answers = [report_of(clipped, left), report_of(left), report_of()]
    propose(fake)
    wait_until(phase_is(env, model.OVERFLOW))
    assert card(env).route.route == fake.routes.cloud.id and not card(env).running
    assert "still cut off or overlapping" in state(env)
    assert {"Undo", "Run again"} <= set(shown_buttons(env))
    assert model.steps(card(env))[-1].icon == "error"

    again = env.window.assistant.task_card._handlers["again"]
    partial = BIGGER.replace(r"\small", r"\footnotesize", 1)
    clean = BIGGER.replace(r"\small", r"\normalsize", 1)
    for body, previous, rules in (
        (partial, BIGGER, {"clipped", "text_size"}),
        (clean, partial, {"text_size"}),
    ):
        fake.reply({"answer": {"body": body}})
        again()
        assert settled(env).startswith("Applied automatically")
        request = requests(fake)[-1]
        assert request.endswith(f"<slide>\n{previous}\n</slide>")
        sent = findings_of(request)
        assert {f["rule"] for f in sent} == rules
        assert any(f["cls"] == "figure text" and f["measured"] == 2.4 for f in sent)
        assert card(env).phase == model.DONE and slide_file(env).editor.text() == body

    assert len(requests(fake)) == 3 and "0 errors, 0 warnings (was 1 error)" in state(env)
    assert "Run again" not in shown_buttons(env)
    env.window.assistant.tasks.undo()
    assert slide_file(env).editor.text() == partial and card(env) is None


def test_undo_after_an_overflow_puts_the_slide_back(fake, measure):  # noqa: F811
    env = fake.env
    know(env, *BEFORE)
    measure.answers = [report_of(finding("body", "error", 3.0, 0, "overlap", "% of the smaller line"))]
    propose(fake)
    wait_until(phase_is(env, model.OVERFLOW))
    assert slide_file(env).editor.text() == BIGGER
    assert env.window.assistant.tasks.undo() == ""
    assert slide_file(env).editor.text() == LF and card(env) is None


def test_a_proposal_that_does_not_compile_says_so_in_review_and_can_still_be_applied(fake, measure):  # noqa: F811
    env = fake.env
    env.window.assistant.chat.session.set_mode(EDIT_ASK)
    know(env, *BEFORE)
    measure.answers = [RuntimeError("! Undefined control sequence.\nl.9 \\foo")]
    propose(fake)
    wait_until(phase_is(env, model.REVIEW))
    assert "The proposal does not compile: Undefined control sequence on line 9." in state(env)
    assert shown_buttons(env)[0] == "Apply"
    env.window.assistant.tasks.apply()
    wait_until(phase_is(env, model.DONE))
    assert slide_file(env).editor.text() == BIGGER and "does not compile" in state(env)


def test_when_it_cannot_fit_the_note_says_so_and_nothing_is_written(fake, measure):  # noqa: F811
    env = fake.env
    know(env, *BEFORE)
    propose(fake, LF, note="Move the second list onto a new slide.")
    assert "Move the second list onto a new slide." in settled(env)
    assert slide_file(env).editor.text() == LF and measure.texts == []


def test_a_stopped_run_during_the_measurement_ends_the_card_stopped(fake, monkeypatch):  # noqa: F811
    env = fake.env
    know(env, *BEFORE)

    def stopping(*args, **kwargs):
        env.window.assistant.tasks.stop()
        raise RuntimeError("Preview canceled")

    monkeypatch.setattr(tasks_module.readability_check, "check_slide", stopping)
    propose(fake)
    wait_until(phase_is(env, model.STOPPED))
    assert slide_file(env).editor.text() == LF


@pytest.mark.parametrize("repaired", [False, True], ids=["refused", "repaired"])
def test_a_protected_edit_gets_one_repair_and_is_never_applied(fake, measure, monkeypatch, repaired):
    from fake_routes import FakeProvider

    invalid = LF.replace("1-0-0", "2-0-0")

    class ScriptedProvider(FakeProvider):
        def chat(self, messages, **kwargs):
            body = invalid
            if self.requests:
                body = BIGGER if repaired else LF.replace("{Hello}", "{Hello")
            self.reply = json.dumps({"body": body})
            return super().chat(messages, **kwargs)

    env = fake.env
    know(env, *BEFORE)
    provider = ScriptedProvider()
    fake.routes.cloud.runner = None
    monkeypatch.setattr(fake.routes.cloud, "provider", lambda *_args: provider)
    click(env, "Make readable")
    wait_until(phase_is(env, model.DONE if repaired else model.FAILED))
    assert len(provider.requests) == 2
    assert "protected part" in provider.requests[1][0][0]["content"]
    assert slide_file(env).editor.text() == (BIGGER if repaired else LF)
    if not repaired:
        assert "answer was refused" in state(env)
        assert measure.texts == [] and not env.window.assistant.tasks.busy


def test_make_readable_is_a_task_every_route_can_run_and_one_of_the_fixes():
    assert tasks_module.KINDS[ai_tasks.READABLE.name] == ai_profile.FIXES
    assert ai_tasks.READABLE in tasks_module.PROVIDER_TASKS and ai_tasks.READABLE in tasks_module.CARD_TASKS
    assert ai_tasks.READABLE not in tasks_module.DECK_TASKS


def test_the_panel_offers_make_readable_per_slide_and_marks_what_the_template_sets(qapp):
    panel = ReadabilityPanel()
    report = readability.Report([
        readability.SlideReport("abc", 1, FILE, [*BEFORE, TEMPLATE]), readability.SlideReport("abd", 1, "abd-EN-Second-current.tex", [TEMPLATE]),
        readability.SlideReport("abe", 1, "", [finding()])])
    panel.show_report("Readability", report, {})
    clicked = []
    panel.make_readable_clicked.connect(clicked.append)
    makers = [b for b in panel.findChildren(Button) if b.text() == "Make readable"]
    maker, = makers  # Only the slide with a file and fixable findings gets an action.
    maker.click()
    assert clicked == [report.slides[0]]
    texts = [label.text() for label in panel.findChildren(QLabel)]
    assert any("set by the template" in text for text in texts)
    assert TEMPLATE_HINT in texts and texts.count("Enlarge it.") == 4


def test_the_palette_command_checks_first_when_nothing_is_known_and_runs_the_task_when_it_is(fake, measure, monkeypatch):  # noqa: F811
    env = fake.env
    command = env.window.commands["slide:readable"]
    assert command.label == "Make this slide readable" and command.enabled(env.window)
    checked = []
    monkeypatch.setattr(env.window.assistant.readability, "check_slide", lambda: checked.append(True))
    command.run(env.window)
    assert checked == [True] and card(env) is None                                    # no findings known: the check comes first
    know(env, *BEFORE)
    fake.reply({"answer": {"body": BIGGER}})
    command.run(env.window)
    assert card(env).task is ai_tasks.READABLE
    settled(env)
    assert slide_file(env).editor.text() == BIGGER
