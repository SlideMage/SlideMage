"""SlideMage's MCP server for the embedded Claude Code (ai/mcp_server.py) over real HTTP on localhost: the
handshake, the token and host checks, each tool through tools/call on a throwaway project, and what it does
not do (no other methods, no GET, no foreign hosts). No Qt, no model."""
from __future__ import annotations

import base64

import pytest
from agent_fakes import FakeWorkspace
from conftest import SLIDE_TEXT
from mcp_client import Client

from slidemage import compiler, preview_target, slide_snapshot
from slidemage.ai.agent_types import EDIT_AUTO
from slidemage.ai.mcp_server import PROTOCOL_VERSIONS, McpServer
from slidemage.ai.tools import CLAUDE_CODE_READ_ONLY, CLAUDE_CODE_TOOLS, build_toolbox
from slidemage.ai.workspace import WorkspaceContext
from slidemage.deck_scan import scan_decks

SLIDE = "slides/abc-EN-Hello-current.tex"
LF = SLIDE_TEXT.replace("\r\n", "\n")


@pytest.fixture
def mcp(root):
    deck = next(d for d in scan_decks() if d.name == "test")
    workspace = FakeWorkspace(root, WorkspaceContext(deck=deck, slide_id="abc", path=root / SLIDE))
    server = McpServer(lambda: build_toolbox(workspace, lambda _e: None, compiler.CancelToken(), EDIT_AUTO,
                                             tools=CLAUDE_CODE_TOOLS))
    server.start()
    client = Client(server)
    client.workspace, client.root = workspace, root
    yield client
    server.stop()


# -- the transport -----------------------------------------------------------------------------------------

def test_the_server_listens_on_localhost_only_with_a_random_port(mcp):
    host, port = mcp.server._http.server_address
    assert host == "127.0.0.1" and port > 1024 and mcp.server.url == f"http://127.0.0.1:{port}/mcp"
    other = McpServer(lambda: None)
    other.start()
    try:
        assert other.port != mcp.server.port and other.token != mcp.server.token and len(other.token) >= 32
    finally:
        other.stop()


def test_a_request_without_the_right_token_is_refused(mcp):
    initialize = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    assert mcp.raw(initialize, token=False)[0] == 401
    assert mcp.raw(initialize, headers={"Authorization": "Bearer nope"})[0] == 401
    assert mcp.raw(initialize, headers={"Authorization": mcp.server.token})[0] == 401      # not a bearer header
    assert mcp.raw(initialize)[0] == 200


def test_a_foreign_host_header_is_refused(mcp):
    initialize = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    assert mcp.raw(initialize, headers={"Host": "evil.example"})[0] == 403
    assert mcp.raw(initialize, headers={"Host": f"localhost:{mcp.server.port}"})[0] == 200


def test_other_http_methods_and_paths_are_not_served(mcp):
    assert mcp.raw(method="GET")[0] == 405 and mcp.raw(method="DELETE")[0] == 405
    assert mcp.raw({"jsonrpc": "2.0", "id": 1, "method": "ping"}, path="/other")[0] == 404
    assert mcp.raw(b"{not json")[0] == 400
    assert mcp.raw([{"jsonrpc": "2.0", "id": 1, "method": "ping"}])[0] == 400       # no batches


# -- the protocol --------------------------------------------------------------------------------------------

def test_initialize_negotiates_the_version_and_offers_tools(mcp):
    result = mcp.rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}})["result"]
    assert result["protocolVersion"] == "2025-03-26" and result["serverInfo"]["name"] == "slidemage"
    assert "tools" in result["capabilities"]
    newer = mcp.rpc("initialize", {"protocolVersion": "2099-01-01"})["result"]
    assert newer["protocolVersion"] == PROTOCOL_VERSIONS[0]


def test_a_notification_gets_no_body_and_unknown_methods_an_error(mcp):
    status, body = mcp.raw({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert status == 202 and body is None
    assert mcp.rpc("server/discover")["error"]["code"] == -32601
    assert mcp.rpc("ping")["result"] == {}
    assert mcp.rpc("tools/call", {"arguments": {}})["error"]["code"] == -32602


def test_tools_list_names_the_claude_code_tools_with_their_schemas(mcp):
    tools = mcp.rpc("tools/list")["result"]["tools"]
    names = [t["name"] for t in tools]
    assert names == ["get_focus", "show_slide", "read_buffer", "list_slides", "lint", "render_preview", "read_guide", "add_slide", "translate_slide"]
    assert [t.spec.name for t in CLAUDE_CODE_READ_ONLY] == names[:-2]
    assert all(t["description"] and t["inputSchema"]["type"] == "object" for t in tools)
    # the chat's file tools are Claude Code's own, and the compile is not offered
    assert not {"read_file", "edit_file", "write_file", "compile_deck"} & set(names)


# -- the tools ------------------------------------------------------------------------------------------------

def test_get_focus_says_what_the_user_looks_at_and_whether_the_buffer_is_dirty(mcp):
    text = mcp.text("get_focus")
    assert "Open deck: decks/test.tex" in text and "Focused slide id: abc" in text
    assert f"File shown: {SLIDE}" in text and "Viewed as: instructor; editing language: EN" in text
    assert "unsaved" not in text and "Lint errors in the file: none" in text
    mcp.workspace.open(mcp.root / SLIDE, LF + "\\begin{itemize}\n", dirty=True)
    text = mcp.text("get_focus")
    assert "unsaved edits in the editor" in text and "Lint errors in the buffer: 1" in text and "line" in text


def test_get_focus_without_a_file(mcp):
    mcp.workspace._context = WorkspaceContext()
    text = mcp.text("get_focus")
    assert "Open deck: none" in text and "The editor shows no file." in text


def test_read_buffer_shows_unsaved_edits_and_only_of_open_files(mcp):
    assert "not open in the editor" in mcp.call("read_buffer", path=SLIDE)["content"][0]["text"]
    mcp.workspace.open(mcp.root / SLIDE, LF + "% typed in the editor\n", dirty=True)
    text = mcp.text("read_buffer", path=SLIDE)
    assert "unsaved edits: yes" in text and "% typed in the editor" in text
    mcp.workspace.dirty.clear()
    assert "unsaved edits: no" in mcp.text("read_buffer", path=SLIDE)
    assert mcp.call("read_buffer", path="../outside.tex")["isError"]


def test_render_preview_comes_back_as_an_image_content(mcp, monkeypatch):
    monkeypatch.setattr(preview_target, "render_text", lambda *a, **k: mcp.root / "x.pdf")
    monkeypatch.setattr(slide_snapshot, "page_png", lambda pdf, width: b"\x89PNG-bytes")
    content = mcp.call("render_preview")["content"]
    assert content[0]["type"] == "text" and content[1]["type"] == "image"
    assert content[1]["mimeType"] == "image/png" and base64.b64decode(content[1]["data"]) == b"\x89PNG-bytes"


def test_add_slide_goes_through_and_a_failing_tool_is_an_error_result_not_a_crash(mcp):
    out = mcp.text("add_slide", slug="Capital-Budgeting", title="Capital budgeting", after="abc")
    assert "Created slide" in out and list((mcp.root / "slides").glob("*-EN-Capital-Budgeting-current.tex"))
    assert mcp.workspace.changed                      # the window is told what was written
    unknown = mcp.call("compile_deck")
    assert unknown["isError"] and "no tool 'compile_deck'" in unknown["content"][0]["text"]
    assert mcp.call("lint", path="slides/zzz-EN-Missing-current.tex")["isError"]


def test_the_toolbox_is_made_afresh_for_every_call(root):
    made = []
    workspace = FakeWorkspace(root, WorkspaceContext(path=root / SLIDE))

    def make():
        made.append(1)
        return build_toolbox(workspace, lambda _e: None, compiler.CancelToken(), tools=CLAUDE_CODE_TOOLS)

    server = McpServer(make)
    server.start()
    try:
        client = Client(server)
        client.rpc("tools/list")
        client.text("get_focus")
        client.text("get_focus")
        assert len(made) == 3
    finally:
        server.stop()


def test_a_failure_inside_a_request_is_an_error_response_not_a_dropped_connection(root):
    def broken():
        raise RuntimeError("the window is gone")

    server = McpServer(broken)
    server.start()
    try:
        client = Client(server)
        status, body = client.raw({"jsonrpc": "2.0", "id": 7, "method": "tools/list"})
        assert status == 200 and body["id"] == 7 and "the window is gone" in body["error"]["message"]
    finally:
        server.stop()
