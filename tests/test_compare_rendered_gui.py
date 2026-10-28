# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compare rendered (ui/workspace/compare_rendered.py): the dialog with a stand-in for the render service (no LaTeX, no
MuPDF) and the places that open it: the task card (Review, Conflict, Done), the chat's diff cards, the palette command
and the Details view for the text before a Claude Code edit. The projects are throwaway ones."""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest
from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel
from test_chat_gui import EDIT, ask, env as chat_env, pump, script, wait_for_card, wait_until, widgets  # noqa: F401 -- a fixture
from test_claude_code_gui import env as claude_env  # noqa: F401 -- a fixture
from test_tasks_gui import BROKEN, FIX, LF, break_slide, click, ctx, fake, slide_file  # noqa: F401 -- fixtures
from test_task_card_gui import area, asked, card, phase_is, press, shown_buttons  # noqa: F401 -- a fixture
from agent_fakes import call, reply

from slidemage import ai_review
from slidemage.ai import claude_hook
from slidemage.ai.agent_types import EDIT_AUTO
from slidemage.ui.kit.widgets import Button
from slidemage.ui.workspace.chat.cards import DiffCard
from slidemage.ui.workspace import compare_rendered, task_card_model as model
from slidemage.ui.workspace.compare_rendered import CompareRendered

pytest.importorskip("PySide6.QtWebEngineWidgets")
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the stand-in for claude is a POSIX script")


def png(color: str, width: int = 320) -> bytes:
    image = QImage(width, width * 9 // 16, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


class FakeRequest:
    def __init__(self, service, index: int, text: str) -> None:
        self.service, self.index, self.text = service, index, text
        self.release, self.cancelled = threading.Event(), False

    def wait(self, cancel=None, timeout=5):
        plan = self.service.plans.get(self.text, {})
        if plan.get("hold"):
            while not self.release.wait(0.01):
                if cancel is not None and cancel.is_set():
                    self.cancelled = True
                    raise RuntimeError("Preview cancelled")
        if plan.get("error"):
            raise RuntimeError(plan["error"])
        return Path(f"/render/{self.index}.pdf"), b"", (), b""


class FakeRenders:
    """A RenderService: it keeps every request and answers it as the test planned for that text."""

    def __init__(self) -> None:
        self.requests, self.plans, self.closed = [], {}, False

    def plan(self, text: str, pages: int = 1, error: str = "", hold: bool = False) -> None:
        self.plans[text] = dict(pages=pages, error=error, hold=hold)

    def request(self, target, text, view, language, log, **kwargs):
        request = FakeRequest(self, len(self.requests), text)
        self.requests.append((request, target, text, view, language, kwargs))
        return request

    def read_pages(self, pdf: Path, project_root: Path) -> list[bytes]:
        request = self.requests[int(pdf.stem)][0]
        return [png("#c04040" if request.index % 2 == 0 else "#40a040", 320 + n)
                for n in range(self.plans.get(request.text, {}).get("pages", 1))]

    def close(self) -> None:
        self.closed = True

    def request_of(self, text: str) -> FakeRequest:
        return next(entry[0] for entry in self.requests if entry[2] == text)

    def dialogs(self, window):
        return [dialog for dialog in window.findChildren(CompareRendered) if not dialog.closed]


@pytest.fixture
def renders(monkeypatch):
    service = FakeRenders()
    monkeypatch.setattr(compare_rendered, "RenderService", lambda: service)
    monkeypatch.setattr(compare_rendered, "read_pages", service.read_pages)
    return service


def settle(dialog) -> None:
    wait_until(lambda: not any(side.busy for side in dialog._sides))


def chips(dialog) -> list[str]:
    return [side.chip.text() for side in dialog._sides]


def messages(dialog) -> list[str]:
    return [side.view.message for side in dialog._sides]


def close(dialog) -> None:
    dialog.reject()
    pump()


# -- the dialog ----------------------------------------------------------------------------------------------

def test_both_sides_render_as_drafts_for_the_view_and_language_of_the_top_bar(chat_env, renders):  # noqa: F811
    env = chat_env
    env.window.state.set_view("during-course")
    before = env.path.read_bytes()
    dialog = compare_rendered.open_compare(env.window, env.path, "old text", "new text")
    (first, second) = renders.requests
    for (request, target, text, view, language, kwargs), expected in zip((first, second), ("old text", "new text")):
        assert text == expected and kwargs == {'require_pdf': True}  # a draft, with its own view's PDF
        assert (view, language) == ("during-course", "EN") and target.source_path == env.path
    assert dialog.windowTitle() == "Compare rendered · abc · During · EN" and not dialog.isModal()
    assert chips(dialog) == ["Rendering…", "Rendering…"] and messages(dialog) == ["Rendering…", "Rendering…"]
    settle(dialog)
    assert chips(dialog) == ["Page 1 of 1", "Page 1 of 1"] and all(side.view.pixmap is not None for side in dialog._sides)
    assert dialog._sides[0].view.accessibleName() == "Before, rendered slide"
    assert dialog._sides[1].view.accessibleName() == "After, rendered slide"
    assert [s.view.size() for s in dialog._sides[:1]] == [dialog._sides[1].view.size()]      # equal size
    assert env.path.read_bytes() == before                                                     # nothing was written
    close(dialog)


def test_the_arrow_keys_and_buttons_move_both_sides_and_the_shorter_one_has_no_page(chat_env, renders):  # noqa: F811
    env = chat_env
    renders.plan("old text", pages=3)
    renders.plan("new text", pages=2)
    dialog = compare_rendered.open_compare(env.window, env.path, "old text", "new text")
    settle(dialog)
    assert dialog.page() == 2 and chips(dialog) == ["Page 2 of 3", "Page 2 of 2"]       # the last page both have
    assert dialog._position.text() == "Page 2 of 3" and dialog._previous.isEnabled() and dialog._next.isEnabled()
    # Window shortcuts require an active window, including on the offscreen platform.
    dialog.activateWindow()
    pump()
    QTest.keyClick(dialog, Qt.Key.Key_Right)
    assert dialog.page() == 3 and chips(dialog) == ["Page 3 of 3", "No page 3"]
    assert messages(dialog)[1] == "After has only 2 pages." and dialog._sides[1].view.pixmap is None
    assert not dialog._next.isEnabled()
    QTest.keyClick(dialog, Qt.Key.Key_Right)                                              # stays on the last page
    assert dialog.page() == 3
    dialog._previous.click()
    QTest.keyClick(dialog, Qt.Key.Key_Left)
    assert dialog.page() == 1 and chips(dialog) == ["Page 1 of 3", "Page 1 of 2"] and not dialog._previous.isEnabled()
    QTest.keyClick(dialog, Qt.Key.Key_Left)
    assert dialog.page() == 1
    close(dialog)


def test_a_side_that_fails_says_why_while_the_other_is_shown(chat_env, renders):  # noqa: F811
    env = chat_env
    renders.plan("new text", error="Render failed.\n! Undefined control sequence.\nl.9 \\Oops")
    dialog = compare_rendered.open_compare(env.window, env.path, "old text", "new text")
    settle(dialog)
    assert chips(dialog) == ["Page 1 of 1", "Not rendered"]
    assert messages(dialog)[1] == "After could not be rendered: Undefined control sequence on line 9"
    assert dialog._sides[0].view.pixmap is not None
    assert dialog._sides[1].view.accessibleDescription() == messages(dialog)[1]
    assert dialog.page() == 1 and not dialog._next.isEnabled()
    close(dialog)
    renders.plan("old", error="boom")
    dialog = compare_rendered.open_compare(env.window, env.path, "old", "new")
    settle(dialog)
    assert chips(dialog) == ["Not rendered", "Page 1 of 1"] and messages(dialog)[0] == "Before could not be rendered: boom"
    close(dialog)


def test_text_diff_shows_the_source_diff_and_the_arrows_only_move_pages(chat_env, renders):  # noqa: F811
    env = chat_env
    renders.plan("old text", pages=3)
    dialog = compare_rendered.open_compare(env.window, env.path, "old text\n", "new text\n")
    settle(dialog)
    dialog.diff_button.click()
    assert dialog._stack.currentIndex() == 1 and dialog.diff_button.text() == "Rendered pages"
    assert dialog.diff.title == env.path.name
    assert any("new text" in label.text() for label in dialog.diff.findChildren(QLabel))
    QTest.keyClick(dialog, Qt.Key.Key_Left)
    assert dialog.page() == 1                                                           # unchanged: it was page 1 of 3
    dialog.diff_button.click()
    assert dialog._stack.currentIndex() == 0 and dialog.diff_button.text() == "Text diff"
    close(dialog)


def test_closing_cancels_the_pending_renders(chat_env, renders):  # noqa: F811
    env = chat_env
    renders.plan("old text", hold=True)
    renders.plan("new text", hold=True)
    dialog = compare_rendered.open_compare(env.window, env.path, "old text", "new text")
    pump(0.1)
    assert chips(dialog) == ["Rendering…", "Rendering…"] and not renders.closed
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    assert dialog.closed and renders.closed and dialog._cancel.is_set()
    wait_until(lambda: all(entry[0].cancelled for entry in renders.requests))
    assert all(not side.worker.isRunning() or side.worker.wait(2000) for side in dialog._sides)


def test_a_slow_side_does_not_hold_the_other(chat_env, renders):  # noqa: F811
    env = chat_env
    renders.plan("new text", hold=True)
    dialog = compare_rendered.open_compare(env.window, env.path, "old text", "new text")
    wait_until(lambda: not dialog._sides[0].busy)
    assert chips(dialog) == ["Page 1 of 1", "Rendering…"] and dialog._sides[0].view.pixmap is not None
    renders.request_of("new text").release.set()
    settle(dialog)
    assert chips(dialog) == ["Page 1 of 1", "Page 1 of 1"]
    close(dialog)


def test_only_a_slide_file_with_a_change_opens(chat_env, renders):  # noqa: F811
    env = chat_env
    assert compare_rendered.open_compare(env.window, env.root / "Slidemaster.bib", "a", "b") is None
    assert compare_rendered.open_compare(env.window, env.root / "decks" / "test.tex", "a", "b") is None
    assert compare_rendered.open_compare(env.window, env.path, "same", "same") is None
    assert renders.requests == []
    with pytest.raises(ValueError):
        CompareRendered(env.window, env.root / "Slidemaster.bib", "a", "b")


@pytest.mark.parametrize("dark", [False, True], ids=["light", "dark"])
def test_the_dialog_in_both_themes(chat_env, renders, dark, tmp_path):  # noqa: F811
    env = chat_env
    env.window.theme.set_dark(dark)
    env.window.theme.apply()
    renders.plan("old text", pages=2)
    renders.plan("new text", pages=2)
    dialog = compare_rendered.open_compare(env.window, env.path, "old text", "new text")
    settle(dialog)
    pump(0.1)
    shot = tmp_path / f"compare-{'dark' if dark else 'light'}.png"
    assert dialog.grab().save(str(shot)) and shot.stat().st_size > 1000
    close(dialog)


# -- the chat's diff cards -----------------------------------------------------------------------------------

def test_a_diff_card_of_a_slide_offers_compare_rendered_in_every_state(chat_env, renders):  # noqa: F811
    env = chat_env
    script(env, reply("", call("edit_file", **EDIT)), reply("Done."))
    env.chat.send("Edit it")
    card_ = wait_for_card(env, "asking")
    assert not card_.compare_button.isHidden()
    after = LF.replace("First point", "1st point")
    card_.compare_button.click()
    (dialog,) = renders.dialogs(env.window)
    assert dialog.texts == {"Before": LF, "After": after} and renders.requests[0][1].source_path == env.path
    close(dialog)
    card_.apply_button.click()
    wait_until(lambda: not env.chat.session.running)
    pump()
    assert card_.state == "applied" and not card_.compare_button.isHidden()
    card_.compare_button.click()
    (dialog,) = renders.dialogs(env.window)
    assert dialog.texts["After"] == after
    close(dialog)


def test_a_diff_card_of_a_new_file_or_a_bib_has_no_compare_rendered(chat_env, renders):  # noqa: F811
    env = chat_env
    env.chat._set_mode(EDIT_AUTO)
    script(env, reply("", call("write_file", path="notes.txt", content="x"),
                      call("edit_file", path="Slidemaster.bib", old_text="Older", new_text="Oldest")), reply("Done."))
    ask(env)
    cards = widgets(env, DiffCard)
    assert len(cards) == 2 and all(c.state == "applied" and c.compare_button.isHidden() for c in cards)


def test_a_chat_edit_keeps_the_text_before_for_the_palette_command(chat_env, renders):  # noqa: F811
    env = chat_env
    env.chat._set_mode(EDIT_AUTO)
    commands, window = env.window.commands, env.window
    assert not commands["slide:compare"].visible(window)
    script(env, reply("", call("edit_file", **EDIT)), reply("Done."))
    ask(env)
    assert commands["slide:compare"].visible(window) and commands["slide:compare"].enabled(window)
    assert commands["slide:compare"].title(window) == "Compare rendered with last AI edit"
    assert commands.run("slide:compare", window)
    (dialog,) = renders.dialogs(window)
    assert dialog.texts["Before"] == LF and dialog.texts["After"] == window.centre.slide_text(env.path)
    assert "1st point" in dialog.texts["After"]
    close(dialog)


# -- Claude Code's edits -------------------------------------------------------------------------------------

def terminal_edit(env, old: str, new: str) -> None:
    event = dict(cwd=str(env.root), tool_name="Edit", tool_use_id=f"t-{new}", hook_event_name="PreToolUse",
                 tool_input={"file_path": "slides/abc-EN-Hello-current.tex"})
    claude_hook.record_write(env.window.project, event)
    env.path.write_bytes(env.path.read_bytes().replace(old.encode(), new.encode()))
    claude_hook.record_write(env.window.project, {**event, "hook_event_name": "PostToolUse"})
    env.window.centre.sync_source(env.path)                                   # the file watcher's job
    env.window.refresh_ai_review()


def test_a_claude_code_edit_can_be_compared_from_the_details_and_the_palette(chat_env, renders):  # noqa: F811
    env = chat_env
    window = env.window
    window.state.set_mode("details")
    window.state.set_focused_slide("abc")
    pump(0.1)
    assert not window.commands["slide:compare"].visible(window)
    assert "Compare rendered" not in [b.text() for b in window.centre.details.findChildren(Button)]
    terminal_edit(env, "First point", "Native change")
    wait_until(lambda: ai_review.is_unreviewed(window.project, env.path))
    pump(0.1)
    assert window.commands["slide:compare"].visible(window)
    button = next(b for b in window.centre.details.findChildren(Button) if b.text() == "Compare rendered")
    button.click()
    (dialog,) = renders.dialogs(window)
    assert dialog.texts["Before"] == LF and "Native change" in dialog.texts["After"]
    assert dialog.target.source_path == env.path
    close(dialog)
    ai_review.mark_reviewed(window.project, [env.path])                      # kept after the review
    window.refresh_ai_review()
    assert window.commands["slide:compare"].visible(window)
    window.state.set_focused_slide("abd")                                     # another slide has no earlier text
    pump(0.1)
    assert not window.commands["slide:compare"].visible(window)


def test_the_command_says_so_when_the_slide_is_as_it_was(chat_env, renders):  # noqa: F811
    env = chat_env
    window, shown = env.window, []
    window.toast.show_message = shown.append
    kept = LF.replace("First", "Old")
    ai_review.mark(window.project, env.path, "edit", "terminal", before=kept)
    window.centre.edit_slide_text(env.path, lambda _text: kept)               # the slide is back to the kept text
    compare_rendered.compare_with_last_edit(window, env.path)
    assert shown == ["Nothing to compare: the slide is as it was before the last AI edit."] and not renders.requests


# -- the task card -------------------------------------------------------------------------------------------

def test_the_task_card_compares_in_review_and_done(asked, renders):  # noqa: F811
    env = asked.env
    break_slide(env)
    asked.reply({"answer": FIX})
    click(env, "Fix LaTeX errors")
    wait_until(phase_is(env, model.REVIEW))
    assert shown_buttons(env) == ["Apply", "Reject", "View full diff", "Compare rendered"]
    press(env, "Compare rendered")
    (dialog,) = renders.dialogs(env.window)
    assert dialog.texts == {"Before": BROKEN, "After": card(env).after} and "\\end{itemize}" in dialog.texts["After"]
    assert dialog.target.source_path == env.path and (dialog.view, dialog.language) == ("instructor", "EN")
    assert len(renders.requests) == 2 and all(entry[6] == {'require_pdf': True} for entry in renders.requests)
    close(dialog)
    press(env, "Apply")
    wait_until(phase_is(env, model.DONE))
    assert shown_buttons(env) == ["View change", "Undo", "Compare rendered", "Close"]
    press(env, "Compare rendered")
    dialog = renders.dialogs(env.window)[0]
    assert dialog.texts == {"Before": BROKEN, "After": LF}                      # the text before the apply, and after
    close(dialog)


def test_the_task_card_in_conflict_compares_the_proposal_with_the_current_text(asked, renders):  # noqa: F811
    env = asked.env
    break_slide(env)
    asked.reply({"answer": FIX, "delay": 0.4})
    click(env, "Fix LaTeX errors")
    typed = BROKEN + "% typed meanwhile\n"
    slide_file(env).editor.replace_all_text(typed)
    wait_until(phase_is(env, model.CONFLICT))
    assert shown_buttons(env) == ["Compare with current", "Compare rendered", "Run again", "Dismiss"]
    press(env, "Compare rendered")
    (dialog,) = renders.dialogs(env.window)
    assert dialog.texts == {"Before": typed, "After": card(env).after}
    close(dialog)


def test_a_card_without_an_earlier_text_offers_no_comparison():
    plain = model.TaskCard(task=None, title="t", route=None)
    assert not plain.can_compare
    plain.before, plain.after = "a", "b"
    assert plain.can_compare
    plain.nothing = True
    assert not plain.can_compare
    plain.nothing, plain.before = False, ""                                   # a new slide
    assert not plain.can_compare
    plain.before = plain.after = "same"
    assert not plain.can_compare
