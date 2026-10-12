"""The Claude Code view of the assistant area (UI redesign step 10c): the user's own `claude`, running in a
terminal in the project folder, connected to SlideMage (session.py).

Three states. No `claude` found: an install hint and "Check again". Otherwise a terminal, started the first
time the view is shown (not at launch, and the web view is not even created before): the process lives on
while the user looks at the chat. When it ends, the terminal keeps its text, the status chip says so and
Restart starts a new one. Closing the window, switching project and `shutdown()` end the process.

Under the status row: the suggestion bubbles for the slide in the Source view (with the scope on Deck, for the
open deck), the model and effort the next bubble task runs with (remembered per user), and the status line of
the running or last task, with Stop (tasks.py does the work).
"""
from __future__ import annotations

from functools import partial
from pathlib import Path

from PySide6.QtCore import QCoreApplication, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QShowEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QStackedWidget, QVBoxLayout

from ....ai import claude_launch, claude_runner, claude_tasks
from ....ai.claude_scope import DECK, SLIDE
from ... import layout_settings
from ...kit import kit_qss as q
from ...kit.widgets import (
    Button, Chip, ModalSheet, PopoverMenu, SegmentedControl, Surface, caption, set_property)
from ..state import WorkspaceState
from .tasks import Bubble, TaskRunner, bubbles, deck_bubbles

HINT, TERMINAL = 0, 1
BUBBLE_DELAY_MS = 500
MODEL_SETTING, EFFORT_SETTING = "claude_task_model", "claude_task_effort"
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
        self.tasks: TaskRunner | None = None
        self.terminal = None
        self._typing = QTimer(self)               # the bubbles follow the text a moment after the last keystroke
        self._typing.setSingleShot(True)
        self._typing.setInterval(BUBBLE_DELAY_MS)
        self._typing.timeout.connect(self._refresh_bubbles)
        self._shown = 0                           # of them, the buttons that fit
        self._bubbles: list[Bubble] = []          # the tasks that fit the slide, as buttons or under "More"
        self._model = self._remembered(MODEL_SETTING, claude_runner.MODELS, claude_runner.MODEL)
        self._effort = self._remembered(EFFORT_SETTING, claude_runner.EFFORTS, claude_runner.EFFORT)
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
        self._terminal_layout.addLayout(self._build_bubble_row())
        self._terminal_layout.addLayout(self._build_task_row())
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

    def _build_bubble_row(self) -> QHBoxLayout:
        self._bubble_row = QHBoxLayout()
        self._bubble_row.setContentsMargins(0, 0, 0, 0)
        self.more = Button("More  ▾", "ghost", compact=True)
        self.more.setToolTip("The other tasks that fit this slide.")
        self.more.clicked.connect(self._open_more)
        self.more.hide()
        self._bubble_row.addWidget(self.more)
        self._bubble_row.addStretch(1)
        return self._bubble_row

    def _build_task_row(self) -> QHBoxLayout:
        """The status line of the task, its buttons and the picker: the picker is always there, so that it never
        takes room from the bubbles."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.task_status = caption("")
        row.addWidget(self.task_status, 1)
        self.result_button = Button("Show result", "ghost", compact=True)
        self.result_button.clicked.connect(self._show_result)
        self.result_button.hide()
        row.addWidget(self.result_button)
        self.stop_button = Button("Stop", "secondary", compact=True)
        self.stop_button.clicked.connect(lambda: self.tasks.stop())
        self.stop_button.hide()
        row.addWidget(self.stop_button)
        self.picker = Button("", "ghost", compact=True)
        self.picker.setToolTip("The model and the effort of the tasks and of the terminal (from its next start).")
        self.picker.clicked.connect(self._open_picker)
        self._show_pick()
        row.addWidget(self.picker)
        return row

    def _on_scope(self, scope: str) -> None:
        if self.session is not None:
            self.session.set_scope(scope)

    def _switch_to_deck(self) -> str:
        """The terminal's switch_to_deck_mode, which the user has allowed (GUI thread)."""
        if self.state.deck is None:
            return "No deck is open in SlideMage: ask the user to open one."
        self.scope.set_current(DECK)
        self._on_scope(DECK)                    # set_current is no click: tell the session (and the bubbles)
        return "SlideMage is in Deck Mode now: go on with the request."

    # -- bubbles and tasks ------------------------------------------------------------------------

    @staticmethod
    def _remembered(key: str, choices: tuple[str, ...], default: str) -> str:
        value = layout_settings.get(key)
        return value if value in choices else default

    def _show_pick(self) -> None:
        self.picker.setText(f"{self._model.capitalize()} · {self._effort}  ▾")

    def _open_picker(self) -> None:
        menu = PopoverMenu(self, min_width=160)
        menu.add_header("Model")
        for model in claude_runner.MODELS:
            menu.add_item(f"{MODEL_SETTING}:{model}", model.capitalize(), icon="check" if model == self._model else "")
        menu.add_header("Effort")
        for effort in claude_runner.EFFORTS:
            menu.add_item(f"{EFFORT_SETTING}:{effort}", effort, icon="check" if effort == self._effort else "")
        menu.triggered.connect(self._on_picked)
        menu.closed.connect(menu.deleteLater)
        menu.popup_below(self.picker, align_right=True)

    def _on_picked(self, key: str) -> None:
        setting, _, value = key.partition(":")
        layout_settings.set(setting, value)
        if setting == MODEL_SETTING:
            self._model = value
        else:
            self._effort = value
        self._show_pick()
        if self.session is not None:
            self.session.model, self.session.effort = self._model, self._effort
            if self.session.running:     # switching would end the conversation: the user restarts when it suits
                self._on_task_status(f"Tasks use {self._model.capitalize()} · {self._effort} now; "
                                     "the terminal after Restart.", "muted")

    def _refresh_bubbles(self) -> None:
        """Show the buttons for the tasks that fit the slide now (none while a task runs)."""
        if self.tasks is None:
            return
        if self.tasks.busy:
            found = []
        else:
            found = deck_bubbles(self.app) if self.scope.current() == DECK else bubbles(self.app)
        if found == self._bubbles:
            return
        for _ in self._bubbles:
            button = self._bubble_row.takeAt(0).widget()
            button.setParent(None)                     # gone now, not at the next event loop
            button.deleteLater()
        for index, bubble in enumerate(found):
            button = Button(bubble.label, "secondary", compact=True)
            button.clicked.connect(partial(self._run, bubble))
            self._bubble_row.insertWidget(index, button)
        self._bubbles = found
        self._fit()

    def _fit(self) -> None:
        """Show as many bubble buttons as fit the row, and the rest under "More"."""
        buttons = [self._bubble_row.itemAt(i).widget() for i in range(len(self._bubbles))]
        spacing, room = self._bubble_row.spacing(), self.width()
        widths = [button.sizeHint().width() + spacing for button in buttons]
        reserve = 0 if sum(widths) <= room else self.more.sizeHint().width() + spacing
        shown, used = 0, reserve
        for width in widths:
            if used + width > room:
                break
            used, shown = used + width, shown + 1
        for index, button in enumerate(buttons):
            button.setVisible(index < shown)
        self.more.setVisible(shown < len(buttons))
        self._shown = shown

    def _open_more(self) -> None:
        menu = PopoverMenu(self, min_width=180)
        for index in range(self._shown, len(self._bubbles)):
            menu.add_item(str(index), self._bubbles[index].label)
        menu.triggered.connect(lambda key: self._run(self._bubbles[int(key)]))
        menu.closed.connect(menu.deleteLater)
        menu.popup_below(self.more)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()

    def _run(self, bubble: Bubble) -> None:
        self.tasks.start(bubble.task, self._model, self._effort, bubble.paths)

    def _translate_slide(self, path: Path) -> str:
        """The terminal's translate_slide: the slide into view, then its Translate bubble (GUI thread)."""
        self.session.workspace.show_slide(path)
        bubble = next((b for b in bubbles(self.app) if b.task is claude_tasks.TRANSLATE), None)
        if bubble is None:
            return f"{path.name} has a translation already, or is not EN or DE: there is nothing to translate."
        if self.tasks.busy:
            return "SlideMage is busy with another task; ask the user to try again when its status line is done."
        self._run(bubble)
        return f"SlideMage is translating it ({bubble.label}); the new slide opens when it is done."

    def _on_task_status(self, text: str, tone: str) -> None:
        self.task_status.setText(text)
        set_property(self.task_status, "tone", tone)
        self.result_button.setVisible(bool(self.tasks.unapplied or self.tasks.report))

    def _on_busy(self, busy: bool) -> None:
        self.stop_button.setVisible(busy)
        self.result_button.hide()
        self._refresh_bubbles()

    def _show_result(self) -> None:
        tasks = self.tasks
        self._show_text(*(("Claude's result", tasks.unapplied) if tasks.unapplied
                          else ("What became of each slide", tasks.report)))

    def _show_text(self, title: str, content: str) -> None:
        sheet = ModalSheet(title, self.app, width=640)
        text = QPlainTextEdit(content)
        text.setReadOnly(True)
        sheet.add_tab(title, text)
        sheet.add_button("Copy").clicked.connect(lambda: QGuiApplication.clipboard().setText(text.toPlainText()))
        sheet.add_button("Close", kind="primary", role="accept")
        sheet.exec()

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
        self.session.model, self.session.effort = self._model, self._effort
        self.terminal = TerminalWidget(self.app.theme.tokens)
        self._terminal_layout.addWidget(self.terminal, 1)
        self.tasks = TaskRunner(self.app, claude, self.session.workspace, self)
        self.session.workspace.translate = self._translate_slide
        self.session.workspace.widen = self._switch_to_deck
        self.tasks.status.connect(self._on_task_status)
        self.tasks.busy_changed.connect(self._on_busy)
        self.tasks.summary.connect(lambda text: self._show_text("Summary of the deck", text))
        self.session.focus_changed.connect(self._refresh_bubbles)
        self.app.centre.source.buffer_changed.connect(lambda _path: self._typing.start())
        self._refresh_bubbles()
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
        if self.tasks is not None:
            self.tasks.shutdown()
            self.tasks = None
        if self.terminal is not None:
            self.terminal.shutdown()
            self.terminal = None
            self.session = None
