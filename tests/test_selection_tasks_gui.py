# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Rewrite selection and Proofread selection through the window (Claude Code reviews plan, step R1): the capture in the
Source view, the header's buttons, the palette's commands, the editor's context menu, and the task card from Generate
to Done on the three routes with stand-ins for `claude -p` and the providers. The project is a throwaway one."""
from __future__ import annotations

import json
import sys

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication
from test_claude_code_gui import env as claude_env, wait_until  # noqa: F401 -- a fixture
from test_tasks_gui import LF, buttons, ctx, fake, on_route, settled, slide_file  # noqa: F401
from test_make_readable_gui import JsonProvider
from test_task_card_gui import card, phase_is, shown_buttons, state

from slidemage import selection
from slidemage.latex_edit import utf16_len
from slidemage.ai import ai_profile, claude_launch, tasks as ai_tasks, credentials, resolver
from slidemage.ai.agent_types import EDIT_ASK
from slidemage.ai.tools import ToolContext, ToolError, focus
from slidemage.ui.kit.widgets import Button, PopoverMenu
from slidemage.ui.workspace import task_card_model as model
from slidemage.ui.workspace.insert_popovers import InstructionPopover
from slidemage.ui.workspace import task_bubbles as tasks_module

pytest.importorskip("PySide6.QtWebEngineWidgets")
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the stand-in for claude is a POSIX script")

OPENING = LF.replace("First point", "Opening remark")
SHOWN = ["Rewrite selection", "Proofread selection"]


def select(env, piece: str, *, mode: str = "source") -> None:
    """Select `piece` in the editor of the slide, which is on show."""
    env.window.state.set_mode(mode)
    editor = source(env).current.editor
    start = utf16_len(editor.text()[:editor.text().index(piece)])           # Qt counts in UTF-16 units
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


def requests(made) -> list[str]:
    return [call["request"] for call in made.calls()]


def popups(kind):
    return [w for w in QApplication.topLevelWidgets() if isinstance(w, kind) and w.isVisible()]


# -- the capture -------------------------------------------------------------------------------------------------------

def test_the_source_view_captures_the_selection_with_the_file_and_the_range(fake):  # noqa: F811
    env = fake.env
    env.window.state.set_mode("details")
    with pytest.raises(selection.SelectionError, match="Open a slide"):             # the Source view is not on show
        source(env).selection()
    select(env, "First point")
    chosen = source(env).selection()
    assert (chosen.path, chosen.selected, chosen.text) == (env.path, "First point", LF)
    assert LF[chosen.start:chosen.end] == "First point"
    slide_file(env).editor.moveCursor(QTextCursor.MoveOperation.Start)
    with pytest.raises(selection.SelectionError, match="Select some text"):
        source(env).selection()


def test_a_selection_keeps_its_python_offsets_after_a_character_outside_the_bmp(fake):  # noqa: F811
    env = fake.env
    slide_file(env).editor.replace_all_text(LF.replace("First point", "𝔄 First point"))
    select(env, "First point")
    chosen = source(env).selection()
    assert chosen.selected == "First point" and chosen.text[chosen.start:chosen.end] == "First point"


def test_a_frozen_version_a_protected_part_and_other_files_have_no_selection_to_work_on(fake):  # noqa: F811
    env = fake.env
    select(env, "\\setSlideVersion{1-0-0}")
    with pytest.raises(selection.SelectionError, match="protected part"):
        source(env).selection()
    slide_file(env).editor.moveCursor(QTextCursor.MoveOperation.Start)
    select(env, "Included in decks: test\n%%\n\n% A note on this slide\n\\setSlideVersion")
    with pytest.raises(selection.SelectionError, match="protected part"):         # it crosses into the version line
        source(env).selection()
    select(env, "Hello}\n\t\\begin{itemize}")
    assert source(env).selection().selected.startswith("Hello}")
    env.window.centre.open_file(env.root / "slides" / "abc-EN-Hello-v1-0-0.tex")
    select(env, "First point")
    with pytest.raises(selection.SelectionError, match="frozen version"):
        source(env).selection()
    env.window.centre.open_file(env.root / "decks" / "test.tex")
    select(env, "Intro")
    with pytest.raises(selection.SelectionError, match="Open a slide"):
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
    assert ", lines 8-8\n" in text and "--- the selection ---\nEdited point\n--- end of the selection ---" in text
    assert "\\item Second point" in text.split("Text after the selection:")[1]
    select(env, "\\setSlideVersion{1-0-0}")
    with pytest.raises(ToolError, match="protected part"):
        focus.read_selection.run(tool, {})


# -- the header, the palette, the context menu ------------------------------------------------------------------

def test_the_header_offers_the_two_tasks_in_place_of_the_slide_tasks_while_a_selection_is_there(fake):  # noqa: F811
    env = fake.env
    header = env.window.assistant.header
    wait_until(lambda: buttons(env) == ["Translate to German", "Better title"])
    select(env, "First point")
    wait_until(lambda: [b.label for b in header.shown] == SHOWN)
    assert buttons(env)[:2] == SHOWN and len(header.shown) == 2                  # at most two, the slide's own wait
    slide_file(env).editor.moveCursor(QTextCursor.MoveOperation.Start)
    wait_until(lambda: [b.label for b in header.shown] == ["Translate to German", "Better title"])
    select(env, "First point", mode="details")                                    # the source is not on show
    wait_until(lambda: [b.label for b in header.shown] == ["Translate to German", "Better title"])


def test_the_header_button_asks_how_to_rewrite_and_the_other_starts_the_proofread(fake):  # noqa: F811
    env = asked(fake)
    area = env.window.assistant
    select(env, "First point")
    wait_until(lambda: [b.label for b in area.header.shown] == SHOWN)
    next(b for b in area.header._actions.itemAt(0).widget().parent().findChildren(Button) if b.text() == "Rewrite selection").click()
    menu, = popups(PopoverMenu)
    assert [row.key for row in menu._rows] == ["Simplify", "Shorten", "Custom…"]
    fake.reply({"answer": {"text": "Opening remark"}})
    menu.triggered.emit("Shorten")
    wait_until(phase_is(env, model.REVIEW))
    assert card(env).title == "Rewrite selection · Shorten" and card(env).instruction == ai_tasks.REWRITE_PRESETS["Shorten"]
    assert [b.label for b in area.header.shown] == []                              # nothing else starts while one waits


def test_the_palette_commands_are_enabled_with_a_selection_only_and_ctrl_shift_r_rewrites(fake):  # noqa: F811
    env = fake.env
    commands = env.window.commands
    ids = ["selection:rewrite", "selection:rewrite:Simplify", "selection:rewrite:Shorten", "selection:rewrite:Custom…",
           "selection:proofread"]
    assert commands["selection:rewrite"].shortcut == "Ctrl+Shift+R"
    assert [commands[i].enabled(env.window) for i in ids] == [False] * 5
    select(env, "First point")
    assert [commands[i].enabled(env.window) for i in ids] == [True] * 5
    assert [commands[i].label if isinstance(commands[i].label, str) else commands[i].label(env.window) for i in ids[1:4]] == [
        "Rewrite selection · Simplify", "Rewrite selection · Shorten", "Rewrite selection · Custom…"]
    select(env, "\\setSlideVersion{1-0-0}")
    assert not commands["selection:proofread"].enabled(env.window)


def test_the_context_menu_offers_the_edit_commands_and_the_two_tasks_when_the_selection_can_be_worked_on(fake):  # noqa: F811
    env = asked(fake)
    select(env, "\\setSlideVersion{1-0-0}")
    source(env)._on_context_menu(QPoint(5, 5))
    menu, = popups(PopoverMenu)
    rows = {row.key: row.isEnabled() for row in menu._rows}
    assert list(rows) == ["undo", "redo", "cut", "copy", "paste", "selectAll", "rewrite:Simplify", "rewrite:Shorten",
                          "rewrite:Custom…", "proofread"]
    assert rows["copy"] and not any(rows[k] for k in rows if k.startswith("rewrite:") or k == "proofread")
    menu.close()
    select(env, "First point")
    source(env)._on_context_menu(QPoint(5, 5))
    menu, = popups(PopoverMenu)
    assert all(row.isEnabled() for row in menu._rows if row.key.startswith("rewrite:") or row.key == "proofread")
    fake.reply({"answer": {"edits": [{"before": "First point", "after": "First points"}]}})
    menu.triggered.emit("proofread")
    wait_until(phase_is(env, model.REVIEW))
    assert card(env).task is ai_tasks.PROOFREAD_SELECTION and card(env).title == "Proofread selection"
    # Starting the task can already close and delete the context menu.
    from shiboken6 import isValid
    if isValid(menu):
        menu.close()


# -- the card: Generate, Review, Apply ------------------------------------------------------------------------------

def test_a_rewrite_is_reviewed_applied_into_the_buffer_and_taken_back_by_the_editors_undo(fake):  # noqa: F811
    env = asked(fake)
    select(env, "First point")
    fake.reply({"answer": {"text": "Opening remark"}})
    env.window.assistant.rewrite_selection("Simplify")
    assert card(env).route.route == ai_profile.CLAUDE_CODE
    wait_until(phase_is(env, model.REVIEW))
    request, = requests(fake)
    assert request.startswith("Rewrite the selection of this slide. Instruction: " + ai_tasks.REWRITE_PRESETS["Simplify"])
    assert "<selection>\nFirst point\n</selection>" in request
    argv = fake.calls()[0]["argv"]
    assert argv[argv.index("--json-schema") + 1] == json.dumps(ai_tasks.REWRITE.schema)
    assert state(env).startswith("Proposed change to abc-EN-Hello-current.tex. Nothing is written yet.")
    assert shown_buttons(env) == ["Apply", "Reject", "View full diff", "Compare rendered"]
    assert (card(env).before, card(env).after, card(env).changed) == (LF, OPENING, 1)
    assert env.window.assistant.tasks.compare_texts() == (env.path, LF, OPENING)
    assert slide_file(env).editor.text() == LF                                        # nothing is written before Apply

    env.window.assistant.tasks.apply()
    wait_until(phase_is(env, model.DONE))
    assert slide_file(env).editor.text() == OPENING and slide_file(env).dirty         # in the buffer, unsaved
    assert (env.root / "slides" / "abc-EN-Hello-current.tex").read_bytes().decode().replace("\r\n", "\n") == LF
    assert len(fake.renders) == 1 and state(env).startswith("Changed 1 line in abc-EN-Hello-current.tex.")
    assert "Undo" in shown_buttons(env)
    slide_file(env).editor.undo()                                                     # the user's own undo
    assert slide_file(env).editor.text() == LF


def test_the_cards_undo_takes_a_rewrite_back_and_edit_automatically_skips_review(fake):  # noqa: F811
    env = fake.env                                                                    # Edit automatically is on
    select(env, "First point")
    fake.reply({"answer": {"text": "Opening remark"}})
    env.window.assistant.rewrite_selection("Shorten")
    assert settled(env).startswith("Applied automatically (Edit automatically is on). Changed 1 line")
    assert slide_file(env).editor.text() == OPENING
    assert env.window.assistant.tasks.undo() == "" and slide_file(env).editor.text() == LF


def test_typing_after_the_capture_ends_in_a_conflict_that_keeps_the_proposal(fake):  # noqa: F811
    env = asked(fake)
    select(env, "First point")
    fake.reply({"answer": {"text": "Opening remark"}})
    env.window.assistant.rewrite_selection("Simplify")
    wait_until(phase_is(env, model.REVIEW))
    slide_file(env).editor.replace_all_text(LF.replace("Second point", "Second points"))     # outside the selection, still a change
    env.window.assistant.tasks.apply()
    wait_until(phase_is(env, model.CONFLICT))
    assert slide_file(env).editor.text() == LF.replace("Second point", "Second points")
    assert card(env).after == OPENING and "Compare rendered" in shown_buttons(env)
    assert state(env) == "abc changed while this task ran. The proposal is kept but not applied."


def test_a_selection_that_changed_while_the_model_worked_is_a_conflict_at_once(fake):  # noqa: F811
    env = asked(fake)
    select(env, "First point")
    fake.reply({"answer": {"text": "Opening remark"}})
    env.window.assistant.rewrite_selection("Simplify")
    slide_file(env).editor.replace_all_text(LF.replace("First point", "First points"))
    wait_until(phase_is(env, model.CONFLICT))
    assert slide_file(env).editor.text() == LF.replace("First point", "First points")


def test_custom_asks_for_the_instruction_in_a_popover_and_carries_it_into_the_request(fake):  # noqa: F811
    env = asked(fake)
    select(env, "First point")
    fake.reply({"answer": {"text": "Is this the first point?"}})
    env.window.assistant.rewrite_selection("Custom…")
    popover, = popups(InstructionPopover)
    assert card(env) is None and fake.calls() == []                                    # nothing starts before it is asked
    rewrite = next(b for b in popover.findChildren(Button) if b.text() == "Rewrite")
    rewrite.click()
    assert popover.isVisible() and "Say what" in popover.note.text()                   # an empty instruction is not accepted
    popover.entry.setText("  as a question  ")
    rewrite.click()
    wait_until(phase_is(env, model.REVIEW))
    assert requests(fake)[0].splitlines()[0] == "Rewrite the selection of this slide. Instruction: as a question"
    assert card(env).title == "Rewrite selection · as a question" and card(env).instruction == "as a question"


def test_a_long_custom_instruction_is_shortened_in_the_title_only(fake):  # noqa: F811
    env = asked(fake)
    select(env, "First point")
    fake.reply({"answer": {"text": "Opening remark"}})
    long = "make it sound like a weather forecast for the whole afternoon"
    env.window.assistant._rewrite(long)
    wait_until(phase_is(env, model.REVIEW))
    assert card(env).title == "Rewrite selection · " + long[:39] + "…" and long in requests(fake)[0]


def test_proofreading_the_selection_applies_its_edits_and_nothing_else(fake):  # noqa: F811
    env = asked(fake)
    slide_file(env).editor.replace_all_text(LF.replace("First point", "Frist point and Secnd point"))
    select(env, "Frist point and Secnd point")
    fake.reply({"answer": {"edits": [{"before": "Frist", "after": "First"}, {"before": "Secnd", "after": "Second"}]}})
    env.window.assistant.proofread_selection()
    wait_until(phase_is(env, model.REVIEW))
    request, = requests(fake)
    assert request.startswith("Proofread the selection of this English slide") and "Frist point and Secnd point\n</selection>" in request
    env.window.assistant.tasks.apply()
    wait_until(phase_is(env, model.DONE))
    assert slide_file(env).editor.text() == LF.replace("First point", "First point and Second point")


def test_a_proofread_with_nothing_to_fix_and_a_refused_answer_end_the_card_without_a_change(fake):  # noqa: F811
    env = asked(fake)
    select(env, "First point")
    fake.reply({"answer": {"edits": []}})
    env.window.assistant.proofread_selection()
    assert settled(env) == "Nothing to change in abc. Nothing was written."
    env.window.assistant.tasks.close_card()
    fake.reply({"answer": {"edits": [{"before": "Second", "after": "2nd"}]}},                 # outside the selection, twice
               {"answer": {"edits": [{"before": "Second", "after": "2nd"}]}})
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


# -- the routes ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("mode, conn, kind", [(ai_profile.LOCAL, ai_profile.CLAUDE_CODE, ai_profile.OLLAMA), (ai_profile.CLOUD, ai_profile.ANTHROPIC_API, ai_profile.ANTHROPIC_API)])
def test_on_local_and_the_api_a_rewrite_runs_on_the_provider_with_the_fixes_model(ctx, fake, monkeypatch, mode, conn, kind):  # noqa: F811
    env = asked(fake)
    ai_profile.mark_cloud_seen(ctx)
    credentials.set_api_key(ctx, "key")
    on_route(fake, mode, conn)
    ai_profile.set_model_choice(ctx, kind, ai_profile.FIXES, "chosen-model")
    select(env, "First point")
    provider, seen = JsonProvider(json.dumps({"text": "Opening remark"}), mode == ai_profile.LOCAL), []
    monkeypatch.setattr(tasks_module.resolver, "provider_for", lambda _ctx, route: seen.append(route) or provider)
    env.window.assistant.rewrite_selection("Shorten")
    wait_until(phase_is(env, model.REVIEW))
    assert fake.calls() == [] and [(r.route, r.model) for r in seen] == [(kind, "chosen-model")]
    (messages, kwargs), = provider.calls
    assert messages[0]["content"].startswith("Rewrite the selection") and kwargs["system"] == ai_tasks.REWRITE.rules
    assert card(env).after == OPENING and (env.window._route_tasks.get("ollama") or (None,))[0] is None
    env.window.assistant.tasks.apply()
    wait_until(phase_is(env, model.DONE))
    assert slide_file(env).editor.text() == OPENING


def test_on_local_a_proofread_edit_list_is_checked_against_the_selection(ctx, fake, monkeypatch):  # noqa: F811
    env = asked(fake)
    on_route(fake, ai_profile.LOCAL)
    ai_profile.set_model_choice(ctx, ai_profile.OLLAMA, ai_profile.FIXES, "chosen-model")
    select(env, "First point")
    provider = JsonProvider(json.dumps({"edits": [{"before": "Second", "after": "2nd"}]}))
    monkeypatch.setattr(tasks_module.resolver, "provider_for", lambda _ctx, _route: provider)
    env.window.assistant.proofread_selection()
    wait_until(phase_is(env, model.FAILED))
    assert len(provider.calls) == 2 and "does not occur" in state(env) and slide_file(env).editor.text() == LF


def test_routes_that_are_not_ready_run_nothing_and_no_other_route_stands_in(ctx, fake, monkeypatch):  # noqa: F811
    env = fake.env
    select(env, "First point")
    tasks = env.window.assistant.tasks
    on_route(fake, ai_profile.LOCAL)                                                 # no Ollama model is chosen
    env.window.assistant.rewrite_selection("Simplify")
    assert card(env).phase == model.SETUP and "Choose an Ollama model" in card(env).note
    tasks.close_card()
    credentials.set_api_key(ctx, "")
    on_route(fake, ai_profile.CLOUD, ai_profile.ANTHROPIC_API)
    env.window.assistant.proofread_selection()
    assert card(env).phase == model.SETUP and "No Anthropic API key" in card(env).note
    tasks.close_card()
    on_route(fake, ai_profile.CLOUD, ai_profile.CLAUDE_CODE)
    monkeypatch.setattr(claude_launch, "find_claude", lambda: None)
    assert tasks.refusal(ai_tasks.REWRITE) == resolver.NO_CLAUDE
    env.window.assistant.rewrite_selection("Custom…")
    popups(InstructionPopover)[0].entry.setText("x")
    next(b for b in popups(InstructionPopover)[0].findChildren(Button) if b.text() == "Rewrite").click()
    assert card(env).phase == model.SETUP and card(env).note == resolver.NO_CLAUDE and card(env).instruction == "x"
    assert fake.calls() == [] and not tasks.busy


def test_the_selection_tasks_are_card_tasks_of_the_fixes_kind_that_every_route_can_run():
    for task in (ai_tasks.REWRITE, ai_tasks.PROOFREAD_SELECTION):
        assert tasks_module.KINDS[task.name] == ai_profile.FIXES
        assert task in tasks_module.CARD_TASKS and task in tasks_module.PROVIDER_TASKS and task in tasks_module.PRIORITY
        assert task not in tasks_module.DECK_TASKS and task not in tasks_module.SLIDE_TASKS
    assert tasks_module.PRIORITY[:2] == (ai_tasks.REWRITE, ai_tasks.PROOFREAD_SELECTION)
