"""The "No decks" state (UI_REDESIGN_PLAN.md, step 9): what the window shows, in place of the
slide list, centre and side panels, while the project has no deck.

A deck is the list of slides for one course or talk. The page offers what SlideMage can do about
an empty project: add the SlideMage manual (bundled_copies: a finished deck to look at and copy
slides from, offered only while this copy carries it and the project has not got it), or open
another project.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from ...deck_scan import PROJECT_ROOT
from ..kit import kit_qss as q
from ..kit.widgets import Card, RowButton, caption


class NoDecksPage(QWidget):
    def __init__(self, app) -> None:
        """`app` is the window: it adds the manual and runs the `open_project` command."""
        super().__init__()
        self.app = app
        card = Card()
        card.setFixedWidth(520)
        layout = card.layout()
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)
        title = QLabel("This project has no decks yet")
        title.setObjectName(q.SHEET_TITLE)
        note = caption("A deck is the list of slides for one course or talk. Slides live once in "
                       "slides/ and any deck can use them.")
        layout.addWidget(title)
        layout.addWidget(note)
        self.manual = RowButton("menu_book", "Add the SlideMage manual",
                                "A finished deck to look at and copy slides from")
        self.manual.clicked.connect(lambda: self.app._on_add_manual())
        layout.addWidget(self.manual)
        other = RowButton("folder_open", "Open another project…", f"Current: {PROJECT_ROOT}")
        other.clicked.connect(lambda: self.app.commands.run("open_project", self.app))
        layout.addWidget(other)

        outer = QHBoxLayout(self)
        outer.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)

    def refresh(self) -> None:
        """Whether the manual can be added is looked up each time the page is shown: it compares files."""
        can = self.app.can_add_manual()
        self.manual.setEnabled(can)
        self.manual.sub.setText("A finished deck to look at and copy slides from" if can
                                else "This copy of SlideMage has no manual to add, or the project has it already")
