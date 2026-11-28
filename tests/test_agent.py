# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The agent loop with a scripted model: tool rounds, events, Stop, the turn limit, errors, and the cloud rules."""
from __future__ import annotations

import pytest
from agent_fakes import FakeWorkspace, ScriptedProvider, call, reply
from conftest import SLIDE_TEXT, make_project

from slidemage.ai import ai_profile
from slidemage.ai.agent import Agent
from slidemage.ai.agent_types import (
    EDIT_ASK,
    EDIT_AUTO,
    Done,
    EditApplied,
    ToolFinished,
    ToolResultsMessage,
    ToolSpec,
)
from slidemage.ai.providers import Cancelled, ProviderError
from slidemage.ai.tools import TOOLS, Tool
from slidemage.ai.workspace import WorkspaceContext

SLIDE = "slides/abc-EN-Hello-current.tex"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = make_project(monkeypatch, tmp_path / "project")
    return FakeWorkspace(root, WorkspaceContext(slide_id="abc", path=root / SLIDE))


def run(provider, workspace, request="Do it", history=None, **options):
    events = []
    agent = Agent(provider, workspace, on_event=events.append, **options)
    history = [] if history is None else history
    return agent.run(history, request), events, history


def kinds(events):
    return [type(e).__name__ for e in events]


def test_tool_rounds_run_in_order_and_the_results_go_back(workspace):
    read = call("read_file", path=SLIDE)
    edit = call("edit_file", path=SLIDE, old_text="First", new_text="1st")
    provider = ScriptedProvider(reply("Let me look.", read), reply("", edit), reply("Done."))
    done, events, history = run(provider, workspace, mode=EDIT_AUTO)
    assert done == events[-1] and done.reason == "end_turn" and done.turns == 3
    assert history[0].shown == "Do it" and history[0].text.endswith("\n\nDo it")
    assert kinds(events) == ["TextDelta", "TextDelta", "ToolStarted", "ToolFinished",
                             "ToolStarted", "EditProposed", "EditApplied", "ToolFinished",
                             "TextDelta", "TextDelta", "Done"]
    finished = [e for e in events if isinstance(e, ToolFinished)]
    assert finished[0].call is read and "Second point" in finished[0].result.text
    assert not finished[1].result.is_error and "saved it" in finished[1].result.text
    assert [type(m).__name__ for m in history] == [
        "UserMessage", "AssistantMessage", "ToolResultsMessage", "AssistantMessage", "ToolResultsMessage",
        "AssistantMessage"]
    assert history[2].results[0].call_id == read.id
    assert len(provider.sent[2]) == 5
    assert "1st point" in (workspace.root / SLIDE).read_text()


def test_a_failing_tool_is_a_result_the_model_sees_not_a_crash(workspace):
    workspace.approve = False
    bad = call("edit_file", path=SLIDE, old_text="no such text", new_text="x")
    declined = call("edit_file", path=SLIDE, old_text="First", new_text="1st")
    unknown = call("teleport", where="moon")
    boom = Tool(ToolSpec("boom", "Always fails.", {"type": "object", "properties": {}, "required": []}),
                lambda ctx, args: 1 / 0)
    provider = ScriptedProvider(reply("", bad, unknown, call("boom"), declined), reply("Understood."))
    done, events, history = run(provider, workspace, mode=EDIT_ASK, tools=[*TOOLS, boom])
    assert done.reason == "end_turn"
    results = history[2].results
    assert all(r.is_error for r in results)
    assert "was not found" in results[0].text and "no tool 'teleport'" in results[1].text
    assert "boom failed unexpectedly: ZeroDivisionError" in results[2].text
    assert "rejected" in results[3].text and "EditRejected" in kinds(events)
    assert len(workspace.asked) == 1 and (workspace.root / SLIDE).read_bytes().decode() == SLIDE_TEXT


def test_tool_calls_follow_scope_and_a_mode_change_during_the_run(workspace):
    workspace.approve = False
    other = "slides/abd-EN-Second-current.tex"
    edit = call("edit_file", path=other, old_text="First", new_text="Changed")

    def switch_to_auto(_provider):
        agent.mode = EDIT_AUTO
        return reply("", call("edit_file", path=other, old_text="First", new_text="Changed"))

    provider = ScriptedProvider(reply("", edit), reply("Done."), switch_to_auto, reply("Done."))
    events, history = [], []
    agent = Agent(provider, workspace, on_event=events.append)
    assert agent.run(history, "This slide", scope="slide").reason == "end_turn"
    assert "Current text of abc-EN-Hello-current.tex" in history[0].text
    assert "switch_to_deck_mode" in history[2].results[0].text
    assert history[2].results[0].is_error and not workspace.asked

    assert agent.run(history, "Whole deck", scope="deck").reason == "end_turn"
    assert "Scope chosen by the user: the whole deck" in history[4].text
    assert "Changed point" in (workspace.root / other).read_text()
    assert not workspace.asked and any(isinstance(e, EditApplied) for e in events)


@pytest.mark.parametrize("last_tokens", [False, True], ids=["during-stream", "at-tool-boundary"])
def test_stop_during_streaming_keeps_no_partial_turn_and_runs_no_tool(workspace, last_tokens):
    def streaming(_provider):
        agent.stop()
        if last_tokens:
            return reply("", call("edit_file", path=SLIDE, old_text="First", new_text="1st"))
        raise Cancelled("Aborted.")

    provider = ScriptedProvider(streaming)
    events, history = [], []
    agent = Agent(provider, workspace, mode=EDIT_AUTO, on_event=events.append)
    done = agent.run(history, "go")
    assert done.reason == "stopped" and events[-1] == done and provider.aborted
    assert history == [] and (workspace.root / SLIDE).read_bytes().decode() == SLIDE_TEXT


def test_stop_between_tool_calls_still_answers_every_call(workspace):
    first, second = call("press_stop"), call("press_stop")
    press_stop = Tool(ToolSpec("press_stop", "Stop.", {"type": "object", "properties": {}, "required": []}),
                      lambda ctx, args: agent.stop() or "pressed")
    agent = Agent(ScriptedProvider(reply("", first, second)), workspace, tools=[press_stop])
    history = []
    done = agent.run(history, "go")
    assert done.reason == "stopped"
    results = history[-1]
    assert isinstance(results, ToolResultsMessage) and [r.call_id for r in results.results] == [first.id, second.id]
    assert not results.results[0].is_error
    assert results.results[1].is_error and "Stopped by the user" in results.results[1].text


def test_the_turn_limit_ends_a_runaway_loop(workspace):
    endless = [reply("", call("list_slides")) for _ in range(10)]
    provider = ScriptedProvider(*endless)
    done, events, history = run(provider, workspace, max_turns=3)
    assert done.reason == "max_turns" and done.turns == 3 and "continue" in done.message
    assert len(provider.sent) == 3 and isinstance(history[-1], ToolResultsMessage)


@pytest.mark.parametrize("error", [ProviderError("Anthropic unreachable: boom"), KeyError("bug")],
                         ids=["provider", "unexpected"])
def test_provider_errors_become_a_final_error_event(workspace, error):
    # Regression (1c7e047): an unanswered request must not leak into the next turn.
    provider = ScriptedProvider(error, reply("Fine."))
    history = []
    done, events, history = run(provider, workspace, "first try", history=history)
    assert events[-1] == done
    if isinstance(error, ProviderError):
        assert done == Done("error", "Anthropic unreachable: boom", 1, {})
    else:
        assert done.reason == "error" and "Unexpected error: KeyError" in done.message
    run(provider, workspace, "second try", history=history)
    assert [type(m).__name__ for m in history] == ["UserMessage", "AssistantMessage"]
    assert history[0].shown == "second try" and "first try" not in provider.sent[-1][0].text


def test_a_cut_off_or_declined_answer_is_an_error_and_not_replayed(workspace):
    cut = call("edit_file", path=SLIDE, old_text="x", new_text="y")
    done, _events, history = run(ScriptedProvider(reply("partial", cut, stop="max_tokens")), workspace)
    assert done.reason == "error" and "cut off" in done.message
    assert history == []       # neither a dangling tool call nor the unanswered request is kept
    done, _events, _history = run(ScriptedProvider(reply("", stop="refusal")), workspace)
    assert done.reason == "error" and "declined" in done.message


def test_done_is_the_last_event_even_for_an_exit_that_is_not_an_exception(workspace):
    events = []
    agent = Agent(ScriptedProvider(KeyboardInterrupt()), workspace, on_event=events.append)
    with pytest.raises(KeyboardInterrupt):
        agent.run([], "go")
    assert isinstance(events[-1], Done) and events[-1].reason == "error"


def test_a_failure_in_reporting_a_tool_still_answers_every_call(workspace):
    first, second = call("list_slides"), call("list_slides")

    def report(event):
        if isinstance(event, ToolFinished):
            raise RuntimeError("the UI broke")

    agent = Agent(ScriptedProvider(reply("", first, second)), workspace, on_event=report)
    history = []
    done = agent.run(history, "go")
    assert done.reason == "error" and "the UI broke" in done.message
    results = history[-1]
    assert isinstance(results, ToolResultsMessage) and [r.call_id for r in results.results] == [first.id, second.id]
    assert results.results[1].is_error


# -- the cloud rules ----------------------------------------------------------------------------

class CloudProvider(ScriptedProvider):
    is_local = False
    label = "scripted · cloud"


def test_only_the_first_cloud_request_needs_consent(workspace):
    assert run(ScriptedProvider(reply("fine")), workspace)[0].reason == "end_turn"
    provider = CloudProvider(reply("no"), reply("yes"), reply("again"))
    done, _events, history = run(provider, workspace)
    assert done.reason == "error" and "not confirmed" in done.message and not provider.sent
    workspace.consent = True
    assert run(provider, workspace)[0].reason == "end_turn"
    workspace.consent = False
    assert run(provider, workspace)[0].reason == "end_turn"
    assert ai_profile.cloud_seen(workspace.project)
