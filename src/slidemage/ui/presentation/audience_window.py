"""The two top-level windows of a presentation. Both hand keys and the wheel to the controller."""
from __future__ import annotations

from typing import Optional, Protocol

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ...presentation.layout import Profile
from .slide_canvas import SlideCanvas


class Controls(Protocol):
    def key_press(self, event) -> bool: ...
    def wheel(self, event) -> None: ...
    def end(self) -> None: ...


class ControlledWindow(QWidget):
    """A window that forwards input to the controller and can show a short message."""
    def __init__(self, controls: Controls) -> None:
        super().__init__()
        self.controls = controls
        self._toast = QLabel(self)
        self._toast.setStyleSheet("background: rgba(0,0,0,170); color: white; padding: 8px 14px; font-size: 15px;")
        self._toast.hide()
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._toast.hide)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def show_toast(self, text: str, milliseconds: int = 4000) -> None:
        self._toast.setText(text)
        self._toast.adjustSize()
        self._toast.move(max(0, (self.width() - self._toast.width()) // 2), max(0, self.height() - self._toast.height() - 30))
        self._toast.show()
        self._toast.raise_()
        self._toast_timer.start(milliseconds)

    def keyPressEvent(self, event) -> None:
        if not self.controls.key_press(event):
            super().keyPressEvent(event)

    def wheelEvent(self, event) -> None:
        self.controls.wheel(event)
        event.accept()

    def closeEvent(self, event) -> None:
        self.controls.end()
        super().closeEvent(event)


class AudienceWindow(ControlledWindow):
    """The projector: one canvas, nothing else. `interactive` (one screen only) lets the mouse lase and draw."""
    def __init__(self, controls: Controls, canvas: SlideCanvas, interactive: bool) -> None:
        super().__init__(controls)
        self.setWindowTitle("SlideMage - Presentation")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setStyleSheet("background: #000000;")
        self.canvas = canvas
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(canvas)
        if not interactive:
            self.setCursor(Qt.CursorShape.BlankCursor)


class PresenterWindow(ControlledWindow):
    """The presenter's screen, filled by the active layout profile."""
    def __init__(self, controls: Controls, build: "BuildLayout") -> None:
        super().__init__(controls)
        self.setWindowTitle("SlideMage - Presenter view")
        self._build = build
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._body: Optional[QWidget] = None
        self.setStyleSheet("background: #1b1b1b; color: #eeeeee;")

    def apply_profile(self, profile: Profile) -> None:
        if self._body is not None:
            self._layout.removeWidget(self._body)
            self._body.setParent(None)
            self._body.deleteLater()
        self._body = self._build(profile)
        self._layout.addWidget(self._body)


class BuildLayout(Protocol):
    def __call__(self, profile: Profile) -> QWidget: ...
