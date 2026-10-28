# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""One embedded Claude Code: the MCP server it talks to, the process on its pty, and the watch over the
files it changes (UI redesign step 10c).

The process is the terminal service's (service.PtySession, the same one plugins start programs with) and the watch
is the external-edit watch's (sync.DiskSync over sync.ExternalEditWatch); what is Claude Code's own is the command,
the environment, the MCP server and the focus.

Threading. The process's reader thread (pty_process.py) is turned into the `output` / `exited` signals for the GUI
thread by the PtySession. The MCP server answers on its own threads; the tools they
run reach editor buffers and the focus through `GuiWorkspace.on_gui`, which hands the work to the GUI thread
and waits (a closing window releases every wait). `stop()` ends the process politely (pty_process.PtyProcess)
and is safe to call twice; `shutdown()` also stops the server.
"""
from __future__ import annotations

import os
import tempfile
import threading
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from .... import compiler
from ....ai import ai_profile, claude_launch, claude_scope
from ....ai.agent_types import EDIT_AUTO
from ....ai.mcp_server import McpServer
from ....ai.agent_toolbox import agent_toolbox
from ....ai.tools import ToolBox
from ..chat.gui_workspace import GuiWorkspace
from .service import PtySession
from .sync import DiskSync


class ClaudeCodeSession(QObject):
    output = Signal(bytes)         # on the GUI thread
    exited = Signal(int)           # the exit code, on the GUI thread
    focus_changed = Signal()       # what publish_focus found different: the focus, the scope, the buffer's state

    def __init__(self, window, claude: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.claude = claude
        self._window = window
        self.scope = claude_scope.SLIDE             # how far a request may reach (the view's switch)
        self.model, self.effort = "", None          # what the process was started on ("": Claude Code's default)
        self.session_id = ""                        # the conversation's id (--session-id), for --resume
        self._focus_file: Path | None = None        # what the hooks read: the focus and the scope
        self._published: tuple | None = None
        self._timer = QTimer(self)                  # the focus also moves without a signal (a file opened)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self.publish_focus)
        self.workspace = GuiWorkspace(window)      # its own focus, apart from the chat's
        self._server: McpServer | None = None
        self._pty = PtySession(self)                # the process; its generations drop a replaced one's late output
        self._lock = threading.Lock()
        self._cancel = compiler.CancelToken()
        self._sync = DiskSync(window, window.project.root, self)
        self._pty.output.connect(self.output)
        self._pty.exited.connect(self._on_ended)

    @property
    def running(self) -> bool:
        return self._pty.running

    @property
    def mcp_url(self) -> str:
        return self._server.url if self._server is not None else ""

    def start(self, cols: int, rows: int, *, resume: bool = False, choice: str | None = None) -> None:
        """(Re)start Claude Code in the project folder with a terminal of `cols` x `rows`, on the saved default
        model. With `resume` it continues the conversation it had (a changed default reaches it this way), when
        Claude Code saved one; else, and always without `resume`, a new conversation starts."""
        self.stop()
        with self._lock:
            self._cancel = compiler.CancelToken()
        if self._server is None:
            server = McpServer(self._toolbox)
            server.start()              # kept only once it listens, so that a failed start can be retried
            self._server = server
        if self._focus_file is None:
            handle, name = tempfile.mkstemp(prefix="slidemage-focus-", suffix=".json")
            os.close(handle)
            self._focus_file = Path(name)
        self.publish_focus(force=True)
        self._timer.start()
        route = ai_profile.route_for(self._window.project, ai_profile.CLAUDE_CODE, ai_profile.CHAT, choice or "")
        self.model, self.effort = route.model, route.effort
        resume = resume and claude_launch.has_transcript(self.session_id)
        if not resume:
            self.session_id = str(uuid.uuid4())
        command = claude_launch.build_command(self.claude, self._server.url, model=route.model, effort=route.effort,
                                              session_id=self.session_id, resume=resume)
        env = claude_launch.environment(self._server.token, self._window.project.root, self.claude, focus_file=self._focus_file)
        self._pty.start(command, env, self._window.project.root, cols, rows)
        self._sync.start()

    def set_scope(self, scope: str) -> None:
        self.scope = scope
        self.publish_focus()

    def publish_focus(self, force: bool = False) -> None:
        """Write what the user is looking at and the scope for the hooks, when it changed (GUI thread)."""
        if self._focus_file is None:
            return
        window, state = self._window, self._window.state
        slide = window.centre.path         # publish() keeps it only if it is a slide
        deck = state.deck.path if state.deck is not None and not state.deck.is_test_deck else None
        values = (self.scope, state.focused_slide, slide, deck, state.view, state.language,
                  slide is not None and window.centre.is_dirty(slide))
        if values == self._published and not force:
            return
        try:
            claude_scope.publish(self._focus_file, values[0], window.project.root, *values[1:])
        except OSError:
            return
        self._published = values
        self.focus_changed.emit()

    def write(self, data: bytes) -> None:
        self._pty.write(data)

    def resize(self, cols: int, rows: int) -> None:
        self._pty.resize(cols, rows)

    def stop(self, *, last_look: bool = True) -> None:
        """End the process, if there is one; its late output and exit are not reported."""
        with self._lock:
            cancel = self._cancel
        cancel.request_stop()
        self._timer.stop()
        self._sync.stop(last_look=last_look)
        self._pty.stop()

    def shutdown(self) -> None:
        """The window closes: end everything, and release the MCP calls that wait for the GUI."""
        self.workspace.close()
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

        def focus():
            self.workspace.begin_request()
            return self.scope, self.workspace.context().path

        scope, path = self.workspace.on_gui(focus, (claude_scope.SLIDE, None))
        return agent_toolbox(self.workspace, scope, path, cancel, EDIT_AUTO)

    def _on_ended(self, code: int) -> None:
        """The process ended by itself: one last look at the files it left changed."""
        self._sync.stop()
        self.exited.emit(code)
