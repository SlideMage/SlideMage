# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""AnthropicProvider.stream_turn against a local server: the request the
agent loop sends (tools, caching, effort), streamed text, tool calls, replaying the history,
usage, and Stop."""
from __future__ import annotations

import base64
import json
import socket
import ssl
import threading
import time

import pytest
from fake_http import ConnectProxy, StallingServer, api_key_of, message_sse, sse_events, wait_for_first_piece

from slidemage.ai.agent_types import (
    AssistantMessage,
    ToolCall,
    ToolResult,
    ToolResultsMessage,
    ToolSpec,
    UserMessage,
)
from slidemage.ai.anthropic_provider import AnthropicProvider
from slidemage.ai.providers import Cancelled, ProviderError

PNG = b"\x89PNG\r\n\x1a\n" + b"fake"
TOOL = ToolSpec("read_file", "Read a file.", {"type": "object", "properties": {"path": {"type": "string"}},
                                              "required": ["path"]})


@pytest.fixture
def server(server):
    server.content_type = "text/event-stream"
    return server


def provider(server, model="claude-sonnet-5-5"):
    p = AnthropicProvider(model, api_key="sk-test")
    p.base_url, p.max_retries = server.url, 0
    return p


def turn(p, messages, texts=None, tools=(TOOL,), system="Be brief."):
    return p.stream_turn(system, messages, list(tools), (texts if texts is not None else []).append)


@pytest.mark.parametrize("model, effort", [("claude-sonnet-5-5", True), ("claude-haiku-4-5-20251001", False)])
def test_the_request_has_tools_system_caching_and_effort(server, model, effort):
    server.body = message_sse([{"type": "text", "text": "Hello there"}])
    texts = []
    reply = turn(provider(server, model), [UserMessage("hi")], texts)
    body = server.requests[0]["body"]
    assert server.requests[0]["path"] == "/v1/messages" and api_key_of(server.requests[0]) == "sk-test"
    assert body["stream"] is True and body["system"] == "Be brief."
    assert body["cache_control"] == {"type": "ephemeral"}
    if effort:
        assert body["output_config"] == {"effort": "medium"}
    else:
        assert "output_config" not in body
    assert body["tools"] == [{"name": "read_file", "description": "Read a file.", "input_schema": TOOL.schema}]
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert "temperature" not in body and "thinking" not in body
    assert texts == ["Hello", " there"] and reply.text == "Hello there"
    assert reply.stop == "end_turn" and reply.tool_calls == []


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
    wait_for_first_piece(thread, texts)    # the first piece arrived; now the server says nothing more
    p.abort()
    thread.join(4)
    assert not thread.is_alive() and texts == ["Hello"]
    assert isinstance(outcome[0], Cancelled)


@pytest.mark.parametrize("stage", ["tls", "proxy_tls", "connect_tunnel"])
def test_abort_ends_stalled_connection_setup(monkeypatch, stage):
    try:
        stalled = StallingServer()
    except PermissionError:
        pytest.skip("sandbox forbids loopback sockets")
    proxy = None
    p = AnthropicProvider(api_key="sk-test")
    outcome = []
    # Isolate both uppercase and lowercase environment settings.
    for name in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "*")
    p.base_url = f"https://127.0.0.1:{stalled.address[1]}"
    worker = None
    try:
        if stage != "tls":
            monkeypatch.setenv("NO_PROXY", "")
            if stage == "proxy_tls":
                proxy = ConnectProxy(stalled.address)
                monkeypatch.setenv("HTTPS_PROXY", proxy.url)
            else:
                monkeypatch.setenv("HTTPS_PROXY", f"http://127.0.0.1:{stalled.address[1]}")
            p.base_url = "https://api.anthropic.test"

        def run():
            try:
                p.stream_turn("", [UserMessage("hi")], [], lambda _: None, timeout=60)
            except ProviderError as exc:
                outcome.append(exc)

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        assert stalled.received.wait(3), "no ClientHello / CONNECT received"
        assert p._sock is not None
        started = time.monotonic()
        p.abort()
        worker.join(1)
        assert not worker.is_alive() and time.monotonic() - started < 1
        assert len(outcome) == 1 and isinstance(outcome[0], Cancelled)
    finally:
        p.abort()
        stalled.close()
        if proxy:
            proxy.close()
        if worker:
            worker.join(2)


def test_abort_ends_a_pending_tcp_connect(monkeypatch):
    # TEST-NET-1: never a real API. Some networks reject immediately rather than
    # leaving the SYN pending; only a pending connection can exercise this case.
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("no_proxy", "*")
    p = AnthropicProvider(api_key="sk-test")
    p.base_url = "https://192.0.2.1:443"
    outcome = []
    try:
        with socket.socket():
            pass
    except PermissionError:
        pytest.skip("sandbox forbids sockets")

    def run():
        try:
            p.chat([{"role": "user", "content": "hi"}], timeout=60)
        except ProviderError as exc:
            outcome.append(exc)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 0.5
        while worker.is_alive() and time.monotonic() < deadline:
            worker.join(0.01)
        if not worker.is_alive() or p._sock is None:
            pytest.skip("network rejects the test address instead of leaving connect pending")
        # A completed TCP connection would have moved on to TLS; this test must
        # observe TCP setup itself, not another handshake timeout.
        if isinstance(p._sock, ssl.SSLSocket):
            pytest.skip("test address unexpectedly accepted TCP")
        started = time.monotonic()
        p.abort()
        worker.join(1)
        assert not worker.is_alive() and time.monotonic() - started < 1
        assert len(outcome) == 1 and isinstance(outcome[0], Cancelled)
    finally:
        p.abort()
        worker.join(2)


def test_abort_reaches_the_tls_socket_before_the_handshake(monkeypatch):
    p = AnthropicProvider(api_key="sk-test")
    entered, closed = threading.Event(), threading.Event()
    outcome = []

    class RawSocket:
        def setsockopt(self, *_args):
            pass

        def close(self):
            pass

    class TLSSocket:
        def do_handshake(self):
            assert p._sock is self
            entered.set()
            assert closed.wait(2), "abort did not close the TLS socket"
            raise OSError("handshake aborted")

        def shutdown(self, _how):
            closed.set()

        def close(self):
            closed.set()

    raw, tls = RawSocket(), TLSSocket()

    def create_socket(*_args):
        p._publish_socket(raw)
        return raw

    def wrap(_context, sock, *, server_hostname, do_handshake_on_connect):
        assert sock is raw and p._sock is raw
        assert server_hostname == "api.anthropic.com" and not do_handshake_on_connect
        return tls

    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("no_proxy", "*")
    monkeypatch.setattr(p, "_create_socket", create_socket)
    monkeypatch.setattr(ssl.SSLContext, "wrap_socket", wrap)
    monkeypatch.setattr("slidemage.ai.providers._shutdown_socket", lambda sock: sock.close() if sock else None)

    def run():
        try:
            p.chat([{"role": "user", "content": "hi"}], timeout=60)
        except ProviderError as exc:
            outcome.append(exc)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        assert entered.wait(2)
        p.abort()
        worker.join(1)
        assert not worker.is_alive() and len(outcome) == 1 and isinstance(outcome[0], Cancelled)
        assert p._sock is None
    finally:
        p.abort()
        closed.set()
        worker.join(2)


# -- the client's own work: retries, the stream's events, the blocks it keeps -----------------------

OVERLOADED = {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}


def start(usage=None):
    return {"type": "message_start", "message": {"id": "m", "type": "message", "role": "assistant", "content": [],
                                                 "usage": {"input_tokens": 5, "output_tokens": 1, **(usage or {})}}}


def block_start(index, block):
    return {"type": "content_block_start", "index": index, "content_block": block}


def delta(index, **fields):
    return {"type": "content_block_delta", "index": index, "delta": fields}


def stop(index):
    return {"type": "content_block_stop", "index": index}


END = [{"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 9}},
       {"type": "message_stop"}]


@pytest.fixture
def waits(monkeypatch):
    """The backoff waits asked for (not waited)."""
    recorded = []
    monkeypatch.setattr(AnthropicProvider, "_wait", lambda self, seconds: recorded.append(seconds))
    return recorded


def retrying(server):
    p = provider(server)
    p.max_retries = 2
    return p


def test_a_529_is_retried_and_the_second_try_answers(server, waits):
    server.script = [(529, OVERLOADED), (529, OVERLOADED), message_sse([{"type": "text", "text": "Hello"}])]
    reply = turn(retrying(server), [UserMessage("hi")])
    assert reply.text == "Hello" and len(server.requests) == 3
    assert 0.3 <= waits[0] <= 0.5 and 0.6 <= waits[1] <= 1.0      # 0.5 s, 1 s, each shortened by up to a quarter


def test_the_error_comes_after_the_retries_are_used_up(server, waits):
    server.status, server.content_type = 529, "application/json"
    server.body = OVERLOADED
    with pytest.raises(ProviderError, match="overloaded .*HTTP 529.*Overloaded"):
        turn(retrying(server), [UserMessage("hi")])
    assert len(server.requests) == 3 and len(waits) == 2


def test_a_400_is_not_retried(server, waits):
    server.status, server.content_type = 400, "application/json"
    server.body = {"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}}
    with pytest.raises(ProviderError, match="HTTP 400: bad"):
        turn(retrying(server), [UserMessage("hi")])
    assert len(server.requests) == 1 and not waits


def test_a_connection_error_is_retried_then_reported(server, waits):
    p = retrying(server)
    p.base_url = "http://127.0.0.1:9"
    with pytest.raises(ProviderError, match="Anthropic unreachable"):
        turn(p, [UserMessage("hi")])
    assert len(waits) == 2


def test_retry_after_is_honoured_and_capped(server, waits):
    ok = message_sse([{"type": "text", "text": "x"}])
    server.script = [(429, OVERLOADED, {"retry-after": "7"}), (429, OVERLOADED, {"retry-after": "900"}), ok]
    turn(retrying(server), [UserMessage("hi")])
    assert waits == [7.0, 60.0]


def test_nothing_is_retried_once_the_stream_has_started(server, waits):
    server.script = [sse_events(start(), block_start(0, {"type": "text", "text": ""}),
                                delta(0, type="text_delta", text="Hel"))]      # ends without message_stop
    texts = []
    with pytest.raises(ProviderError, match="ended the answer early"):
        turn(retrying(server), [UserMessage("hi")], texts)
    assert texts == ["Hel"] and len(server.requests) == 1 and not waits


def test_an_error_event_in_the_stream_is_an_error(server, waits):
    server.body = sse_events(start(), block_start(0, {"type": "text", "text": ""}),
                             delta(0, type="text_delta", text="Hi"), OVERLOADED)
    texts = []
    with pytest.raises(ProviderError, match="overloaded .*HTTP 529.*Overloaded"):
        turn(retrying(server), [UserMessage("hi")], texts)
    assert texts == ["Hi"] and len(server.requests) == 1


def test_unknown_events_and_deltas_are_ignored(server):
    server.body = ": a comment\n\n" + sse_events(
        start(), {"type": "ping"}, {"type": "something_new", "x": 1},
        block_start(0, {"type": "text", "text": ""}), delta(0, type="citations_delta", citation={"a": 1}),
        delta(0, type="text_delta", text="Hi"), delta(7, type="text_delta", text="nobody"), stop(0), *END)
    reply = turn(provider(server), [UserMessage("hi")])
    assert reply.text == "Hi" and reply.raw == [{"type": "text", "text": "Hi"}]
    assert reply.usage["output"] == 9 and reply.usage["input"] == 5


def test_a_tool_input_is_put_together_from_its_pieces(server):
    server.body = sse_events(
        start(), block_start(0, {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {}}),
        delta(0, type="input_json_delta", partial_json=""), delta(0, type="input_json_delta", partial_json='{"pa'),
        delta(0, type="input_json_delta", partial_json='th": "a/b'), delta(0, type="input_json_delta", partial_json='.tex"}'),
        stop(0),
        block_start(1, {"type": "tool_use", "id": "toolu_2", "name": "read_file", "input": {}}), stop(1),
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 4}},
        {"type": "message_stop"})
    reply = turn(provider(server), [UserMessage("hi")])
    assert reply.tool_calls == [ToolCall("toolu_1", "read_file", {"path": "a/b.tex"}),
                                ToolCall("toolu_2", "read_file", {})]
    assert reply.raw[0] == {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {"path": "a/b.tex"}}


def test_thinking_blocks_are_kept_and_replayed_unchanged(server):
    server.body = sse_events(
        start(), block_start(0, {"type": "thinking", "thinking": "", "signature": ""}),
        delta(0, type="thinking_delta", thinking="Let me "), delta(0, type="thinking_delta", thinking="see."),
        delta(0, type="signature_delta", signature="EuYBsig=="), stop(0),
        block_start(1, {"type": "redacted_thinking", "data": "opaque=="}), stop(1),
        block_start(2, {"type": "text", "text": ""}), delta(2, type="text_delta", text="Done."), stop(2),
        block_start(3, {"type": "future_block", "payload": [1, 2]}), stop(3),
        block_start(4, {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {}}),
        delta(4, type="input_json_delta", partial_json='{"path": "a"}'), stop(4),
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 4}},
        {"type": "message_stop"})
    p = provider(server)
    first = turn(p, [UserMessage("hi")])
    expected = [{"type": "thinking", "thinking": "Let me see.", "signature": "EuYBsig=="},
                {"type": "redacted_thinking", "data": "opaque=="},
                {"type": "text", "text": "Done."},
                {"type": "future_block", "payload": [1, 2]},
                {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {"path": "a"}}]
    assert first.raw == expected and first.text == "Done."
    server.body = message_sse([{"type": "text", "text": "next"}])
    turn(p, [UserMessage("hi"), first, ToolResultsMessage([ToolResult("toolu_1", "ok")])])
    sent = server.requests[1]["body"]["messages"][1]["content"]
    assert json.dumps(sent) == json.dumps(expected)


def test_abort_ends_the_wait_between_retries(server):
    server.script = [(529, OVERLOADED, {"retry-after": "30"})] * 3
    p = retrying(server)
    outcome = []

    def run():
        try:
            turn(p, [UserMessage("hi")])
        except ProviderError as exc:
            outcome.append(exc)

    thread = threading.Thread(target=run)
    started = time.monotonic()
    thread.start()
    while not server.requests and time.monotonic() - started < 5:
        time.sleep(0.01)
    time.sleep(0.1)         # now in the 30 s wait
    p.abort()
    thread.join(4)
    assert not thread.is_alive() and isinstance(outcome[0], Cancelled)
    assert len(server.requests) == 1 and time.monotonic() - started < 10
