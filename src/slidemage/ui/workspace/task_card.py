"""The task card (workspace v6 handoff, section 4): the run of one AI task on one slide, shown in the assistant's body
in place of the conversation, with Back to conversation above it.

The card (task_card_model.py) is the TaskRunner's; this view shows what the model says of its phase: the title, the
slide it was started on and the route it runs on, the state line with its icon (and the seconds while it
generates), the diff of the proposal in Review and Conflict (the chat's DiffCard), the buttons of the phase and the
collapsible steps. It acts only through the runner and the window.

For the keyboard and for assistive technology: the state line is a status (its text is announced when the phase
changes, not on every tick of the seconds), the icons say in words what they show, the steps toggle says whether
it is open, and the focus stays on the buttons when a phase replaces them (`focus_first`; a phase without buttons parks
it on the steps toggle until the next one has some).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QVBoxLayout

from ..kit import kit_qss as q
from ..kit.flow import FlowLayout
from ..kit.widgets import Button, IconLabel, Surface, announce, clear_layout, set_property
from . import compare_rendered, task_card_model as model
from .chat.cards import DiffCard
from .task_card_model import TaskCard
from .terminal.tasks import TaskRunner

MOVED_ON = " (still this slide, though you moved on)"


class TaskCardView(Surface):
    back_clicked = Signal()             # Back to conversation
    sign_in_clicked = Signal()          # Sign in…: the setup card of Claude Code's login

    def __init__(self, app, tasks: TaskRunner) -> None:
        super().__init__()
        self.app, self.tasks = app, tasks
        self._shown: TaskCard | None = None
        self._compare = self._change = self._steps_open = False   # Compare with current, View change, the steps
        self._seen: dict[str, object] = {}                          # what the rebuilt parts show now
        self._announced: tuple | None = None                        # (card, phase) the state line last announced
        self._parked = False                                        # the keyboard waits on the steps toggle for buttons
        self._diff: DiffCard | None = None
        self._handlers = {
            "stop": tasks.stop, "apply": tasks.apply, "reject": self._reject, "diff": self._full_diff, "view": self._view,
            "undo": self._undo, "close": tasks.close_card, "compare": self._compare_with_current, "rendered": self._compare_rendered, "again": tasks.run_again,
            "source": self._open_source, "log": self._open_log, "sign_in": self.sign_in_clicked.emit}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.back = Button("← Back to conversation", "ghost", compact=True)
        self.back.clicked.connect(self.back_clicked)
        layout.addWidget(self.back, 0, Qt.AlignmentFlag.AlignLeft)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setObjectName(q.SURFACE)
        scroll.viewport().setObjectName(q.SURFACE)
        layout.addWidget(scroll, 1)
        page = Surface()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addWidget(self._build_card())
        page_layout.addStretch(1)
        scroll.setWidget(page)
        tasks.card_changed.connect(self.render)
        self.render()

    def _build_card(self) -> Surface:
        frame = Surface()
        frame.setObjectName(q.TASK_CARD)
        body = QVBoxLayout(frame)
        body.setContentsMargins(14, 14, 14, 14)
        body.setSpacing(10)
        head = QVBoxLayout()
        head.setSpacing(3)
        self.title = QLabel()
        self.title.setObjectName(q.TASK_TITLE)
        self.title.setWordWrap(True)
        head.addWidget(self.title)
        self.target = QLabel()
        self.target.setObjectName(q.ASSISTANT_TARGET)
        self.target.setWordWrap(True)
        head.addWidget(self.target)
        route = QHBoxLayout()
        route.setSpacing(5)
        self.route_icon = IconLabel("computer", 15)
        route.addWidget(self.route_icon)
        self.route = QLabel()
        self.route.setObjectName(q.TASK_ROUTE)
        self.route.setWordWrap(True)
        route.addWidget(self.route, 1)
        head.addLayout(route)
        body.addLayout(head)

        state = QHBoxLayout()
        state.setSpacing(8)
        self.state_icon = IconLabel("autorenew", 18)
        state.addWidget(self.state_icon, 0, Qt.AlignmentFlag.AlignTop)
        self.state = QLabel()
        self.state.setObjectName(q.TASK_STATE)
        self.state.setWordWrap(True)
        self.state.setAccessibleName("Task status")
        state.addWidget(self.state, 1)
        self.elapsed = QLabel()
        self.elapsed.setObjectName(q.TASK_ELAPSED)
        state.addWidget(self.elapsed, 0, Qt.AlignmentFlag.AlignTop)
        body.addLayout(state)

        self._diff_box = QVBoxLayout()
        body.addLayout(self._diff_box)
        self._buttons = FlowLayout(spacing=8)
        body.addLayout(self._buttons)
        self.steps_toggle = Button("", "ghost", compact=True)
        self.steps_toggle.clicked.connect(self._toggle_steps)
        body.addWidget(self.steps_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self._steps = QVBoxLayout()
        self._steps.setSpacing(6)
        body.addLayout(self._steps)
        return frame

    # -- showing the card -------------------------------------------------------------------------

    def render(self) -> None:
        card = self.tasks.card
        if card is not self._shown:                 # another card: its own comparison and view
            self._shown = card
            self._compare = self._change = False
        if card is None:
            self._announced = None
            self._set_diff(None)
            return
        self.title.setText(card.title)
        self.target.setText(self._target_text(card))
        cloud = not card.route.is_local
        self.route_icon.set_icon("cloud" if cloud else "computer")
        self.route_icon.set_tone("cloud" if cloud else "local")
        self.route.setText(card.route.label)
        self.route_icon.setAccessibleName("Cloud" if cloud else "Local")
        set_property(self.route, "cloud", cloud)
        icon, tone = model.LOOKS[card.phase]
        text = model.state_text(card)
        self.state_icon.set_icon(icon)
        self.state_icon.set_tone(tone)
        self.state.setText(text)
        self.state.setAccessibleDescription(text)
        if (id(card), card.phase) != self._announced:
            self._announced = (id(card), card.phase)
            announce(self.state, text)
        set_property(self.state, "tone", "" if tone == "strong" else tone)
        self.elapsed.setText(f"{card.elapsed} s" if card.phase == model.GENERATE else "")
        self._set_diff(self._diff_of(card))
        self._set_buttons(model.actions(card))
        self.steps_toggle.setText(("▾ " if self._steps_open else "▸ ") + model.steps_text(card))
        self.steps_toggle.setAccessibleName(model.steps_text(card))
        self.steps_toggle.setAccessibleDescription("Expanded" if self._steps_open else "Collapsed")
        self._set_steps(model.steps(card) if self._steps_open else [])

    def _target_text(self, card: TaskCard) -> str:
        if not card.target:
            return "No slide in view"
        moved = card.focus is not None and self.app.centre.path != card.focus
        return f"Target: {card.target}" + (f" · {card.target_title}" if card.target_title else "") + (MOVED_ON if moved else "")

    def _diff_of(self, card: TaskCard) -> tuple[str, str, str, str] | None:
        """The diff the card shows: (title, before, after, note), or None."""
        if card.phase in (model.REVIEW, model.CONFLICT) or (card.phase == model.DONE and self._change):
            if self._compare and card.phase == model.CONFLICT:
                return card.diff_title, self.tasks.current_text(), card.after, "The proposal against the slide as it is now."
            return card.diff_title, card.before, card.after, ""
        return None

    def _set_diff(self, diff: tuple[str, str, str, str] | None) -> None:
        """Rebuild the diff only when it is another (the card renders every second while it generates)."""
        key = (id(self._shown), diff)
        if self._seen.get("diff") == key:
            return
        self._seen["diff"] = key
        clear_layout(self._diff_box)
        self._diff = None
        if diff is not None:
            self._diff = DiffCard(*diff)
            self._diff_box.addWidget(self._diff)

    def _set_buttons(self, actions: list[model.Action]) -> None:
        if self._seen.get("actions") == actions:
            return
        self._seen["actions"] = actions
        focused = (self._parked and self.steps_toggle.hasFocus()) or any(
            self._buttons.itemAt(i).widget().hasFocus() for i in range(self._buttons.count()))
        while self._buttons.count():
            button = self._buttons.takeAt(0).widget()
            button.setParent(None)
            button.deleteLater()
        for action in actions:
            button = Button(action.label, "primary" if action.primary else "secondary")
            button.clicked.connect(self._handlers[action.key])
            self._buttons.addWidget(button)
        self._parked = False
        if focused:                     # the phase replaced the button the keyboard was on
            self.focus_first()
            self._parked = not actions

    def focus_first(self) -> None:
        """The keyboard goes to the first action of the phase (Stop, Apply, Run again…), else to the steps toggle."""
        item = self._buttons.itemAt(0)
        (item.widget() if item is not None else self.steps_toggle).setFocus(Qt.FocusReason.OtherFocusReason)

    def _set_steps(self, steps: list[model.Step]) -> None:
        if self._seen.get("steps") == steps:
            return
        self._seen["steps"] = steps
        clear_layout(self._steps)
        for step in steps:
            line = QHBoxLayout()
            line.setSpacing(8)
            icon = IconLabel(step.icon, 17)
            icon.set_tone(step.tone)
            icon.setAccessibleName(step.word)
            line.addWidget(icon)
            line.addWidget(QLabel(step.label), 1)
            note = QLabel(step.note)
            note.setObjectName(q.TASK_STEP)
            line.addWidget(note)
            self._steps.addLayout(line)

    def _toggle_steps(self) -> None:
        self._steps_open = not self._steps_open
        self.render()

    # -- the buttons -------------------------------------------------------------------------------

    def _reject(self) -> None:
        self.tasks.close_card()
        self.app.toast.show_message("Rejected. Nothing was changed.")

    def _full_diff(self) -> None:
        if self._diff is not None:
            self._diff.show_all()

    def _compare_with_current(self) -> None:
        self._compare = True
        self.render()

    def _compare_rendered(self) -> None:
        found = self.tasks.compare_texts()
        if found is None or compare_rendered.open_compare(self.app, *found) is None:
            self.app.toast.show_message("Nothing to compare: the two texts are the same.")

    def _view(self) -> None:
        """View DE version: the new slide in the centre column; View change: the diff of what was written."""
        if self.tasks.card.is_translation:
            self.tasks.show_result()
        else:
            self._change = True
            self.render()

    def _undo(self) -> None:
        name = self.tasks.card.result_path.name
        problem = self.tasks.undo()
        self.app.toast.show_message(problem or f"Undone: {name} is as it was before the change.")

    def _open_source(self) -> None:
        self.app.open_slide_editor(self.tasks.card.result_path)
        self.app.state.set_mode("source")

    def _open_log(self) -> None:
        self.app.compile_display.drawer.open()
