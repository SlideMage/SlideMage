# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The agent loop with a scripted model: tool rounds, events, Stop, the turn limit, errors, and the cloud rules."""
from __future__ import annotations

import pytest
from agent_fakes import FakeWorkspace, ScriptedProvider, call, reply
from conftest import SLIDE_TEXT, make_project

from slidemage.ai import ai_profile
from slidemage.project import ProjectContext
from slidemage.ai.agent import Agent
from slidemage.ai.agent_types import (
    EDIT_AUTO,
    AssistantMessage,
    Done,
    EditApplied,
    EditProposed,
    EditRejected,
    TextDelta,
    ToolFinished,
    ToolResultsMessage,
    ToolSpec,
    UserMessage,
)
from slidemage.ai.providers import Cancelled, ProviderError
from slidemage.ai.tools import TOOLS, Tool
from slidemage.ai.workspace import WorkspaceContext

SLIDE = "slides/abc-EN-Hello-current.tex"


@pytest.fixture
def ctx(tmp_path):
    return ProjectContext.at(tmp_path / "project")


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = make_project(monkeypatch, tmp_path / "project")
    return FakeWorkspace(root, WorkspaceContext(slide_id="abc", path=root / SLIDE))


def run(provider, workspace, request="Do it", mode=None, history=None, **options):
    events = []
    agent = Agent(provider, workspace, on_event=events.append, **({"mode": mode} if mode else {}), **options)
    history = [] if history is None else history
    return agent.run(history, request), events, history


def kinds(events):
    return [type(e).__name__ for e in events]


def test_a_plain_answer_streams_and_ends(workspace):
    provider = ScriptedProvider(reply("All good."), reply("Second answer."))
    done, events, history = run(provider, workspace)
    assert kinds(events) == ["TextDelta", "TextDelta", "Done"]
    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "All good."
    assert done == events[-1] == Done("end_turn", "", 1, {"input": 100, "output": 10})
    assert isinstance(history[0], UserMessage) and history[0].text.endswith("\n\nDo it")
    assert history[0].shown == "Do it"
    assert "The editor shows: slides/abc-EN-Hello-current.tex" in history[0].text    # the context block
    assert isinstance(history[1], AssistantMessage)
    run(provider, workspace, "two", history=history)
    assert [type(m).__name__ for m in history] == ["UserMessage", "AssistantMessage"] * 2
    assert len(provider.sent[1]) == 3 and provider.systems[0] == provider.systems[1]


def test_tool_rounds_run_in_order_and_the_results_go_back(workspace):
    read = call("read_file", path=SLIDE)
    edit = call("edit_file", path=SLIDE, old_text="First", new_text="1st")
    provider = ScriptedProvider(reply("Let me look.", read), reply("", edit), reply("Done."))
    done, events, history = run(provider, workspace, mode=EDIT_AUTO)
    assert done.reason == "end_turn" and done.turns == 3
    assert kinds(events) == ["TextDelta", "TextDelta", "ToolStarted", "ToolFinished",
                             "ToolStarted", "EditProposed", "EditApplied", "ToolFinished",
                             "TextDelta", "TextDelta", "Done"]
    finished = [e for e in events if isinstance(e, ToolFinished)]
    assert finished[0].call is read and "Second point" in finished[0].result.text
    assert not finished[1].result.is_error and "saved it" in finished[1].result.text
    assert [type(m).__name__ for m in history] == [
        "UserMessage", "AssistantMessage", "ToolResultsMessage", "AssistantMessage", "ToolResultsMessage",
        "AssistantMessage"]
    assert history[2].results[0].call_id == read.id                      # the call id comes back
    assert len(provider.sent[2]) == 5                                    # the third turn saw all of it
    assert "1st point" in (workspace.root / SLIDE).read_text()


def test_a_failing_tool_is_a_result_the_model_sees_not_a_crash(ctx, workspace):
    bad = call("edit_file", path=SLIDE, old_text="no such text", new_text="x")
    unknown = call("teleport", where="moon")
    boom = Tool(ToolSpec("boom", "Always fails.", {"type": "object", "properties": {}, "required": []}),
                lambda ctx, args: 1 / 0)
    provider = ScriptedProvider(reply("", bad, unknown, call("boom")), reply("I see, sorry."))
    done, events, history = run(provider, workspace, mode=EDIT_AUTO, tools=[*TOOLS, boom])
    assert done.reason == "end_turn"
    results = history[2].results
    assert [r.is_error for r in results] == [True, True, True]
    assert "was not found" in results[0].text and "no tool 'teleport'" in results[1].text
    assert "boom failed unexpectedly: ZeroDivisionError" in results[2].text


@pytest.mark.parametrize("approve", [False, True], ids=["rejected", "approved"])
def test_ask_mode_reports_the_decision_and_the_model_goes_on(workspace, approve):
    workspace.approve = approve
    edit = call("edit_file", path=SLIDE, old_text="First", new_text="1st")
    provider = ScriptedProvider(reply("", edit), reply("Understood, I will not."))
    done, events, history = run(provider, workspace)       # default mode: ask
    assert done.reason == "end_turn"
    if approve:
        proposed = next(e for e in events if isinstance(e, EditProposed))
        assert workspace.asked and workspace.asked[0][2] == proposed.after
        assert any(isinstance(e, EditApplied) for e in events) and not any(isinstance(e, EditRejected) for e in events)
    else:
        assert kinds(events).count("EditProposed") == 1 and kinds(events).count("EditRejected") == 1
        assert "EditApplied" not in kinds(events)
        assert "rejected" in history[2].results[0].text and history[2].results[0].is_error
        assert (workspace.root / SLIDE).read_bytes().decode() == SLIDE_TEXT


def test_the_mode_can_be_changed_while_the_run_is_under_way(workspace):
    workspace.approve = False
    edit = call("edit_file", path=SLIDE, old_text="First", new_text="1st")
    holder = {}

    def user_switches_to_auto(provider):
        holder["agent"].mode = EDIT_AUTO
        return reply("", edit)

    provider = ScriptedProvider(user_switches_to_auto, reply("done"))
    agent = Agent(provider, workspace)
    holder["agent"] = agent
    assert agent.run([], "go").reason == "end_turn"
    assert "1st point" in (workspace.root / SLIDE).read_text() and not workspace.asked


def test_stop_in_the_middle_of_a_streamed_answer(workspace):
    holder = {}

    def streaming(provider):
        holder["agent"].stop()                       # the user presses Stop while the answer streams
        raise Cancelled("Aborted.")

    provider = ScriptedProvider(streaming)
    agent = Agent(provider, workspace)
    holder["agent"] = agent
    events, history = [], []
    agent._on_event = events.append
    done = agent.run(history, "go")
    assert done.reason == "stopped" and events[-1] == done and provider.aborted
    assert history == []                             # no half answer, and the unanswered request is taken out again


def test_stop_between_tool_calls_still_answers_every_call(ctx, workspace):
    holder = {}
    first, second = call("press_stop"), call("press_stop")
    press_stop = Tool(ToolSpec("press_stop", "Stop.", {"type": "object", "properties": {}, "required": []}),
                      lambda ctx, args: holder["agent"].stop() or "pressed")
    provider = ScriptedProvider(reply("", first, second))
    agent = Agent(provider, workspace, tools=[press_stop])
    holder["agent"] = agent
    history = []
    done = agent.run(history, "go")
    assert done.reason == "stopped"
    results = history[-1]
    assert isinstance(results, ToolResultsMessage) and [r.call_id for r in results.results] == [first.id, second.id]
    assert not results.results[0].is_error                       # it ran
    assert results.results[1].is_error and "Stopped by the user" in results.results[1].text   # history stays valid


def test_the_turn_limit_ends_a_runaway_loop(workspace):
    endless = [reply("", call("list_slides")) for _ in range(10)]
    provider = ScriptedProvider(*endless)
    done, events, history = run(provider, workspace, max_turns=3)
    assert done.reason == "max_turns" and done.turns == 3 and "continue" in done.message
    assert len(provider.sent) == 3 and isinstance(history[-1], ToolResultsMessage)    # still a valid history


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
    events = []

    def report(event):
        events.append(event)
        if isinstance(event, ToolFinished):
            raise RuntimeError("the UI broke")

    agent = Agent(ScriptedProvider(reply("", first, second)), workspace, on_event=report)
    history = []
    done = agent.run(history, "go")
    assert done.reason == "error" and "the UI broke" in done.message
    results = history[-1]
    assert isinstance(results, ToolResultsMessage) and [r.call_id for r in results.results] == [first.id, second.id]
    assert results.results[1].is_error


def test_stop_during_the_last_tokens_runs_no_tool(workspace):
    holder = {}

    def streamed_then_stopped(provider):
        holder["agent"].stop()
        return reply("", call("edit_file", path=SLIDE, old_text="First", new_text="1st"))

    agent = Agent(ScriptedProvider(streamed_then_stopped), workspace, mode=EDIT_AUTO)
    holder["agent"] = agent
    done = agent.run([], "go")
    assert done.reason == "stopped" and "First point" in (workspace.root / SLIDE).read_text()


def test_the_scope_changes_the_context(workspace):
    provider = ScriptedProvider(reply("a"), reply("b"))
    agent = Agent(provider, workspace)
    history = []
    agent.run(history, "this", "slide")
    assert "Current text of abc-EN-Hello-current.tex" in history[0].text
    assert Agent(provider, workspace).run(history, "all", "deck").reason == "end_turn"
    assert "Deck outline" not in history[2].text               # no deck is open in this workspace
    assert "Scope chosen by the user: the whole deck" in history[2].text


# -- the cloud rules ----------------------------------------------------------------------------

class CloudProvider(ScriptedProvider):
    is_local = False
    label = "scripted · cloud"


def test_the_first_cloud_request_needs_consent_once(ctx, workspace):
    provider = CloudProvider(reply("no"), reply("yes"), reply("again"))
    done, _events, history = run(provider, workspace)                  # the user declines
    assert done.reason == "error" and "not confirmed" in done.message and not provider.sent
    workspace.consent = True
    assert run(provider, workspace)[0].reason == "end_turn"            # agrees: remembered
    workspace.consent = False
    assert run(provider, workspace)[0].reason == "end_turn"            # not asked again
    assert ai_profile.cloud_seen(ctx)


def test_a_local_provider_never_asks(ctx, workspace):
    assert run(ScriptedProvider(reply("fine")), workspace)[0].reason == "end_turn"


@pytest.mark.parametrize("scope,refused", [("slide", True), ("deck", False)])
def test_run_enforces_scope_on_tool_calls(workspace, scope, refused):
    edit = call("edit_file", path="slides/abd-EN-Second-current.tex", old_text="First", new_text="Changed")
    provider = ScriptedProvider(reply("", edit), reply("Done."))
    history = []
    agent = Agent(provider, workspace, mode=EDIT_AUTO)
    agent.run(history, "Change it", scope=scope)
    result = history[2].results[0]
    assert result.is_error == refused
    if refused:
        assert "switch_to_deck_mode" in result.text
