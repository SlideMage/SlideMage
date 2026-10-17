"""The assistant card of the right column (workspace v6 handoff, section 3): one card for every route, in place of
the Chat | Claude Code tabs.

A header (assistant_header.py: the route, the scope, the task buttons, the running task), the task row (task_row.py:
the status of batches, image tasks and the summary) and a body that follows the AI switch: the native chat
(chat/view.py) on Local and Cloud · API, the real terminal (terminal/view.py) on Cloud · Claude Code. A task on one
slide takes the body's place with its task card (task_card.py) until Back to conversation (the header's pill brings it
back) or until it is closed; an image task, when it ends, takes it with the results panel (pages/image_results.py:
what became of each image, Retry failed) until Back to conversation. The readability check (readability_panel.py: the
header's "Check readability", the palette) takes it with its findings, on every route. The scope and the TaskRunner
(terminal/tasks.py) are the card's, so both bodies and the header share them; "New conversation" clears the route on show and no other.
Focus hides the side panels (side_panels.py listens); it is not remembered.

The keyboard follows the body: a task card that opens takes the focus on its first action, and a card or a results panel
that closes while the keyboard is on it gives it back to the message box of the chat (the terminal takes it
itself when it is shown).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QApplication, QScrollArea, QStackedWidget, QWidget

from ...ai import ai_profile
from ...ai.agent_context import SCOPE_DECK, SCOPE_SLIDE
from ...ai.agent_types import EDIT_AUTO
from ...ai.claude_tasks import PROOFREAD_SELECTION, READABLE, REWRITE, REWRITE_PRESETS, TRANSLATE
from ...selection import SelectionError
from ..kit import kit_qss as q
from ..kit.widgets import Card, SegmentedControl
from ..pages.image_results import BatchResultView
from .assistant_header import AssistantHeader
from .chat.gui_workspace import GuiWorkspace
from .insert_popovers import InstructionPopover
from .chat.view import ChatView
from .selection_tasks import CUSTOM, rewrite_menu
from .readability_panel import ReadabilityCheck, ReadabilityPanel
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
        self.scope = SegmentedControl(SCOPES, current=SCOPE_SLIDE, roving=True)
        self.workspace = GuiWorkspace(app)                  # where the tasks write: its own, apart from both bodies'
        self.tasks = TaskRunner(app, self.workspace, self, edit_auto=lambda: self.chat.session.mode == EDIT_AUTO)
        self.chat = ChatView(app, state, self.scope)
        self.claude_code = ClaudeCodeView(app, state, self.scope, self.tasks)
        self.header = AssistantHeader(app, state, self.scope, self.tasks, self._tasks_blocked)
        self.task_row = TaskRow(app, self.tasks)
        self.task_card = TaskCardView(app, self.tasks)
        self.image_results = BatchResultView(back=True)
        self.readability_panel = ReadabilityPanel()
        self.readability = ReadabilityCheck(app, self.readability_panel, self.workspace)
        self._stack = QStackedWidget()
        self._stack.setObjectName(q.SURFACE)
        self._results_page = self._scrolled(self.image_results)
        self._readability_page = self._scrolled(self.readability_panel)
        for body in (self.chat, self.claude_code, self.task_card, self._results_page, self._readability_page):
            self._stack.addWidget(body)
        for widget, stretch in ((self.header, 0), (self.task_row, 0), (self._stack, 1)):
            self.layout().addWidget(widget, stretch)

        self.header.focus_toggled.connect(self.focus_toggled)
        self.header.new_conversation.connect(self.new_conversation)
        self.header.task_chosen.connect(self.run_task)
        self.header.check_chosen.connect(self.check_readability)
        self.header.task_opened.connect(self._open_task)
        self.task_card.back_clicked.connect(self.tasks.hide_card)
        self.task_card.sign_in_clicked.connect(self._sign_in)
        self.tasks.card_changed.connect(self._show_body)
        self.tasks.result_changed.connect(self._show_body)
        self.readability.changed.connect(self._show_body)
        self.readability.reported.connect(self.header.schedule)
        self.readability.make_readable.connect(self.make_readable)
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
    def _scrolled(body: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setObjectName(q.SURFACE)
        scroll.viewport().setObjectName(q.SURFACE)
        scroll.setWidget(body)
        return scroll

    def _show_body(self, _route: str = "") -> None:
        """The task card while there is one on show, else the readability findings, else the image results, else the
        conversation of the route."""
        card, result = self.tasks.card, self.tasks.result
        before = self._stack.currentWidget()
        focus = QApplication.focusWidget()
        had_focus = focus is not None and before.isAncestorOf(focus)
        if card is not None and not card.hidden:
            self._stack.setCurrentWidget(self.task_card)
        elif self.readability.active:
            self._stack.setCurrentWidget(self._readability_page)
        elif result is not None:
            if self.image_results.result is not result:
                self.image_results.show_result(result)
            self._stack.setCurrentWidget(self._results_page)
        else:
            self._stack.setCurrentWidget(self.claude_code if self.state.ai_route == ai_profile.CLAUDE_CODE else self.chat)
        now = self._stack.currentWidget()
        if now is self.task_card and before is not now:
            self.task_card.focus_first()
        elif now is self.chat and had_focus and before is not now:
            self.chat.composer.setFocus(Qt.FocusReason.OtherFocusReason)

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
        if bubble.task is REWRITE:
            self.rewrite_selection()
        elif bubble.task is PROOFREAD_SELECTION:
            self.proofread_selection()
        else:
            self.tasks.start(bubble.task, bubble.paths, bubble.label)

    def _selection_ready(self) -> bool:
        """Whether the Source view has a selection to work on; if not, the toast says why."""
        try:
            self.app.centre.source.selection()
        except SelectionError as exc:
            self.app.toast.show_message(str(exc))
            return False
        return True

    def rewrite_selection(self, choice: str = "") -> None:
        """Rewrite the selected text of the slide in the Source view as `choice` says: Simplify, Shorten or Custom…
        (which asks for the instruction in a popover); with no choice, a menu of them under the selection."""
        if not self._selection_ready():
            return
        source = self.app.centre.source
        if not choice:
            menu = rewrite_menu(source)
            menu.triggered.connect(self.rewrite_selection)
            source.popup_at_selection(menu)
        elif choice == CUSTOM:
            popover = InstructionPopover()
            popover.chosen.connect(self._rewrite)
            source.popup_at_selection(popover)
        else:
            self._rewrite(REWRITE_PRESETS[choice], choice)

    def _rewrite(self, instruction: str, label: str = "") -> None:
        label = label or (instruction if len(instruction) <= 40 else instruction[:39] + "…")
        self.tasks.start(REWRITE, title=f"Rewrite selection · {label}", instruction=instruction)

    def proofread_selection(self) -> None:
        if self._selection_ready():
            self.tasks.start(PROOFREAD_SELECTION, title="Proofread selection")

    def check_readability(self, scope: str) -> None:
        """Check the readability of the slide in view or of the open deck (the header's button, the palette); the
        findings take the place of the conversation."""
        if scope == SCOPE_DECK:
            self.readability.check_deck()
        else:
            self.readability.check_slide()

    def make_readable(self, path: Path | None = None) -> None:
        """Make readable on the slide `path` (the findings panel's button, which has just measured it) or the slide in
        view (the palette): the task works from the findings of a check of exactly this text, so without them the
        check runs first and its panel offers the button."""
        in_view = path is None
        if in_view and not self.header.can_check(SCOPE_SLIDE):
            self.app.toast.show_message("Open a slide first: Make readable works on a slide that was measured.")
            return
        path = path or self.app.centre.path
        if not self.app.readability_known.fixable(path, self.app.centre.slide_text(path)):
            if in_view:
                self.check_readability(SCOPE_SLIDE)
            else:
                self.app.toast.show_message("The slide changed since it was checked: check it again.")
            return
        if not in_view:
            self.workspace.show_slide(path)
        self.tasks.start(READABLE, title="Make readable", focus=path)

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
        self.readability.close()
        self.workspace.close()
