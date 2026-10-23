# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Update version → New slide… (v8.58.0): the name of the new slide and the decks that load it instead of the old
one (slide_branch.py). The deck the slide is edited in is ticked; the other decks that follow the slide's current
content are offered, unticked.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Optional

from PySide6.QtWidgets import QCheckBox, QLineEdit, QVBoxLayout

from ... import slide_add, slide_versioning
from ..kit.widgets import Field, ModalSheet, Surface, caption, set_property


class NewSlideVersionSheet(ModalSheet):
    """After exec(): `slug` and `decks` (the names ticked)."""

    def __init__(self, parent, id_slug: str, version: slide_versioning.Version, slug: str,
                 decks: Sequence[tuple[str, int]], edited_deck: Optional[str]) -> None:
        """`decks`: (deck name, how many of its calls follow the slide) for every deck that could switch."""
        super().__init__("Save as a new slide", parent, width=520)
        body = Surface()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        old = f"v{slide_versioning.format_dot(version)}"
        intro = caption(f"The changes since {old} become a new slide with an id of its own. {id_slug} goes back to "
                        f"{old}, unchanged, so the decks that keep it look as before.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.name_edit = QLineEdit(slug)
        self.name_edit.selectAll()
        self.name_edit.textChanged.connect(lambda _text: self._show_problem(""))
        layout.addWidget(Field("Name of the new slide (letters and digits, joined by hyphens)", self.name_edit))
        self._boxes: dict[str, QCheckBox] = {}
        if decks:
            box = Surface()
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(0, 0, 0, 0)
            box_layout.setSpacing(6)
            for name, count in decks:
                label = name + (" (this deck)" if name == edited_deck else "") + (f", {count} places" if count > 1 else "")
                check = QCheckBox(label)
                check.setChecked(name == edited_deck)
                box_layout.addWidget(check)
                self._boxes[name] = check
            layout.addWidget(Field("Use the new slide in", box))
            note = caption(f"A deck pinned to a version of {id_slug} keeps it. Unticked decks keep {id_slug} at {old}.")
            note.setWordWrap(True)
            layout.addWidget(note)
        self.problem = caption()
        self.problem.hide()
        layout.addWidget(self.problem)
        self.add_tab("", body)
        self.add_button("Cancel", role="reject")
        ok = self.add_button("Save as new slide", kind="primary")
        ok.setDefault(True)
        ok.clicked.connect(self._on_ok)
        self.name_edit.setFocus()
        self.slug = ""
        self.decks: list[str] = []

    def _show_problem(self, text: str) -> None:
        self.problem.setText(text)
        set_property(self.problem, "tone", "error")
        self.problem.setVisible(bool(text))

    def _on_ok(self) -> None:
        slug = self.name_edit.text().strip()
        if not slide_add.SLUG_RE.match(slug):
            self._show_problem("Use letters and digits, joined by single hyphens, e.g. Demo-revised.")
            return
        self.slug = slug
        self.decks = [name for name, box in self._boxes.items() if box.isChecked()]
        self.accept()
