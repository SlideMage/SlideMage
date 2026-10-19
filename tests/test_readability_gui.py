# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The readability check in the window: the findings panel in the assistant (grouping, severity, a click that focuses the slide,
Check again, Back), the two commands, the header's Check readability button, and the deck flow (a stale PDF is never compiled
silently; Compile the deck first starts the normal compile and the check runs when it is over). The slide is rendered by a
stand-in for the LaTeX render that writes a synthetic PDF (test_readability.py builds them); the throwaway project is a
temporary one."""
from __future__ import annotations

import types

import pytest
from conftest import build_window, make_project, wait_until
from test_claude_code_gui import pump
from PySide6.QtWidgets import QLabel
from test_readability import footer, pdf_of, record_for, slide, title, body

from slidemage import preview_raster_client, preview_target, readability
from slidemage.compile_status import DONE, FAILED
from slidemage.deck_scan import scan_decks
from slidemage.project import ProjectContext
from slidemage.ui.kit.widgets import Button, ClickFrame
from slidemage.ui.workspace import assistant_header, compile_actions
from slidemage.ui.workspace.palette import command_entries
from slidemage.ui.workspace.readability_panel import ReadabilityPanel

SLIDE = "slides/abc-EN-Hello-current.tex"


class Env:
    pass


@pytest.fixture
def env(qapp, tmp_path, monkeypatch):
    root = make_project(monkeypatch, tmp_path / "project")
    context = ProjectContext.at(root)
    window = build_window(monkeypatch, context)
    window.show()
    window.state.set_mode("source")             # no Preview render thread to outlive the test
    window.state.set_deck(next(d for d in scan_decks(window.project) if d.name == "test"))
    window.state.set_focused_slide("abc")
    e = Env()
    e.window, e.root, e.tmp, e.path = window, root, tmp_path, root / SLIDE
    e.area, e.panel = window.assistant, window.assistant.readability_panel
    e.renders = []
    e.pdfs = [slide(pct=2.8)]                   # what the next renders draw (the last one repeats)

    def render_text(target, text, view, language, **kwargs):
        e.renders.append((target.bare_id, text, view, language, kwargs))
        return pdf_of(tmp_path, e.pdfs[min(len(e.renders), len(e.pdfs)) - 1], name=f"render-{len(e.renders)}.pdf")

    monkeypatch.setattr(preview_target, "render_text", render_text)
    yield e
    window.assistant.shutdown()


def open_slide(env) -> None:
    env.window.open_slide_editor(env.path)


def finished(env):
    wait_until(lambda: env.panel.report is not None or "could not run" in env.panel.summary.text()
               or "out of date" in env.panel.summary.text())


def labels(panel) -> list[str]:
    return [label.text() for label in panel.findChildren(QLabel)]


def shown_buttons(env) -> list[str]:
    row = env.area.header._actions
    pump(0.05)
    return [row.itemAt(i).widget().text() for i in range(row.count()) if row.itemAt(i).widget().isVisibleTo(env.area.header)]


def no_slide_in_view(env, monkeypatch) -> None:
    monkeypatch.setattr(type(env.window.centre), "path", property(lambda _self: None))


def deck_pdf(env, *draws, inputs=None):
    """A compiled deck PDF of the project's deck with a compile record that vouches for it."""
    deck = next(d for d in scan_decks(env.window.project) if d.name == "test")
    pdf = pdf_of(env.root, *draws, name="test.pdf")
    record_for(env.window.project, deck, pdf, inputs or [deck.path, env.root / "slides" / "abc-EN-Hello-current.tex"])
    return pdf


# -- this slide ---------------------------------------------------------------------------------------------------

def test_the_slide_command_checks_a_draft_of_the_slide_in_view_and_shows_the_findings_in_the_assistant(env):
    open_slide(env)
    before = env.path.read_bytes()
    env.window.state.set_view("during-course")
    command = env.window.commands["slide:readability"]
    assert command.title(env.window) == "Check readability of this slide" and command.enabled(env.window)
    assert env.window.commands.run("slide:readability", env.window)
    assert env.area._stack.currentWidget() is env.area._readability_page
    assert env.panel.title.text() == "Readability · abc · Hello" and "Typesetting the slide as a draft" in env.panel.summary.text()
    finished(env)
    (bare_id, text, view, language, kwargs), = env.renders
    assert (bare_id, view, language, kwargs["capture_snapshot"]) == ("abc", "during-course", "EN", False)
    assert text == env.window.centre.slide_text(env.path)                         # a draft of the Source view's text
    assert env.panel.summary.text() == "1 slide checked · 1 with errors · 0 with warnings."
    texts = labels(env.panel)
    assert "abc · Hello" in texts
    assert "Body text · 2.8 % of slide height, needs ≥ 3.3 · 3 lines" in texts
    assert any(t.startswith("Body text 2.8 % of slide height (≈ 15 pt projected) is below the floor of 3.3 %") for t in texts)
    assert "An ordinary line of body text" in texts
    assert env.path.read_bytes() == before                                         # nothing was written


def test_a_clean_slide_says_there_is_nothing_to_report(env):
    open_slide(env)
    env.pdfs = [slide(pct=4.0)]
    env.window.commands.run("slide:readability", env.window)
    finished(env)
    assert env.panel.summary.text() == "1 slide checked · 0 with errors · 0 with warnings. Nothing to report: every slide passes."
    assert env.panel.summary.property("tone") == "ok"


def test_clicking_a_finding_focuses_that_slide_in_the_centre(env):
    deck_pdf(env, lambda page: (footer(page, "abc"), title(page), body(page, 2.8)),
             lambda page: (footer(page, "abd"), title(page), body(page, 2.8)))
    env.window.state.set_focused_slide("abc")
    env.window.commands.run("deck:readability", env.window)
    finished(env)
    rows = [row for row in env.panel.findChildren(ClickFrame) if row.toolTip().startswith("Show slide")]
    assert [row.toolTip() for row in rows] == ["Show slide abc", "Show slide abd"]
    rows[1].clicked.emit()
    wait_until(lambda: env.window.state.focused_slide == "abd")
    show = [b for b in env.panel.findChildren(Button) if b.text() == "Show slide"]
    show[0].click()
    wait_until(lambda: env.window.state.focused_slide == "abc")


def test_check_again_renders_the_slide_again_and_reports_the_new_state(env):
    open_slide(env)
    env.pdfs = [slide(pct=2.8), slide(pct=4.0)]
    env.window.commands.run("slide:readability", env.window)
    finished(env)
    assert env.panel.report.slides[0].findings
    env.panel.again.click()
    assert "Typesetting" in env.panel.summary.text() and env.panel.report is None
    finished(env)
    assert len(env.renders) == 2 and env.panel.report.slides[0].findings == []


def test_a_slide_that_does_not_compile_says_so_and_close_goes_back_to_the_conversation(env, monkeypatch):
    open_slide(env)

    def broken(*args, **kwargs):
        raise RuntimeError("Render failed\n! Undefined control sequence.")

    monkeypatch.setattr(preview_target, "render_text", broken)
    env.window.commands.run("slide:readability", env.window)
    finished(env)
    assert "The check could not run: Render failed" in env.panel.summary.text()
    assert env.panel.summary.property("tone") == "error" and env.panel.again is not None
    env.panel.close_button.click()
    assert env.area._stack.currentWidget() is env.area.chat and not env.area.readability.active
    env.window.commands.run("slide:readability", env.window)
    env.panel.back.click()                                       # (the render is dropped, whatever it was doing)
    assert env.area._stack.currentWidget() is env.area.chat
    wait_until(lambda: env.area.readability._worker is None)


def test_the_slide_command_needs_a_slide_in_view(env, monkeypatch):
    command = env.window.commands["slide:readability"]
    open_slide(env)
    assert command.enabled(env.window)
    assert "Check readability of this slide" in {e.label for e in command_entries(env.window, [])}
    no_slide_in_view(env, monkeypatch)
    assert not command.enabled(env.window)
    env.area.check_readability("slide")
    assert env.renders == [] and not env.area.readability.active


# -- this deck ------------------------------------------------------------------------------------------------------

def test_the_deck_command_groups_the_findings_by_slide_with_a_summary(env):
    deck_pdf(env, lambda page: (footer(page, "abc"), title(page), body(page, 2.8)),
             lambda page: (footer(page, "abd"), title(page), body(page, 4.0)),
             lambda page: (footer(page, "abd"), title(page), body(page, 3.4, text="Near the floor")))
    command = env.window.commands["deck:readability"]
    assert command.title(env.window) == "Check readability of this deck" and command.enabled(env.window)
    env.window.commands.run("deck:readability", env.window)
    assert env.panel.title.text() == "Readability · test · Instructor · EN"
    finished(env)
    assert env.panel.summary.text() == "2 slides checked · 1 with errors · 1 with warnings."
    texts = labels(env.panel)
    assert texts.index("abc · Hello") < texts.index("abd · Second")                     # slides in the deck's order
    assert "Body text · 2.8 % of slide height, needs ≥ 3.3 · 3 lines" in texts
    assert "Body text · 3.4 % of slide height, needs ≥ 3.3 · 3 lines" in texts          # the last page of abd is judged
    assert [f.severity for f in env.panel.report.slides[1].findings] == ["warning"]
    icons = [b.accessibleName() for b in env.panel.findChildren(QLabel) if b.accessibleName() in ("Error", "Warning")]
    assert icons == ["Error", "Warning"]
    assert not env.window.compile.running                                      # the check did not touch the compile slot


def test_a_stale_deck_pdf_is_not_compiled_silently_and_compile_first_checks_it_afterwards(env, monkeypatch):
    compiles = []

    def compile_current(window, kind, pages=None):
        compiles.append(kind)
        env.compiled_pdf = deck_pdf(env, lambda page: (footer(page, "abc"), title(page), body(page, 2.8)))

    monkeypatch.setattr(compile_actions, "compile_current", compile_current)
    monkeypatch.setattr(type(env.window.compile), "running", property(lambda _self: bool(compiles)))
    env.window.commands.run("deck:readability", env.window)
    finished(env)
    assert compiles == [] and "test has not been compiled yet" in env.panel.summary.text()
    assert env.panel.summary.property("tone") == "warning" and env.panel.compile_button.text() == "Compile the deck first"
    env.panel.compile_button.click()
    assert compiles == ["instructor"] and "Compiling the deck" in env.panel.summary.text()
    # an unrelated run ending does not start it; the run it started does
    env.area.readability._compile_settled(types.SimpleNamespace(rows={"other": types.SimpleNamespace(state=DONE)}))
    assert env.panel.report is None
    env.area.readability._compile_settled(types.SimpleNamespace(rows={"test": types.SimpleNamespace(state=DONE)}))
    finished(env)
    assert env.panel.summary.text() == "1 slide checked · 1 with errors · 0 with warnings."


def test_a_compile_that_fails_ends_the_wait_with_a_message(env, monkeypatch):
    monkeypatch.setattr(compile_actions, "compile_current", lambda *a, **k: None)
    monkeypatch.setattr(type(env.window.compile), "running", property(lambda _self: True))
    env.window.commands.run("deck:readability", env.window)
    finished(env)
    env.panel.compile_button.click()
    env.area.readability._compile_settled(types.SimpleNamespace(rows={"test": types.SimpleNamespace(state=FAILED)}))
    assert env.panel.summary.text() == "The compile did not finish, so the deck was not checked."
    assert env.panel.again is not None


def test_declining_the_compile_leaves_the_message_and_changing_a_slide_makes_the_pdf_stale(env, monkeypatch):
    monkeypatch.setattr(compile_actions, "compile_current", lambda *a, **k: None)      # the user said no to a question
    deck_pdf(env, slide(pct=4.0))
    env.window.commands.run("deck:readability", env.window)
    finished(env)
    assert env.panel.report is not None
    (env.root / SLIDE).write_bytes((env.root / SLIDE).read_bytes() + b"% edited\r\n")
    env.panel.again.click()
    finished(env)
    assert "abc-EN-Hello-current.tex changed since it was compiled" in env.panel.summary.text()
    env.panel.compile_button.click()
    assert "Compiling" not in env.panel.summary.text() and env.panel.compile_button is not None


def test_check_again_reads_the_deck_pdf_again(env, monkeypatch):
    deck_pdf(env, lambda page: (footer(page, "abc"), title(page), body(page, 2.8)))
    reads = []
    real = preview_raster_client.read_layout
    monkeypatch.setattr(preview_raster_client, "read_layout", lambda path: reads.append(path) or real(path))
    env.window.commands.run("deck:readability", env.window)
    finished(env)
    env.panel.again.click()
    finished(env)
    assert len(reads) == 2


# -- the header's button -----------------------------------------------------------------------------------------

def test_the_header_offers_check_readability_for_the_scope_when_no_task_is_on_show(env, monkeypatch):
    header = env.area.header
    env.window.state.set_deck(None)
    env.window.state.set_deck(next(d for d in scan_decks(env.window.project) if d.name == "test"))
    header.refresh_content()
    env.area.scope.set_current("deck")
    header.refresh_content()
    assert shown_buttons(env)[-2:] == ["Check deck readability", "All actions…"] and header.check_shown == "deck"
    env.area.scope.set_current("slide")
    open_slide(env)
    header.refresh_content()
    assert shown_buttons(env)[-2:] == ["Check readability", "All actions…"] and header.check_shown == "slide"
    button = next(b for b in header.findChildren(Button) if b.text() == "Check readability")
    button.click()
    wait_until(lambda: env.area.readability.active)
    assert env.area._stack.currentWidget() is env.area._readability_page
    finished(env)
    env.panel.close_button.click()


def test_a_task_keeps_the_row_to_itself_and_the_check_works_without_any_task(env, monkeypatch):
    header = env.area.header
    open_slide(env)
    bubbles = [types.SimpleNamespace(label="One")]
    monkeypatch.setattr(assistant_header, "contextual", lambda found, tasks, limit=2: bubbles)
    header.schedule()
    header.refresh_content()
    assert header.check_shown == "" and "Check readability" not in shown_buttons(env)
    monkeypatch.setattr(assistant_header, "contextual", lambda found, tasks, limit=2: [])
    monkeypatch.setattr(header, "_blocked", lambda: True)             # Claude Code needs setup: no task can run
    header.schedule()
    header.refresh_content()
    assert header.check_shown == "slide" and "Check readability" in shown_buttons(env)


def test_no_check_button_without_a_slide_or_a_deck(env, monkeypatch):
    header = env.area.header
    no_slide_in_view(env, monkeypatch)
    header.refresh_content()
    assert "Check readability" not in shown_buttons(env)                       # no slide in the Source view yet
    assert header.can_check("deck") and not header.can_check("slide")
    env.window.state.set_deck(None)
    assert not header.can_check("deck")
    assert not env.window.commands["deck:readability"].enabled(env.window)


# -- the panel -----------------------------------------------------------------------------------------------------

def test_the_panel_shows_each_finding_with_its_severity_class_values_excerpt_and_suggestion(qapp):
    panel = ReadabilityPanel()
    findings = [
        readability.Finding("abc", 2, "text_size", "body", "error", 2.8, 3.3, "min", "% of slide height",
                            (0.1, 0.2, 0.5, 0.4), "A line", "Make it bigger.", count=4),
        readability.Finding("abc", 2, "image_size", "image", "warning", 12.0, 25.0, "min", "% of the slide area",
                            (0.5, 0.2, 0.9, 0.7), "", "Enlarge it.", image="chart.png", pixels=(160, 90))]
    report = readability.Report([readability.SlideReport("abc", 2, "abc-EN-Hello-current.tex", findings),
                                 readability.SlideReport("abd", 1, "", [])])
    panel.show_report("Readability · test", report, {"abc": "Hello"})
    texts = labels(panel)
    assert texts[:2] == ["Readability · test", "2 slides checked · 1 with errors · 0 with warnings."]
    assert "abc · Hello" in texts and "abd" not in " ".join(t for t in texts if t.startswith("abd"))
    assert "Body text · 2.8 % of slide height, needs ≥ 3.3 · 4 lines" in texts
    assert "Image · 12 % of the slide area, needs ≥ 25" in texts and "chart.png" in texts and "A line" in texts
    assert "Make it bigger." in texts and "Enlarge it." in texts
    clicked = []
    panel.slide_clicked.connect(clicked.append)
    next(b for b in panel.findChildren(Button) if b.text() == "Show slide").click()
    assert clicked == [report.slides[0]]
    panel.show_stale("Readability · test", "slide.tex changed since it was compiled")
    assert panel.report is None and panel.compile_button is not None and panel.again is None
    panel.show_error("Readability · test", "boom")
    assert panel.compile_button is None and panel.again is not None
