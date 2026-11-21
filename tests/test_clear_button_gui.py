# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The "x" that empties a search box is larger than Qt's default (kit/widgets.enable_clear_button)."""
from __future__ import annotations

from PySide6.QtWidgets import QLineEdit, QToolButton

from slidemage.ui.kit.widgets import enable_clear_button


def shown(qapp, edit: QLineEdit) -> QToolButton:
    edit.setText("abc")
    edit.resize(260, 36)
    edit.show()
    qapp.processEvents()
    [button] = edit.findChildren(QToolButton)
    return button


def test_the_clear_button_is_larger_than_qts_default_and_stays_inside_the_box(qapp):
    plain = QLineEdit()
    plain.setClearButtonEnabled(True)
    default = shown(qapp, plain)
    edit = QLineEdit()
    enable_clear_button(edit)
    button = shown(qapp, edit)
    assert button.width() > default.width() and button.height() > default.height()
    assert button.geometry().right() < edit.width()                 # not hanging over the right edge
    assert button.geometry().top() >= 0 and button.geometry().bottom() < edit.height()
    edit.setText("xyz")
    button.click()                                                  # it still empties the box
    assert edit.text() == ""
