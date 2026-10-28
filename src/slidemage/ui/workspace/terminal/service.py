# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The embedded terminal as a service: a program on a pseudo-terminal, and the xterm view that shows it. Nothing
in here knows Claude Code; session.py (the Claude Code session) and view.py use it like a plugin does
(Host.terminal(), plugin_api.TerminalService).

Two layers. PtySession is the process alone, with Qt signals: the reader thread of pty_process.py calls back on its
own thread, and the signals bring the output and the exit to the GUI thread. A restart (or a stop) must not be
confused by the late output of the process it replaced, so every start counts a generation and what arrives
for an older one is dropped. TerminalSession adds the view (web.TerminalWidget) and wires the two: keystrokes in,
output out, the view's size to the process, and the start when the view knows its size.
"""
from __future__ import annotations

import os
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget

from ....pty_process import PtyProcess
from ...kit.tokens import Tokens, tokens_for


class PtySession(QObject):
    output = Signal(bytes)         # on the GUI thread
    exited = Signal(int)           # the exit code, on the GUI thread
    _chunk = Signal(int, bytes)    # generation, output: from the reader thread
    _ended = Signal(int, int)      # generation, exit code: from the reader thread

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process: PtyProcess | None = None
        self._generation = 0                        # which process the callbacks belong to
        self._lock = threading.Lock()
        self._chunk.connect(self._on_chunk)
        self._ended.connect(self._on_ended)

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.alive

    def start(self, argv: Sequence[str], env: Mapping[str, str], cwd: Path, cols: int, rows: int) -> None:
        """(Re)start: the program `argv` in `cwd` on a terminal of `cols` x `rows`. Raises OSError if it cannot be
        started."""
        self.stop()
        with self._lock:
            self._generation += 1
            generation = self._generation
        self._process = PtyProcess(
            list(argv), cwd, dict(env), lambda data: self._emit(self._chunk, generation, data),
            lambda code: self._emit(self._ended, generation, code), cols, rows)

    def write(self, data: bytes) -> None:
        if self._process is not None:
            self._process.write(data)

    def resize(self, cols: int, rows: int) -> None:
        if self._process is not None:
            self._process.resize(cols, rows)

    def stop(self) -> None:
        """End the process, if there is one; its late output and exit are not reported."""
        with self._lock:
            self._generation += 1
        process, self._process = self._process, None
        if process is not None:
            process.stop()

    # The reader thread's callbacks only name the process they come from. What arrives on the GUI thread
    # (queued, so possibly after a restart or the shutdown) is checked against the generation again.

    def _on_chunk(self, generation: int, data: bytes) -> None:
        if generation == self._generation:
            self.output.emit(data)

    def _on_ended(self, generation: int, code: int) -> None:
        if generation == self._generation:
            self.exited.emit(code)

    @staticmethod
    def _emit(signal, *values) -> None:
        try:
            signal.emit(*values)
        except RuntimeError:       # this object is gone with the window
            pass


class TerminalSession(PtySession):
    """A program with its view: the object Host.terminal().start() returns."""

    def __init__(self, argv: Sequence[str], env: Mapping[str, str], cwd: Path, widget: QWidget | None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.widget = widget
        self._launch = (list(argv), dict(env), cwd)
        if widget is not None:
            widget.input_data.connect(self.write)
            widget.resized.connect(self.resize)
            widget.ready.connect(self._on_ready)
            self.output.connect(widget.write)

    def _on_ready(self, cols: int, rows: int) -> None:
        self.start(*self._launch, cols, rows)

    def close(self) -> None:
        """Stop the program and free the view."""
        self.stop()
        if self.widget is not None:
            self.widget.shutdown()
            self.widget = None


class TerminalService:
    """Makes terminal views and sessions. `tokens` gives the current design tokens (the terminal's colours; the
    window's theme), `root` is the folder programs start in unless told otherwise."""

    def __init__(self, root: Path, tokens: Callable[[], Tokens] | None = None) -> None:
        self.root = root
        self._tokens = tokens or (lambda: tokens_for(False))

    def create_widget(self, parent: QWidget | None = None) -> QWidget:
        """A terminal view with no process behind it (ClaudeCodeView connects its own session)."""
        # Imported here: the web engine is heavy, and most sessions never need a terminal.
        from .web import TerminalWidget

        return TerminalWidget(self._tokens(), parent)

    def start(
        self, argv: list[str], env: dict[str, str] | None = None, cwd: Path | None = None, *,
        on_output: Callable[[bytes], None] | None = None, on_exit: Callable[[int], None] | None = None,
        with_widget: bool = True, cols: int = 80, rows: int = 24,
    ) -> TerminalSession:
        widget = self.create_widget() if with_widget else None
        session = TerminalSession(argv, os.environ.copy() if env is None else env,
                                  self.root if cwd is None else cwd, widget)
        if on_output is not None:
            session.output.connect(on_output)
        if on_exit is not None:
            session.exited.connect(on_exit)
        if widget is None:
            session.start(*session._launch, cols, rows)
        return session
