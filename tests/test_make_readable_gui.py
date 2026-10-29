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


from slidemage import readability, slide_versioning
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
    """The readability measurement of a proposal: answers the queued reports (an exception is raised), notes the texts."""

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
    """The slide has been checked: these were the findings for `text`."""
    env.window.readability_known.remember_slide(env.path, text, report_of(*findings))
    env.window.assistant.header.schedule()
    wait_until(lambda: ("Make readable" in buttons(env)) == any(f.severity == "error" and not f.template_level for f in findings))


def asked_fake(fake):  # noqa: F811
    fake.env.window.assistant.chat.session.set_mode(EDIT_ASK)
    return fake


def requests(made) -> list[str]:
    return [call["request"] for call in made.calls()]


def findings_of(request: str) -> list[dict]:
    return json.loads(request.split("Findings (JSON):\n")[1].split("\n<slide>")[0])["findings"]


# -- the header's button -----------------------------------------------------------------------------------------------

def test_the_header_offers_make_readable_for_a_slide_with_known_errors_until_its_text_changes(fake):  # noqa: F811
    env = fake.env
    wait_until(lambda: buttons(env) == ["Translate to German", "Better title"])
    know(env, finding("image", "warning", 20.0, 25.0, "image_size"))                  # a warning is no reason
    know(env, TEMPLATE)                                                               # nor is what the template sets
    know(env, *BEFORE)
    assert buttons(env)[:3] == ["Translate to German", "Make readable", "Better title"]
    assert [b.label for b in env.window.assistant.header.shown] == ["Translate to German", "Make readable"]
    slide_file(env).editor.replace_all_text(LF + "% edited\n")                         # the text is no longer the measured one
    wait_until(lambda: "Make readable" not in buttons(env))
    slide_file(env).editor.replace_all_text(LF)
    wait_until(lambda: "Make readable" in buttons(env))                                # the same text, the same findings


def test_the_header_runs_no_check_to_decide_its_button(fake, monkeypatch):  # noqa: F811
    env = fake.env
    measured = []
    monkeypatch.setattr(tasks_module.readability_check, "check_slide", lambda *a, **k: measured.append(a))
    wait_until(lambda: buttons(env) == ["Translate to German", "Better title"])
    env.window.assistant.header.schedule()
    pump(0.2)
    assert measured == [] and "Make readable" not in buttons(env)


# -- the card: Generate, Review, Apply, Check preview ---------------------------------------------------------------

def test_review_says_what_the_change_does_to_the_findings_and_done_what_is_left(fake, measure):  # noqa: F811
    env = asked_fake(fake).env
    know(env, *BEFORE, TEMPLATE)
    measure.answers = [report_of(finding("image", "warning", 24.0, 25.0, "image_size", "% of the slide area"), TEMPLATE)]
    fake.reply({"answer": {"body": BIGGER, "note": "The table could move to a second slide."}})
    click(env, "Make readable")
    assert card(env).route.route == fake.routes.cloud.id
    wait_until(phase_is(env, model.REVIEW))
    assert state(env) == ("Proposed change to abc-EN-Hello-current.tex. Nothing is written yet. After the change: 0 errors, "
                          "1 warning (was 2 errors, 1 warning). Note: The table could move to a second slide.")
    assert shown_buttons(env) == ["Apply", "Reject", "View full diff", "Compare rendered"]
    request, = requests(fake)                                                        # what the model was sent
    assert request.startswith("Make this slide readable.\nThe typeset page is 272 pt high.") and request.endswith(f"<slide>\n{LF}\n</slide>")
    assert [(f["cls"], f["severity"]) for f in findings_of(request)] == [("body", "error"), ("figure text", "error"), ("image", "warning")]
    assert measure.texts == [BIGGER] and slide_file(env).editor.text() == LF         # measured as a draft, nothing written
    assert card(env).readable.before == tuple(BEFORE)
    area = env.window.assistant
    assert area.tasks.compare_texts() == (env.path, LF, BIGGER)                      # Compare rendered, from S3

    area.tasks.apply()
    wait_until(phase_is(env, model.DONE))
    assert slide_file(env).editor.text() == BIGGER and len(fake.renders) == 1       # written, then rendered as always
    assert measure.texts == [BIGGER]                                                 # the proposal's numbers are the written text's
    assert state(env) == ("Changed 1 line in abc-EN-Hello-current.tex. The preview is current. After the change: 0 errors, "
                          "1 warning (was 2 errors, 1 warning). Now readable: Body text, Text in a figure. Still close to the "
                          "limit: image (24 % of the slide area, needs ≥ 25). Note: The table could move to a second slide.")
    assert shown_buttons(env) == ["View change", "Undo", "Run again", "Compare rendered", "Close"]


def test_run_again_sends_the_findings_that_remain_and_a_clean_result_ends_it(fake, measure):  # noqa: F811
    env = fake.env                                                                   # Edit automatically is on
    know(env, *BEFORE)
    left = finding("figure text", "error", 2.4, 2.6)
    measure.answers = [report_of(left)]
    fake.reply({"answer": {"body": BIGGER}})
    click(env, "Make readable")
    assert settled(env).startswith("Applied automatically (Edit automatically is on). Changed 1 line")
    assert "After the change: 1 error, 0 warnings (was 2 errors, 1 warning). Now readable: Body text, Image." in state(env)
    assert "Still below the floor: text in a figure (2.4 % of slide height, needs ≥ 2.6)." in state(env)
    assert "Run again" in shown_buttons(env)
    assert env.window.assistant.tasks.card.readable.after == (left,)

    again = BIGGER.replace("\\small", "\\normalsize", 1)
    measure.answers = [report_of()]
    fake.reply({"answer": {"body": again}})
    env.window.assistant.task_card._handlers["again"]()
    assert settled(env).startswith("Applied automatically")
    first, second = requests(fake)
    assert [f["cls"] for f in findings_of(second)] == ["figure text"] and findings_of(second)[0]["measured"] == 2.4
    assert second.endswith(f"<slide>\n{BIGGER}\n</slide>")                           # the slide as the first run left it
    assert "After the change: 0 errors, 0 warnings (was 1 error)." in state(env) and "Run again" not in shown_buttons(env)
    assert slide_file(env).editor.text() == again


def test_text_cut_off_after_the_change_counts_as_failed_and_offers_undo_and_run_again(fake, measure):  # noqa: F811
    env = fake.env
    know(env, *BEFORE)
    clipped = finding("body", "error", 6.0, 0, "clipped", "pt beyond the page")
    measure.answers = [report_of(clipped, finding("body", "warning", 3.4, 3.3))]
    fake.reply({"answer": {"body": BIGGER}})
    click(env, "Make readable")
    wait_until(phase_is(env, model.OVERFLOW))
    assert state(env) == ("Changes applied to abc-EN-Hello-current.tex. After the change text is still cut off or overlapping: "
                                 "the slide does not fit. Now readable: Text in a figure, Image. Still below the floor: body text (6 pt beyond the page); body text (3.4 % of slide height, "
                                 "needs ≥ 3.3). Undo it, or run again to fix what remains.")
    assert shown_buttons(env) == ["Undo", "Run again", "Compare rendered", "Close"] and card(env).running is False
    assert [s.icon for s in model.steps(card(env))][-1] == "error"
    measure.answers = [report_of(finding("body", "warning", 3.4, 3.3))]
    fake.reply({"answer": {"body": LF.replace("\\begin{itemize}", "\\begin{itemize}\\normalsize", 1)}})
    env.window.assistant.task_card._handlers["again"]()
    wait_until(lambda: len(requests(fake)) == 2)
    assert {f["rule"] for f in findings_of(requests(fake)[1])} == {"clipped", "text_size"}      # what remained, not the first findings
    settled(env)
    assert card(env).phase == model.DONE

    env.window.assistant.tasks.undo()
    assert slide_file(env).editor.text() == BIGGER and card(env) is None            # back to the first run's result


def test_undo_after_an_overflow_puts_the_slide_back(fake, measure):  # noqa: F811
    env = fake.env
    know(env, *BEFORE)
    measure.answers = [report_of(finding("body", "error", 3.0, 0, "overlap", "% of the smaller line"))]
    fake.reply({"answer": {"body": BIGGER}})
    click(env, "Make readable")
    wait_until(phase_is(env, model.OVERFLOW))
    assert slide_file(env).editor.text() == BIGGER
    assert env.window.assistant.tasks.undo() == ""
    assert slide_file(env).editor.text() == LF and card(env) is None


def test_a_proposal_that_does_not_compile_says_so_in_review_and_can_still_be_applied(fake, measure):  # noqa: F811
    env = asked_fake(fake).env
    know(env, *BEFORE)
    measure.answers = [RuntimeError("! Undefined control sequence.\nl.9 \\foo")]
    fake.reply({"answer": {"body": BIGGER}})
    click(env, "Make readable")
    wait_until(phase_is(env, model.REVIEW))
    assert state(env) == ("Proposed change to abc-EN-Hello-current.tex. Nothing is written yet. The proposal does not compile: "
                          "Undefined control sequence on line 9.")
    assert shown_buttons(env)[0] == "Apply"
    env.window.assistant.tasks.apply()
    wait_until(phase_is(env, model.DONE))
    assert slide_file(env).editor.text() == BIGGER and "does not compile" in state(env)


def test_when_it_cannot_fit_the_note_says_so_and_nothing_is_written(fake, measure):  # noqa: F811
    env = fake.env
    know(env, *BEFORE)
    fake.reply({"answer": {"body": LF, "note": "Too much for one slide: move the second list onto a new slide."}})
    click(env, "Make readable")
    assert settled(env) == ("Nothing to change in abc. Nothing was written. Note: Too much for one slide: move the second list "
                            "onto a new slide.")
    assert slide_file(env).editor.text() == LF and measure.texts == []


def test_a_refused_answer_gets_one_repair_round(fake, measure, monkeypatch):
    from fake_routes import FakeProvider
    from slidemage.ai.providers import ChatReply

    env = fake.env
    know(env, *BEFORE)

    class ScriptedProvider(FakeProvider):
        def chat(self, messages, **kwargs):
            self.requests.append((messages, kwargs))
            answer = (LF.replace("1-0-0", "2-0-0") if len(self.requests) == 1 else BIGGER)
            return ChatReply(json.dumps({"body": answer}))

    provider = ScriptedProvider()
    fake.routes.cloud.runner = None
    monkeypatch.setattr(fake.routes.cloud, "provider", lambda *_args: provider)
    click(env, "Make readable")
    assert settled(env).startswith("Applied automatically")
    assert len(provider.requests) == 2 and "protected part" in provider.requests[1][0][0]["content"]
    assert slide_file(env).editor.text() == BIGGER


def test_a_stopped_run_during_the_measurement_ends_the_card_stopped(fake, monkeypatch):  # noqa: F811
    env = fake.env
    know(env, *BEFORE)

    def stopping(*args, **kwargs):
        env.window.assistant.tasks.stop()
        raise RuntimeError("Preview cancelled")

    monkeypatch.setattr(tasks_module.readability_check, "check_slide", stopping)
    fake.reply({"answer": {"body": BIGGER}})
    click(env, "Make readable")
    wait_until(phase_is(env, model.STOPPED))
    assert slide_file(env).editor.text() == LF


# -- the routes -----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("mode, side", [(ai_profile.LOCAL, "local"), (ai_profile.CLOUD, "cloud")])
def test_make_readable_runs_on_the_selected_route(ctx, fake, measure, mode, side):
    env = asked_fake(fake).env
    route = getattr(fake.routes, side)
    ai_profile.set_mode(ctx, mode)
    ai_profile.set_model_choice(ctx, route.id, ai_profile.FIXES, "fake-2")
    know(env, *BEFORE)
    fake.reply({"answer": {"body": BIGGER, "note": "Split it."}})
    click(env, "Make readable")
    wait_until(phase_is(env, model.REVIEW))
    assert (card(env).route.route, card(env).route.model) == (route.id, "fake-2")
    assert fake.runner.calls[-1][0] is ai_tasks.READABLE
    assert "Note: Split it." in state(env) and measure.texts == [BIGGER]
    env.window.assistant.tasks.apply()
    wait_until(phase_is(env, model.DONE))
    assert slide_versioning.strip_marker(slide_file(env).editor.text()) == slide_versioning.strip_marker(BIGGER)


def test_invalid_provider_answer_is_refused_without_changing_the_slide(fake, measure, monkeypatch):
    from fake_routes import FakeProvider

    env = fake.env
    know(env, *BEFORE)
    fake.routes.cloud.runner = None
    provider = FakeProvider(reply=json.dumps({"body": LF.replace("{Hello}", "{Hello")}))
    monkeypatch.setattr(fake.routes.cloud, "provider", lambda *_args: provider)
    click(env, "Make readable")
    wait_until(phase_is(env, model.FAILED))
    assert "answer was refused" in state(env) and len(provider.requests) == 2
    assert slide_file(env).editor.text() == LF and not env.window.assistant.tasks.busy


def test_unavailable_route_starts_no_readability_task(fake, measure):
    env = fake.env
    know(env, *BEFORE)
    fake.routes.cloud.problem_text = "Fake cloud unavailable."
    click(env, "Make readable")
    assert card(env).phase == model.SETUP and card(env).note == "Fake cloud unavailable."
    assert fake.calls() == [] and measure.texts == [] and not env.window.assistant.tasks.busy


def test_make_readable_is_a_task_every_route_can_run_and_one_of_the_fixes():
    assert tasks_module.KINDS[ai_tasks.READABLE.name] == ai_profile.FIXES
    assert ai_tasks.READABLE in tasks_module.PROVIDER_TASKS and ai_tasks.READABLE in tasks_module.CARD_TASKS
    assert ai_tasks.READABLE not in tasks_module.DECK_TASKS


# -- the findings panel, the palette ----------------------------------------------------------------------------------------

def test_the_panel_offers_make_readable_per_slide_and_marks_what_the_template_sets(qapp):
    panel = ReadabilityPanel()
    report = readability.Report([
        readability.SlideReport("abc", 1, FILE, [*BEFORE, TEMPLATE]), readability.SlideReport("abd", 1, "abd-EN-Second-current.tex", [TEMPLATE]),
        readability.SlideReport("abe", 1, "", [finding()])])
    panel.show_report("Readability", report, {})
    clicked = []
    panel.make_readable_clicked.connect(clicked.append)
    makers = [b for b in panel.findChildren(Button) if b.text() == "Make readable"]
    assert [b.accessibleName() for b in makers] == ["Make slide abc readable"]        # not abd (the template's), not abe (no file)
    makers[0].click()
    assert clicked == [report.slides[0]]
    texts = [label.text() for label in panel.findChildren(QLabel)]
    assert "Source or footnote text · 1.25 % of slide height, needs ≥ 2.2 · set by the template" in texts
    assert TEMPLATE_HINT in texts and texts.count("Enlarge it.") == 4                # the template's rows have the hint instead


def test_the_panels_button_runs_the_task_on_that_slide_and_a_changed_slide_is_checked_again_first(fake, measure):  # noqa: F811
    env = fake.env
    know(env, *BEFORE)
    area = env.window.assistant
    slide = report_of(*BEFORE).slides[0]
    slide_file(env).editor.replace_all_text(LF + "% edited\n")
    toasts = []
    env.window.toast.show_message = toasts.append
    area.readability_panel.make_readable_clicked.emit(slide)
    assert toasts == ["The slide changed since it was checked: check it again."] and card(env) is None
    slide_file(env).editor.replace_all_text(LF)
    fake.reply({"answer": {"body": BIGGER}})
    area.readability_panel.make_readable_clicked.emit(slide)
    assert card(env).task is ai_tasks.READABLE and card(env).title == "Make readable"
    settled(env)
    assert slide_file(env).editor.text() == BIGGER


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


def test_a_check_in_the_panel_remembers_the_slide_for_the_header_button(fake, monkeypatch):  # noqa: F811
    env = fake.env
    known = env.window.readability_known
    monkeypatch.setattr(tasks_module.readability_check, "check_slide", Measure(report_of()))
    check = env.window.assistant.readability
    monkeypatch.setattr("slidemage.ui.workspace.readability_panel.readability_check.check_slide",
                        lambda *a, **k: report_of(*BEFORE, TEMPLATE))
    check.check_slide()
    wait_until(lambda: check.panel.report is not None)
    assert known.has_errors(env.path, LF) and known.fixable(env.path, LF) == list(BEFORE)
    wait_until(lambda: "Make readable" in buttons(env))
