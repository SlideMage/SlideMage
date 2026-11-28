# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Selection tasks through the source view, commands, menus and task card on scripted routes."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid
from selection_make_readable_image_batches_helpers import (LF, card, phase_is, settled, shown_buttons,
                                                        slide_file, state, wait_until)
from selection_make_readable_image_batches_helpers import ctx as ctx, fake as fake

from slidemage import selection
from slidemage.latex_edit import utf16_len
from slidemage.ai import ai_profile, tasks as ai_tasks
from slidemage.ai.agent_types import EDIT_ASK
from slidemage.ai.tools import ToolContext, ToolError, focus
from slidemage.ui.kit.widgets import Button, PopoverMenu
from slidemage.ui.workspace import task_card_model as model
from slidemage.ui.workspace.insert_popovers import InstructionPopover


OPENING = LF.replace("First point", "Opening remark")
SHOWN = ["Rewrite selection", "Proofread selection"]


def select(env, piece: str) -> None:
    env.window.state.set_mode("source")
    editor = source(env).current.editor
    text = editor.text()
    start = utf16_len(text[:text.index(piece)])
    cursor = editor.textCursor()
    cursor.setPosition(start)
    cursor.setPosition(start + utf16_len(piece), QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    env.window.assistant.header.schedule()


def source(env):
    return env.window.centre.source


def asked(fake):  # noqa: F811
    fake.env.window.assistant.chat.session.set_mode(EDIT_ASK)
    return fake.env


@pytest.fixture
def selected(fake):  # noqa: F811
    select(fake.env, "First point")
    return fake


def requests(made) -> list[str]:
    return [call["request"] for call in made.calls()]


def popups(kind):
    return [w for w in QApplication.topLevelWidgets() if isinstance(w, kind) and w.isVisible()]


def test_source_captures_selection_offsets_after_a_non_bmp_character(fake):  # noqa: F811
    env = fake.env
    env.window.state.set_mode("details")
    with pytest.raises(selection.SelectionError, match="Open a slide"):
        source(env).selection()
    text = LF.replace("First point", "𝔄 First point")
    slide_file(env).editor.replace_all_text(text)
    select(env, "First point")
    chosen = source(env).selection()
    assert (chosen.path, chosen.selected, chosen.text) == (env.path, "First point", text)
    assert text[chosen.start:chosen.end] == chosen.selected


def test_selection_refuses_protected_ranges_frozen_versions_and_deck_files(fake):  # noqa: F811
    env = fake.env
    for piece in ("\\setSlideVersion{1-0-0}", "Included in decks: test\n%%\n\n% A note on this slide\n\\setSlideVersion"):
        select(env, piece)
        with pytest.raises(selection.SelectionError, match="protected part"):
            source(env).selection()
    for path, piece, reason in (
        ("slides/abc-EN-Hello-v1-0-0.tex", "First point", "frozen version"),
        ("decks/test.tex", "Intro", "Open a slide"),
    ):
        env.window.centre.open_file(env.root / path)
        select(env, piece)
        with pytest.raises(selection.SelectionError, match=reason):
            source(env).selection()


def test_the_read_selection_tool_gives_the_selection_from_the_buffer_and_says_why_there_is_none(fake):  # noqa: F811
    env = fake.env
    area = env.window.assistant
    tool = ToolContext(env.window.project, area.workspace, lambda _event: None, None)
    with pytest.raises(ToolError, match="Select some text"):
        focus.read_selection.run(tool, {})
    slide_file(env).editor.replace_all_text(LF.replace("First point", "Edited point"))        # unsaved, so only the buffer has it
    select(env, "Edited point")
    text = focus.read_selection.run(tool, {})
    assert text.startswith("File: slides/abc-EN-Hello-current.tex (the editor's buffer)\nSelected: characters ")
    assert "--- the selection ---\nEdited point\n--- end of the selection ---" in text
    assert "\\item Second point" in text.split("Text after the selection:")[1]
    select(env, "\\setSlideVersion{1-0-0}")
    with pytest.raises(ToolError, match="protected part"):
        focus.read_selection.run(tool, {})


def test_header_rewrite_menu_starts_the_selected_preset(fake):  # noqa: F811
    env = asked(fake)
    area = env.window.assistant
    header = area.header
    slide_tasks = ["Translate to German", "Better title"]

    def labels():
        return [b.label for b in header.shown]

    select(env, "First point")
    wait_until(lambda: labels() == SHOWN)
    slide_file(env).editor.moveCursor(QTextCursor.MoveOperation.Start)
    wait_until(lambda: labels() == slide_tasks)
    select(env, "First point")
    wait_until(lambda: labels() == SHOWN)
    env.window.state.set_mode("details")
    wait_until(lambda: labels() == slide_tasks)
    select(env, "First point")
    wait_until(lambda: labels() == SHOWN)
    next(b for b in header.findChildren(Button) if b.text() == "Rewrite selection").click()
    menu, = popups(PopoverMenu)
    assert [row.key for row in menu._rows] == ["Simplify", "Shorten", "Custom…"]
    fake.reply({"answer": {"text": "Opening remark"}})
    menu.triggered.emit("Shorten")
    wait_until(phase_is(env, model.REVIEW))
    assert card(env).title == "Rewrite selection · Shorten" and card(env).instruction == ai_tasks.REWRITE_PRESETS["Shorten"]


def test_palette_commands_require_an_editable_selection(fake):  # noqa: F811
    env = fake.env
    commands = env.window.commands
    ids = ["selection:rewrite", "selection:rewrite:Simplify", "selection:rewrite:Shorten",
           "selection:rewrite:Custom…", "selection:proofread"]
    assert commands["selection:rewrite"].shortcut == "Ctrl+Shift+R"
    for piece, enabled in ((None, False), ("First point", True), ("\\setSlideVersion{1-0-0}", False)):
        if piece:
            select(env, piece)
        assert all(commands[i].enabled(env.window) == enabled for i in ids)


def test_the_context_menu_offers_the_edit_commands_and_the_two_tasks_when_the_selection_can_be_worked_on(fake):  # noqa: F811
    env = asked(fake)
    task_keys = ("rewrite:Simplify", "rewrite:Shorten", "rewrite:Custom…", "proofread")
    for piece, enabled in (("\\setSlideVersion{1-0-0}", False), ("First point", True)):
        select(env, piece)
        source(env)._on_context_menu(QPoint(5, 5))
        menu, = popups(PopoverMenu)
        rows = {row.key: row.isEnabled() for row in menu._rows}
        assert rows["copy"] and all(rows[key] == enabled for key in task_keys)
        if not enabled:
            menu.close()
    fake.reply({"answer": {"edits": [{"before": "First", "after": "Opening"}, {"before": "point", "after": "remark"}]}})
    menu.triggered.emit("proofread")
    wait_until(phase_is(env, model.REVIEW))
    assert card(env).task is ai_tasks.PROOFREAD_SELECTION
    assert "Proofread the selection of this English slide" in requests(fake)[0]
    env.window.assistant.tasks.apply()
    wait_until(phase_is(env, model.DONE))
    assert slide_file(env).editor.text() == OPENING
    # Starting the task can already delete the context menu.
    if isValid(menu):
        menu.close()


def test_a_route_that_takes_a_rewrite_as_a_prompt_gets_the_instruction(selected):
    env, filled = asked(selected), []
    area = env.window.assistant
    area.surface_for("fake_cloud").fill_prompt = lambda text: filled.append(text) or True
    selected.routes.cloud.task_prompt = lambda ctx, route, name, slide, language, **kw: (
        "" if slide is None else f"{name} {slide.name}: {kw['instruction']}")
    area.rewrite_selection("Simplify")
    assert filled == ["rewrite abc-EN-Hello-current.tex: " + ai_tasks.REWRITE_PRESETS["Simplify"]]
    assert selected.calls() == [] and area.tasks.card is None


def test_rewrite_on_the_selected_route_is_reviewed_applied_and_undone(ctx, fake):
    env = asked(fake)
    ai_profile.set_mode(ctx, ai_profile.LOCAL)
    ai_profile.set_model_choice(ctx, fake.routes.local.id, ai_profile.FIXES, "fake-2")
    select(env, "First point")
    fake.reply({"answer": {"text": "Opening remark"}})
    env.window.assistant.rewrite_selection("Simplify")
    assert (card(env).route.route, card(env).route.model) == (fake.routes.local.id, "fake-2")
    wait_until(phase_is(env, model.REVIEW))
    request, = requests(fake)
    assert request.startswith("Rewrite the selection of this slide. Instruction: " + ai_tasks.REWRITE_PRESETS["Simplify"])
    assert "<selection>\nFirst point\n</selection>" in request
    assert fake.runner.calls[-1][0] is ai_tasks.REWRITE
    assert env.window.assistant.tasks.compare_texts() == (env.path, LF, OPENING)
    assert slide_file(env).editor.text() == LF

    env.window.assistant.tasks.apply()
    wait_until(phase_is(env, model.DONE))
    assert slide_file(env).editor.text() == OPENING and slide_file(env).dirty
    assert env.path.read_text() == LF and len(fake.renders) == 1
    slide_file(env).editor.undo()
    assert slide_file(env).editor.text() == LF


def test_the_cards_undo_takes_a_rewrite_back_and_edit_automatically_skips_review(selected):
    env = selected.env
    selected.reply({"answer": {"text": "Opening remark"}})
    env.window.assistant.rewrite_selection("Shorten")
    assert settled(env).startswith("Applied automatically (Edit automatically is on). Changed 1 line")
    assert slide_file(env).editor.text() == OPENING
    assert env.window.assistant.tasks.undo() == "" and slide_file(env).editor.text() == LF


@pytest.mark.parametrize("during_review", [False, True], ids=["during-run", "during-review"])
def test_typing_after_capture_keeps_the_proposal_but_does_not_overwrite(selected, during_review):
    env = asked(selected)
    selected.reply({"answer": {"text": "Opening remark"}})
    env.window.assistant.rewrite_selection("Simplify")
    if during_review:
        wait_until(phase_is(env, model.REVIEW))
    point = "Second point" if during_review else "First point"
    typed = LF.replace(point, point + "s")
    slide_file(env).editor.replace_all_text(typed)
    if during_review:
        env.window.assistant.tasks.apply()
    wait_until(phase_is(env, model.CONFLICT))
    assert slide_file(env).editor.text() == typed
    assert card(env).after == OPENING and "Compare rendered" in shown_buttons(env)


def test_custom_asks_for_the_instruction_in_a_popover_and_carries_it_into_the_request(selected):
    env = asked(selected)
    selected.reply({"answer": {"text": "Is this the first point?"}})
    env.window.assistant.rewrite_selection("Custom…")
    popover, = popups(InstructionPopover)
    assert card(env) is None and selected.calls() == []                                    # nothing starts before it is asked
    rewrite = next(b for b in popover.findChildren(Button) if b.text() == "Rewrite")
    rewrite.click()
    assert popover.isVisible() and "Say what" in popover.note.text()                   # an empty instruction is not accepted
    popover.entry.setText("  as a question  ")
    rewrite.click()
    wait_until(phase_is(env, model.REVIEW))
    assert "Instruction: as a question" in requests(selected)[0]
    assert card(env).instruction == "as a question"


def test_a_proofread_with_nothing_to_fix_and_a_refused_answer_end_the_card_without_a_change(selected):
    env = asked(selected)
    selected.reply({"answer": {"edits": []}})
    env.window.assistant.proofread_selection()
    assert settled(env) == "Nothing to change in abc. Nothing was written."
    env.window.assistant.tasks.close_card()
    selected.reply({"answer": {"edits": [{"before": "Second", "after": "2nd"}]}})
    env.window.assistant.proofread_selection()
    wait_until(phase_is(env, model.FAILED))
    assert "answer was refused" in state(env) and slide_file(env).editor.text() == LF


def test_nothing_starts_without_a_selection_to_work_on(fake):  # noqa: F811
    env = fake.env
    toasts = []
    env.window.toast.show_message = toasts.append
    env.window.assistant.rewrite_selection("Simplify")
    env.window.assistant.proofread_selection()
    assert len(toasts) == 2 and card(env) is None and fake.calls() == []
    select(env, "First point")
    tasks = env.window.assistant.tasks
    slide_file(env).editor.moveCursor(QTextCursor.MoveOperation.Start)
    tasks.start(ai_tasks.PROOFREAD_SELECTION)                                      # the selection went before the click
    assert card(env) is None and env.window.assistant.task_row.status.text() == selection.NO_SELECTION


def test_provider_proofreading_is_checked_against_the_selection(ctx, fake, monkeypatch):
    from fake_routes import FakeProvider

    env = asked(fake)
    ai_profile.set_mode(ctx, ai_profile.LOCAL)
    fake.routes.local.runner = None
    provider = FakeProvider(reply='{"edits": [{"before": "Second", "after": "2nd"}]}')
    monkeypatch.setattr(fake.routes.local, "provider", lambda *_args: provider)
    select(env, "First point")
    env.window.assistant.proofread_selection()
    wait_until(phase_is(env, model.FAILED))
    assert len(provider.requests) == 2 and "does not occur" in state(env)
    assert provider.requests[0][1]["system"] == ai_tasks.PROOFREAD_SELECTION.rules
    assert slide_file(env).editor.text() == LF


def test_unavailable_route_starts_no_selection_task(selected):
    env = selected.env
    selected.routes.cloud.problem_text = "Fake cloud unavailable."
    env.window.assistant.rewrite_selection("Simplify")
    assert card(env).phase == model.SETUP and card(env).note == "Fake cloud unavailable."
    env.window.assistant.tasks.close_card()
    env.window.assistant.rewrite_selection("Custom…")
    popover, = popups(InstructionPopover)
    popover.entry.setText("x")
    next(b for b in popover.findChildren(Button) if b.text() == "Rewrite").click()
    assert card(env).phase == model.SETUP and card(env).instruction == "x"
    assert selected.calls() == [] and not env.window.assistant.tasks.busy
