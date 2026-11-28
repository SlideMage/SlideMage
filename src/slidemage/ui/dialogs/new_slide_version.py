# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Update version → New slide… (v8.58.0): the name of the new slide and the decks that load it instead of the old
one (slide_branch.py). The deck the slide is edited in is ticked; the other decks that follow the slide's current
content are offered, unticked.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QLineEdit, QVBoxLayout

from ... import slide_add, slide_versioning
from ..kit.tokens import SPACE
from ..kit.widgets import Field, ModalSheet, Surface, caption, show_problem


class NewSlideVersionSheet(ModalSheet):
    """After acceptance, `sources` holds the selected physical file paths."""

    def __init__(self, parent, id_slug: str, version: slide_versioning.Version, slug: str,
                 sources: dict[Path, tuple[int, list[Path]]], edited_deck: Optional[Path], root: Path,
                 preview: Callable[[str, list[Path]], str]) -> None:
        super().__init__("Save as a new slide", parent, width=520)
        body = Surface()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE.xl)
        old = f"v{slide_versioning.format_dot(version)}"
        intro = caption(f"The changes since {old} become a new slide with an id of its own. {id_slug} goes back to "
                        f"{old}, unchanged, so the decks that keep it look as before.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.name_edit = QLineEdit(slug)
        self.name_edit.selectAll()
        self.name_edit.textChanged.connect(lambda _text: show_problem(self.problem, ""))
        layout.addWidget(Field("Name of the new slide (letters and digits, joined by hyphens)", self.name_edit))
        self._boxes: dict[Path, QCheckBox] = {}
        if sources:
            box = Surface()
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(0, 0, 0, 0)
            box_layout.setSpacing(SPACE.sm)
            for path in sorted(sources, key=lambda path: (path != edited_deck, path)):
                count, decks = sources[path]
                label = path.relative_to(root).as_posix()
                if path == edited_deck:
                    label += " (this deck)"
                if count > 1:
                    label += f", {count} places"
                check = QCheckBox(label)
                check.setChecked(path == edited_deck)
                box_layout.addWidget(check)
                self._boxes[path] = check
                if decks != [path]:
                    used_by = caption("Used by " + ", ".join(deck.relative_to(root).as_posix() for deck in decks))
                    used_by.setWordWrap(True)
                    box_layout.addWidget(used_by)
            layout.addWidget(Field("Use the new slide in", box))
            note = caption(f"Pinned calls keep their versions. Unticked files keep {id_slug}.")
            note.setWordWrap(True)
            layout.addWidget(note)
        summary = caption()
        summary.setTextFormat(Qt.TextFormat.PlainText)
        summary.setWordWrap(True)
        layout.addWidget(summary)

        def refresh():
            name = self.name_edit.text().strip()
            text = preview(name if slide_add.SLUG_RE.fullmatch(name) else slug, self._selected_sources())
            summary.setText(text)
            summary.setVisible(bool(text))

        self.name_edit.textChanged.connect(refresh)
        for check in self._boxes.values():
            check.toggled.connect(refresh)
        refresh()
        self.problem = caption()
        self.problem.hide()
        layout.addWidget(self.problem)
        self.add_tab("", body, scroll=True)
        self.add_button("Cancel", role="reject")
        ok = self.add_button("Save as new slide", kind="primary")
        ok.setDefault(True)
        ok.clicked.connect(self._on_ok)
        self.name_edit.setFocus()
        self.slug = ""
        self.sources: list[Path] = []

    def _selected_sources(self) -> list[Path]:
        return [path for path, box in self._boxes.items() if box.isChecked()]

    def _on_ok(self) -> None:
        slug = self.name_edit.text().strip()
        if not slide_add.SLUG_RE.match(slug):
            show_problem(self.problem, "Use letters and digits, joined by single hyphens, e.g. Demo-revised.")
            return
        self.slug = slug
        self.sources = self._selected_sources()
        self.accept()
