# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The sheet before a deck compile that takes slides with a "+" from their last version (issue #97): which
slides of which deck, and whether to compile the last versions, the edits, or update the versions first. Its
checkbox makes the compile choice the setting for deck compiles (Settings → General)."""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QCheckBox, QLabel

from ..kit.tokens import SPACE
from ..kit.widgets import Card, ModalSheet, Page, caption, text_label

LAST, EDITS, UPDATE = "last", "edits", "update"


def _slides(n: int) -> str:
    return f"{n} slide" if n == 1 else f"{n} slides"


class SavedVersionsSheet(ModalSheet):
    def __init__(self, parent, found: dict[str, list[str]]) -> None:
        """`found`: {deck name: the bare ids it takes from their last version}. After exec(), `choice` is LAST,
        EDITS, UPDATE or None (cancelled), and `remember` whether the checkbox was ticked."""
        super().__init__("Slides compiled from their last version", parent, width=680)
        total = len({slide for slides in found.values() for slide in slides})
        page = Page()
        intro = text_label(f"{_slides(total)} have edits that are not a version yet (the “+” after the version "
                           "number). The deck PDF shows their last version, without these edits. The slides’ "
                           "Previews show the edits.")
        intro.setWordWrap(True)
        page.body.addWidget(intro)
        card = Card()
        for index, (name, slides) in enumerate(found.items()):
            if index:
                card.layout().addSpacing(SPACE.md)
            card.layout().addWidget(text_label(f"{name} · {_slides(len(slides))}", "heading"))
            shown = ", ".join(slides[:8]) + (", …" if len(slides) > 8 else "")
            ids: QLabel = text_label(shown, "mono")
            ids.setWordWrap(True)
            card.layout().addWidget(ids)
        page.body.addWidget(card)
        self.remember_check = QCheckBox("Make this the setting for deck compiles")
        page.body.addWidget(self.remember_check)
        page.body.addWidget(caption(
            "With edits: deck PDFs always show the “+” edits. With last versions: they show only versioned "
            "slides, without asking. You can change it in Settings → General → Changed slides in decks."))
        self.add_tab("", page)

        self.choice: Optional[str] = None
        self.add_button("Cancel", role="reject")
        for key, label, kind in ((UPDATE, "Update versions first", "secondary"),
                                 (EDITS, "Compile with edits (+)", "secondary"),
                                 (LAST, "Compile last versions", "primary")):
            button = self.add_button(label, kind=kind)
            button.clicked.connect(lambda _checked=False, key=key: self._choose(key))
        button.setDefault(True)

    @property
    def remember(self) -> bool:
        return self.remember_check.isChecked()

    def _choose(self, key: str) -> None:
        self.choice = key
        self.accept()
