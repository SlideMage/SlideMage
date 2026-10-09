r"""Visibility: in which views (Instructor, During course, After course) the open deck typesets
the focused slide, one row per call of it -- the whole slide, or the reveal steps of a
\slidestep call.

A cell writes \conditionalslide / \slidestep through deck_editor.set_calls_visibility(), the
function the slide list's menu and bulk bar use, as an edit of the deck (with Undo). A call that
has no per-view form (a pinned version, \slidefinal) or sits on a line of its own that the editor
cannot rewrite shows its state but cannot be changed."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton

from ....deck_editor import VISIBILITY_MACROS, SlideCall, set_calls_visibility
from ...kit import kit_qss as q
from ..menus import VIEW_LABELS
from ..state import VIEWS
from .base import Row, SidePanel, box, text

# The matrix has room for the short names; the kit's view tones are "instructor", "during", "after".
HEADS = {"instructor": "Instructor", "during-course": "During", "after-course": "After"}
TONES = {"instructor": "instructor", "during-course": "during", "after-course": "after"}


class Visibility(SidePanel):
    key = "visibility"
    title = "Visibility"

    def suffix(self) -> str:
        return f"{VIEW_LABELS[self.state.view]} highlighted"

    def build(self, id_slug: str) -> None:
        calls = self.deck_calls()
        if not calls:
            self.body.addWidget(text(f"{self.state.deck.name} does not call this slide.", q.DETAILS_LABEL))
            return
        frame, layout = box()
        row = Row(layout)
        grid = QGridLayout()
        grid.setHorizontalSpacing(0)
        grid.setVerticalSpacing(0)
        grid.setColumnStretch(0, 1)
        for column, view in enumerate(VIEWS, start=1):
            head = QLabel(HEADS[view])
            head.setObjectName(q.MATRIX_HEAD)
            head.setProperty("view", TONES[view])
            head.setProperty("current", view == self.state.view)
            head.setAlignment(Qt.AlignmentFlag.AlignCenter)
            head.setMinimumWidth(64)
            grid.addWidget(head, 0, column)
        for line, (position, call) in enumerate(calls, start=1):
            grid.addLayout(self._label(call, position), line, 0)
            for column, view in enumerate(VIEWS, start=1):
                grid.addWidget(self._cell(call, view), line, column)
        row.body.addLayout(grid)
        self.body.addWidget(frame)
        self.body.addWidget(text("A slide has to stay in at least one view. Pinned versions and the final "
                                 "overlay state cannot be hidden per view.", q.PANEL_CAPTION))
        self.body.addStretch(1)

    def _label(self, call: SlideCall, position: int) -> QGridLayout:
        grid = QGridLayout()
        what = f"Steps {call.steps}" if call.macro == "slidestep" else "Whole slide"
        grid.addWidget(text(what, q.DETAILS_VALUE), 0, 0)
        grid.addWidget(text(f"\\{call.macro} · #{position}", q.PANEL_CAPTION), 1, 0)
        grid.setContentsMargins(0, 6, 0, 6)
        grid.setVerticalSpacing(0)
        return grid

    def _cell(self, call: SlideCall, view: str) -> QFrame:
        slot = QFrame()
        slot.setObjectName(q.MATRIX_SLOT)
        slot.setProperty("current", view == self.state.view)
        layout = QHBoxLayout(slot)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cell = QPushButton("✓" if call.included_in(view) else "")
        cell.setObjectName(q.MATRIX_CELL)
        cell.setProperty("view", TONES[view])
        cell.setCheckable(True)
        cell.setChecked(call.included_in(view))
        cell.setFixedSize(18, 18)
        cell.setCursor(Qt.CursorShape.PointingHandCursor)
        cell.setToolTip(f"Shown in {VIEW_LABELS[view]}" if call.included_in(view) else f"Hidden in {VIEW_LABELS[view]}")
        if not call.editable or call.macro not in VISIBILITY_MACROS:
            cell.setEnabled(False)
            cell.setToolTip(call.readonly_reason or f"\\{call.macro} has no per-view form.")
        cell.clicked.connect(lambda checked: self._set(call, view, checked))
        layout.addWidget(cell)
        return slot

    def _set(self, call: SlideCall, view: str, visible: bool) -> None:
        done = self.app.slide_list.edit(
            "Change failed",
            f"{'Showed' if visible else 'Hid'} {call.id_slug} in {VIEW_LABELS[view]} of {self.state.deck.name}",
            lambda path, deck_text: set_calls_visibility(path, deck_text, [call], view, visible))
        if not done:
            self.refresh()   # refused: the cell goes back to what the deck says
