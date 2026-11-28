# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The enlarged search clear button fits inside its field and clears it."""
from __future__ import annotations

from PySide6.QtWidgets import QLineEdit, QToolButton

from slidemage.ui.kit.widgets import enable_clear_button


def test_the_clear_button_is_larger_than_qts_default_and_stays_inside_the_box(qapp):
    plain, edit = QLineEdit(), QLineEdit()
    plain.setClearButtonEnabled(True)
    enable_clear_button(edit)
    for field in (plain, edit):
        field.setText("abc")
        field.resize(260, 36)
        field.show()
    qapp.processEvents()
    default, = plain.findChildren(QToolButton)
    button, = edit.findChildren(QToolButton)
    assert button.width() > default.width() and button.height() > default.height()
    assert edit.rect().contains(button.geometry())
    button.click()
    assert edit.text() == ""
