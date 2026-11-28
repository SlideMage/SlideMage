# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendered comparisons opened from the workspace, task cards and chat diffs."""
from __future__ import annotations

import threading
from pathlib import Path

import pytest
from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel
from slidemage.ui.kit.widgets import Button
from test_tasks_gui import pump, wait_until
from test_tasks_gui import BROKEN, FIX, LF, break_slide, click, ctx, fake, slide_file  # noqa: F401 -- fixtures
from test_task_card_gui import area, asked, card, phase_is, press  # noqa: F401 -- a fixture

from slidemage import ai_review, preview_requests
from slidemage.ui.workspace import compare_rendered, task_card_model as model
from slidemage.ui.workspace.compare_rendered import CompareRendered


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
                    raise RuntimeError("Preview canceled")
        if plan.get("error"):
            raise RuntimeError(plan["error"])
        return Path(f"/render/{self.index}.pdf"), b"", (), b""


class FakeRenders:
    def __init__(self) -> None:
        self.requests, self.plans, self.closed = [], {}, False

    def plan(self, text: str, pages: int = 1, error: str = "", hold: bool = False) -> None:
        self.plans[text] = dict(pages=pages, error=error, hold=hold)

    def request(self, target, text, view, language, log, **kwargs):
        request = FakeRequest(self, len(self.requests), text)
        request.spec = preview_requests.PreviewRequest(target, preview_requests.SourceRevision.capture(target.source_path, text), view, language)
        self.requests.append((request, target, text, view, language, kwargs))
        return request

    def read_pages(self, pdf: Path, **kwargs) -> dict:
        request = self.requests[int(pdf.stem)][0]
        return dict(images=[png("#c04040" if request.index % 2 == 0 else "#40a040", 320 + n)
                            for n in range(self.plans.get(request.text, {}).get("pages", 1))])

    def close(self) -> None:
        self.closed = True

    def request_of(self, text: str) -> FakeRequest:
        return next(entry[0] for entry in self.requests if entry[2] == text)

    def dialogs(self, window):
        return [dialog for dialog in window.findChildren(CompareRendered) if not dialog.closed]


@pytest.fixture
def env(fake):  # noqa: F811
    return fake.env


@pytest.fixture
def renders(env, monkeypatch):
    service = FakeRenders()
    monkeypatch.setattr(env.window.centre.preview, "_renders", service)
    monkeypatch.setattr(compare_rendered.preview_pages, "read_document", service.read_pages)
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


def test_draft_comparison_uses_workspace_view_and_navigates_unequal_page_counts(env, renders):  # noqa: F811
    renders.plan("old text", pages=3)
    renders.plan("new text", pages=2)
    env.window.state.set_view("during-course")
    before = env.path.read_bytes()
    dialog = compare_rendered.open_compare(env.window, env.path, "old text", "new text")
    assert [(text, view, lang) for _, _, text, view, lang, _ in renders.requests] == [
        ("old text", "during-course", "EN"), ("new text", "during-course", "EN")]
    assert all(target.source_path == env.path and not options for _, target, _, _, _, options in renders.requests)
    assert not dialog.isModal()
    settle(dialog)
    assert env.path.read_bytes() == before
    assert all(side.view.pixmap is not None for side in dialog._sides)
    assert dialog.page() == 2 and chips(dialog) == ["Page 2 of 3", "Page 2 of 2"]       # the last page both have
    # Window shortcuts require an active window, including on the offscreen platform.
    dialog.activateWindow()
    pump()
    QTest.keyClick(dialog, Qt.Key.Key_Right)
    assert dialog.page() == 3 and chips(dialog) == ["Page 3 of 3", "No page 3"]
    assert messages(dialog)[1] == "After has only 2 pages." and dialog._sides[1].view.pixmap is None
    assert not dialog._next.isEnabled()
    dialog._previous.click()
    QTest.keyClick(dialog, Qt.Key.Key_Left)
    assert dialog.page() == 1 and chips(dialog) == ["Page 1 of 3", "Page 1 of 2"] and not dialog._previous.isEnabled()
    close(dialog)


def test_a_side_that_fails_says_why_while_the_other_is_shown(env, renders):  # noqa: F811
    renders.plan("new text", error="Render failed.\n! Undefined control sequence.\nl.9 \\Oops")
    dialog = compare_rendered.open_compare(env.window, env.path, "old text", "new text")
    settle(dialog)
    assert chips(dialog) == ["Page 1 of 1", "Not rendered"]
    assert messages(dialog)[1] == "After could not be rendered: Undefined control sequence on line 9"
    assert dialog._sides[0].view.pixmap is not None
    assert dialog._sides[1].view.accessibleDescription() == messages(dialog)[1]
    assert dialog.page() == 1 and not dialog._next.isEnabled()
    close(dialog)


def test_text_diff_shows_the_source_diff_and_the_arrows_only_move_pages(env, renders):  # noqa: F811
    renders.plan("old text", pages=3)
    dialog = compare_rendered.open_compare(env.window, env.path, "old text\n", "new text\n")
    settle(dialog)
    dialog.diff_button.click()
    assert dialog._stack.currentIndex() == 1
    assert dialog.diff.title == env.path.name
    assert any("new text" in label.text() for label in dialog.diff.findChildren(QLabel))
    QTest.keyClick(dialog, Qt.Key.Key_Left)
    assert dialog.page() == 1                                                           # unchanged: it was page 1 of 3
    dialog.diff_button.click()
    assert dialog._stack.currentIndex() == 0
    close(dialog)


def test_closing_cancels_the_pending_renders(env, renders):  # noqa: F811
    renders.plan("old text", hold=True)
    renders.plan("new text", hold=True)
    dialog = compare_rendered.open_compare(env.window, env.path, "old text", "new text")
    pump(0.1)
    assert chips(dialog) == ["Rendering…", "Rendering…"] and not renders.closed
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    assert dialog.closed and not renders.closed and dialog._cancel.is_set()
    wait_until(lambda: all(entry[0].cancelled for entry in renders.requests))
    assert all(not side.worker.isRunning() or side.worker.wait(2000) for side in dialog._sides)


def test_a_slow_side_does_not_hold_the_other(env, renders):  # noqa: F811
    renders.plan("new text", hold=True)
    dialog = compare_rendered.open_compare(env.window, env.path, "old text", "new text")
    wait_until(lambda: not dialog._sides[0].busy)
    assert chips(dialog) == ["Page 1 of 1", "Rendering…"] and dialog._sides[0].view.pixmap is not None
    renders.request_of("new text").release.set()
    settle(dialog)
    assert chips(dialog) == ["Page 1 of 1", "Page 1 of 1"]
    close(dialog)


def test_only_a_slide_file_with_a_change_opens(env, renders):  # noqa: F811
    assert compare_rendered.open_compare(env.window, env.root / "SlideMage.bib", "a", "b") is None
    assert compare_rendered.open_compare(env.window, env.root / "decks" / "test.tex", "a", "b") is None
    assert compare_rendered.open_compare(env.window, env.path, "same", "same") is None
    assert renders.requests == []
    with pytest.raises(ValueError):
        CompareRendered(env.window, env.root / "SlideMage.bib", "a", "b")


def test_slide_diff_card_offers_compare_in_each_state(env, renders):
    chat = env.window.assistant.chat
    after = LF.replace("First point", "1st point")
    card_ = chat._new_diff("edit", env.path, LF, after)
    assert not card_.compare_button.isHidden()
    card_.ask()
    assert not card_.compare_button.isHidden()
    card_.applied(True, True, False)
    card_.compare_button.click()
    (dialog,) = renders.dialogs(env.window)
    assert dialog.texts == {"Before": LF, "After": after}
    close(dialog)


def test_new_file_and_bib_diff_cards_have_no_compare(env):
    chat = env.window.assistant.chat
    new = chat._new_diff("new", env.root / "notes.txt", "", "x")
    bib = chat._new_diff("bib", env.root / "SlideMage.bib", "old", "new")
    assert new.compare_button.isHidden() and bib.compare_button.isHidden()


def test_a_recorded_ai_edit_can_be_compared_from_details_and_palette(env, renders):
    window = env.window
    window.state.set_mode("details")
    window.state.set_focused_slide("abc")
    pump(0.1)
    assert not window.commands["slide:compare"].visible(window)
    after = LF.replace("First point", "AI change")
    ai_review.mark(window.project, env.path, "edit", "fake route", before=LF, text=after)
    window.centre.edit_slide_text(env.path, lambda _text: after)
    window.refresh_ai_review()
    wait_until(lambda: window.commands["slide:compare"].visible(window))
    button = next(b for b in window.centre.details.findChildren(Button) if b.text() == "Compare rendered")
    button.click()
    (dialog,) = renders.dialogs(window)
    assert dialog.texts["Before"] == LF and "AI change" in dialog.texts["After"]
    close(dialog)
    assert window.commands.run("slide:compare", window)
    (dialog,) = renders.dialogs(window)
    assert dialog.texts["Before"] == LF and "AI change" in dialog.texts["After"]
    close(dialog)
    ai_review.mark_reviewed(window.project, [env.path])
    window.refresh_ai_review()
    assert window.commands["slide:compare"].visible(window)
    window.state.set_focused_slide("abd")
    pump(0.1)
    assert not window.commands["slide:compare"].visible(window)


def test_the_command_says_so_when_the_slide_is_as_it_was(env, renders):  # noqa: F811
    window, shown = env.window, []
    window.toast.show_message = shown.append
    kept = LF.replace("First", "Old")
    ai_review.mark(window.project, env.path, "edit", "terminal", before=kept)
    window.centre.edit_slide_text(env.path, lambda _text: kept)               # the slide is back to the kept text
    compare_rendered.compare_with_last_edit(window, env.path)
    assert shown == ["Nothing to compare: the slide is as it was before the last AI edit."] and not renders.requests


def test_the_task_card_compares_in_review_and_done(asked, renders):  # noqa: F811
    env = asked.env
    break_slide(env)
    asked.reply({"answer": FIX})
    click(env, "Fix LaTeX errors")
    wait_until(phase_is(env, model.REVIEW))
    press(env, "Compare rendered")
    (dialog,) = renders.dialogs(env.window)
    assert dialog.texts == {"Before": BROKEN, "After": card(env).after} and "\\end{itemize}" in dialog.texts["After"]
    close(dialog)
    press(env, "Apply")
    wait_until(phase_is(env, model.DONE))
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
    press(env, "Compare rendered")
    (dialog,) = renders.dialogs(env.window)
    assert dialog.texts == {"Before": typed, "After": card(env).after}
    close(dialog)
