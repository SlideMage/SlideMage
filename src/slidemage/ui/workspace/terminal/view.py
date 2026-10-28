# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Claude Code body of the assistant card (assistant.py), shown while the route is Cloud · Claude Code: the
user's own `claude`, running in a terminal in the project folder, connected to SlideMage (session.py).

Two bodies. No `claude` found, or not signed in (`claude auth status`): an amber card says so, with "Check again"
or "Sign in…" (which starts the terminal, where Claude Code asks for its login itself); nothing is sent and no other
model is used meanwhile. Otherwise a terminal, started the first time the view is shown (not at launch, and the
web view is not even created before): the process lives on while the view is out of sight (the column hidden, the
Images page). Leaving the route ends it
(`end_session`, after the switch asked), and showing the view again starts a new one. When it ends by itself, the
terminal keeps its text, the status chip says so and Restart starts a new one. Closing the window and `shutdown()`
end the process.

Under the terminal: the caption with the model the task buttons of the header use. The task buttons, their status
line and the scope (This slide | Whole deck) are the assistant card's (tasks.py does the work).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QPalette, QShowEvent
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout

from ....ai import ai_profile, claude_launch, tasks as ai_tasks
from ....ai.claude_scope import DECK
from ... import background
from ...kit import kit_qss as q
from ...kit.widgets import Button, Chip, IconButton, IconLabel, SegmentedControl, Surface, caption
from ..attachments import place_file, save_image
from ..state import WorkspaceState
from .draft import input_box_shown, paste_bytes, prompt_draft
from ..task_bubbles import TaskRunner, bubbles

SETUP, TERMINAL = 0, 1
# switch_session: the pause between the two Esc of Esc Esc, and the time Claude Code gets to save the draft.
ESC_GAP_MS, SAVE_DRAFT_MS = 250, 600
# switch_session: how often and how long the restarted Claude Code is looked at for its input box, to type the draft.
DRAFT_POLL_MS, DRAFT_WAIT_MS = 300, 20_000
NEVER_SENT = "Cloud stays selected. Nothing is sent and no other model is used"
INSTALL_TEXT = ("SlideMage runs your own Claude Code here, in the project folder, with your Claude "
                "subscription. It is not installed on this computer (or not found).")
INSTALL_STEPS = (f'Install it as the <a href="{claude_launch.INSTALL_URL}">Claude Code setup guide</a> says, '
                 "start <b>claude</b> once in a terminal to sign in, then come back and check again.")
NOT_INSTALLED = ("Claude Code is not installed", f"{INSTALL_TEXT} {NEVER_SENT} until it is.", INSTALL_STEPS, "Check again")
NOT_SIGNED_IN = ("Claude Code is not signed in", f"{NEVER_SENT} until you sign in.", "", "Sign in…")


class _SignedIn(QThread):
    """Asks `claude auth status`, off the GUI thread."""

    answer = Signal(object)         # True, False, or None when Claude Code cannot say

    def __init__(self, claude: Path) -> None:
        super().__init__()
        self.claude = claude

    def run(self) -> None:
        self.answer.emit(claude_launch.signed_in(self.claude))


class ClaudeCodeView(Surface):
    subtitle = "Terminal · permissions are handled in Claude Code"      # the assistant header's note for this surface
    notice = Signal(str, str)       # a line for the assistant's task row: its text and tone
    setup_changed = Signal()        # the amber card came up or went (the task buttons wait for it)

    def __init__(self, app, state: WorkspaceState, scope: SegmentedControl, tasks: TaskRunner, *, context=None) -> None:
        """`scope` is the assistant header's; `tasks` its runner, which the terminal's translate tool asks."""
        super().__init__()
        self._surface_context = context
        self.app = app
        self.state = state
        self.scope = scope
        self.tasks = tasks
        self.session = None                       # created with the terminal
        self.terminal = None
        self._started = False
        self._closed = False
        self._restart_on_show = False             # the route left and came back: a new session
        self._checking: _SignedIn | None = None
        self._claude: Path | None = None
        self._size = (80, 24)
        scope.changed.connect(self._on_scope)
        self._stack = QStackedWidget()
        self._stack.setObjectName(q.SURFACE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)
        self._stack.addWidget(self._build_setup())
        self._terminal_page = Surface()
        self._terminal_layout = QVBoxLayout(self._terminal_page)
        self._terminal_layout.setContentsMargins(0, 0, 0, 0)
        self._terminal_layout.setSpacing(4)
        self._terminal_layout.addLayout(self._build_status_row())
        self.caption = caption("")
        self.caption.setTextFormat(Qt.TextFormat.RichText)
        self.caption.linkActivated.connect(lambda _link: self.app.ai_route.open_setup())
        self._terminal_layout.addWidget(self.caption)
        self._stack.addWidget(self._terminal_page)
        self.refresh_caption()
        self.refresh_colors()
        QCoreApplication.instance().aboutToQuit.connect(self.shutdown)

    # -- building ---------------------------------------------------------------------------

    def _build_setup(self) -> Surface:
        """The amber card that replaces the terminal while Claude Code cannot be used."""
        page = Surface()
        box = QVBoxLayout(page)
        box.setAlignment(Qt.AlignmentFlag.AlignTop)
        card = QFrame()
        card.setObjectName(q.CLOUD_CARD)
        inner = QVBoxLayout(card)
        inner.setContentsMargins(14, 14, 14, 14)
        inner.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(IconLabel("cloud", 20))
        self.setup_title = QLabel()
        self.setup_title.setObjectName(q.ASSISTANT_TITLE)
        head.addWidget(self.setup_title, 1)
        inner.addLayout(head)
        self.setup_text = QLabel()
        self.setup_text.setWordWrap(True)
        inner.addWidget(self.setup_text)
        self.setup_steps = QLabel()
        self.setup_steps.setWordWrap(True)
        self.setup_steps.setOpenExternalLinks(True)
        inner.addWidget(self.setup_steps)
        self.setup_button = Button("", "cloud", compact=True)
        self.setup_button.clicked.connect(self.sign_in)
        inner.addWidget(self.setup_button, 0, Qt.AlignmentFlag.AlignLeft)
        box.addWidget(card)
        return page

    def _show_setup(self, title: str, text: str, steps: str, button: str) -> None:
        self.setup_title.setText(title)
        self.setup_text.setText(text)
        self.setup_steps.setText(steps)
        self.setup_steps.setVisible(bool(steps))
        self.setup_button.setText(button)
        self._stack.setCurrentIndex(SETUP)
        self.setup_changed.emit()

    @property
    def needs_setup(self) -> bool:
        """The amber card is up: Claude Code is not installed or not signed in."""
        return self._stack.currentIndex() == SETUP and self._started

    def _build_status_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.status = Chip("Starting…", "muted")
        row.addWidget(self.status)
        row.addStretch(1)
        self.attach_button = IconButton("attach_file", "Attach a paper (PDF), a figure or another file: "
                                                       "Claude Code gets its @path at the prompt")
        self.attach_button.clicked.connect(self._pick_files)
        self.attach_button.setEnabled(False)
        row.addWidget(self.attach_button)
        self.restart_button = Button("Restart", "ghost", compact=True)
        self.restart_button.setToolTip("End Claude Code and start it again in this project (the conversation "
                                       "can be continued with /resume).")
        self.restart_button.clicked.connect(lambda: self.restart())     # a new conversation
        row.addWidget(self.restart_button)
        return row

    def refresh_caption(self) -> None:
        """What the header's task buttons run on: the model of the Claude Code route for fixes (AI setup)."""
        route = (self._surface_context.selected_route(ai_profile.CLAUDE_CODE, ai_profile.FIXES)
                 if self._surface_context else ai_profile.route_for(self.state.project, ai_profile.CLAUDE_CODE, ai_profile.FIXES))
        self.caption.setText("Permissions are handled in Claude Code. Conversation model: set in Claude Code. "
                             f"Task buttons: {route.label.removeprefix('Claude Code · ')} "
                             '(<a href="setup">AI setup</a>).')

    def _on_scope(self, scope: str) -> None:
        if self.session is not None:
            self.session.set_scope(scope)

    def _switch_to_deck(self) -> str:
        """The terminal's switch_to_deck_mode, which the user has allowed (GUI thread)."""
        if self.state.deck is None:
            return "No deck is open in SlideMage: ask the user to open one."
        self.scope.set_current(DECK)
        self.scope.changed.emit(DECK)           # set_current is no click: tell the session and the header
        return "SlideMage is in Deck Mode now: go on with the request."

    # -- attachments ------------------------------------------------------------------------------

    def _pick_files(self) -> None:
        names, _filter = QFileDialog.getOpenFileNames(self, "Attach files", str(self.state.project.root))
        self.attach_files(names)

    def attach_files(self, names: list[str]) -> None:
        """Place the files in the project (see attachments.py) and type their @paths at the prompt."""
        for name in names:
            try:
                rel = (self._surface_context.attach_file(Path(name)) if self._surface_context
                       else place_file(self.state.project, name, dash_spaces=True))
            except OSError as exc:
                self.notice.emit(f"{Path(name).name} could not be attached: {exc.strerror or exc}", "error")
                continue
            if rel:
                self._mention(rel)

    def attach_image(self, image) -> None:
        rel = (self._surface_context.attach_image(image) if self._surface_context
               else save_image(self.state.project, image))
        if rel:
            self._mention(rel)
        else:
            self.notice.emit("The pasted image could not be attached.", "error")

    def _mention(self, rel: str) -> None:
        """Type `@path ` at the prompt without Enter; a path with spaces is quoted."""
        if self.session is None or not self.session.running:
            return
        self.session.write((f'@"{rel}" ' if " " in rel else f"@{rel} ").encode("utf-8"))
        self.terminal.focus_terminal()

    def switch_session(self) -> bool:
        """Move the running Claude Code onto the saved default model and effort, keeping its conversation and the
        prompt typed but not sent: that is read off the screen (draft.py), then Esc Esc stops a reply that is
        running (and puts the prompt into Claude Code's input history too), then a restart with --resume
        (ClaudeCodeSession.start), and once the new input box is up the prompt is typed into it again, not sent.
        /model would also make the model Claude Code's own default for every session, which SlideMage leaves alone.
        False without a running session."""
        if not self.session_live:
            return False
        if self.terminal is None:
            self._switch_keeping("")
        else:
            self.terminal.read_screen(lambda lines: self._switch_keeping(prompt_draft(lines)))
        return True

    def _switch_keeping(self, draft: str) -> None:
        if not self.session_live:
            return
        self.session.write(b"\x1b")
        QTimer.singleShot(ESC_GAP_MS, lambda: self.session_live and self.session.write(b"\x1b"))
        QTimer.singleShot(ESC_GAP_MS + SAVE_DRAFT_MS, lambda: self._resume_with(draft))

    def _resume_with(self, draft: str) -> None:
        self.restart(resume=True)
        if draft and self.terminal is not None:
            self._restore_draft(draft, DRAFT_WAIT_MS // DRAFT_POLL_MS)

    def _restore_draft(self, draft: str, tries: int) -> None:
        """Type `draft` into the restarted Claude Code's input box once it is on the screen, empty; looked for every
        DRAFT_POLL_MS for DRAFT_WAIT_MS, after which the draft is only in Claude Code's input history (Esc Esc)."""
        def check(lines: list) -> None:
            if not self.session_live:
                return
            if input_box_shown(lines):
                self.session.write(paste_bytes(draft))
            elif tries > 1:
                self._restore_draft(draft, tries - 1)
        QTimer.singleShot(DRAFT_POLL_MS, lambda: self.terminal is not None and self.terminal.read_screen(check))

    def _set_attachable(self) -> None:
        self.attach_button.setEnabled(self.session is not None and self.session.running)

    # -- the terminal's translate tool ---------------------------------------------------------------

    def _translate_slide(self, path: Path) -> str:
        """The terminal's translate_slide: the slide into view, then its Translate bubble (GUI thread)."""
        self.session.workspace.show_slide(path)
        bubble = next((b for b in bubbles(self.app) if b.task is ai_tasks.TRANSLATE), None)
        if bubble is None:
            return f"{path.name} has a translation already, or is not EN or DE: there is nothing to translate."
        if self.tasks.occupied:
            return "SlideMage is busy with another task; ask the user to try again when its card is done."
        if reason := self.tasks.refusal(bubble.task):
            return reason
        self.tasks.start(bubble.task, bubble.paths, bubble.label)
        return f"SlideMage is translating it ({bubble.label}); the task card in the assistant shows the proposed slide."

    # -- starting and stopping --------------------------------------------------------------------

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._started:
            self._started = True
            self._open()
        elif self._restart_on_show:
            self._restart_on_show = False
            self.restart()
        if self.terminal is not None:
            self.terminal.focus_terminal()

    def _open(self) -> None:
        """Show the card that says what is missing, or build the terminal (once) and start Claude Code in it."""
        self._claude = claude_launch.find_claude()
        if self._claude is None:
            self._show_setup(*NOT_INSTALLED)
        elif self.terminal is None and self._checking is None:
            self._stack.setCurrentIndex(TERMINAL)
            self.setup_changed.emit()
            self._checking = checking = _SignedIn(self._claude)
            checking.answer.connect(self._on_signed_in)
            background.start_detached(checking)

    def _on_signed_in(self, signed_in) -> None:
        """`claude auth status` answered: the terminal, unless Claude Code says it is signed out."""
        self._checking = None
        if self._closed:
            return
        if signed_in is False:
            self._show_setup(*NOT_SIGNED_IN)
        else:
            self._build_terminal(self._claude)

    def sign_in(self) -> None:
        """The amber card's button, and the task card's Sign in…: "Check again" looks for `claude` again, "Sign in…"
        starts the terminal, where Claude Code asks for its login itself."""
        if self._claude is None:
            self._open()
        else:
            self._stack.setCurrentIndex(TERMINAL)
            self._build_terminal(self._claude)

    def _build_terminal(self, claude: Path) -> None:
        # Imported here: the web engine is heavy, and most sessions never open this view.
        from .session import ClaudeCodeSession
        from .service import TerminalService

        if self.terminal is not None:
            return
        self.session = ClaudeCodeSession(self.app, claude, self)
        self.setup_changed.emit()
        self.session.scope = self.scope.current()
        self.terminal = TerminalService(self.state.project.root, lambda: self.app.theme.tokens).create_widget()
        self._terminal_layout.insertWidget(1, self.terminal, 1)
        self.session.workspace.translate = self._translate_slide
        self.session.workspace.widen = self._switch_to_deck
        self.terminal.ready.connect(self._on_ready)
        self.terminal.resized.connect(self._on_resized)
        self.terminal.input_data.connect(self.session.write)
        self.terminal.files_dropped.connect(self.attach_files)
        self.terminal.image_pasted.connect(self.attach_image)
        self.session.output.connect(self.terminal.write)
        self.session.exited.connect(self._on_exited)

    def _on_ready(self, cols: int, rows: int) -> None:
        self._size = (cols, rows)
        self._spawn()

    def _on_resized(self, cols: int, rows: int) -> None:
        self._size = (cols, rows)
        if self.session is not None:
            self.session.resize(cols, rows)

    def _spawn(self, resume: bool = False) -> None:
        try:
            choice = getattr(self, "_next_choice", None)
            self._next_choice = None
            if choice is None:
                self.session.start(*self._size, resume=resume)
            else:
                self.session.start(*self._size, resume=resume, choice=choice)
        except Exception as exc:  # noqa: BLE001 -- the MCP server could not bind, the program could not start
            self.status.set_text("Could not start")
            self.status.set_tone("error")
            self.terminal.write(f"\r\n\x1b[31m[Claude Code could not be started: {exc}. "
                                "Use Restart to try again.]\x1b[0m\r\n".encode("utf-8", "replace"))
            return
        self.status.set_text("Running")
        self.status.set_tone("ok")
        self._set_attachable()
        self.terminal.focus_terminal()

    def restart(self, choice: str | None = None, continue_conversation: bool = False, *, resume: bool = False) -> None:
        """Restart on the saved choice, optionally preserving the conversation and pending input."""
        if choice is not None:
            self._next_choice = choice
        if continue_conversation:
            self.switch_session()
            return
        if self.session is not None:
            self.session.stop()
            self.terminal.reset()
            self._set_attachable()
            self._spawn(resume)

    @property
    def session_live(self) -> bool:
        """Whether the terminal's Claude Code process is running (it cannot be told whether it is idle)."""
        return self.session is not None and self.session.running

    def stop(self) -> None:
        self.end_session()

    def end_session(self) -> None:
        """The AI switch leaves Claude Code: end the process; showing the view again starts a new one."""
        if not self.session_live:
            return
        self.session.stop()
        self._restart_on_show = True
        self._set_attachable()
        self.status.set_text("Ended")
        self.status.set_tone("muted")
        self.terminal.write(b"\r\n\x1b[2m[Claude Code ended: AI tasks use another route now. "
                            b"It starts again when you switch back.]\x1b[0m\r\n")

    def _on_exited(self, code: int) -> None:
        if self.terminal is None:       # reported while the window was closing
            return
        self._set_attachable()
        self.status.set_text(f"Ended (exit code {code})")
        self.status.set_tone("muted" if code in (0, 143) else "warning")
        self.terminal.write(b"\r\n\x1b[2m[Claude Code ended. Use Restart to start it again.]\x1b[0m\r\n")

    def refresh_colors(self) -> None:
        palette = self.caption.palette()           # the caption's link: QSS cannot color it
        palette.setColor(QPalette.ColorRole.Link, QColor(self.app.theme.tokens.info))
        self.caption.setPalette(palette)
        if self.terminal is not None:
            self.terminal.set_tokens(self.app.theme.tokens)

    def shutdown(self) -> None:
        """End the process, the MCP server and the terminal page (window close, project switch, app quit)."""
        self._closed = True
        if self._surface_context is not None:
            self._surface_context.close()
            self._surface_context = None
        if self.session is not None:
            self.session.shutdown()
        if self.terminal is not None:
            self.terminal.shutdown()
            self.terminal = None
            self.session = None
