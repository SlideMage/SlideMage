"""Edit a deck's course page URL and optionally open it."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import deck_editor


class CourseLinkDialog(QDialog):
    def __init__(self, parent: QWidget, deck_name: str, course_url: str | None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Course link — {deck_name}")
        self.url = course_url or ""
        self.action: str | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Course page URL:"))
        self.url_edit = QLineEdit(self.url)
        self.url_edit.setPlaceholderText("https://online.uni-graz.at/...")
        self.url_edit.setMinimumWidth(520)
        layout.addWidget(self.url_edit)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel_button = QPushButton("Cancel")
        save_button = QPushButton("Save")
        save_button.setDefault(True)
        self.open_button = QPushButton("Open")
        self.open_button.setEnabled(bool(self.url.strip()))
        self.url_edit.textChanged.connect(
            lambda text: self.open_button.setEnabled(bool(text.strip()))
        )
        cancel_button.clicked.connect(self.reject)
        save_button.clicked.connect(lambda: self._finish("save"))
        self.open_button.clicked.connect(lambda: self._finish("open"))
        buttons.addWidget(cancel_button)
        buttons.addWidget(save_button)
        buttons.addWidget(self.open_button)
        layout.addLayout(buttons)

    def _finish(self, action: str) -> None:
        raw = self.url_edit.text()
        try:
            url = deck_editor.normalize_course_url(raw) if raw.strip() else ""
        except ValueError as exc:
            QMessageBox.warning(self, "Course link", str(exc))
            return
        if action == "open" and not url:
            return
        self.url = url
        self.action = action
        self.accept()
