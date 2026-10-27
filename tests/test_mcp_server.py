# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""SlideMage's MCP server for the embedded Claude Code (ai/mcp_server.py) over real HTTP on localhost: the
handshake, the token and host checks, each tool through tools/call on a throwaway project, and what it does
not do (no other methods, no GET, no foreign hosts). No Qt, no model."""
from __future__ import annotations

import base64

import pytest
from agent_fakes import FakeWorkspace
from conftest import SLIDE_TEXT
from slidemage.project import ProjectContext
from mcp_client import Client

from slidemage import compiler, deck_editor, preview_target, slide_add, slide_snapshot
from slidemage.ai.agent_types import EDIT_AUTO
from slidemage.ai.mcp_server import PROTOCOL_VERSIONS, McpServer
from slidemage.ai.tools import CLAUDE_CODE_READ_ONLY, CLAUDE_CODE_TOOLS, build_toolbox
from slidemage.ai.workspace import WorkspaceContext
from slidemage.deck_scan import scan_decks


@pytest.fixture
def ctx(root):
    return ProjectContext.at(root)

SLIDE = "slides/abc-EN-Hello-current.tex"
LF = SLIDE_TEXT.replace("\r\n", "\n")


@pytest.fixture
def mcp_tools(root, monkeypatch):
    """Exercise the real JSON-RPC tool handler without a listening socket or model."""
    deck = next(d for d in scan_decks(ProjectContext.at(root)) if d.name == "test")
    workspace = FakeWorkspace(root, WorkspaceContext(deck=deck, slide_id="abc", path=root / SLIDE))
    server = McpServer(lambda: build_toolbox(workspace, lambda _e: None, compiler.CancelToken(), EDIT_AUTO,
                                            tools=CLAUDE_CODE_TOOLS))
    client = Client(server)
    client.workspace, client.root = workspace, root
    monkeypatch.setattr(client, "raw", lambda body: (200, server.handle(body)))
    return client


@pytest.fixture
def mcp(root):
    deck = next(d for d in scan_decks(ProjectContext.at(root)) if d.name == "test")
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


def test_tools_list_names_the_claude_code_tools_with_their_schemas(mcp_tools):
    tools = mcp_tools.rpc("tools/list")["result"]["tools"]
    names = [t["name"] for t in tools]
    assert names == ["get_focus", "show_slide", "read_buffer", "read_selection", "list_slides", "lint", "render_preview", "refresh_preview", "check_readability", "read_guide", "add_slide", "create_slide", "modify_slide", "make_qr_code", "translate_slide", "switch_to_deck_mode", "refresh_deck_previews"]
    assert [t.spec.name for t in CLAUDE_CODE_READ_ONLY] == names[:-7]
    assert all(t["description"] and t["inputSchema"]["type"] == "object" for t in tools)
    # the chat's file tools are Claude Code's own, and the compile is not offered
    assert not {"read_file", "edit_file", "write_file", "compile_deck"} & set(names)


def test_terminal_tool_instructions_name_only_available_tools(mcp_tools):
    mcp = mcp_tools
    tools = mcp.rpc("tools/list")["result"]["tools"]
    for spec in tools:
        text = str(spec)
        assert not any(name in text for name in ("edit_file", "write_file", "read_file", "find_files"))
    focus = next(t for t in tools if t["name"] == "get_focus")
    assert "missing or stale" in focus["description"] and "Call it first" not in focus["description"]
    for args in ({"slug": "Skeleton", "title": "T", "add_to_deck": False},
                 {"slug": "Translation", "title": "T", "language": "DE", "translation_of": "abc"}):
        text = mcp.text("add_slide", **args)
        assert "edit_file" not in text and "write_file" not in text


# -- the tools ------------------------------------------------------------------------------------------------

def test_get_focus_says_what_the_user_looks_at_and_whether_the_buffer_is_dirty(mcp):
    text = mcp.text("get_focus")
    assert "Open deck: decks/test.tex" in text and "Focused slide id: abc" in text
    assert f"File shown: {SLIDE}" in text and "Viewed as: instructor; editing language: EN" in text
    assert "unsaved" not in text and "Lint errors in file: none" in text
    mcp.workspace.open(mcp.root / SLIDE, LF + "\\begin{itemize}\n", dirty=True)
    text = mcp.text("get_focus")
    assert "unsaved edits in the editor" in text and "Lint errors in editor (unsaved): 1" in text and "line" in text


def test_get_focus_without_a_file(mcp):
    mcp.workspace._context = WorkspaceContext()
    text = mcp.text("get_focus")
    assert "Open deck: none" in text and "The editor shows no file." in text


def test_read_buffer_shows_unsaved_edits_and_only_of_open_files(mcp):
    assert "not open in the editor" in mcp.call("read_buffer", path=SLIDE)["content"][0]["text"]
    mcp.workspace.open(mcp.root / SLIDE, LF + "% typed in the editor\n", dirty=True)
    text = mcp.text("read_buffer", path=SLIDE)
    assert "editor (unsaved)" in text and "% typed in the editor" in text
    mcp.workspace.dirty.clear()
    assert "; file)" in mcp.text("read_buffer", path=SLIDE)
    assert mcp.call("read_buffer", path="../outside.tex")["isError"]


def test_render_preview_comes_back_as_an_image_content(mcp_tools, monkeypatch):
    mcp = mcp_tools
    monkeypatch.setattr(preview_target, "render_text", lambda *a, **k: mcp.root / "x.pdf")
    monkeypatch.setattr(slide_snapshot, "prepare_preview_images",
                        lambda *a: ((b"\x89PNG-bytes", b"\x89PNG-bytes"), ()))
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


@pytest.mark.parametrize("error", [deck_editor.StaleFileError, OSError, ValueError])
@pytest.mark.parametrize("retry", ["id", "id_slug", "path"])
def test_failed_insertion_returns_existing_slide_and_retry_never_duplicates(mcp_tools, monkeypatch, error, retry):
    mcp = mcp_tools
    deck = mcp.root / "decks/test.tex"
    original_insert = deck_editor.insert_slide_call
    original_deck = deck.read_bytes()

    def fail(*args, **kwargs):
        raise error("insertion failed")

    monkeypatch.setattr(deck_editor, "insert_slide_call", fail)
    result = mcp.call("add_slide", slug="Retry", title="T", after="abc")
    assert result["isError"]
    created, = (mcp.root / "slides").glob("*-EN-Retry-current.tex")
    id_slug = created.name.removesuffix("-current.tex")
    path = created.relative_to(mcp.root).as_posix()
    text = result["content"][0]["text"]
    assert id_slug in text and path in text and f"add_slide(existing='{id_slug}', after='abc')" in text
    assert (created, None) in mcp.workspace.changed and deck.read_bytes() == original_deck
    id_store = mcp.workspace.project.slide_ids_csv.read_bytes()
    slide_text = created.read_bytes()
    monkeypatch.setattr(deck_editor, "insert_slide_call", original_insert)
    existing = {"id": id_slug[:3], "id_slug": id_slug, "path": path}[retry]
    assert "Inserted slide" in mcp.text("add_slide", existing=existing, after="abc")
    inserted = deck.read_bytes()
    # The second retry is safe even if its anchor no longer exists.
    assert "already in test" in mcp.text("add_slide", existing=existing, after="zzz")
    calls = deck_editor.parse_slide_calls(next(d for d in scan_decks(mcp.workspace.project) if d.name == "test"))
    assert [c.id_slug for c in calls] == ["abc-EN-Hello", id_slug, "abd-EN-Second"]
    assert deck.read_bytes() == inserted and created.read_bytes() == slide_text
    assert mcp.workspace.project.slide_ids_csv.read_bytes() == id_store
    assert list((mcp.root / "slides").glob("*-EN-Retry-current.tex")) == [created]


def test_deck_becoming_dirty_after_creation_returns_recoverable_error(mcp_tools, monkeypatch):
    mcp = mcp_tools
    deck = mcp.root / "decks/test.tex"
    before = deck.read_bytes()
    create = slide_add.create_new

    def become_dirty(*args, **kwargs):
        created = create(*args, **kwargs)
        mcp.workspace.open(deck, "unsaved deck edits", dirty=True)
        return created

    monkeypatch.setattr(slide_add, "create_new", become_dirty)
    result = mcp.call("add_slide", slug="Dirty", title="T")
    assert result["isError"] and "unsaved edits" in result["content"][0]["text"]
    created, = (mcp.root / "slides").glob("*-EN-Dirty-current.tex")
    assert created.name in result["content"][0]["text"] and "existing=" in result["content"][0]["text"]
    assert deck.read_bytes() == before and mcp.workspace.buffer_text(deck) == "unsaved deck edits"
    assert mcp.call("add_slide", existing=created.relative_to(mcp.root).as_posix())["isError"]
    mcp.workspace.dirty.clear()
    assert "Inserted slide" in mcp.text("add_slide", existing=created.relative_to(mcp.root).as_posix())


def test_real_stale_deck_during_creation_keeps_newer_text_and_allows_retry(mcp_tools, monkeypatch):
    mcp = mcp_tools
    deck = mcp.root / "decks/test.tex"
    newer = deck.read_text() + "% changed while creating\n"
    create = slide_add.create_new

    def change_deck(*args, **kwargs):
        created = create(*args, **kwargs)
        deck.write_text(newer)
        return created

    monkeypatch.setattr(slide_add, "create_new", change_deck)
    result = mcp.call("add_slide", slug="Stale", title="T")
    assert result["isError"] and "existing=" in result["content"][0]["text"]
    created, = (mcp.root / "slides").glob("*-EN-Stale-current.tex")
    assert deck.read_text() == newer
    assert "Inserted slide" in mcp.text("add_slide", existing=created.relative_to(mcp.root).as_posix())
    assert "% changed while creating\n" in deck.read_text()
    assert list((mcp.root / "slides").glob("*-EN-Stale-current.tex")) == [created]


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


@pytest.mark.parametrize('hidden,failed', [(False, False), (True, False), (False, True)])
def test_all_preview_images_are_labelled_through_mcp_serialization(mcp_tools, monkeypatch, hidden, failed):
    client = mcp_tools
    if hidden:
        deck = client.workspace.context().deck.path
        deck.write_text(deck.read_text().replace(r'\slide{abc-EN-Hello}',
                        r'\conditionalslide[instructor,after-course]{abc-EN-Hello}'))
    seen = []

    def render(target, text, view, language, **kwargs):
        seen.append((view, text))
        if failed and view == 'during-course':
            raise RuntimeError('! During course failed')
        return client.root / f'{view}.pdf'

    monkeypatch.setattr(preview_target, 'render_text', render)
    monkeypatch.setattr(slide_snapshot, 'prepare_preview_images',
                        lambda pdf, *a: ((b'\x89PNG-' + pdf.stem.encode(),) * 2, ()))
    draft = LF + '% captured draft\n'
    client.workspace.open(client.root / SLIDE, draft)
    original_context = client.workspace.context()
    response = client.call('render_preview', view='all')
    assert not response['isError']
    text = response['content'][0]['text']
    expected = ['instructor', 'after-course'] if hidden or failed else ['instructor', 'during-course', 'after-course']
    images = response['content'][1:]
    assert [base64.b64decode(item['data']) for item in images] == [b'\x89PNG-' + v.encode() for v in expected]
    for index, view in enumerate(expected, 1):
        assert f'image #{index} = {view}, EN' in text
    assert text.index('abc: instructor') < text.index('abc: during-course') < text.index('abc: after-course')
    if hidden:
        assert 'during-course, EN: hidden;' in text
    if failed:
        assert 'during-course, EN: failed;' in text and '! During course failed' in text
    assert all(source == draft for _, source in seen)
    assert client.workspace.context() == original_context


def test_explicit_during_course_preview_returns_that_view(mcp_tools, monkeypatch):
    client = mcp_tools
    seen = []
    monkeypatch.setattr(preview_target, 'render_text',
                        lambda target, text, view, *a, **kw: seen.append(view) or client.root / 'x.pdf')
    monkeypatch.setattr(slide_snapshot, 'prepare_preview_images',
                        lambda *a: ((b'\x89PNG-during',) * 2, ()))
    result = client.call('render_preview', view='during-course')
    assert not result['isError'] and seen == ['during-course']
    assert 'image #1 = during-course, EN' in result['content'][0]['text']
    assert base64.b64decode(result['content'][1]['data']) == b'\x89PNG-during'


@pytest.mark.parametrize('selected', ['instructor', 'during-course', 'after-course'])
def test_claude_refresh_without_view_populates_every_course_view(mcp_tools, monkeypatch, selected):
    from dataclasses import replace
    client = mcp_tools
    client.workspace._context = replace(client.workspace.context(), view=selected)
    seen = []
    monkeypatch.setattr(preview_target, 'render_text',
                        lambda target, text, view, *a, **kw: seen.append(view) or client.root / f'{view}.pdf')
    monkeypatch.setattr(slide_snapshot, 'prepare_preview_images', lambda *a: ((b'PNG', b'PNG'), ()))
    response = client.call('refresh_preview')
    assert not response['isError']
    assert sorted(seen) == sorted(['instructor', 'during-course', 'after-course'])                            # the views render at once, in any order
    assert len(response['content']) == 1  # refresh reports statuses; render_preview returns images
    text = response['content'][0]['text']
    assert all(f'abc: {view}, EN: rendered' in text for view in seen)
    assert client.workspace.context().view == selected


def test_claude_refresh_with_explicit_instructor_stays_single_view(mcp_tools, monkeypatch):
    client = mcp_tools
    seen = []
    monkeypatch.setattr(preview_target, 'render_text',
                        lambda target, text, view, *a, **kw: seen.append(view) or client.root / 'x.pdf')
    monkeypatch.setattr(slide_snapshot, 'prepare_preview_images', lambda *a: ((b'PNG', b'PNG'), ()))
    response = client.call('refresh_preview', view='instructor')
    assert not response['isError'] and seen == ['instructor']
    assert 'abc: instructor, EN: rendered' in response['content'][0]['text']


def test_slide_scope_refuses_another_slide_over_http(root):
    deck = next(d for d in scan_decks(ProjectContext.at(root)) if d.name == "test")
    workspace = FakeWorkspace(root, WorkspaceContext(deck=deck, slide_id="abc", path=root / SLIDE))

    def toolbox():
        box = build_toolbox(workspace, lambda _e: None, compiler.CancelToken(), EDIT_AUTO, tools=CLAUDE_CODE_TOOLS)
        box.ctx.scope, box.ctx.focus_slide = "slide", root / SLIDE
        return box

    server = McpServer(toolbox)
    server.start()
    try:
        result = Client(server).call("modify_slide", slide="abd", edits=[{"old": "First", "new": "Changed"}])
        assert result["isError"] and "switch_to_deck_mode" in result["content"][0]["text"]
        assert "First" in (root / "slides/abd-EN-Second-current.tex").read_text()
    finally:
        server.stop()


def test_slide_scope_refusal_in_mcp_handler(mcp_tools):
    original = mcp_tools.server._make_toolbox

    def toolbox():
        box = original()
        box.ctx.scope, box.ctx.focus_slide = "slide", mcp_tools.root / SLIDE
        return box

    mcp_tools.server._make_toolbox = toolbox
    result = mcp_tools.call("modify_slide", slide="abd", edits=[{"old": "First", "new": "Changed"}])
    assert result["isError"] and "switch_to_deck_mode" in result["content"][0]["text"]
