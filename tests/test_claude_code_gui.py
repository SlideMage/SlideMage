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

from slidemage import app_settings
from slidemage.ai import claude_launch
from slidemage.deck_scan import scan_decks
from slidemage.ui.workspace.chat import gui_workspace
from slidemage.ui.workspace.chat.assistant import CHAT, CLAUDE_CODE
from slidemage.ui.workspace import source_file
from slidemage.ui.workspace.source_file import SAME
from slidemage.ui.workspace.terminal import session as session_module
from slidemage.ui.workspace.terminal import view as view_module
from slidemage.ui.workspace.terminal.sync import DiskSync

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
    monkeypatch.setattr(session_module, "PROJECT_ROOT", root)
    monkeypatch.setattr(gui_workspace, "PROJECT_ROOT", root)
    app_settings.set("assistant_view", CHAT)
    fake = make_fake_claude(tmp_path)
    e = Env()
    e.root, e.fake, e.log = root, fake, tmp_path / "fake.log"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(e.log))
    monkeypatch.setattr(claude_launch, "find_claude", lambda: fake)
    e.window = build_window(monkeypatch)
    e.window.show()
    e.window.state.set_mode("source")           # no Preview render thread to outlive the test
    e.window.state.set_deck(next(d for d in scan_decks() if d.name == "test"))
    e.window.state.set_focused_slide("abc")
    e.view = e.window.assistant.claude_code
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


def start_view(env):
    env.window.assistant.show_view(CLAUDE_CODE)
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
    env.window.assistant.show_view(CLAUDE_CODE)
    pump(0.2)
    assert env.view._stack.currentIndex() == view_module.HINT and env.view.terminal is None and env.view.session is None
    assert env.view._stack.currentWidget().isVisibleTo(env.view)
    texts = " ".join(label.text() for label in env.view._stack.currentWidget().findChildren(QLabel))
    assert "not installed" in texts and claude_launch.INSTALL_URL in texts
    monkeypatch.setattr(claude_launch, "find_claude", lambda: env.fake)
    env.view.check_again()
    wait_until(lambda: env.view.session is not None and env.view.session.running)
    assert env.view._stack.currentIndex() == view_module.TERMINAL


def test_a_process_that_cannot_start_is_shown_in_the_terminal_not_raised(env, monkeypatch):
    def busy(self):
        raise OSError("port busy")

    original = session_module.McpServer.start
    monkeypatch.setattr(session_module.McpServer, "start", busy)
    env.window.assistant.show_view(CLAUDE_CODE)
    wait_until(lambda: env.view.status.text() == "Claude Code could not start")
    wait_until(lambda: "could not be started" in terminal_text(env).replace("\n", " "))     # the terminal is narrow
    assert not env.view.session.running
    monkeypatch.setattr(session_module.McpServer, "start", original)      # the port is free again: Restart works
    env.view.restart_button.click()
    wait_until(lambda: env.view.session.running and env.view.status.text() == "Claude Code running")


def test_typing_resize_theme_exit_restart_and_shutdown(env):
    assert env.view.terminal is None and env.view.session is None and not env.log.exists()      # the chat is shown
    start_view(env)
    assert env.view.status.text() == "Claude Code running"
    logged = json.loads(env.log.read_text())
    assert logged["cwd"] == str(env.root) and logged["project"] == str(env.root) and logged["term"] == "xterm-256color"
    assert logged["argv"][0::2] == ["--mcp-config", "--settings", "--append-system-prompt"]
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
    env.view.terminal.resize(900, 300)
    wait_until(lambda: env.view._size != (cols, rows))
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
    wait_until(lambda: env.view.session.running and env.view.status.text() == "Claude Code running")
    wait_until(lambda: "Fake Claude Code" in terminal_text(env))
    assert "Claude Code ended" not in terminal_text(env) and sync._timer.isActive()
    # Restart of a running process: the old one is ended, and its end is not reported as the new one's
    first = env.view.session._process
    session = env.view.session
    old = session._generation
    env.view.restart_button.click()
    wait_until(lambda: session._process is not first and session.running and session._generation > old)
    # Regression (1c7e047): queued output and exit from the previous process must not affect the new one.
    session._ended.emit(old, 7)
    session._chunk.emit(old, b"stale output\r\n")
    pump(0.3)
    assert not first.alive and env.view.status.text() == "Claude Code running"
    assert session._sync._timer.isActive() and "stale output" not in terminal_text(env)
    # Shutdown: process and MCP server are gone, twice is fine
    session, process, port = env.view.session, env.view.session._process, env.view.session._server.port
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
    assert "% typed in the editor" in buffer and "unsaved edits: yes" in buffer
    assert "% typed in the editor" not in env.path.read_text()           # the disk is older
    env.window.state.set_focused_slide("abd")                            # the focus is read afresh per call
    assert "Focused slide id: abd" in on_thread(lambda: client.text("get_focus"))


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
    monkeypatch.setattr(source_file, "PROJECT_ROOT", watch.root)
    monkeypatch.setattr(source_file, "prompt_version_choice", lambda *a: "overwrite")
    file.editor.replace_selection("% mine\n")
    assert file.save()
    reloaded = []
    file.reload = lambda: reloaded.append(1)
    watch.sync.poll()                                   # the save changed the file on disk
    assert reloaded == [] and file.disk_changed() == SAME and "% mine" in file.editor.text()


def test_ctrl_s_saves_the_open_file_from_the_window_whichever_view_has_the_focus(watch, monkeypatch):
    file = open_slide(watch)
    monkeypatch.setattr(source_file, "PROJECT_ROOT", watch.root)
    monkeypatch.setattr(source_file, "prompt_version_choice", lambda *a: "overwrite")
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
    monkeypatch.setattr(source_file, "PROJECT_ROOT", watch.root)
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
    assert file.save()                                                    # no "changed on disk" refusal
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
