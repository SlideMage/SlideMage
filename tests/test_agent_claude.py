"""AnthropicProvider.stream_turn through the real SDK against a local server: the request the
agent loop sends (tools, caching, effort), streamed text, tool calls, replaying the history,
usage, and Stop."""
from __future__ import annotations

import base64
import threading

import pytest
from fake_http import Server, message_sse

from slidemage.ai.agent_types import (
    AssistantMessage,
    ToolCall,
    ToolResult,
    ToolResultsMessage,
    ToolSpec,
    UserMessage,
)
from slidemage.ai.providers import AnthropicProvider, Cancelled, ProviderError

PNG = b"\x89PNG\r\n\x1a\n" + b"fake"
TOOL = ToolSpec("read_file", "Read a file.", {"type": "object", "properties": {"path": {"type": "string"}},
                                              "required": ["path"]})


@pytest.fixture
def server():
    srv = Server()
    srv.content_type = "text/event-stream"
    yield srv
    srv.close()


def provider(server, model="claude-sonnet-5-5"):
    p = AnthropicProvider(model, api_key="sk-test")
    p.base_url, p.max_retries = server.url, 0
    return p


def turn(p, messages, texts=None, tools=(TOOL,), system="Be brief."):
    return p.stream_turn(system, messages, list(tools), (texts if texts is not None else []).append)


def test_the_request_has_tools_system_caching_and_effort(server):
    server.body = message_sse([{"type": "text", "text": "Hello there"}])
    texts = []
    reply = turn(provider(server), [UserMessage("hi")], texts)
    body = server.requests[0]["body"]
    assert server.requests[0]["path"] == "/v1/messages" and server.requests[0]["headers"]["x-api-key"] == "sk-test"
    assert body["stream"] is True and body["system"] == "Be brief."
    assert body["cache_control"] == {"type": "ephemeral"} and body["output_config"] == {"effort": "medium"}
    assert body["tools"] == [{"name": "read_file", "description": "Read a file.", "input_schema": TOOL.schema}]
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert "temperature" not in body and "thinking" not in body
    assert texts == ["Hello", " there"] and reply.text == "Hello there"
    assert reply.stop == "end_turn" and reply.tool_calls == []


def test_older_models_get_no_effort(server):
    server.body = message_sse([{"type": "text", "text": "ok"}])
    turn(provider(server, "claude-haiku-4-5-20251001"), [UserMessage("hi")])
    assert "output_config" not in server.requests[0]["body"]


def test_tool_calls_stop_reason_and_usage(server):
    server.body = message_sse(
        [{"type": "text", "text": "Reading."},
         {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {"path": "slides/a.tex"}}],
        "tool_use", {"input_tokens": 50, "cache_read_input_tokens": 400, "cache_creation_input_tokens": 7,
                     "output_tokens": 33})
    reply = turn(provider(server), [UserMessage("hi")])
    assert reply.stop == "tool_use"
    assert reply.tool_calls == [ToolCall("toolu_1", "read_file", {"path": "slides/a.tex"})]
    assert reply.usage == {"input": 50, "output": 33, "cache_read": 400, "cache_write": 7}


def test_other_stop_reasons_are_passed_on(server):
    for given, expected in (("max_tokens", "max_tokens"), ("refusal", "refusal"), ("stop_sequence", "end_turn")):
        server.body = message_sse([{"type": "text", "text": "x"}], given)
        assert turn(provider(server), [UserMessage("hi")]).stop == expected


def test_the_history_is_replayed_with_the_models_own_blocks_and_tool_results(server):
    server.body = message_sse([{"type": "text", "text": "first"},
                               {"type": "tool_use", "id": "toolu_9", "name": "read_file", "input": {"path": "a"}}],
                              "tool_use")
    p = provider(server)
    history = [UserMessage("hi")]
    first = turn(p, history)
    history += [first, ToolResultsMessage([
        ToolResult("toolu_9", "contents", False),
        ToolResult("toolu_x", "bad", True),
        ToolResult("toolu_y", "look", False, [PNG])])]
    server.body = message_sse([{"type": "text", "text": "second"}])
    turn(p, history)
    sent = server.requests[1]["body"]["messages"]
    assert [m["role"] for m in sent] == ["user", "assistant", "user"]
    assert [b["type"] for b in sent[1]["content"]] == ["text", "tool_use"]
    assert sent[1]["content"][1]["id"] == "toolu_9" and sent[1]["content"][1]["input"] == {"path": "a"}
    results = sent[2]["content"]
    assert results[0] == {"type": "tool_result", "tool_use_id": "toolu_9", "content": "contents"}
    assert results[1] == {"type": "tool_result", "tool_use_id": "toolu_x", "content": "bad", "is_error": True}
    assert results[2]["content"] == [
        {"type": "text", "text": "look"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                     "data": base64.b64encode(PNG).decode()}}]


def test_a_history_without_raw_blocks_is_built_from_the_neutral_fields(server):
    server.body = message_sse([{"type": "text", "text": "x"}])
    history = [UserMessage("hi"), AssistantMessage("calling", [ToolCall("t1", "read_file", {"path": "a"})], "tool_use"),
               ToolResultsMessage([ToolResult("t1", "ok")])]
    turn(provider(server), history)
    assert server.requests[0]["body"]["messages"][1] == {"role": "assistant", "content": [
        {"type": "text", "text": "calling"},
        {"type": "tool_use", "id": "t1", "name": "read_file", "input": {"path": "a"}}]}


def test_errors_become_provider_errors(server):
    server.status, server.content_type = 429, "application/json"
    server.body = {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}}
    with pytest.raises(ProviderError, match="rate limit reached .*slow down"):
        turn(provider(server), [UserMessage("hi")])
    with pytest.raises(ProviderError, match="No Anthropic API key"):
        turn(AnthropicProvider(api_key=""), [UserMessage("hi")])


def test_stop_ends_a_stream_that_went_quiet(server):
    body = message_sse([{"type": "text", "text": "Hello there"}])
    server.body = body
    server.stall_after = body.index("event: content_block_delta", body.index("content_block_delta") + 1)   # after the first piece
    p = provider(server)
    texts, outcome = [], []

    def run():
        try:
            turn(p, [UserMessage("hi")], texts)
        except ProviderError as exc:
            outcome.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    while not texts:                       # the first piece arrived; now the server says nothing more
        thread.join(0.01)
    p.abort()
    thread.join(4)
    assert not thread.is_alive() and texts == ["Hello"]
    assert isinstance(outcome[0], Cancelled)
