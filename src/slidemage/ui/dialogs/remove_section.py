# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The sheet of the slide list's "Remove section": the heading alone, the section with its slides, or every
section of the deck. Slides are only taken out of the deck; their files stay in the project."""
from __future__ import annotations

from PySide6.QtWidgets import QButtonGroup, QRadioButton, QVBoxLayout

from ..kit.widgets import ModalSheet, Surface, caption

HEADING, WITH_SLIDES, ALL_SECTIONS = "heading", "with_slides", "all_sections"


def _slides(n: int) -> str:
    return f"{n} slide" if n == 1 else f"{n} slides"


class RemoveSectionSheet(ModalSheet):
    def __init__(self, parent, title: str, slides: int, sections: int) -> None:
        """After exec(), `choice` is HEADING, WITH_SLIDES or ALL_SECTIONS."""
        super().__init__("Remove section", parent, width=480)
        body = Surface()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        buttons = QButtonGroup(self)
        self._radios: dict[str, QRadioButton] = {}
        options = [
            (HEADING, f"Only the section “{title}” – its {_slides(slides)} stay in the deck"),
            (WITH_SLIDES, f"The section “{title}” and its {_slides(slides)}"),
            (ALL_SECTIONS, f"All {sections} sections of this deck – every slide stays in the deck"),
        ]
        for key, label in options:
            if key == ALL_SECTIONS and sections < 2:
                continue
            radio = QRadioButton(label)
            radio.setChecked(key == HEADING)
            buttons.addButton(radio)
            self._radios[key] = radio
            layout.addWidget(radio)
        layout.addWidget(caption("Slides are only taken out of the deck: their files stay in the project. "
                                 "Undo takes the removal back."))
        self.add_tab("", body)
        self.add_button("Cancel", role="reject")
        ok = self.add_button("Remove", kind="primary")
        ok.setDefault(True)
        ok.clicked.connect(self._on_ok)
        self._radios[HEADING].setFocus()
        self.choice = HEADING

    def _on_ok(self) -> None:
        self.choice = next(key for key, radio in self._radios.items() if radio.isChecked())
        self.accept()
