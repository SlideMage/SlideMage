# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""SlideMage's MCP server for the embedded Claude Code (UI redesign step 10c): a local HTTP endpoint that
speaks the Model Context Protocol ("streamable HTTP" transport, JSON responses) and offers the tools of
`ai/tools` to the one client that holds its secret. No Qt.

Hand-written instead of the official `mcp` package: the server needs four methods (initialize, ping,
tools/list, tools/call), the package brings starlette, uvicorn, pydantic-settings and more into the app and
into the PyInstaller bundle, and a stateless JSON-RPC handler on `http.server` is ~150 lines the tests cover.

Safety. The server binds 127.0.0.1 only, on a random port; every request must carry
`Authorization: Bearer <token>` (a fresh random secret per server, compared in constant time) and a Host header
naming the loopback address (against DNS rebinding from a web page). The tools run on the request's thread;
the workspace marshals GUI work (ai/workspace.py), so a call that waits for the GUI never blocks the server.
"""
from __future__ import annotations

import base64
import hmac
import json
import secrets
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .agent_types import ToolCall
from .tools.base import ToolBox

PATH = "/mcp"
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")     # newest first
MAX_BODY = 1_000_000
JSONRPC_PARSE_ERROR, JSONRPC_INVALID, JSONRPC_NO_METHOD, JSONRPC_BAD_PARAMS, JSONRPC_INTERNAL = (
    -32700, -32600, -32601, -32602, -32603)


def _image_type(data: bytes) -> str:
    return "image/png" if data.startswith(b"\x89PNG") else "image/jpeg"


class McpServer:
    def __init__(self, make_toolbox: Callable[[], ToolBox], name: str = "slidemage", version: str = "1") -> None:
        """`make_toolbox()` gives the tools for one call (it refreshes what the tools see of the
        window); it runs on the request's thread."""
        self._make_toolbox = make_toolbox
        self._info = {"name": name, "version": version}
        self.token = secrets.token_urlsafe(32)
        self._http: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # -- life ---------------------------------------------------------------------------------

    def start(self) -> str:
        """Listen on a free port of 127.0.0.1 and return the URL."""
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                server._post(self)

            def do_GET(self) -> None:           # no server-initiated stream, no sessions to close
                server._reply(self, 405, {"error": "this server only answers POST"}, {"Allow": "POST"})

            do_DELETE = do_GET

            def log_message(self, *_args) -> None:
                pass

        self._http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._http.daemon_threads = True
        self._thread = threading.Thread(target=self._http.serve_forever, kwargs={"poll_interval": 0.05},
                                        name="mcp-server", daemon=True)
        self._thread.start()
        return self.url

    @property
    def port(self) -> int:
        return self._http.server_address[1]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}{PATH}"

    def stop(self) -> None:
        if self._http is not None:
            self._http.shutdown()
            self._http.server_close()
            self._http = None

    # -- HTTP ----------------------------------------------------------------------------------

    @staticmethod
    def _reply(handler: BaseHTTPRequestHandler, status: int, body: dict | None, headers: dict | None = None) -> None:
        data = json.dumps(body).encode("utf-8") if body is not None else b""
        handler.send_response(status)
        if body is not None:
            handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(data)))
        for key, value in (headers or {}).items():
            handler.send_header(key, value)
        handler.end_headers()
        handler.wfile.write(data)

    def _post(self, handler: BaseHTTPRequestHandler) -> None:
        if handler.headers.get("Host", "") not in (f"127.0.0.1:{self.port}", f"localhost:{self.port}"):
            return self._reply(handler, 403, {"error": "wrong host"})
        given = handler.headers.get("Authorization", "")
        if not hmac.compare_digest(given.encode(), f"Bearer {self.token}".encode()):
            return self._reply(handler, 401, {"error": "missing or wrong token"}, {"WWW-Authenticate": "Bearer"})
        if handler.path.split("?")[0] != PATH:
            return self._reply(handler, 404, {"error": "not found"})
        try:
            length = int(handler.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                raise ValueError(length)
            message = json.loads(handler.rfile.read(length))
        except ValueError:
            return self._reply(handler, 400, self._error(None, JSONRPC_PARSE_ERROR, "invalid JSON"))
        if not isinstance(message, dict):         # batches are not part of the 2025-06-18 transport
            return self._reply(handler, 400, self._error(None, JSONRPC_INVALID, "expected one JSON-RPC message"))
        try:
            answer = self.handle(message)
        except Exception as exc:  # noqa: BLE001 -- a failure inside a request must not drop the connection
            answer = self._error(message.get("id"), JSONRPC_INTERNAL, f"{type(exc).__name__}: {exc}")
        self._reply(handler, 202 if answer is None else 200, answer)

    # -- JSON-RPC ------------------------------------------------------------------------------

    @staticmethod
    def _error(request_id, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    def handle(self, message: dict) -> dict | None:
        """The response to one JSON-RPC message; None for a notification (or a response) -- nothing to say."""
        method, params, request_id = message.get("method"), message.get("params") or {}, message.get("id")
        if "id" not in message or not isinstance(method, str):
            return None
        if not isinstance(params, dict):
            return self._error(request_id, JSONRPC_BAD_PARAMS, "params must be an object")
        if method == "initialize":
            asked = params.get("protocolVersion")
            result = {"protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                      "capabilities": {"tools": {"listChanged": False}}, "serverInfo": self._info}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": [{"name": s.name, "description": s.description, "inputSchema": s.schema}
                                for s in self._make_toolbox().specs]}
        elif method == "tools/call":
            if not isinstance(params.get("name"), str) or not isinstance(params.get("arguments") or {}, dict):
                return self._error(request_id, JSONRPC_BAD_PARAMS, "tools/call needs a tool name and arguments")
            result = self._call(params["name"], params.get("arguments") or {})
        else:
            return self._error(request_id, JSONRPC_NO_METHOD, f"unknown method {method}")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _call(self, name: str, arguments: dict) -> dict:
        outcome = self._make_toolbox().execute(ToolCall(secrets.token_hex(4), name, arguments))
        content: list[dict] = [{"type": "text", "text": outcome.text}]
        content += [{"type": "image", "data": base64.b64encode(png).decode("ascii"), "mimeType": _image_type(png)}
                    for png in outcome.images]
        return {"content": content, "isError": outcome.is_error}
