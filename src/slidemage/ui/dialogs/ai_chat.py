# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-request cloud confirmation for the host-owned ai.chat service."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from ...plugin_api import AiChatRequest, Route
from ..kit.widgets import ModalSheet


class CloudRequestSheet(ModalSheet):
    def __init__(self, route: Route, request: AiChatRequest, parent=None) -> None:
        super().__init__("Send text to cloud AI?", parent, width=680)
        body = QWidget()
        layout = QVBoxLayout(body)
        target = QLabel(f"Send to {route.name} · {route.model} (up to {request.max_tokens} output tokens).")
        target.setTextFormat(Qt.TextFormat.PlainText)
        target.setWordWrap(True)
        layout.addWidget(target)
        for label, text in (("Instructions", request.instructions), ("Text", request.text)):
            layout.addWidget(QLabel(label))
            view = QPlainTextEdit()
            view.setPlainText(text)
            view.setReadOnly(True)
            view.setAccessibleName(label)
            view.setMinimumHeight(140)
            layout.addWidget(view)
        self.add_tab("Request", body)
        cancel = self.add_button("Cancel", role="reject")
        self.add_button("Send", kind="primary", role="accept")
        cancel.setDefault(True)
        cancel.setFocus()
