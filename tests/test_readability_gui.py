# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Readability commands and findings in the window, using synthetic PDFs."""
from __future__ import annotations

import types

import pytest
from conftest import build_window, make_project, wait_until
from PySide6.QtWidgets import QApplication
import time
from PySide6.QtWidgets import QLabel
from test_readability import footer, pdf_of, record_for, slide, title, body

from slidemage import preview_target
from slidemage.compile_status import DONE, FAILED
from slidemage.deck_scan import scan_decks
from slidemage.project import ProjectContext
from slidemage.ui.kit.widgets import Button, ClickFrame
from slidemage.ui.workspace import assistant_header, compile_actions
from slidemage.ui.workspace.palette import command_entries

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
    e.window, e.root, e.path = window, root, root / SLIDE
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
    end = time.monotonic() + 0.05
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.005)
    return [row.itemAt(i).widget().text() for i in range(row.count()) if row.itemAt(i).widget().isVisibleTo(env.area.header)]


def no_slide_in_view(env, monkeypatch) -> None:
    monkeypatch.setattr(type(env.window.centre), "path", property(lambda _self: None))


def deck_pdf(env, *draws):
    deck = next(d for d in scan_decks(env.window.project) if d.name == "test")
    pdf = pdf_of(env.root, *draws, name="test.pdf")
    record_for(env.window.project, deck, pdf, [deck.path, env.path])
    return pdf


def test_the_slide_command_checks_a_draft_and_check_again_uses_the_edited_buffer(env):
    open_slide(env)
    before = env.path.read_bytes()
    env.pdfs = [slide(pct=2.8), slide(pct=4.0)]
    env.window.state.set_view("during-course")
    assert env.window.commands.run("slide:readability", env.window)
    assert env.area._stack.currentWidget() is env.area._readability_page
    finished(env)
    assert env.panel.report.slides[0].findings
    texts = labels(env.panel)
    assert "Body text · 2.8 % of slide height, needs ≥ 3.3 · 3 lines" in texts
    assert "An ordinary line of body text" in texts

    env.window.centre.source.current.editor.insertPlainText("% edited\n")
    env.panel.again.click()
    assert env.panel.report is None
    finished(env)
    assert len(env.renders) == 2
    bare_id, text, view, language, _ = env.renders[-1]
    assert (bare_id, view, language) == ("abc", "during-course", "EN")
    assert "% edited\n" in text and text == env.window.centre.slide_text(env.path)
    assert env.path.read_bytes() == before
    assert env.panel.report.slides[0].findings == []
    assert "Nothing to report" in env.panel.summary.text() and env.panel.summary.property("tone") == "ok"


def test_deck_findings_are_grouped_and_clicking_one_focuses_its_slide(env):
    deck_pdf(env, lambda page: (footer(page, "abc"), title(page), body(page, 2.8)),
             lambda page: (footer(page, "abd"), title(page), body(page, 3.4)))
    env.window.commands.run("deck:readability", env.window)
    finished(env)
    assert "2 slides checked · 1 with errors · 1 with warnings" in env.panel.summary.text()
    assert labels(env.panel).index("abc · Hello") < labels(env.panel).index("abd · Second")
    assert [label.accessibleName() for label in env.panel.findChildren(QLabel)
            if label.accessibleName() in ("Error", "Warning")] == ["Error", "Warning"]
    assert not env.window.compile.running
    _, second = [row for row in env.panel.findChildren(ClickFrame) if row.toolTip().startswith("Show slide")]
    second.clicked.emit()
    wait_until(lambda: env.window.state.focused_slide == "abd")
    next(b for b in env.panel.findChildren(Button) if b.text() == "Show slide").click()
    wait_until(lambda: env.window.state.focused_slide == "abc")


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


def test_a_stale_deck_pdf_is_not_compiled_silently_and_compile_first_checks_it_afterwards(env, monkeypatch):
    compiles = []

    def compile_current(window, kind, pages=None):
        compiles.append(kind)
        deck_pdf(env, lambda page: (footer(page, "abc"), title(page), body(page, 2.8)))

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


def test_check_again_rereads_the_deck_pdf_and_declining_recompile_keeps_the_stale_notice(env, monkeypatch):
    monkeypatch.setattr(compile_actions, "compile_current", lambda *a, **k: None)  # User declines.
    deck_pdf(env, slide(pct=4.0))
    env.window.commands.run("deck:readability", env.window)
    finished(env)
    assert not env.panel.report.findings

    deck_pdf(env, slide(pct=2.8))
    env.panel.again.click()
    finished(env)
    assert env.panel.report.findings

    env.path.write_bytes(env.path.read_bytes() + b"% edited\r\n")
    env.panel.again.click()
    finished(env)
    assert "abc-EN-Hello-current.tex changed since it was compiled" in env.panel.summary.text()
    env.panel.compile_button.click()
    assert "Compiling" not in env.panel.summary.text() and env.panel.compile_button is not None


def test_the_header_checks_the_selected_scope_when_no_task_is_shown(env, monkeypatch):
    header = env.area.header
    env.window.state.set_deck(None)
    env.window.state.set_deck(next(d for d in scan_decks(env.window.project) if d.name == "test"))
    header.refresh_content()
    env.area.scope.set_current("deck")
    header.refresh_content()
    assert "Check deck readability" in shown_buttons(env) and header.check_shown == "deck"
    env.area.scope.set_current("slide")
    open_slide(env)
    header.refresh_content()
    assert "Check readability" in shown_buttons(env) and header.check_shown == "slide"
    button = next(b for b in header.findChildren(Button) if b.text() == "Check readability")
    button.click()
    wait_until(lambda: env.area.readability.active)
    assert env.area._stack.currentWidget() is env.area._readability_page
    finished(env)
    env.panel.close_button.click()

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


    no_slide_in_view(env, monkeypatch)
    header.refresh_content()
    assert "Check readability" not in shown_buttons(env)
    assert header.can_check("deck") and not header.can_check("slide")
    env.window.state.set_deck(None)
    assert not header.can_check("deck")
    assert not env.window.commands["deck:readability"].enabled(env.window)
