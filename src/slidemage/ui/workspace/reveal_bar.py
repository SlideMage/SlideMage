"""The reveal-step bar under the Preview's page: a slider over the steps of the slide, tick marks for
what the selected deck call includes, and, expanded, one timeline per deck version.

A tick is one step. Filled: the selected call includes it in that version; hollow: it does not (the slide
shows it in the Preview, the deck leaves it out); crossed: the slide's own frame spec drops it. Dashed
outlines: the pages come from the editor buffer, not the saved file. The bar draws what it is given
(RowSpec per version) and says what the user did (step_selected, view_requested, tick_toggled); the
Preview pane owns the renders and the deck edits (docs/plans/reveal-step-slider.md, 4).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QToolTip, QVBoxLayout, QWidget

from ...reveal_steps import StepPlan
from ..kit.tokens import Tokens
from ..kit import kit_qss as q
from ..kit.widgets import ElidedLabel, IconButton, Surface, ToggleChip, clear_layout
from .menus import VIEW_LABELS
from .state import VIEWS
from .topbar import VIEW_TONES

TRACK_HEIGHT = 30
MARGIN = 16
TICK = 6.0          # radius of a tick


def short_view(view: str) -> str:
    return VIEW_LABELS[view].replace(" course", "")


@dataclass
class RowSpec:
    """One deck version's timeline. `plan` None: the steps are still being counted."""
    view: str
    plan: Optional[StepPlan]
    editable: bool = False
    reason: str = ""          # why the ticks cannot be edited (a tooltip), or a warning when they can
    present: bool = True      # False: the slide is not in this version at all

    @property
    def n(self) -> int:
        return self.plan.n if self.plan is not None else 0


class StepTrack(QWidget):
    """A row of ticks, one per stop. Click or the arrow keys pick a step (`selected`); in edit mode a click on a
    tick asks to toggle its inclusion (`toggled`) instead."""

    selected = Signal(int)
    toggled = Signal(int)

    def __init__(self, tokens: Callable[[], Tokens], view: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self.view = view
        self.plan: Optional[StepPlan] = None
        self.stops: list[int] = []
        self.current = 0
        self.draft = False
        self.edit_mode = False
        self.counting = False
        self.setFixedHeight(TRACK_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAccessibleName("Reveal step")

    # -- state --------------------------------------------------------------------------

    def set_plan(self, plan: Optional[StepPlan], deck_only: bool, current: int, draft: bool) -> None:
        self.plan, self.draft, self.current = plan, draft, current
        self.counting = plan is None
        self.stops = plan.stops(deck_only) if plan is not None else []
        self.update()

    def color(self) -> QColor:
        return QColor(self._tokens().view_color(VIEW_TONES[self.view]))

    def _x(self, index: int) -> float:
        if len(self.stops) <= 1:
            return self.width() / 2
        return MARGIN + index * (self.width() - 2 * MARGIN) / (len(self.stops) - 1)

    def _index_at(self, x: float) -> Optional[int]:
        if not self.stops:
            return None
        index = min(range(len(self.stops)), key=lambda i: abs(self._x(i) - x))
        return index if abs(self._x(index) - x) <= max(TICK + 4, (self.width() - 2 * MARGIN) / max(len(self.stops) - 1, 1) / 2) else None

    def state_of(self, step: int) -> str:
        """included, excluded, slide (dropped by the slide's own frame spec) or plain (nothing to tell apart)."""
        plan = self.plan
        if plan is None or not plan.marked and step not in plan.slide_excluded:
            return "plain"
        if step in plan.slide_excluded:
            return "slide"
        return "included" if step in plan.included else "excluded"

    def tip_for(self, step: int) -> str:
        label = VIEW_LABELS[self.view]
        state = self.state_of(step)
        text = {"included": f"in {label}", "excluded": f"not in {label}",
                "slide": "left out by the slide's own frame", "plain": ""}[state]
        base = f"Step {step}" + (f" · {text}" if text else "")
        if self.edit_mode and state in ("included", "excluded"):
            base += f" · click to {'remove it from' if state == 'included' else 'add it to'} {label}"
        return base

    # -- painting -----------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        tokens = self._tokens()
        mid = self.height() / 2
        if not self.stops:
            painter.setPen(QColor(tokens.text_3))
            painter.drawText(self.rect().adjusted(MARGIN, 0, -MARGIN, 0),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             "Counting steps…" if self.counting else "")
            return
        color = self.color()
        line = QColor(tokens.line)
        painter.setPen(QPen(line, 2))
        painter.drawLine(QPointF(self._x(0), mid), QPointF(self._x(len(self.stops) - 1), mid))
        for index, step in enumerate(self.stops):
            x, state = self._x(index), self.state_of(step)
            outline = QPen(color if state != "plain" else QColor(tokens.text_3), 1.6)
            if self.draft:
                outline.setStyle(Qt.PenStyle.DashLine)
            if state in ("included", "plain"):
                painter.setBrush(color if state == "included" else QColor(tokens.text_3))
                if self.draft:
                    painter.setBrush(QColor(color.red(), color.green(), color.blue(), 150) if state == "included"
                                     else QColor(tokens.text_4))
                painter.setPen(outline)
            elif state == "excluded":
                painter.setBrush(QColor(tokens.surface))
                painter.setPen(outline)
            else:
                painter.setBrush(QColor(tokens.surface))
                dim = QPen(QColor(tokens.text_4), 1.4)
                if self.draft:
                    dim.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(dim)
            painter.drawEllipse(QPointF(x, mid), TICK, TICK)
            if state == "slide":
                painter.drawLine(QPointF(x - TICK + 1.5, mid + TICK - 1.5), QPointF(x + TICK - 1.5, mid - TICK + 1.5))
            if step == self.current:
                ring = QPen(QColor(tokens.text), 1.6)
                if self.draft:
                    ring.setStyle(Qt.PenStyle.DashLine)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(ring)
                painter.drawEllipse(QPointF(x, mid), TICK + 4, TICK + 4)
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(tokens.focus), 2))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 6, 6)

    # -- input --------------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        index = self._index_at(event.position().x())
        if index is None or event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        step = self.stops[index]
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        if self.edit_mode and self.state_of(step) in ("included", "excluded"):
            self.toggled.emit(step)
        else:
            self.selected.emit(step)

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.ToolTip:
            index = self._index_at(event.pos().x())
            if index is None:
                QToolTip.hideText()
            else:
                QToolTip.showText(event.globalPos(), self.tip_for(self.stops[index]), self)
            return True
        return super().event(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self.stops and self.current in self.stops:
            position = self.stops.index(self.current)
            jump = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1, Qt.Key.Key_PageUp: -1, Qt.Key.Key_PageDown: 1}.get(
                event.key())
            if jump is not None:
                self.selected.emit(self.stops[min(max(position + jump, 0), len(self.stops) - 1)])
                return
            if event.key() == Qt.Key.Key_Home:
                self.selected.emit(self.stops[0])
                return
            if event.key() == Qt.Key.Key_End:
                self.selected.emit(self.stops[-1])
                return
        super().keyPressEvent(event)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.update()


class RevealBar(QWidget):
    """‹ [ticks] ›  "Step 3 of 5 · in During course"  [Deck steps only]  [expand]; expanded, a row per version."""

    step_selected = Signal(int)
    view_requested = Signal(str)
    tick_toggled = Signal(str, int)          # (view, step) -- the user clicked a tick of an editable row
    expanded_changed = Signal(bool)

    def __init__(self, tokens: Callable[[], Tokens], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._rows: dict[str, RowSpec] = {}
        self._view = VIEWS[0]
        self._step = 0
        self._draft = False
        self._expanded = False
        self._rows_widgets: dict[str, tuple[QLabel, StepTrack]] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(6)
        self._previous = IconButton("chevron_left", "Previous step")
        self._next = IconButton("chevron_right", "Next step")
        self.track = StepTrack(tokens, self._view)
        self.label = ElidedLabel()
        self.label.setObjectName(q.SOURCE_NOTE)
        self.deck_only = ToggleChip("Deck steps only")
        self.deck_only.setToolTip("Slide through only the steps the deck includes in this version")
        self.expand = IconButton("unfold_more", "Show every deck version")
        top.addWidget(self._previous)
        top.addWidget(self.track, 1)
        top.addWidget(self._next)
        outer.addLayout(top)
        below = QHBoxLayout()
        below.setSpacing(6)
        below.addWidget(self.label, 1)
        below.addWidget(self.deck_only)
        below.addWidget(self.expand)
        outer.addLayout(below)
        self._rows_box = QVBoxLayout()
        self._rows_box.setSpacing(2)
        self._rows_holder = Surface()
        self._rows_holder.setLayout(self._rows_box)
        self._rows_holder.setVisible(False)
        outer.addWidget(self._rows_holder)
        self.setVisible(False)

        self._previous.clicked.connect(lambda: self.move(-1))
        self._next.clicked.connect(lambda: self.move(1))
        self.track.selected.connect(self._select)
        self.deck_only.toggled.connect(lambda _on: self._relayout())
        self.expand.clicked.connect(lambda: self.set_expanded(not self._expanded))

    # -- state --------------------------------------------------------------------------

    @property
    def step(self) -> int:
        return self._step

    @property
    def expanded(self) -> bool:
        return self._expanded

    @property
    def deck_steps_only(self) -> bool:
        return self.deck_only.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        if expanded != self._expanded:
            self._expanded = expanded
            self.expand.set_icon("unfold_less" if expanded else "unfold_more")
            self.expand.setToolTip("Hide the other deck versions" if expanded else "Show every deck version")
            self._relayout()
            self.expanded_changed.emit(expanded)

    def set_state(self, view: str, step: int, rows: dict[str, RowSpec], draft: bool) -> None:
        """`rows`: the timeline of every version the bar knows (a missing one is left out)."""
        self._view, self._step, self._rows, self._draft = view, step, rows, draft
        self.track.view = view
        self._relayout()

    def _relayout(self) -> None:
        main = self._rows.get(self._view)
        plan = main.plan if main else None
        self.setVisible(plan is not None and plan.n > 1 or self._expanded and any(
            row.plan is not None and row.plan.n > 1 for row in self._rows.values()))
        only = self.deck_only.isChecked()
        self.track.set_plan(plan, only, self._step, self._draft)
        stops = self.track.stops
        marked = plan is not None and plan.marked
        self.deck_only.setVisible(marked)
        self.deck_only.setEnabled(marked)
        self.track.edit_mode = False
        position = stops.index(self._step) + 1 if self._step in stops else 0
        text = ""
        if plan is not None and plan.n:
            text = f"Step {self._step} of {plan.n}"
            if marked:
                state = self.track.state_of(self._step)
                text += {"included": f" · in {short_view(self._view)}",
                         "excluded": f" · not in {short_view(self._view)}",
                         "slide": " · left out by the slide itself"}.get(state, "")
            if self._draft:
                text += " · buffer"
        self.label.set_full_text(text)
        if plan is not None and plan.note:
            self.label.setToolTip(f"{text}\n{plan.note}")
        self._previous.setEnabled(position > 1)
        self._next.setEnabled(0 < position < len(stops))
        self.expand.setVisible(bool(self._rows) and len(self._rows) > 1)
        self._rows_holder.setVisible(self._expanded)
        if self._expanded:
            self._build_rows()

    def _build_rows(self) -> None:
        clear_layout(self._rows_box)
        self._rows_widgets.clear()
        only = self.deck_only.isChecked()
        for view in VIEWS:
            row = self._rows.get(view)
            if row is None:
                continue
            holder = Surface(self._rows_holder)         # children are made with their parent, else they stay hidden
            line = QHBoxLayout(holder)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(6)
            name = ToggleChip(VIEW_LABELS[view], VIEW_TONES[view], holder)
            name.setChecked(view == self._view)
            name.setToolTip(f"Show the slide in {VIEW_LABELS[view]}")
            name.setFixedWidth(120)
            name.clicked.connect(lambda _checked=False, v=view: self.view_requested.emit(v))
            track = StepTrack(self._tokens, view, holder)
            track.edit_mode = row.editable
            track.set_plan(row.plan, only, self._step if view == self._view else 0, self._draft)
            track.counting = row.plan is None and row.present
            track.selected.connect(lambda step, v=view: self._pick(v, step))
            track.toggled.connect(lambda step, v=view: self.tick_toggled.emit(v, step))
            note = ElidedLabel("", holder)
            note.setObjectName(q.SOURCE_NOTE)
            note.setMinimumWidth(60)
            text = "" if row.present else "not in this version"
            if row.reason:
                track.setToolTip(row.reason)
                text = ("" if row.editable else "read-only: ") + row.reason
            note.set_full_text(text)
            line.addWidget(name)
            line.addWidget(track, 3)
            line.addWidget(note, 2)
            self._rows_box.addWidget(holder)
            holder.show()
            self._rows_widgets[view] = (note, track)

    def _pick(self, view: str, step: int) -> None:
        if view != self._view:
            self.view_requested.emit(view)
        self._select(step)

    # -- moving -------------------------------------------------------------------------

    def move(self, delta: int) -> None:
        stops = self.track.stops
        if not stops:
            return
        if self._step in stops:
            position = min(max(stops.index(self._step) + delta, 0), len(stops) - 1)
        else:
            later = [s for s in stops if (s > self._step if delta > 0 else s < self._step)]
            position = stops.index((later[0] if delta > 0 else later[-1]) if later else stops[-1 if delta > 0 else 0])
        self._select(stops[position])

    def _select(self, step: int) -> None:
        if step != self._step:
            self._step = step
            self.step_selected.emit(step)
            self._relayout()
