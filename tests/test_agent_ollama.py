# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""OllamaProvider.stream_turn against a local server that streams /api/chat the way Ollama does
(NDJSON): the request the agent loop sends, streamed text, tool calls, replaying the history, Stop,
the errors, and the tool-capable model list. A whole Agent round trip is in the middle."""
from __future__ import annotations

import base64
import threading

import pytest
from agent_fakes import FakeWorkspace
from conftest import make_project
from fake_http import ollama_ndjson, wait_for_first_piece

from slidemage.ai.agent import Agent
from slidemage.ai.agent_types import (
    AssistantMessage,
    Done,
    TextDelta,
    ToolCall,
    ToolFinished,
    ToolResult,
    ToolResultsMessage,
    ToolSpec,
    UserMessage,
)
from slidemage.ai.providers import Cancelled, InstalledModel, OllamaProvider, ProviderError
from slidemage.ai.workspace import WorkspaceContext

PNG = b"\x89PNG\r\n\x1a\n" + b"fake"
TOOL = ToolSpec("read_file", "Read a file.", {"type": "object", "properties": {"path": {"type": "string"}},
                                              "required": ["path"]})
SLIDE = "slides/abc-EN-Hello-current.tex"


@pytest.fixture
def server(server):
    server.content_type = "application/x-ndjson"
    return server


def turn(p, messages, texts=None, tools=(TOOL,), system="Be brief."):
    return p.stream_turn(system, messages, list(tools), (texts if texts is not None else []).append)


@pytest.mark.parametrize("done_reason, stop", [("stop", "end_turn"), ("length", "max_tokens")])
def test_the_request_has_tools_system_and_a_context_window(server, done_reason, stop):
    server.body = ollama_ndjson(["Hello", " there"], done_reason=done_reason)
    texts = []
    reply = turn(OllamaProvider("qwen3", host=server.url), [UserMessage("hi")], texts)
    request = server.requests[0]
    body = request["body"]
    assert request["path"] == "/api/chat" and body["model"] == "qwen3" and body["stream"] is True
    assert body["messages"] == [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "hi"}]
    assert body["tools"] == [{"type": "function", "function": {
        "name": "read_file", "description": "Read a file.", "parameters": TOOL.schema}}]
    assert body["options"]["num_ctx"] >= 8192 and body["options"]["num_predict"] == 16000
    assert texts == ["Hello", " there"] and reply.text == "Hello there"
    assert reply.stop == stop and reply.tool_calls == []
    assert reply.usage == {"input": 12, "output": 5}


def test_tool_calls_arrive_whole_and_get_ids(server):
    server.body = ollama_ndjson(["Reading."], [("read_file", {"path": "a.tex"}), ("read_file", '{"path": "b.tex"}')])
    reply = turn(OllamaProvider("m", host=server.url), [UserMessage("hi")])
    assert reply.stop == "tool_use" and reply.text == "Reading."
    assert [(c.name, c.input) for c in reply.tool_calls] == [
        ("read_file", {"path": "a.tex"}), ("read_file", {"path": "b.tex"})]        # a string of JSON works too
    assert len({c.id for c in reply.tool_calls}) == 2 and all(c.id for c in reply.tool_calls)


def test_the_history_is_replayed_with_tool_calls_and_named_tool_results(server):
    server.body = ollama_ndjson(["done"])
    history = [UserMessage("hi"),
               AssistantMessage("calling", [ToolCall("t1", "read_file", {"path": "a"}),
                                            ToolCall("t2", "lint", {})], "tool_use", raw=["claude blocks"]),
               ToolResultsMessage([ToolResult("t1", "contents"), ToolResult("t2", "boom", True)])]
    turn(OllamaProvider("m", host=server.url), history, tools=())
    body = server.requests[0]["body"]
    assert "tools" not in body
    assert body["messages"][1:] == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "calling", "tool_calls": [
            {"function": {"name": "read_file", "arguments": {"path": "a"}}},
            {"function": {"name": "lint", "arguments": {}}}]},
        {"role": "tool", "content": "contents", "tool_name": "read_file"},
        {"role": "tool", "content": "Error: boom", "tool_name": "lint"}]


@pytest.mark.parametrize("vision", [True, False], ids=["vision", "text-only"])
def test_an_image_goes_to_a_model_that_sees_and_is_described_to_one_that_does_not(server, vision):
    server.body = ollama_ndjson(["ok"])
    history = [UserMessage("hi"), AssistantMessage("", [ToolCall("t1", "render_preview", {})], "tool_use"),
               ToolResultsMessage([ToolResult("t1", "rendered", images=[PNG])])]
    server.routes["/api/show"] = (200, {"capabilities": ["completion", "tools"] + (["vision"] if vision else [])})
    turn(OllamaProvider("m", host=server.url), history)
    sent = server.requests[-1]["body"]["messages"]
    if vision:
        assert sent[-2] == {"role": "tool", "content": "rendered", "tool_name": "render_preview"}
        assert sent[-1]["role"] == "user" and sent[-1]["images"] == [base64.b64encode(PNG).decode()]
    else:
        assert "cannot look at images" in sent[-1]["content"] and sent[-1]["role"] == "tool"
        assert not any("images" in m for m in sent)


def test_ollama_errors_become_clear_provider_errors(server):
    p = OllamaProvider("gemma", host=server.url)
    server.status, server.content_type = 400, "application/json"
    server.body = {"error": "registry.ollama.ai/library/gemma:2b does not support tools"}
    with pytest.raises(ProviderError, match="gemma cannot call tools"):
        turn(p, [UserMessage("hi")])
    server.status, server.body = 404, {"error": "model 'gemma' not found"}
    with pytest.raises(ProviderError, match="no model 'gemma'.*ollama pull gemma"):
        turn(p, [UserMessage("hi")])
    server.status, server.body = 500, {"error": "model runner has unexpectedly stopped"}
    with pytest.raises(ProviderError, match="HTTP 500: model runner has unexpectedly stopped"):
        turn(p, [UserMessage("hi")])
    with pytest.raises(ProviderError, match="Ollama unreachable"):
        turn(OllamaProvider("m", host="http://127.0.0.1:9"), [UserMessage("hi")])


def test_an_error_in_the_middle_of_the_stream_and_a_stream_that_just_ends(server):
    p = OllamaProvider("m", host=server.url)
    server.body = ollama_ndjson(["Hel"]).splitlines()[0] + '\n{"error": "out of memory"}\n'
    with pytest.raises(ProviderError, match="Ollama: out of memory"):
        turn(p, [UserMessage("hi")])
    server.body = ollama_ndjson(["Hel"]).splitlines()[0] + "\n"
    with pytest.raises(ProviderError, match="ended the answer early"):
        turn(p, [UserMessage("hi")])


def test_abort_ends_a_stream_that_went_quiet(server):
    body = ollama_ndjson(["Hello", " there"])
    server.body = body
    server.stall_after = body.index("\n") + 1       # the first piece, then silence
    p = OllamaProvider("m", host=server.url)
    texts, outcome = [], []

    def run():
        try:
            turn(p, [UserMessage("hi")], texts)
        except ProviderError as exc:
            outcome.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    wait_for_first_piece(thread, texts)
    p.abort()
    thread.join(4)
    assert not thread.is_alive() and texts == ["Hello"]
    assert isinstance(outcome[0], Cancelled)


def test_an_agent_round_trip_through_a_tool(server, tmp_path, monkeypatch):
    root = make_project(monkeypatch, tmp_path / "project")
    workspace = FakeWorkspace(root, WorkspaceContext(slide_id="abc", path=root / SLIDE))
    server.script = [ollama_ndjson(["Let me look."], [("read_file", {"path": SLIDE})]),
                     ollama_ndjson(["The first point is ", "'First point'."])]
    events, history = [], []
    done = Agent(OllamaProvider("qwen3", host=server.url), workspace, on_event=events.append).run(
        history, "What is the first point?")
    assert done == events[-1] and done.reason == "end_turn" and done.turns == 2
    assert done.usage == {"input": 24, "output": 10}
    finished = next(e for e in events if isinstance(e, ToolFinished))
    assert finished.call.name == "read_file" and "First point" in finished.result.text
    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "Let me look.The first point is 'First point'."
    second = server.requests[1]["body"]["messages"]
    assert [m["role"] for m in second] == ["system", "user", "assistant", "tool"]
    assert second[2]["tool_calls"][0]["function"]["name"] == "read_file"
    assert second[3]["tool_name"] == "read_file" and "First point" in second[3]["content"]
    assert isinstance(history[-1], AssistantMessage) and isinstance(done, Done)


# -- which models the chat may offer ---------------------------------------------------------------

def test_the_model_list_keeps_the_tool_capable_ones(server):
    server.routes["/api/tags"] = (200, {"models": [
        {"name": "chatty:7b", "modified_at": "2026-03-01", "size": 1},
        {"name": "mt-only:7b", "modified_at": "2026-02-01", "size": 1},
        {"name": "seer:7b", "modified_at": "2026-01-01", "size": 1}]})
    shown = {"chatty:7b": ["completion", "tools"], "mt-only:7b": ["completion"],
             "seer:7b": ["completion", "vision", "tools"]}
    server.script = []
    provider = OllamaProvider(host=server.url)
    original = provider.capabilities
    provider.capabilities = lambda model=None: tuple(shown[model]) if model in shown else original(model)
    assert provider.tool_models() == ["chatty:7b", "seer:7b"]
    assert [m.capabilities for m in provider.installed(detailed=True)][1] == ("completion",)


def test_an_old_ollama_without_capabilities_falls_back_to_the_family_name():
    def supports(name, *caps):
        return InstalledModel(name, 1, "", caps).supports_tools

    assert supports("qwen3:8b") and supports("library/llama3.1:8b") and supports("hf.co/x/Mistral-Nemo:q4")
    assert not supports("sun_leaf/HY-MT:7b") and not supports("gemma2:9b") and not supports("llava:7b")
    assert not supports("qwen3:8b", "completion") and supports("anything", "completion", "tools")
