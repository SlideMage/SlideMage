# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compile -> "Several decks…": the old deck table's checkboxes as one dialog.

One row per active deck (grouped as in the deck switcher) with a checkbox for
each PDF the deck can make and for its transcripts, so that e.g. every
deck's PDFs can be rebuilt in one run at the end of term. The window queues
the choice on the normal compile slot, which orders it version by version
(compiler.order_jobs). Nothing is remembered between uses, as before.
"""
from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtWidgets import QCheckBox, QGridLayout, QLabel, QScrollArea, QWidget

from ...deck_groups import DEFAULT_GROUPS, DeckGroup
from ...deck_scan import Deck
from ...transcript import STUDENT_VERSIONS
from ..kit.widgets import ModalSheet
from .menus import VIEW_LABELS, deck_sections
from .state import VIEWS

COLUMNS = [(view, VIEW_LABELS[view]) for view in VIEWS] + [
    ("chapters", "Per chapter"), ("presenter", "Presenter")] + [
    (f"transcript:{v}", f"Transcript {VIEW_LABELS[v].lower()}") for v in STUDENT_VERSIONS]


def offered(deck: Deck, kind: str) -> bool:
    """Whether the old table offered this checkbox for the deck."""
    if kind in VIEWS[1:] or kind.startswith("transcript:"):
        return deck.supports_version
    return deck.has_chapters if kind == "chapters" else True


class MultiCompileSheet(ModalSheet):
    def __init__(self, parent: QWidget, decks: list[Deck], groups: Sequence[DeckGroup] = DEFAULT_GROUPS) -> None:
        super().__init__("Compile several decks", parent, width=900)
        self.boxes: dict[tuple[str, str], QCheckBox] = {}
        self._decks = {deck.name: deck for deck in decks}
        body = QWidget()
        grid = QGridLayout(body)
        for col, (_kind, label) in enumerate(COLUMNS, start=1):
            grid.addWidget(QLabel(label), 0, col)
        row = 1
        for heading, group in deck_sections(decks, groups):
            if group and heading:
                grid.addWidget(QLabel(f"<b>{heading}</b>"), row, 0)
                row += 1
            for deck in group:
                grid.addWidget(QLabel(deck.name), row, 0)
                for col, (kind, _label) in enumerate(COLUMNS, start=1):
                    if offered(deck, kind):
                        box = QCheckBox()
                        self.boxes[(deck.name, kind)] = box
                        grid.addWidget(box, row, col)
                row += 1
        grid.setColumnStretch(0, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        scroll.setMinimumHeight(320)
        self.add_tab("", scroll)
        self.add_button("Select all").clicked.connect(lambda: self._set_all(True))
        self.add_button("Clear").clicked.connect(lambda: self._set_all(False))
        self.add_button("Cancel", role="reject")
        self.add_button("Compile", kind="primary", role="accept")

    def _set_all(self, checked: bool) -> None:
        for box in self.boxes.values():
            box.setChecked(checked)

    def chosen(self) -> list[tuple[Deck, str]]:
        """(deck, kind) of every ticked box, decks in table order."""
        return [(self._decks[name], kind) for (name, kind), box in self.boxes.items()
                if box.isChecked()]
