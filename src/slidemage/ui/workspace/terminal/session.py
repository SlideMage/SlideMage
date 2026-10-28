# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""One embedded Claude Code: the MCP server it talks to, the process on its pty, and the watch over the
files it changes (UI redesign step 10c).

The host owns the process and edit watch. The context constructs a fresh toolbox on the GUI thread for each
MCP request and releases pending requests when the surface closes. The injected launch, scope, server and hook
command are Claude-specific and can live alongside this module in the plugin.
"""
from __future__ import annotations

import os
import tempfile
import threading
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from slidemage.plugin_api import CancelToken, ChatSurfaceContext, Host, ToolBox


class ClaudeCodeSession(QObject):
    output = Signal(bytes)         # on the GUI thread
    exited = Signal(int)           # the exit code, on the GUI thread
    focus_changed = Signal()       # what publish_focus found different: the focus, the scope, the buffer's state

    def __init__(self, host: Host, context: ChatSurfaceContext, claude: Path, launch, scope, server, hook_command,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.claude = claude
        self.host, self.context = host, context
        self._launch, self._scope, self._server_factory, self._hook_command = launch, scope, server, hook_command
        self.scope = "slide"             # how far a request may reach (the view's switch)
        self.model, self.effort = "", None          # what the process was started on ("": Claude Code's default)
        self.session_id = ""                        # the conversation's id (--session-id), for --resume
        self._focus_file: Path | None = None        # what the hooks read: the focus and the scope
        self._published: tuple | None = None
        self._timer = QTimer(self)                  # the focus also moves without a signal (a file opened)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self.publish_focus)
        self._server = None
        self._pty = None
        self._lock = threading.Lock()
        self._cancel = CancelToken()
        self._sync = host.watch_external_edits(context.apply_external_edits)

    @property
    def running(self) -> bool:
        return self._pty is not None and self._pty.running

    @property
    def mcp_url(self) -> str:
        return self._server.url if self._server is not None else ""

    def start(self, cols: int, rows: int, *, resume: bool = False, choice: str | None = None) -> None:
        """(Re)start Claude Code in the project folder with a terminal of `cols` x `rows`, on the saved default
        model. With `resume` it continues the conversation it had (a changed default reaches it this way), when
        Claude Code saved one; else, and always without `resume`, a new conversation starts."""
        self.stop()
        with self._lock:
            self._cancel = CancelToken()
        if self._server is None:
            server = self._server_factory(self._toolbox)
            server.start()              # kept only once it listens, so that a failed start can be retried
            self._server = server
        if self._focus_file is None:
            handle, name = tempfile.mkstemp(prefix="slidemage-focus-", suffix=".json")
            os.close(handle)
            self._focus_file = Path(name)
        self.publish_focus(force=True)
        route = self.context.selected_route("claude_code", "chat", choice or "")
        self.model, self.effort = route.model, route.effort
        resume = resume and self._launch.has_transcript(self.session_id)
        if not resume:
            self.session_id = str(uuid.uuid4())
        command = self._launch.build_command(self.claude, self._server.url, hook=self._hook_command(),
                                             model=route.model, effort=route.effort,
                                             session_id=self.session_id, resume=resume)
        env = self._launch.environment(self._server.token, self.context.project_root, self.claude, focus_file=self._focus_file)
        try:
            self._sync.start()
            self._pty = self.host.terminal().start(command, env, self.context.project_root, with_widget=False,
                                                   cols=cols, rows=rows, on_output=self.output.emit,
                                                   on_exit=self._on_ended)
            self._timer.start()
        except Exception:
            self.stop()
            raise

    def set_scope(self, scope: str) -> None:
        self.scope = scope
        self.publish_focus()

    def publish_focus(self, force: bool = False) -> None:
        """Write what the user is looking at and the scope for the hooks, when it changed (GUI thread)."""
        if self._focus_file is None:
            return
        focus = self.context.focus_details()
        values = (self.scope, focus.slide_id, focus.slide, focus.deck, focus.view, focus.language, focus.dirty)
        if values == self._published and not force:
            return
        try:
            self._scope.publish(self._focus_file, values[0], self.context.project_root, *values[1:])
        except OSError:
            return
        self._published = values
        self.focus_changed.emit()

    def write(self, data: bytes) -> None:
        if self._pty is not None:
            self._pty.write(data)

    def resize(self, cols: int, rows: int) -> None:
        if self._pty is not None:
            self._pty.resize(cols, rows)

    def stop(self, *, last_look: bool = True) -> None:
        """End the process, if there is one; its late output and exit are not reported."""
        with self._lock:
            cancel = self._cancel
        cancel.request_stop()
        self._timer.stop()
        if self._pty is not None:
            self._pty.stop()
            self._pty = None
        self._sync.stop(last_look=last_look)

    def shutdown(self) -> None:
        """The window closes: end everything, and release the MCP calls that wait for the GUI."""
        self.stop(last_look=False)
        if self._server is not None:
            self._server.stop()
            self._server = None
        if self._focus_file is not None:
            self._focus_file.unlink(missing_ok=True)
            self._focus_file = None

    def _toolbox(self) -> ToolBox:
        """The tools for one MCP call, looking at the window as it is now."""
        with self._lock:
            cancel = self._cancel

        box = self.context.build_tools(self.host, self.scope, cancel)
        if box is None:
            raise RuntimeError("The chat surface is closed")
        return box

    def _on_ended(self, code: int) -> None:
        """The process ended by itself: one last look at the files it left changed."""
        self._timer.stop()
        self._sync.stop()
        self.exited.emit(code)
