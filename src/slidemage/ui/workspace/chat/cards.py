"""The things the chat shows in its message list: the user's bubble, the model's text, tool cards,
diff cards (a proposed, applied or rejected edit) and notices. Plain widgets: they report clicks as
signals and the chat (view.py) decides what they mean."""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QMouseEvent, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout

from ....ai.agent_types import ToolCall, ToolResult
from ...kit import kit_qss as q
from ...kit.widgets import Button, IconLabel, Surface, caption, set_property
from .format import diff_rows, summarize_call

BUBBLE_WIDTH = 270       # the user's bubble wraps here
RESULT_CHARS = 1500      # of a tool's result shown when its card is opened
THUMB_WIDTH = 250
DIFF_ROWS = 24           # diff rows shown before "Show all"


def text_label(text: str, name: str, *, markdown: bool = False) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.MarkdownText if markdown else Qt.TextFormat.PlainText)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
    return label


class UserBubble(Surface):
    def __init__(self, text: str) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        bubble = QFrame()
        bubble.setObjectName(q.CHAT_USER)
        bubble.setMaximumWidth(BUBBLE_WIDTH)
        inner = QVBoxLayout(bubble)
        inner.setContentsMargins(12, 9, 12, 9)
        label = text_label(text, q.CHAT_USER)
        label.ensurePolished()
        wrapped = label.fontMetrics().boundingRect(QRect(0, 0, BUBBLE_WIDTH - 24, 100000), Qt.TextFlag.TextWordWrap, text)
        label.setFixedWidth(wrapped.width() + 2)      # as wide as the text, up to the bubble
        inner.addWidget(label)
        row.addWidget(bubble)


class AssistantText(QLabel):
    """A piece of the model's answer, grown as it streams (Markdown)."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName(q.CHAT_TEXT)
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.MarkdownText)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        self.raw = ""

    def append(self, text: str) -> None:
        self.raw += text
        self.setText(self.raw)


class Notice(QLabel):
    """A line the chat says itself: stopped, a failure, the step limit. tone "", "warning" or "error"."""

    def __init__(self, text: str, tone: str = "") -> None:
        super().__init__(text)
        self.setObjectName(q.CHAT_NOTICE)
        self.setProperty("tone", tone)
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)


class Status(QLabel):
    """The "Thinking…" line with moving dots, shown while the agent works."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName(q.PANEL_CAPTION)
        self._base = "Thinking"
        self._dots = 0
        self._timer = QTimer(self)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def run(self, text: str = "Thinking") -> None:
        if self.isHidden() or text != self._base:
            self._base = text
            self.show()
            self._tick(reset=True)
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def _tick(self, reset: bool = False) -> None:
        self._dots = 0 if reset else (self._dots + 1) % 4
        self.setText(self._base + "." * self._dots)


class ToolCard(QFrame):
    """One tool call: its name, a few words on what it is about, whether it worked; a click opens
    the tool's answer. An image it returned (a render) is shown as a thumbnail."""

    def __init__(self, call: ToolCall) -> None:
        super().__init__()
        self.call = call
        self.setObjectName(q.CHAT_TOOL)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(5)
        head = QHBoxLayout()
        head.setSpacing(6)
        self._status = IconLabel("more_horiz", 16)
        head.addWidget(self._status)
        name = QLabel(call.name)
        name.setObjectName(q.CHAT_TOOL_NAME)
        head.addWidget(name)
        summary = QLabel(summarize_call(call))
        summary.setObjectName(q.CHAT_TOOL_SUMMARY)
        summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        head.addWidget(summary, 1)
        self._chevron = IconLabel("expand_more", 16)
        self._chevron.hide()
        head.addWidget(self._chevron)
        self._head = head
        layout.addLayout(head)
        self._thumbs = QVBoxLayout()
        layout.addLayout(self._thumbs)
        self._body = text_label("", q.CHAT_TOOL_BODY)
        self._body.hide()
        layout.addWidget(self._body)
        self.result: ToolResult | None = None

    @property
    def expanded(self) -> bool:
        return not self._body.isHidden()

    def finish(self, result: ToolResult) -> None:
        self.result = result
        self._status.set_icon("error_outline" if result.is_error else "check")
        self._status.set_tone("error" if result.is_error else "ok")
        self._body.setText(result.text if len(result.text) <= RESULT_CHARS else result.text[:RESULT_CHARS] + "…")
        self._chevron.setVisible(bool(result.text.strip()))
        for data in result.images:
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                thumb = QLabel()
                thumb.setPixmap(pixmap.scaledToWidth(THUMB_WIDTH, Qt.TransformationMode.SmoothTransformation))
                thumb.setAlignment(Qt.AlignmentFlag.AlignLeft)
                self._thumbs.addWidget(thumb)
        if result.is_error:
            self.set_expanded(True)

    def set_expanded(self, expanded: bool) -> None:
        self._body.setVisible(expanded and bool(self._body.text().strip()))
        self._chevron.set_icon("expand_less" if expanded else "expand_more")

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() <= self._head.geometry().bottom() + 7:
            self.set_expanded(not self.expanded)
        super().mouseReleaseEvent(event)


class DiffCard(QFrame):
    """An edit of a file as a diff. States: "proposed" (just announced), "asking" (Apply / Reject
    wait for the user), "working" (Apply was clicked), "applied" (with Undo, when it can be undone), "rejected"
    (refused, or could not be applied) and "undone" (greyed)."""

    apply_clicked = Signal()
    reject_clicked = Signal()
    undo_clicked = Signal()

    def __init__(self, title: str, before: str, after: str, note: str = "") -> None:
        super().__init__()
        self.setObjectName(q.CHAT_DIFF)
        self.state = "proposed"
        self.title = title
        self._rows = diff_rows(before, after)
        self._all_rows = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(6)
        head = QHBoxLayout()
        head.setContentsMargins(10, 0, 10, 0)
        head.setSpacing(6)
        head.addWidget(IconLabel("description", 16))
        name = QLabel(title)
        name.setObjectName(q.CHAT_TOOL_NAME)
        name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        name.setToolTip(title)
        head.addWidget(name, 1)
        layout.addLayout(head)
        if note:
            note_label = caption(note)
            note_label.setContentsMargins(10, 0, 10, 0)
            layout.addWidget(note_label)
        self._lines = QVBoxLayout()
        self._lines.setSpacing(0)
        layout.addLayout(self._lines)
        self._more = Button("", "ghost", compact=True)
        self._more.clicked.connect(self._show_all)
        layout.addWidget(self._more, 0, Qt.AlignmentFlag.AlignLeft)
        foot = QHBoxLayout()
        foot.setContentsMargins(10, 0, 10, 0)
        foot.setSpacing(6)
        self._caption = caption("")
        foot.addWidget(self._caption, 1)
        self.apply_button = Button("Apply", "primary", compact=True)
        self.reject_button = Button("Reject", "ghost", compact=True)
        self.undo_button = Button("Undo", "secondary", compact=True)
        self.apply_button.clicked.connect(self.apply_clicked)
        self.reject_button.clicked.connect(self.reject_clicked)
        self.undo_button.clicked.connect(self.undo_clicked)
        for button in (self.reject_button, self.apply_button, self.undo_button):
            foot.addWidget(button)
        self._foot = foot
        layout.addLayout(foot)
        self._fill()
        self._show_state("", False)

    # -- the diff ------------------------------------------------------------------------

    def _fill(self) -> None:
        while (item := self._lines.takeAt(0)) is not None:
            widget = item.widget()
            widget.setParent(None)
            widget.deleteLater()
        shown = self._rows if self._all_rows else self._rows[:DIFF_ROWS]
        for kind, line in shown:
            label = QLabel({"add": "+ ", "del": "− ", "ctx": "  ", "gap": "⋯"}[kind] + line)
            label.setObjectName(q.CHAT_DIFF_LINE)
            label.setProperty("kind", kind)
            label.setWordWrap(True)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
            self._lines.addWidget(label)
        hidden = len(self._rows) - len(shown)
        self._more.setVisible(hidden > 0)
        self._more.setText(f"Show {hidden} more lines")

    def _show_all(self) -> None:
        self._all_rows = True
        self._fill()

    # -- the states ----------------------------------------------------------------------

    def _show_state(self, text: str, error: bool, *, asking: bool = False, undo: bool = False) -> None:
        self._caption.setText(text)
        set_property(self._caption, "tone", "error" if error else "")
        self._caption.setVisible(bool(text))
        self.apply_button.setVisible(asking)
        self.reject_button.setVisible(asking)
        self.undo_button.setVisible(undo)
        set_property(self, "state", self.state)

    def ask(self) -> None:
        self.state = "asking"
        self._show_state("Waiting for you", False, asking=True)

    def working(self) -> None:
        """Apply was clicked: the agent is making the change."""
        self.state = "working"
        self._show_state("Applying…", False)

    def applied(self, via_buffer: bool, undoable: bool, new_file: bool) -> None:
        self.state = "applied"
        text = ("Created" if new_file else "Applied in the editor, not saved yet" if via_buffer
                else "Saved to the file (a backup is kept)")
        self._show_state(text, False, undo=undoable)

    def rejected(self) -> None:
        self.state = "rejected"
        self._show_state("Not applied", False)

    def undone(self) -> None:
        self.state = "undone"
        self._show_state("Undone", False)

    def undo_failed(self, why: str) -> None:
        self._show_state(why, True, undo=True)


def suggestion_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName(q.CHAT_SUGGESTION)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button
