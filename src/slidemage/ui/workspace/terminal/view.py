"""The Claude Code view of the assistant area (UI redesign step 10c): the user's own `claude`, running in a
terminal in the project folder, connected to SlideMage (session.py).

Three states. No `claude` found: an install hint and "Check again". Otherwise a terminal, started the first
time the view is shown (not at launch, and the web view is not even created before): the process lives on
while the user looks at the chat. When it ends, the terminal keeps its text, the status chip says so and
Restart starts a new one. Closing the window, switching project and `shutdown()` end the process.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout

from ....ai import claude_launch
from ....ai.claude_scope import DECK, SLIDE
from ...kit import kit_qss as q
from ...kit.widgets import Button, Chip, SegmentedControl, Surface, caption
from ..state import WorkspaceState

HINT, TERMINAL = 0, 1
INSTALL_TEXT = ("SlideMage runs your own Claude Code here, in the project folder, with your Claude "
                "subscription. It is not installed on this computer (or not found).")
INSTALL_STEPS = (f'Install it as the <a href="{claude_launch.INSTALL_URL}">Claude Code setup guide</a> says, '
                 "start <b>claude</b> once in a terminal to sign in, then come back and check again.")


class ClaudeCodeView(Surface):
    def __init__(self, app, state: WorkspaceState) -> None:
        super().__init__()
        self.app = app
        self.state = state
        self.session = None                       # created with the terminal
        self.terminal = None
        self._started = False
        self._size = (80, 24)
        self._stack = QStackedWidget()
        self._stack.setObjectName(q.SURFACE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)
        self._stack.addWidget(self._build_hint())
        self._terminal_page = Surface()
        self._terminal_layout = QVBoxLayout(self._terminal_page)
        self._terminal_layout.setContentsMargins(0, 0, 0, 0)
        self._terminal_layout.setSpacing(4)
        self._terminal_layout.addLayout(self._build_status_row())
        self._stack.addWidget(self._terminal_page)
        QCoreApplication.instance().aboutToQuit.connect(self.shutdown)

    # -- building ---------------------------------------------------------------------------

    def _build_hint(self) -> Surface:
        page = Surface()
        box = QVBoxLayout(page)
        box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Claude Code is not installed")
        title.setObjectName(q.CHAT_TEXT)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(title)
        for text in (INSTALL_TEXT, INSTALL_STEPS):
            note = caption(text)
            note.setAlignment(Qt.AlignmentFlag.AlignCenter)
            note.setOpenExternalLinks(True)
            box.addWidget(note)
        check = Button("Check again", "secondary", compact=True)
        check.clicked.connect(self.check_again)
        box.addWidget(check, 0, Qt.AlignmentFlag.AlignCenter)
        return page

    def _build_status_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        labels = {SLIDE: "Slide", DECK: "Deck"}
        self.scope = SegmentedControl(tuple(labels.items()), current=SLIDE)
        self.scope.set_labels(labels, compact=True, tooltips={   # compact: fits the narrowest column
            SLIDE: "Claude Code works only on the slide you are looking at: it is told to read nothing else, "
                   "and edits of other slides or decks are refused.",
            DECK: "Claude Code may look at and change any slide of the open deck."})
        self.scope.changed.connect(self._on_scope)
        row.addWidget(self.scope)
        self.status = Chip("Starting…", "muted")
        row.addWidget(self.status)
        row.addStretch(1)
        self.restart_button = Button("Restart", "ghost", compact=True)
        self.restart_button.setToolTip("End Claude Code and start it again in this project (the conversation "
                                       "can be continued with /resume).")
        self.restart_button.clicked.connect(self.restart)
        row.addWidget(self.restart_button)
        return row

    def _on_scope(self, scope: str) -> None:
        if self.session is not None:
            self.session.set_scope(scope)

    # -- starting and stopping --------------------------------------------------------------------

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._started:
            self._started = True
            self._open()
        if self.terminal is not None:
            self.terminal.focus_terminal()

    def check_again(self) -> None:
        self._open()

    def _open(self) -> None:
        """Show the install hint, or build the terminal (once) and start Claude Code in it."""
        claude = claude_launch.find_claude()
        if claude is None:
            self._stack.setCurrentIndex(HINT)
            return
        self._stack.setCurrentIndex(TERMINAL)
        if self.terminal is None:
            self._build_terminal(claude)

    def _build_terminal(self, claude: Path) -> None:
        # Imported here: the web engine is heavy, and most sessions never open this view.
        from .session import ClaudeCodeSession
        from .web import TerminalWidget

        self.session = ClaudeCodeSession(self.app, claude, self)
        self.session.scope = self.scope.current()
        self.terminal = TerminalWidget(self.app.theme.tokens)
        self._terminal_layout.addWidget(self.terminal, 1)
        self.terminal.ready.connect(self._on_ready)
        self.terminal.resized.connect(self._on_resized)
        self.terminal.input_data.connect(self.session.write)
        self.session.output.connect(self.terminal.write)
        self.session.exited.connect(self._on_exited)

    def _on_ready(self, cols: int, rows: int) -> None:
        self._size = (cols, rows)
        self._spawn()

    def _on_resized(self, cols: int, rows: int) -> None:
        self._size = (cols, rows)
        if self.session is not None:
            self.session.resize(cols, rows)

    def _spawn(self) -> None:
        try:
            self.session.start(*self._size)
        except Exception as exc:  # noqa: BLE001 -- the MCP server could not bind, the program could not start
            self.status.set_text("Could not start")
            self.status.set_tone("error")
            self.terminal.write(f"\r\n\x1b[31m[Claude Code could not be started: {exc}. "
                                "Use Restart to try again.]\x1b[0m\r\n".encode("utf-8", "replace"))
            return
        self.status.set_text("Running")
        self.status.set_tone("ok")
        self.terminal.focus_terminal()

    def restart(self) -> None:
        if self.session is not None:
            self.session.stop()
            self.terminal.reset()
            self._spawn()

    def _on_exited(self, code: int) -> None:
        if self.terminal is None:       # reported while the window was closing
            return
        self.status.set_text(f"Ended (exit code {code})")
        self.status.set_tone("muted" if code in (0, 143) else "warning")
        self.terminal.write(b"\r\n\x1b[2m[Claude Code ended. Use Restart to start it again.]\x1b[0m\r\n")

    def refresh_colors(self) -> None:
        if self.terminal is not None:
            self.terminal.set_tokens(self.app.theme.tokens)

    def shutdown(self) -> None:
        """End the process, the MCP server and the terminal page (window close, project switch, app quit)."""
        if self.session is not None:
            self.session.shutdown()
        if self.terminal is not None:
            self.terminal.shutdown()
            self.terminal = None
            self.session = None
