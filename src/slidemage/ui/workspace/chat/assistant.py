"""The assistant area, below the side panels: a switch between the views that answer the user's requests,
Chat (view.py) and Claude Code. The choice is remembered (app_settings).

Claude Code is a terminal running the user's own `claude` (terminal/view.py), started when it is first
shown and stopped with the area.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QStackedWidget, QWidget

from .... import app_settings
from ...kit import kit_qss as q
from ...kit.widgets import Card, SegmentedControl
from ..state import WorkspaceState
from ..terminal.view import ClaudeCodeView
from .view import ChatView

SETTING = "assistant_view"
CHAT, CLAUDE_CODE = "chat", "claude_code"
VIEWS = ((CHAT, "Chat"), (CLAUDE_CODE, "Claude Code"))
MIN_HEIGHT = 416   # mode/scope rows, suggestions menu, six-line input, send and model rows


class AssistantArea(Card):
    def __init__(self, app, state: WorkspaceState) -> None:
        super().__init__()
        self.setMinimumHeight(MIN_HEIGHT)
        self.state = state
        remembered = app_settings.get(state.project, SETTING)
        self.switch = SegmentedControl(VIEWS, current=remembered if remembered in dict(VIEWS) else CHAT)
        self.switch.changed.connect(self.show_view)
        self.layout().addWidget(self.switch, 0, Qt.AlignmentFlag.AlignLeft)
        self._stack = QStackedWidget()
        self._stack.setObjectName(q.SURFACE)
        self.layout().addWidget(self._stack, 1)
        self.chat = ChatView(app, state)
        self.claude_code = ClaudeCodeView(app, state)
        self._pages: dict[str, QWidget] = {CHAT: self.chat, CLAUDE_CODE: self.claude_code}
        for page in self._pages.values():
            self._stack.addWidget(page)
        self._stack.setCurrentWidget(self._pages[self.switch.current()])

    @property
    def current(self) -> str:
        return self.switch.current()

    def show_view(self, key: str) -> None:
        if key in self._pages:
            self.switch.set_current(key)
            self._stack.setCurrentWidget(self._pages[key])
            app_settings.set(self.state.project, SETTING, key)

    def refresh_colors(self) -> None:
        self.claude_code.refresh_colors()

    def shutdown(self) -> None:
        """The window closes: end a running chat request and the Claude Code process."""
        self.chat.shutdown()
        self.claude_code.shutdown()
