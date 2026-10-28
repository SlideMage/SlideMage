# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Claude Code view of the assistant area (ui/workspace/terminal/): the not-installed state, a terminal
that runs a stand-in for `claude` (fake_claude.py; the real CLI is never started and no model is called),
restart, the ended state, the MCP server reaching the window's editor buffers, shutdown ending the process,
and the watch over the files Claude Code changes (reload, conflict notice, deck edits, new slides). The
project is a throwaway one, never example/."""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from functools import partial

import pytest
from conftest import SLIDE_TEXT, build_window, make_project, wait_until as _wait_until
from fake_claude import make_fake_claude
from mcp_client import Client
from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from slidemage.ai import ai_profile, claude_launch
from slidemage.deck_scan import scan_decks
from slidemage.ui.workspace.source_file import SAME
from slidemage.ui.workspace.terminal import session as session_module
from slidemage.ui.workspace.terminal import view as view_module
from slidemage.ui.workspace.terminal.sync import DiskSync
from slidemage.project import ProjectContext

pytest.importorskip("PySide6.QtWebEngineWidgets")
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the stand-in for claude is a POSIX script")

SLIDE = "slides/abc-EN-Hello-current.tex"
LF = SLIDE_TEXT.replace("\r\n", "\n")


wait_until = partial(_wait_until, seconds=20)


def pump(seconds=0.0):
    end = time.time() + seconds
    QApplication.processEvents()
    while time.time() < end:
        QApplication.processEvents()
        time.sleep(0.005)


def on_thread(function):
    """Run `function` on a thread (like the MCP server's request thread) while the GUI keeps going."""
    box = {}
    thread = threading.Thread(target=lambda: box.update(result=function()), daemon=True)
    thread.start()
    wait_until(lambda: not thread.is_alive())
    return box["result"]


class Env:
    pass


@pytest.fixture
def env(qapp, tmp_path, monkeypatch):
    root = make_project(monkeypatch, tmp_path / "project")
    context = ProjectContext.at(root)
    fake = make_fake_claude(tmp_path)
    e = Env()
    e.root, e.fake, e.log = root, fake, tmp_path / "fake.log"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(e.log))
    monkeypatch.setattr(claude_launch, "find_claude", lambda: fake)
    e.window = build_window(monkeypatch, context)
    e.window.show()
    e.window.state.set_mode("source")           # no Preview render thread to outlive the test
    e.window.state.set_deck(next(d for d in scan_decks(e.window.project) if d.name == "test"))
    e.window.state.set_focused_slide("abc")
    e.view = e.window.assistant.surface_for("claude_code")
    e.path = root / SLIDE
    yield e
    e.window.assistant.shutdown()


def terminal_text(env) -> str:
    box = {}
    env.view.terminal.view.page().runJavaScript(
        "Array.from({length: term.buffer.active.length}, (_, i) => "
        "term.buffer.active.getLine(i).translateToString(true)).join('\\n')", lambda text: box.update(text=text))
    wait_until(lambda: "text" in box)
    return box["text"]


def use_claude_code(env):
    """The AI switch on Cloud · Claude Code (as it is committed: the first-use question is behind it)."""
    ai_profile.mark_cloud_seen(env.window.project)
    env.window.state.set_ai_route(ai_profile.CLOUD, ai_profile.CLAUDE_CODE)


def start_view(env):
    use_claude_code(env)
    wait_until(lambda: env.view.session is not None and env.view.session.running)
    wait_until(lambda: "Fake Claude Code" in terminal_text(env))


# -- the page's bridge ---------------------------------------------------------------------------------------------

def test_copy_and_paste_go_through_the_clipboard_and_only_web_links_open(qapp, monkeypatch):
    from slidemage.ui.workspace.terminal.web import TerminalBridge

    bridge = TerminalBridge("{}")
    bridge.copy_text("selected text")
    assert QGuiApplication.clipboard().text() == "selected text"
    pasted, typed, opened = [], [], []
    bridge.paste.connect(pasted.append)
    bridge.input_data.connect(typed.append)
    bridge.paste_requested()
    assert pasted == ["selected text"]
    bridge.send_input("é\r")
    bridge.send_binary("\x1b[M\xe9")                 # a mouse report is raw bytes, not UTF-8
    assert typed == ["é\r".encode(), b"\x1b[M\xe9"]
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or True)
    for url in ("https://example.org/a", "mailto:a@b.c", "file:///etc/passwd", "javascript:alert(1)", "qrc:///x"):
        bridge.open_url(url)
    assert opened == ["https://example.org/a", "mailto:a@b.c"]


# -- the states ------------------------------------------------------------------------------------------------

def test_without_claude_the_view_says_how_to_install_it_and_starts_no_process(env, monkeypatch):
    monkeypatch.setattr(claude_launch, "find_claude", lambda: None)
    use_claude_code(env)
    pump(0.2)
    assert env.view._stack.currentIndex() == view_module.SETUP and env.view.terminal is None and env.view.session is None
    assert env.view._stack.currentWidget().isVisibleTo(env.view)
    texts = " ".join(label.text() for label in env.view._stack.currentWidget().findChildren(QLabel))
    assert "not installed" in texts and claude_launch.INSTALL_URL in texts
    monkeypatch.setattr(claude_launch, "find_claude", lambda: env.fake)
    env.view.setup_button.click()
    wait_until(lambda: env.view.session is not None and env.view.session.running)
    assert env.view._stack.currentIndex() == view_module.TERMINAL


def test_a_process_that_cannot_start_is_shown_in_the_terminal_not_raised(env, monkeypatch):
    def busy(self):
        raise OSError("port busy")

    original = session_module.McpServer.start
    monkeypatch.setattr(session_module.McpServer, "start", busy)
    use_claude_code(env)
    wait_until(lambda: env.view.status.text() == "Could not start")
    wait_until(lambda: "could not be started" in terminal_text(env).replace("\n", " "))     # the terminal is narrow
    assert not env.view.session.running
    monkeypatch.setattr(session_module.McpServer, "start", original)      # the port is free again: Restart works
    env.view.restart_button.click()
    wait_until(lambda: env.view.session.running and env.view.status.text() == "Running")


def test_typing_resize_theme_exit_restart_and_shutdown(env):
    assert env.view.terminal is None and env.view.session is None and not env.log.exists()      # the chat is shown
    start_view(env)
    assert env.view.status.text() == "Running"
    logged = json.loads(env.log.read_text())
    assert logged["cwd"] == str(env.root) and logged["project"] == str(env.root) and logged["term"] == "xterm-256color"
    assert logged["argv"][0::2] == ["--mcp-config", "--settings", "--append-system-prompt"]    # the model is Claude Code's own
    assert logged["token"] == env.view.session._server.token and logged["token"] not in json.dumps(logged["argv"])
    assert env.view.session.mcp_url in logged["argv"][1]
    assert not (env.root / ".claude").exists() and not (env.root / ".mcp.json").exists()
    # what is typed reaches the process, its output the terminal
    env.view.terminal.bridge.send_input("hello there\r")
    wait_until(lambda: "echo: hello there" in terminal_text(env))
    # ... and so do real key presses in the web view
    keys = env.view.terminal.view.focusProxy() or env.view.terminal.view
    QTest.keyClicks(keys, "typed")
    QTest.keyClick(keys, Qt.Key.Key_Return)
    wait_until(lambda: "echo: typed" in terminal_text(env))
    # the terminal's size is the process's size
    cols, rows = env.view._size
    assert cols > 20 and rows > 5
    env.view.terminal.setFixedSize(900, 300)           # the layout leaves it alone
    wait_until(lambda: env.view._size != (cols, rows))
    env.view.terminal.view.page().runJavaScript("refit();")        # the page settles (a scrollbar may take a column)
    pump(0.5)
    reported = []                                   # a refit that finds the same size tells nobody (no SIGWINCH)
    env.view.terminal.resized.connect(lambda c, r: reported.append((c, r)))
    env.view.terminal.view.page().runJavaScript("refit(); refit();")
    pump(0.3)
    assert reported == []
    # the colours follow the app theme
    seen = []
    env.view.terminal.bridge.theme.connect(seen.append)
    env.window.theme.apply = lambda: None       # applying the QSS to the whole app would slow every later test
    env.window.set_dark_mode(not env.window.theme.dark)
    assert json.loads(seen[-1])["background"] == env.window.theme.tokens.surface
    # while the process runs the files are watched; when it ends by itself the view says so
    sync = env.view.session._sync
    assert sync._timer.isActive()
    env.view.terminal.bridge.send_input("/exit\r")
    wait_until(lambda: "exit code 3" in env.view.status.text())
    assert not env.view.session.running and "Claude Code ended" in terminal_text(env) and not sync._timer.isActive()
    # Restart: a new process in a reset terminal
    env.view.restart_button.click()
    wait_until(lambda: env.view.session.running and env.view.status.text() == "Running")
    wait_until(lambda: "Fake Claude Code" in terminal_text(env))
    assert "Claude Code ended" not in terminal_text(env) and sync._timer.isActive()
    # Restart of a running process: the old one is ended, and its end is not reported as the new one's
    first = env.view.session._pty._process
    session = env.view.session
    old = session._pty._generation
    env.view.restart_button.click()
    wait_until(lambda: session._pty._process is not first and session.running and session._pty._generation > old)
    # Regression (1c7e047): queued output and exit from the previous process must not affect the new one.
    session._pty._ended.emit(old, 7)
    session._pty._chunk.emit(old, b"stale output\r\n")
    pump(0.3)
    assert not first.alive and env.view.status.text() == "Running"
    assert session._sync._timer.isActive() and "stale output" not in terminal_text(env)
    # Shutdown: process and MCP server are gone, twice is fine
    session, process, port = env.view.session, env.view.session._pty._process, env.view.session._server.port
    env.window.assistant.shutdown()
    assert not process.alive and not session.running and env.view.session is None and env.view.terminal is None
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1)
    env.window.assistant.shutdown()
    env.view._on_exited(0)                              # an exit reported while the window closes: nothing to show


# -- the MCP server and the window's editor ----------------------------------------------------------------------

def test_claude_code_reads_the_unsaved_buffer_and_the_focus_through_mcp(env):
    start_view(env)
    env.window.open_slide_editor(env.path)
    file = env.window.centre.source.file_for(env.path)
    file.editor.replace_selection("% typed in the editor\n")
    client = Client(env.view.session._server)
    focus = on_thread(lambda: client.text("get_focus"))
    assert "Focused slide id: abc" in focus and "unsaved edits in the editor" in focus and SLIDE in focus
    buffer = on_thread(lambda: client.text("read_buffer", path=SLIDE))
    assert "% typed in the editor" in buffer and "editor (unsaved)" in buffer
    assert "% typed in the editor" not in env.path.read_text()           # the disk is older
    env.window.state.set_focused_slide("abd")                            # the focus is read afresh per call
    assert "Focused slide id: abd" in on_thread(lambda: client.text("get_focus"))


def test_switch_to_deck_mode_sets_the_scope_switch(env):
    from slidemage.ai import claude_scope

    start_view(env)
    client = Client(env.view.session._server)
    assert on_thread(lambda: client.text("switch_to_deck_mode")) == "SlideMage is in Deck Mode now: go on with the request."
    assert env.view.scope.current() == claude_scope.DECK
    assert claude_scope.load(env.view.session._focus_file)["scope"] == claude_scope.DECK


def test_show_slide_brings_a_deck_slide_into_focus(env):
    start_view(env)
    client = Client(env.view.session._server)
    assert "shows slides/abd-EN-Second-current.tex" in on_thread(
        lambda: client.text("show_slide", path="slides/abd-EN-Second-current.tex"))
    assert env.window.state.focused_slide == "abd"


def test_the_scope_switch_and_the_focus_reach_the_hooks(env):
    from slidemage.ai import claude_scope

    start_view(env)
    env.window.open_slide_editor(env.path)
    focus_file = env.view.session._focus_file
    wait_until(lambda: (claude_scope.load(focus_file) or {}).get("slide") == SLIDE)
    assert claude_scope.load(focus_file)["scope"] == claude_scope.SLIDE
    assert "THIS SLIDE" in claude_scope.prompt_context(claude_scope.load(focus_file))
    env.view.scope._buttons[claude_scope.DECK].click()                  # the user switches to Deck
    assert claude_scope.load(focus_file)["scope"] == claude_scope.DECK
    env.window.assistant.shutdown()
    assert not focus_file.exists()                                       # removed with the session


# -- the watch over the files Claude Code changes ------------------------------------------------------------------

@pytest.fixture
def watch(env):
    sync = DiskSync(env.window, env.root)
    sync.start()
    env.sync = sync
    yield env
    sync.stop()


def rewrite(path, text):
    """Change a file on disk the way Claude Code would, with a different size and time."""
    path.write_bytes(text.replace("\n", "\r\n").encode())
    stamp = path.stat().st_mtime_ns + 2_000_000_000
    os.utime(path, ns=(stamp, stamp))


def open_slide(env, dirty=False):
    env.window.open_slide_editor(env.path)
    file = env.window.centre.source.file_for(env.path)
    if dirty:
        file.editor.replace_selection("% typed\n")
    return file


def test_stopping_looks_once_more_and_a_failed_change_is_tried_again(watch, monkeypatch):
    file = open_slide(watch)
    rewrite(watch.path, LF.replace("First point", "Claude's last-second point"))
    watch.sync.stop()                                   # the process ended: its final write is not missed
    assert "last-second point" in file.editor.text() and not watch.sync._timer.isActive()
    watch.sync.start()
    rewrite(watch.path, LF.replace("First point", "Claude's point"))
    applied = []
    monkeypatch.setattr(watch.sync, "_apply", lambda changes: applied.append(changes) or (_ for _ in ()).throw(RuntimeError))
    with pytest.raises(RuntimeError):
        watch.sync.poll()
    monkeypatch.undo()          # (the fixture's own patches go with it; the watch has all it needs)
    watch.sync.poll()                                   # the window did not take the first one in: again
    assert "Claude's point" in file.editor.text() and len(applied) == 1
    watch.sync.stop(last_look=False)


def test_a_clean_buffer_is_reloaded_and_our_own_save_is_not_a_change(watch, monkeypatch):
    file = open_slide(watch)
    rewrite(watch.path, LF.replace("First point", "Claude's point"))
    watch.sync.poll()
    assert "Claude's point" in file.editor.text() and not file.dirty and not file.conflict_bar.isVisibleTo(file)
    file.editor.replace_selection("% mine\n")
    assert file.write_now()
    reloaded = []
    file.reload = lambda: reloaded.append(1)
    watch.sync.poll()                                   # the save changed the file on disk
    assert reloaded == [] and file.disk_changed() == SAME and "% mine" in file.editor.text()


def test_ctrl_s_saves_the_open_file_from_the_window_whichever_view_has_the_focus(watch, monkeypatch):
    file = open_slide(watch)
    file.editor.replace_selection("% saved from afar\n")
    assert file.dirty
    watch.window.centre.preview.setFocus()                     # not the editor
    shortcuts = [s for s in watch.window.findChildren(QShortcut) if s.key() == QKeySequence("Ctrl+S")]
    assert len(shortcuts) == 1 and shortcuts[0].context() == Qt.ShortcutContext.WindowShortcut
    shortcuts[0].activated.emit()
    assert not file.dirty and "% saved from afar" in watch.path.read_text()


def test_a_dirty_buffer_is_not_overwritten_and_reload_from_disk_takes_claudes_version(watch):
    file = open_slide(watch, dirty=True)
    mine = file.editor.text()
    rewrite(watch.path, LF.replace("First point", "Claude's point"))
    watch.sync.poll()
    assert file.editor.text() == mine and file.dirty
    assert file.conflict_bar.isVisibleTo(file) and "changed on disk" in file.conflict_label.text()
    rewrite(watch.path, LF.replace("First point", "Claude's other point"))
    watch.sync.poll()
    assert file.editor.text() == mine and file.conflict_bar.isVisibleTo(file)
    file._reload_conflicting()
    assert "Claude's other point" in file.editor.text() and "% typed" not in file.editor.text()
    assert not file.dirty and not file.conflict_bar.isVisibleTo(file)


def test_keep_my_edits_lets_the_next_save_replace_the_file_on_disk(watch, monkeypatch):
    bib = watch.root / "Slidemaster.bib"
    watch.window.open_slide_editor(bib)
    file = watch.window.centre.source.file_for(bib)
    file.editor.replace_selection("% my note\n")
    bib.write_text(bib.read_text() + "% claude's note\n")
    stamp = bib.stat().st_mtime_ns + 2_000_000_000
    os.utime(bib, ns=(stamp, stamp))
    watch.sync.poll()
    assert file.conflict_bar.isVisibleTo(file)
    file.keep_edits()
    assert not file.conflict_bar.isVisibleTo(file) and file.dirty and file.disk_changed() == SAME
    assert file.write_now()                                               # no "changed on disk" refusal
    assert "% my note" in bib.read_text() and "claude's note" not in bib.read_text()
    assert file.disk_changed() == SAME


def test_other_files_refresh_the_lists_and_hidden_places_are_ignored(watch, monkeypatch):
    rebuilt = []
    monkeypatch.setattr(watch.window.slide_list, "rebuild", lambda: rebuilt.append("list"))
    monkeypatch.setattr(watch.window.side_panels, "refresh", lambda: rebuilt.append("panels"))
    for name in (".build/test.tex", "pdf/test.tex", ".slidemage/notes.md", "slides/.backups/old.tex"):
        path = watch.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")
    watch.sync.poll()
    assert rebuilt == []
    rewrite(watch.root / "slides" / "abd-EN-Second-current.tex", LF.replace("Hello", "Changed"))
    watch.sync.poll()
    assert rebuilt == ["list", "panels"]
    watch.sync.poll()
    assert rebuilt == ["list", "panels"]                       # nothing changed since


def test_the_preview_of_a_slide_that_is_not_open_in_the_editor_learns_it_is_older(watch, monkeypatch):
    centre = watch.window.centre
    monkeypatch.setattr(centre, "disk_changed", lambda path: None)       # in Preview the file is not loaded
    monkeypatch.setattr(type(centre), "path", property(lambda self: watch.path))
    refreshed = []
    monkeypatch.setattr(centre, "refresh", lambda: refreshed.append(1))
    rewrite(watch.path, LF.replace("First point", "Claude's point"))
    watch.sync.poll()
    assert refreshed == [1]
    watch.sync.poll()
    assert refreshed == [1]                                    # nothing changed since


def test_decks_and_new_or_removed_slides_go_through_the_deck_sequences(watch, monkeypatch):
    seen, rescans = [], []
    monkeypatch.setattr(watch.window, "after_deck_edit", lambda path, summary, previous=None: seen.append((path, summary)))
    original = watch.window.reload_decks
    monkeypatch.setattr(watch.window, "reload_decks", lambda: rescans.append(1) or original())
    deck = watch.root / "decks" / "test.tex"
    text = deck.read_bytes().decode().replace("\r\n", "\n")
    rewrite(deck, text.replace("\\slide{abd-EN-Second}", "\\slide{abd-EN-Second}\n\\slide{abc-EN-Hello}"))
    watch.sync.poll()
    assert seen == [(deck, "Claude Code changed test.tex")] and rescans == []
    # SlideMage's own deck edit (the deck on record already is what is on disk) is not announced as Claude's
    seen.clear()
    original()
    stamp = deck.stat().st_mtime_ns + 4_000_000_000
    os.utime(deck, ns=(stamp, stamp))
    watch.sync.poll()
    assert seen == []
    new = watch.root / "slides" / "abe-EN-Third-current.tex"
    new.write_bytes(SLIDE_TEXT.encode())
    watch.sync.poll()
    assert rescans == [1]
    new.unlink()
    watch.sync.poll()
    assert rescans == [1, 1]


# -- attachments ---------------------------------------------------------------------------------------------------

def test_attaching_files_types_their_at_paths_without_enter(env, tmp_path, monkeypatch):
    start_view(env)
    typed = []
    monkeypatch.setattr(env.view.session, "write", typed.append)
    assert env.view.attach_button.isEnabled()
    outside, other = tmp_path / "paper.pdf", tmp_path / "my fig.png"
    outside.write_bytes(b"%PDF")
    other.write_bytes(b"x")
    env.view.attach_files([str(outside)])
    env.view.attach_files([str(env.path), str(other)])
    assert (env.root / "sources" / "paper.pdf").read_bytes() == b"%PDF"
    assert typed == [b"@sources/paper.pdf ", f"@{SLIDE} ".encode(), b"@sources/my-fig.png "]


def test_dropping_files_on_the_terminal_attaches_them(env, tmp_path, monkeypatch):
    from PySide6.QtCore import QMimeData, QPointF, QUrl, Qt
    from PySide6.QtGui import QDropEvent
    start_view(env)
    typed = []
    monkeypatch.setattr(env.view.session, "write", typed.append)
    dropped = tmp_path / "notes.txt"
    dropped.write_text("hi")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(dropped))])
    event = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    assert env.view.terminal.eventFilter(env.view.terminal.view, event)      # a synthetic drop is not routed by Qt offscreen
    assert typed == [b"@sources/notes.txt "] and event.isAccepted()


def test_attaching_is_off_while_claude_code_is_not_running(env):
    assert not env.view.attach_button.isEnabled()
    start_view(env)
    env.view.terminal.bridge.send_input("/exit\r")
    wait_until(lambda: "exit code" in env.view.status.text())
    assert not env.view.attach_button.isEnabled()
    env.view.attach_files([str(env.path)])      # nothing typed, nothing raised


def test_saved_chat_choice_applies_on_start_and_restart(env):
    ai_profile.set_model_choice(env.window.project, ai_profile.CLAUDE_CODE, ai_profile.CHAT, "sonnet:medium")
    start_view(env)
    assert json.loads(env.log.read_text())["argv"][:4] == ["--model", "sonnet", "--effort", "medium"]
    ai_profile.set_model_choice(env.window.project, ai_profile.CLAUDE_CODE, ai_profile.CHAT, "opus:high")
    env.view.restart_button.click()
    wait_until(lambda: json.loads(env.log.read_text())["argv"][:4] == ["--model", "opus", "--effort", "high"])


def test_mcp_toolbox_reads_scope_and_focus_on_gui_thread(env):
    from slidemage.ai import claude_scope

    session = session_module.ClaudeCodeSession(env.window, env.fake)
    try:
        env.window.open_slide_editor(env.path)
        box = on_thread(session._toolbox)
        assert box.ctx.scope == claude_scope.SLIDE and box.ctx.focus_slide == env.path
        session.set_scope(claude_scope.DECK)
        box = on_thread(session._toolbox)
        assert box.ctx.scope == claude_scope.DECK and box.ctx.focus_slide == env.path
    finally:
        session.shutdown()
