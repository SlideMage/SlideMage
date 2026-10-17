"""A minimal MCP client over HTTP for the tests of the SlideMage MCP server (what Claude Code sends)."""
from __future__ import annotations

import http.client
import json

from slidemage.ai.mcp_server import McpServer


class Client:
    def __init__(self, server: McpServer) -> None:
        self.server = server
        self.next_id = 0

    def raw(self, body=None, headers=None, method="POST", path="/mcp", token=True):
        merged = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if token:
            merged["Authorization"] = f"Bearer {self.server.token}"
        merged.update(headers or {})
        connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=10)
        data = body if isinstance(body, bytes) else json.dumps(body).encode() if body is not None else None
        connection.request(method, path, body=data, headers=merged)
        response = connection.getresponse()
        text = response.read()
        connection.close()
        return response.status, (json.loads(text) if text else None)

    def rpc(self, method, params=None):
        self.next_id += 1
        status, body = self.raw({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or {}})
        assert status == 200, body
        return body

    def call(self, name, **arguments):
        body = self.rpc("tools/call", {"name": name, "arguments": arguments})
        return body["result"]

    def text(self, name, **arguments):
        result = self.call(name, **arguments)
        assert not result["isError"], result
        return result["content"][0]["text"]
