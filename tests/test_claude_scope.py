# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Slide / Deck scope of the embedded Claude Code: the focus file, the context block of
every prompt, and the edit guard of the hook."""
from __future__ import annotations

import io
import json

from slidemage.ai import claude_hook, claude_scope


def publish(tmp_path, scope, slide="slides/1aa-EN-One-current.tex", dirty=False):
    file = tmp_path / "focus.json"
    claude_scope.publish(file, scope, tmp_path, "1aa", tmp_path / slide if slide else None,
                         tmp_path / "decks" / "course.tex", "instructor", "EN", dirty)
    return file


def test_slide_scope_names_the_file_and_forbids_exploring(tmp_path):
    data = claude_scope.load(publish(tmp_path, "slide", dirty=True))
    text = claude_scope.prompt_context(data)
    assert "THIS SLIDE" in text and "slides/1aa-EN-One-current.tex" in text
    assert "read_buffer" in text and "do not explore" in text


def test_deck_scope_allows_the_deck(tmp_path):
    text = claude_scope.prompt_context(claude_scope.load(publish(tmp_path, "deck")))
    assert "WHOLE DECK" in text and "decks/course.tex" in text and "do not explore" not in text


def test_no_slide_in_focus(tmp_path):
    text = claude_scope.prompt_context(claude_scope.load(publish(tmp_path, "slide", slide=None)))
    assert "No slide is in focus" in text


def test_edit_guard_only_in_slide_scope(tmp_path):
    other = tmp_path / "slides" / "2bb-EN-Two-current.tex"
    own = tmp_path / "slides" / "1aa-EN-One-current.tex"
    slide = claude_scope.load(publish(tmp_path, "slide"))
    deck = claude_scope.load(publish(tmp_path, "deck"))
    assert "outside it" in claude_scope.edit_problem(slide, tmp_path, other)
    assert claude_scope.edit_problem(slide, tmp_path, tmp_path / "decks" / "course.tex")
    assert claude_scope.edit_problem(slide, tmp_path, own) is None
    assert claude_scope.edit_problem(slide, tmp_path, tmp_path / "Slidemaster.bib") is None
    assert claude_scope.edit_problem(deck, tmp_path, other) is None
    assert claude_scope.edit_problem(None, tmp_path, other) is None


def test_hook_prints_the_context_for_a_prompt(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(claude_scope.FOCUS_ENV, str(publish(tmp_path, "slide")))
    event = json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "make it shorter"})
    monkeypatch.setattr("sys.stdin", type("S", (), {"buffer": io.BytesIO(event.encode())})())
    assert claude_hook.main() == 0
    assert "THIS SLIDE" in capsys.readouterr().out


def test_failed_focus_publish_is_retried_without_a_focus_change(qapp, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from slidemage.project import ProjectContext
    from slidemage.ui.workspace.terminal.session import ClaudeCodeSession
    from slidemage.ai import claude_launch
    from slidemage.ai.mcp_server import McpServer

    window = SimpleNamespace(
        project=ProjectContext.at(tmp_path),
        state=SimpleNamespace(deck=None, focused_slide="abc", view="instructor", language="EN"),
        centre=SimpleNamespace(path=tmp_path / "slides/abc-EN-Hello-current.tex", is_dirty=lambda path: False))
    host, context = session_services(window)
    session = ClaudeCodeSession(host, context, tmp_path / "fake-claude", claude_launch, claude_scope, McpServer, claude_launch.hook_command)
    session._focus_file = tmp_path / "focus.json"
    changed, attempts = [], []
    session.focus_changed.connect(lambda: changed.append(True))
    publish = claude_scope.publish

    def fail_once(*args):
        attempts.append(args)
        if len(attempts) == 1:
            raise OSError("write failed")
        publish(*args)

    monkeypatch.setattr(claude_scope, "publish", fail_once)
    try:
        session.publish_focus()
        assert session._published is None and not changed and not session._focus_file.exists()
        session.publish_focus()
        assert session._published is not None and changed == [True] and len(attempts) == 2
        assert claude_scope.load(session._focus_file)["slide_id"] == "abc"
        session.publish_focus()
        assert len(attempts) == 2 and changed == [True]
    finally:
        session.shutdown()


def test_a_restart_resumes_the_conversation_only_when_claude_code_saved_it(qapp, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from slidemage.project import ProjectContext
    from slidemage.ui.workspace.terminal import session as session_mod
    from slidemage.ui.workspace.terminal import service as service_mod

    started = []

    class FakeServer:
        url, token = "http://127.0.0.1:1/mcp", "t"

        def __init__(self, _toolbox):
            pass

        def start(self):
            pass

        def stop(self):
            pass

    class FakePty:
        alive = True

        def __init__(self, command, *_args):
            started.append(command)

        def stop(self):
            pass

    monkeypatch.setattr(service_mod, "PtyProcess", FakePty)      # the terminal service starts the process
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "config"))
    window = SimpleNamespace(
        project=ProjectContext.at(tmp_path),
        state=SimpleNamespace(deck=None, focused_slide=None, view="instructor", language="EN"),
        centre=SimpleNamespace(path=None, is_dirty=lambda path: False))
    from slidemage.ai import claude_launch
    host, context = session_services(window)
    session = session_mod.ClaudeCodeSession(host, context, tmp_path / "fake-claude", claude_launch, claude_scope, FakeServer, claude_launch.hook_command)
    session._sync = SimpleNamespace(start=lambda: None, stop=lambda last_look=True: None)
    try:
        session.start(80, 24)
        first = session.session_id
        assert started[-1][1:3] == ["--session-id", first]
        session.start(80, 24, resume=True)                     # nothing was sent yet: no transcript to resume
        assert session.session_id != first and started[-1][1:3] == ["--session-id", session.session_id]
        transcript = tmp_path / "config" / "projects" / "proj" / f"{session.session_id}.jsonl"
        transcript.parent.mkdir(parents=True)
        transcript.write_text("{}\n", encoding="utf-8")
        kept = session.session_id
        session.start(80, 24, resume=True)
        assert session.session_id == kept and started[-1][1:3] == ["--resume", kept]
        session.start(80, 24)                                  # Restart: a new conversation
        assert session.session_id != kept and started[-1][1] == "--session-id"
    finally:
        session.shutdown()


def session_services(window):
    from types import SimpleNamespace
    from slidemage.ai import ai_profile
    from slidemage.plugin_api import ChatFocus
    from slidemage.ui.workspace.terminal.service import TerminalService
    from slidemage.ui.workspace.terminal.sync import ExternalEditWatch

    host = SimpleNamespace(terminal=lambda: TerminalService(window.project.root),
                           watch_external_edits=lambda callback: ExternalEditWatch(window.project.root, callback))
    def focus():
        state, centre = window.state, window.centre
        return ChatFocus(state.focused_slide, centre.path, None, state.view, state.language,
                         centre.path is not None and centre.is_dirty(centre.path))
    context = SimpleNamespace(project_root=window.project.root, focus_details=focus,
                              apply_external_edits=lambda changes: None,
                              selected_route=lambda route, task, choice: ai_profile.route_for(window.project, route, task, choice))
    return host, context


def test_session_uses_host_services_and_stops_writer_before_final_watch(qapp, tmp_path):
    from types import SimpleNamespace
    from slidemage.ai import claude_launch
    from slidemage.plugin_api import ChatFocus
    from slidemage.ui.workspace.terminal.session import ClaudeCodeSession

    calls = []
    class Server:
        url, token = "http://example/mcp", "token"
        def __init__(self, toolbox):
            self.toolbox = toolbox
        def start(self):
            calls.append("server start")
        def stop(self):
            calls.append("server stop")
    class Watch:
        def start(self):
            calls.append("watch start")
        def stop(self, *, last_look=True):
            calls.append(("watch stop", last_look))
    class Process:
        running = True
        def write(self, data):
            calls.append(("write", data))
        def resize(self, cols, rows):
            calls.append(("resize", cols, rows))
        def stop(self):
            calls.append("process stop")
            self.running = False
    def start(command, env, cwd, **kwargs):
        calls.append(("process start", command, env, cwd, kwargs))
        return Process()
    host = SimpleNamespace(watch_external_edits=lambda callback: Watch(),
                           terminal=lambda: SimpleNamespace(start=start))
    context = SimpleNamespace(project_root=tmp_path, apply_external_edits=lambda changes: None,
                              focus_details=lambda: ChatFocus("abc", tmp_path / "slides/abc.tex", None,
                                                               "instructor", "EN", True),
                              selected_route=lambda route, task, choice: SimpleNamespace(model="sonnet", effort="high"),
                              build_tools=lambda host, scope, cancel: (scope, cancel))
    session = ClaudeCodeSession(host, context, tmp_path / "claude", claude_launch, claude_scope, Server,
                                lambda: "hook command")
    try:
        session.start(90, 30)
        process_start = next(call for call in calls if isinstance(call, tuple) and call[0] == "process start")
        assert process_start[3] == tmp_path and process_start[4]["with_widget"] is False
        assert process_start[4]["cols"] == 90 and process_start[4]["rows"] == 30
        assert "hook command" in " ".join(process_start[1])
        assert claude_scope.load(session._focus_file)["dirty"] is True
        assert session._toolbox()[0] == "slide"
        session.set_scope("deck")
        assert session._toolbox()[0] == "deck"
        session.write(b"hello")
        session.resize(100, 40)
        session.stop()
        assert calls.index("process stop") < len(calls) - 1
        assert calls[-1] == ("watch stop", True)
        assert not session.running
    finally:
        session.shutdown()
