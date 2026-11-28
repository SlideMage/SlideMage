# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The version buttons at the top right of the Preview (Split and Preview views).

Revert (back to the saved version), Overwrite (the changes go into that version), Patch / Minor / Major (the changes
become the next version at that level) and "Save as new" (the changes become a slide of their own). Each button shows the version it makes,
the digit that changes in the accent color with an arrow after it: 1.0.1↑ · 1.1↑.0 · 2↑.0.0. The Source view's
toolbar computes the state (`VersionState`) and the pane shows it; the buttons send the same requests the Source
view's button and caret menu do.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from ... import slide_versioning
from ..kit.tokens import SPACE, Tokens
from ..kit.widgets import Button, Surface

ARROW = "↑"      # ↑ the digit that is bumped
REVERT = "↶"     # ↶
OVERWRITE = "↻"  # ↻


@dataclass(frozen=True)
class VersionState:
    """What the buttons show: the slide, the version its changes were made to (`base`, "1.0.0"), whether there is
    something to make a version of (`changes`), and the tooltip that says why not."""
    id_slug: str
    base: str
    changes: bool
    why_not: str = ""


def bumped(base: str, level: str) -> tuple[str, int]:
    """(the version `level` makes of `base`, the index 0..2 of its digit that changes)."""
    major, minor, patch = (int(part) for part in base.split("."))
    new = slide_versioning.bump((major, minor, patch), level)
    return slide_versioning.format_dot(new), {"major": 0, "minor": 1, "patch": 2}[level]


def rich(parts: list[str], changed: Optional[int], color: str, text_color: str, *, lead: str = "", lead_color: str = "") -> str:
    """The button's text: `parts` joined by dots, the digit `changed` in `color` with the arrow after it."""
    pieces = []
    for index, part in enumerate(parts):
        text = escape(part)
        if index == changed:
            text = f'<span style="color:{color}">{text}{ARROW}</span>'
        pieces.append(text)
    head = f'<span style="color:{lead_color or color}">{escape(lead)}</span> ' if lead else ""
    return f'<span style="color:{text_color}">{head}{".".join(pieces)}</span>'


class _VersionButton(Button):
    """A bordered button whose label is rich text (a colored digit); the label ignores the mouse, so the button gets
    the clicks."""

    def __init__(self, tip: str) -> None:
        super().__init__("", "secondary", compact=True)
        self.setToolTip(tip)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(SPACE.md, 0, SPACE.md, 0)
        self._label = QLabel()
        self._label.setTextFormat(Qt.TextFormat.RichText)
        self._label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self._label)

    def set_markup(self, html: str) -> None:
        self._label.setFont(self.font())
        self._label.setText(html)
        self.setMinimumWidth(self._label.sizeHint().width() + 2 * SPACE.md + 4)

    def sizeHint(self):      # noqa: N802 -- Qt's name
        hint = super().sizeHint()
        return hint.expandedTo(self.minimumSize())


class VersionBar(Surface):
    revert_requested = Signal(str)            # id_slug
    overwrite_requested = Signal(str)         # id_slug
    level_requested = Signal(str, str)        # id_slug, "patch" | "minor" | "major"
    new_slide_requested = Signal(str)         # id_slug: Save as new (slide_branch)

    def __init__(self, tokens: Callable[[], Tokens], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._state: Optional[VersionState] = None
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACE.sm)
        self._revert = _VersionButton("")
        self._overwrite = _VersionButton("")
        self._levels = {level: _VersionButton("") for level in ("patch", "minor", "major")}
        self._new = Button("Save as new", "secondary", compact=True)
        for button in (self._revert, self._overwrite, *self._levels.values(), self._new):
            row.addWidget(button)
        self._revert.clicked.connect(lambda: self._send(self.revert_requested))
        self._overwrite.clicked.connect(lambda: self._send(self.overwrite_requested))
        self._new.clicked.connect(lambda: self._send(self.new_slide_requested))
        for level, button in self._levels.items():
            button.clicked.connect(lambda _=False, level=level: self._send_level(level))
        self.setVisible(False)

    def _send(self, signal) -> None:
        if self._state is not None:
            signal.emit(self._state.id_slug)

    def _send_level(self, level: str) -> None:
        if self._state is not None:
            self.level_requested.emit(self._state.id_slug, level)

    def set_state(self, state: Optional[VersionState]) -> None:
        """None: no slide that has versions on show, the buttons are hidden."""
        self._state = state
        self.setVisible(state is not None)
        if state is not None:
            self._apply(state)

    def refresh_colors(self) -> None:
        if self._state is not None:
            self._apply(self._state)

    def _apply(self, state: VersionState) -> None:
        tokens = self._tokens()
        accent, danger, text = tokens.info, tokens.error, tokens.text
        base_parts = state.base.split(".")
        self._revert.set_markup(rich(base_parts, None, accent, text, lead=REVERT, lead_color=danger))
        self._overwrite.set_markup(rich(base_parts, None, accent, text, lead=OVERWRITE, lead_color=accent))
        names = {"patch": "patch", "minor": "minor", "major": "major"}
        for level, button in self._levels.items():
            new, index = bumped(state.base, level)
            button.set_markup(rich(new.split("."), index, accent, text))
            button.setToolTip(state.why_not if not state.changes else
                              f"Save the changes as a {names[level]} version: v{new}")
        self._revert.setToolTip(state.why_not if not state.changes else
                                f"Revert to v{state.base}: discard the changes since then (Ctrl+Z brings them back)")
        self._overwrite.setToolTip(state.why_not if not state.changes else
                                   f"Overwrite v{state.base} with the changes: it keeps its number")
        self._new.setToolTip(state.why_not if not state.changes else
                             "Save the changes as a new slide of their own; this slide goes back to its saved version")
        for widget in (self._revert, self._overwrite, *self._levels.values(), self._new):
            widget.setEnabled(state.changes)
