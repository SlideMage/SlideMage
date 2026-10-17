"""The Log drawer (prototype v3): a dark panel over the bottom of the centre
column, closed until the job panel's Log button, the toast's Log action, a
failed compile or the ⋮ menu opens it. Every log writer (the window's `log()`,
`signals.log`) ends up in `append()`; Copy log and Clear log are the old log
pane's two buttons.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from ..kit import kit_qss as q

DRAWER_HEIGHT = 240
MAX_WIDTH = 900         # a log line is read at this width; wider only pushes Copy/Clear/Close away from the title
MAX_LINES = 100_000


class LogDrawer(QFrame):
    error_clicked = Signal()   # the red "Show 1ab" button

    def __init__(self, parent: QWidget, anchor: QWidget) -> None:
        """`parent` is the window's central widget, `anchor` the column the drawer covers the bottom of."""
        super().__init__(parent)
        self.setObjectName(q.LOG_DRAWER)
        self._anchor = anchor
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        head = QFrame()
        head.setObjectName(q.LOG_HEAD)
        row = QHBoxLayout(head)
        row.setContentsMargins(14, 6, 8, 6)
        row.setSpacing(8)
        title = QLabel("Log")
        title.setObjectName(q.LOG_TITLE)
        row.addWidget(title)
        self._title = QLabel("")
        row.addWidget(self._title)
        row.addStretch(1)
        self._error = QPushButton("")
        self._error.setObjectName(q.LOG_ERROR)
        self._error.setCursor(Qt.CursorShape.PointingHandCursor)
        self._error.clicked.connect(self.error_clicked)
        self._error.hide()
        row.addWidget(self._error)
        self._action(row, "Copy log", "Copy the entire log to the clipboard.", self._copy)
        self._action(row, "Clear log", "Remove all lines from the log.", self.clear)
        self._action(row, "Close", "", self.hide)
        layout.addWidget(head)
        self.text = QPlainTextEdit()
        self.text.setObjectName(q.LOG_TEXT)
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(MAX_LINES)
        layout.addWidget(self.text, 1)
        for watched in (parent, anchor):
            watched.installEventFilter(self)
        self.hide()

    @staticmethod
    def _action(row: QHBoxLayout, text: str, tip: str, handler) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(q.LOG_ACTION)
        button.setToolTip(tip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(handler)
        row.addWidget(button)
        return button

    # -- content -----------------------------------------------------------------

    def append(self, line: str) -> None:
        self.text.appendPlainText(line)

    def clear(self) -> None:
        self.text.clear()

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.text.toPlainText())

    def set_status(self, title: str, error_button: str = "") -> None:
        """The grey note after "Log" ("course · failed") and the label of the red button, if any."""
        self._title.setText(title)
        self._error.setText(error_button)
        self._error.setVisible(bool(error_button))

    # -- showing -----------------------------------------------------------------

    def open(self) -> None:
        self._place()
        self.show()
        self.raise_()
        self.text.verticalScrollBar().setValue(self.text.verticalScrollBar().maximum())

    def toggle(self) -> None:
        if self.isHidden():
            self.open()
        else:
            self.hide()

    def _place(self) -> None:
        parent = self.parentWidget()
        top_left = self._anchor.mapTo(parent, QPoint(0, 0))
        height = min(DRAWER_HEIGHT, self._anchor.height())
        self.setGeometry(top_left.x(), top_left.y() + self._anchor.height() - height, min(MAX_WIDTH, self._anchor.width()), height)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if self.isVisible() and event.type() in (QEvent.Type.Resize, QEvent.Type.Move):
            self._place()
        return super().eventFilter(obj, event)
