"""The assistant card of the right column (workspace v6 handoff, section 3): one card for every route, in place of
the Chat | Claude Code tabs.

A header (assistant_header.py: the route, the scope, the task buttons, the running task), the status line of the
tasks (task_row.py) and a body that follows the AI switch: the native chat (chat/view.py) on Local and Cloud · API,
the real terminal (terminal/view.py) on Cloud · Claude Code. The scope and the TaskRunner (terminal/tasks.py) are the
card's, so both bodies and the header share them; "New conversation" clears the route on show and no other.
Focus hides the side panels (side_panels.py listens); it is not remembered.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QStackedWidget

from ...ai import ai_profile
from ...ai.agent_context import SCOPE_DECK, SCOPE_SLIDE
from ..kit import kit_qss as q
from ..kit.widgets import Card, SegmentedControl
from .assistant_header import AssistantHeader
from .chat.gui_workspace import GuiWorkspace
from .chat.view import ChatView
from .state import WorkspaceState
from .task_row import TaskRow
from .terminal.tasks import Bubble, TaskRunner
from .terminal.view import ClaudeCodeView

MIN_HEIGHT = 380   # the prototype's: the side panels give way first
SCOPES = ((SCOPE_SLIDE, "This slide"), (SCOPE_DECK, "Whole deck"))


class AssistantArea(Card):
    focus_toggled = Signal(bool)

    def __init__(self, app, state: WorkspaceState) -> None:
        super().__init__()
        self.setMinimumHeight(MIN_HEIGHT)
        self.layout().setContentsMargins(16, 12, 16, 16)
        self.app, self.state = app, state
        self.scope = SegmentedControl(SCOPES, current=SCOPE_SLIDE)
        self.workspace = GuiWorkspace(app)                  # where the tasks write: its own, apart from both bodies'
        self.tasks = TaskRunner(app, self.workspace, self)
        self.chat = ChatView(app, state, self.scope)
        self.claude_code = ClaudeCodeView(app, state, self.scope, self.tasks)
        self.header = AssistantHeader(app, state, self.scope, self.tasks, self._tasks_blocked)
        self.task_row = TaskRow(app, self.tasks)
        self._stack = QStackedWidget()
        self._stack.setObjectName(q.SURFACE)
        self._stack.addWidget(self.chat)
        self._stack.addWidget(self.claude_code)
        for widget, stretch in ((self.header, 0), (self.task_row, 0), (self._stack, 1)):
            self.layout().addWidget(widget, stretch)

        self.header.focus_toggled.connect(self.focus_toggled)
        self.header.new_conversation.connect(self.new_conversation)
        self.header.task_chosen.connect(self.run_task)
        self.header.task_opened.connect(self.task_row.reveal)
        self.chat.route_changed.connect(self._refresh_route)
        self.claude_code.setup_changed.connect(self.header.schedule)
        state.ai_route_changed.connect(self._show_body)
        self._show_body()
        self._refresh_route()

    def _tasks_blocked(self) -> bool:
        """The task buttons wait while the amber card asks for Claude Code to be installed or signed in."""
        return self.state.ai_route == ai_profile.CLAUDE_CODE and self.claude_code.needs_setup

    def _show_body(self, _route: str = "") -> None:
        self._stack.setCurrentWidget(self.claude_code if self.state.ai_route == ai_profile.CLAUDE_CODE else self.chat)

    def _refresh_route(self) -> None:
        """The header names the route on show and, for the chat, the model that answers."""
        route = ai_profile.Route(ai_profile.CLAUDE_CODE, ai_profile.CHAT) if self.state.ai_route == ai_profile.CLAUDE_CODE \
            else self.chat.route()
        self.header.show_route(route)

    def refresh_models(self) -> None:
        """A route, a default model or a list of models changed (AI setup, Settings, Ollama answering)."""
        self.chat.refresh_route()
        self.claude_code.refresh_caption()
        self.header.schedule()

    def new_conversation(self) -> None:
        """Forget the conversation of the route on show: the chat's, or the terminal's (a new Claude Code session;
        /resume goes back). The other route's is kept."""
        if self.state.ai_route == ai_profile.CLAUDE_CODE:
            self.claude_code.restart()
        else:
            self.chat.new_chat()

    def run_task(self, bubble: Bubble) -> None:
        """Start a task of the header or the palette; a route that cannot run it says why instead (the task row
        says it too, as `start` does)."""
        if reason := self.tasks.refusal(bubble.task):
            self.app.toast.show_message(reason)
        self.tasks.start(bubble.task, bubble.paths)

    def refresh_colors(self) -> None:
        self.claude_code.refresh_colors()

    def shutdown(self) -> None:
        """The window closes: end a running chat request, the tasks and the Claude Code process."""
        self.chat.shutdown()
        self.claude_code.shutdown()
        self.tasks.shutdown()
        self.workspace.close()
