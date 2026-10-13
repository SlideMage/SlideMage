"""The assistant card of the right column (workspace v6 handoff, section 3): one card for every route, in place of
the Chat | Claude Code tabs.

A header (assistant_header.py: the route, the scope, the task buttons, the running task), the task row (task_row.py:
the status of batches, image tasks and the summary) and a body that follows the AI switch: the native chat
(chat/view.py) on Local and Cloud · API, the real terminal (terminal/view.py) on Cloud · Claude Code. A task on one
slide takes the body's place with its task card (task_card.py) until Back to conversation (the header's pill brings it
back) or until it is closed; an image task, when it ends, takes it with the results panel (pages/image_results.py:
what became of each image, Retry failed) until Back to conversation. The scope and the TaskRunner (terminal/tasks.py) are the card's, so both bodies and the
header share them; "New conversation" clears the route on show and no other.
Focus hides the side panels (side_panels.py listens); it is not remembered.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QScrollArea, QStackedWidget

from ...ai import ai_profile
from ...ai.agent_context import SCOPE_DECK, SCOPE_SLIDE
from ...ai.agent_types import EDIT_AUTO
from ...ai.claude_tasks import TRANSLATE
from ..kit import kit_qss as q
from ..kit.widgets import Card, SegmentedControl
from ..pages.image_results import BatchResultView
from .assistant_header import AssistantHeader
from .chat.gui_workspace import GuiWorkspace
from .chat.view import ChatView
from .state import WorkspaceState
from .task_card import TaskCardView
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
        self.tasks = TaskRunner(app, self.workspace, self, edit_auto=lambda: self.chat.session.mode == EDIT_AUTO)
        self.chat = ChatView(app, state, self.scope)
        self.claude_code = ClaudeCodeView(app, state, self.scope, self.tasks)
        self.header = AssistantHeader(app, state, self.scope, self.tasks, self._tasks_blocked)
        self.task_row = TaskRow(app, self.tasks)
        self.task_card = TaskCardView(app, self.tasks)
        self.image_results = BatchResultView(back=True)
        self._stack = QStackedWidget()
        self._stack.setObjectName(q.SURFACE)
        self._results_page = self._scrolled(self.image_results)
        for body in (self.chat, self.claude_code, self.task_card, self._results_page):
            self._stack.addWidget(body)
        for widget, stretch in ((self.header, 0), (self.task_row, 0), (self._stack, 1)):
            self.layout().addWidget(widget, stretch)

        self.header.focus_toggled.connect(self.focus_toggled)
        self.header.new_conversation.connect(self.new_conversation)
        self.header.task_chosen.connect(self.run_task)
        self.header.task_opened.connect(self._open_task)
        self.task_card.back_clicked.connect(self.tasks.hide_card)
        self.task_card.sign_in_clicked.connect(self._sign_in)
        self.tasks.card_changed.connect(self._show_body)
        self.tasks.result_changed.connect(self._show_body)
        self.image_results.retry_clicked.connect(self.tasks.retry_failed)
        self.image_results.closed.connect(self.tasks.close_result)
        self.chat.route_changed.connect(self._refresh_route)
        self.claude_code.setup_changed.connect(self.header.schedule)
        state.ai_route_changed.connect(self._show_body)
        self._show_body()
        self._refresh_route()

    def _tasks_blocked(self) -> bool:
        """The task buttons wait while the amber card asks for Claude Code to be installed or signed in."""
        return self.state.ai_route == ai_profile.CLAUDE_CODE and self.claude_code.needs_setup

    @staticmethod
    def _scrolled(body: BatchResultView) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setObjectName(q.SURFACE)
        scroll.viewport().setObjectName(q.SURFACE)
        scroll.setWidget(body)
        return scroll

    def _show_body(self, _route: str = "") -> None:
        """The task card while there is one on show, else the image results, else the conversation of the route."""
        card, result = self.tasks.card, self.tasks.result
        if card is not None and not card.hidden:
            self._stack.setCurrentWidget(self.task_card)
        elif result is not None:
            if self.image_results.result is not result:
                self.image_results.show_result(result)
            self._stack.setCurrentWidget(self._results_page)
        else:
            self._stack.setCurrentWidget(self.claude_code if self.state.ai_route == ai_profile.CLAUDE_CODE else self.chat)

    def _open_task(self) -> None:
        """The header's pill: the task card that was left, else the line of the running batch."""
        if self.tasks.card is not None:
            self.tasks.show_card()
        else:
            self.task_row.reveal()

    def _sign_in(self) -> None:
        self.tasks.close_card()
        self.claude_code.sign_in()

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
        """Start a task of the header or the palette; a route that cannot run it says why on the task card (or, for a
        batch, in the task row)."""
        self.tasks.start(bubble.task, bubble.paths, bubble.label)

    def translate_slide(self) -> None:
        """The Language panel's Translate: the Translate task of the slide in view, on its card."""
        bubble = next((b for b in self.header.offers(SCOPE_SLIDE) if b.task is TRANSLATE), None)
        if bubble is None:
            self.app.toast.show_message("This slide cannot be translated: it has a translation, or is not EN or DE.")
        else:
            self.run_task(bubble)

    def refresh_colors(self) -> None:
        self.claude_code.refresh_colors()

    def shutdown(self) -> None:
        """The window closes: end a running chat request, the tasks and the Claude Code process."""
        self.chat.shutdown()
        self.claude_code.shutdown()
        self.tasks.shutdown()
        self.workspace.close()
