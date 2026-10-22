# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""A throwaway local HTTP server standing in for Ollama and the Anthropic API (no external
network), and the streaming wire formats of both for it to answer with."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Server:
    """Answers every request with `status`/`body` (or, for a path in `routes`, with that route's
    (status, body); a `script` of bodies is used up first, one per request) and records what it got."""

    def __init__(self):
        self.status = 200
        self.body: dict | str = {}
        self.content_type = "application/json"
        self.delay = threading.Event()  # set to release a held response
        self.hold = False
        self.stall_after: int | None = None   # answer only this many bytes of the body, then wait
        self.script: list[dict | str] = []   # bodies for the next requests, in turn (else `body`)
        self.routes: dict[str, tuple[int, dict | str]] = {}
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                outer.requests.append({
                    "method": self.command, "path": self.path,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": json.loads(raw) if raw else None})
                if outer.hold:
                    outer.delay.wait(5)
                status, body = outer.routes.get(self.path, (outer.status, outer.body))
                if outer.script:
                    body = outer.script.pop(0)
                data = (body if isinstance(body, str) else json.dumps(body)).encode()
                try:
                    if outer.stall_after is not None:      # a stream that goes quiet in the middle
                        self.send_response(status)
                        self.send_header("Content-Type", outer.content_type)
                        self.end_headers()
                        self.wfile.write(data[:outer.stall_after])
                        self.wfile.flush()
                        outer.delay.wait(5)
                        return
                    self.send_response(status)
                    self.send_header("Content-Type", outer.content_type)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass  # the client aborted

            do_GET = do_POST = _answer

            def log_message(self, *_args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(
            target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        ).start()

    def close(self):
        self.delay.set()
        self.httpd.shutdown()
        self.httpd.server_close()


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


def message_sse(content: list[dict], stop_reason: str = "end_turn", usage: dict | None = None) -> str:
    """The server-sent events of a streamed message made of `content` blocks: {"type": "text",
    "text"} (streamed in two pieces) or {"type": "tool_use", "id", "name", "input"}."""
    usage = {"input_tokens": 10, "output_tokens": 1, **(usage or {})}
    out = [_event("message_start", {"type": "message_start", "message": {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-test", "content": [],
        "stop_reason": None, "stop_sequence": None, "usage": usage}})]
    for index, block in enumerate(content):
        if block["type"] == "text":
            half = len(block["text"]) // 2
            out.append(_event("content_block_start", {"type": "content_block_start", "index": index,
                                                      "content_block": {"type": "text", "text": ""}}))
            for piece in (block["text"][:half], block["text"][half:]):
                out.append(_event("content_block_delta", {"type": "content_block_delta", "index": index,
                                                          "delta": {"type": "text_delta", "text": piece}}))
        else:
            out.append(_event("content_block_start", {"type": "content_block_start", "index": index,
                                                      "content_block": {**block, "input": {}}}))
            out.append(_event("content_block_delta", {"type": "content_block_delta", "index": index,
                                                      "delta": {"type": "input_json_delta",
                                                                "partial_json": json.dumps(block["input"])}}))
        out.append(_event("content_block_stop", {"type": "content_block_stop", "index": index}))
    out.append(_event("message_delta", {"type": "message_delta",
                                        "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                                        "usage": {"output_tokens": usage["output_tokens"]}}))
    out.append(_event("message_stop", {"type": "message_stop"}))
    return "".join(out)


def ollama_ndjson(pieces=(), tool_calls=(), done_reason: str = "stop") -> str:
    """The lines /api/chat streams: one per text piece, then one carrying `tool_calls` (a list of
    (name, arguments) pairs, each whole), then the closing statistics."""
    lines = [{"model": "m", "message": {"role": "assistant", "content": piece}, "done": False}
             for piece in pieces]
    if tool_calls:
        lines.append({"model": "m", "done": False, "message": {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": name, "arguments": arguments}} for name, arguments in tool_calls]}})
    lines.append({"model": "m", "message": {"role": "assistant", "content": ""}, "done": True,
                  "done_reason": done_reason, "prompt_eval_count": 12, "eval_count": 5})
    return "".join(json.dumps(line) + "\n" for line in lines)


def api_key_of(request) -> str:
    """The key a request carries: the anthropic SDK sends it as x-api-key up to 1.x, as a Bearer token from 2.0."""
    headers = request["headers"]
    return headers.get("x-api-key") or headers.get("authorization", "").removeprefix("Bearer ")


def wait_for_first_piece(thread, texts, seconds=5.0):
    """Until the streaming thread has handed over its first text; fails instead of spinning when it ended without."""
    end = time.monotonic() + seconds
    while not texts:
        assert thread.is_alive(), "the stream ended before its first piece"
        assert time.monotonic() < end, "no first piece in time"
        thread.join(0.01)
