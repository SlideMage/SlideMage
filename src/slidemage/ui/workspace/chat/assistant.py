"""The assistant area, below the side panels: a switch between the views that answer the user's requests,
Chat (view.py) and Claude Code. The choice is remembered (app_settings).

Claude Code is a placeholder until the terminal of step 10c exists. The host is ready for it: 10c builds
its terminal widget and passes it to `set_view_widget("claude_code", widget)`; nothing else of the area
changes.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QStackedWidget, QVBoxLayout, QWidget

from .... import app_settings
from ...kit import kit_qss as q
from ...kit.widgets import Card, SegmentedControl, Surface, caption
from ..state import WorkspaceState
from .view import ChatView

SETTING = "assistant_view"
CHAT, CLAUDE_CODE = "chat", "claude_code"
VIEWS = ((CHAT, "Chat"), (CLAUDE_CODE, "Claude Code"))


class _ClaudeCodePlaceholder(Surface):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Claude Code in SlideMage")
        title.setObjectName(q.CHAT_TEXT)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        note = caption("Coming soon: your installed Claude Code, running here in the project folder.")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(note)


class AssistantArea(Card):
    def __init__(self, app, state: WorkspaceState) -> None:
        super().__init__()
        remembered = app_settings.get(SETTING)
        self.switch = SegmentedControl(VIEWS, current=remembered if remembered in dict(VIEWS) else CHAT)
        self.switch.changed.connect(self.show_view)
        self.layout().addWidget(self.switch, 0, Qt.AlignmentFlag.AlignLeft)
        self._stack = QStackedWidget()
        self._stack.setObjectName(q.SURFACE)
        self.layout().addWidget(self._stack, 1)
        self.chat = ChatView(app, state)
        self._pages: dict[str, QWidget] = {}
        self.set_view_widget(CHAT, self.chat)
        self.set_view_widget(CLAUDE_CODE, _ClaudeCodePlaceholder())
        self._stack.setCurrentWidget(self._pages[self.switch.current()])

    @property
    def current(self) -> str:
        return self.switch.current()

    def set_view_widget(self, key: str, widget: QWidget) -> None:
        """Make `widget` the page of the view `key` (replacing the one there)."""
        old = self._pages.get(key)
        if old is not None:
            self._stack.removeWidget(old)
            old.deleteLater()
        self._pages[key] = widget
        self._stack.addWidget(widget)
        if self.switch.current() == key:
            self._stack.setCurrentWidget(widget)

    def show_view(self, key: str) -> None:
        if key in self._pages:
            self.switch.set_current(key)
            self._stack.setCurrentWidget(self._pages[key])
            app_settings.set(SETTING, key)

    def shutdown(self) -> None:
        """The window closes: end a running chat request."""
        self.chat.shutdown()
