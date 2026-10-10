"""One embedded Claude Code: the MCP server it talks to, the process on its pty, and the watch over the
files it changes (UI redesign step 10c).

Threading. The process's reader thread (pty_process.py) calls `_on_output` / `_on_exit`, which turn into
the `output` / `exited` signals for the GUI thread. The MCP server answers on its own threads; the tools they
run reach editor buffers and the focus through `GuiWorkspace.on_gui`, which hands the work to the GUI thread
and waits (a closing window releases every wait). `stop()` ends the process politely (pty_process.PtyProcess)
and is safe to call twice; `shutdown()` also stops the server.
"""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .... import compiler
from ....ai import claude_launch
from ....ai.agent_types import EDIT_AUTO
from ....ai.mcp_server import McpServer
from ....ai.tools import CLAUDE_CODE_TOOLS, ToolBox, build_toolbox
from ....deck_scan import PROJECT_ROOT
from ....pty_process import PtyProcess
from ..chat.gui_workspace import GuiWorkspace
from .sync import DiskSync


class ClaudeCodeSession(QObject):
    output = Signal(bytes)         # on the GUI thread
    exited = Signal(int)           # the exit code, on the GUI thread
    _chunk = Signal(int, bytes)    # generation, output: from the reader thread
    _ended = Signal(int, int)      # generation, exit code: from the reader thread

    def __init__(self, window, claude: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.claude = claude
        self._workspace = GuiWorkspace(window)      # its own focus, apart from the chat's
        self._server: McpServer | None = None
        self._process: PtyProcess | None = None
        self._generation = 0                        # which process the callbacks belong to
        self._lock = threading.Lock()
        self._sync = DiskSync(window, PROJECT_ROOT, self)
        self._chunk.connect(self._on_chunk)
        self._ended.connect(self._on_ended)

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.alive

    @property
    def mcp_url(self) -> str:
        return self._server.url if self._server is not None else ""

    def start(self, cols: int, rows: int) -> None:
        """(Re)start Claude Code in the project folder with a terminal of `cols` x `rows`."""
        self.stop()
        if self._server is None:
            server = McpServer(self._toolbox)
            server.start()              # kept only once it listens, so that a failed start can be retried
            self._server = server
        command = claude_launch.build_command(self.claude, self._server.url)
        env = claude_launch.environment(self._server.token, PROJECT_ROOT, self.claude)
        with self._lock:
            self._generation += 1
            generation = self._generation
        self._process = PtyProcess(
            command, PROJECT_ROOT, env, lambda data: self._on_output(generation, data),
            lambda code: self._on_exit(generation, code), cols, rows)
        self._sync.start()

    def write(self, data: bytes) -> None:
        if self._process is not None:
            self._process.write(data)

    def resize(self, cols: int, rows: int) -> None:
        if self._process is not None:
            self._process.resize(cols, rows)

    def stop(self, *, last_look: bool = True) -> None:
        """End the process, if there is one; its late output and exit are not reported."""
        with self._lock:
            self._generation += 1
        self._sync.stop(last_look=last_look)
        process, self._process = self._process, None
        if process is not None:
            process.stop()

    def shutdown(self) -> None:
        """The window closes: end everything, and release the MCP calls that wait for the GUI."""
        self._workspace.close()
        self.stop(last_look=False)
        if self._server is not None:
            self._server.stop()
            self._server = None

    def _toolbox(self) -> ToolBox:
        """The tools for one MCP call, looking at the window as it is now."""
        self._workspace.on_gui(self._workspace.begin_request)
        return build_toolbox(self._workspace, lambda _event: None, compiler.CancelToken(), EDIT_AUTO,
                             tools=CLAUDE_CODE_TOOLS)

    # The reader thread's callbacks only name the process they come from. What arrives on the GUI thread
    # (queued, so possibly after a Restart or the shutdown) is checked against the generation again.

    def _on_output(self, generation: int, data: bytes) -> None:
        self._emit(self._chunk, generation, data)

    def _on_exit(self, generation: int, code: int) -> None:
        self._emit(self._ended, generation, code)

    def _on_chunk(self, generation: int, data: bytes) -> None:
        if generation == self._generation:
            self.output.emit(data)

    def _on_ended(self, generation: int, code: int) -> None:
        """The process ended by itself: one last look at the files it left changed."""
        if generation == self._generation:
            self._sync.stop()
            self.exited.emit(code)

    @staticmethod
    def _emit(signal, *values) -> None:
        try:
            signal.emit(*values)
        except RuntimeError:       # this object is gone with the window
            pass
