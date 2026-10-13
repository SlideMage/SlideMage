"""The two things around an image batch that name its route (workspace v6 handoff, section 5): the question asked
before it starts, and the results panel shown when it ends, is stopped or is cancelled by a switch of the route.

The results panel lists every image of the batch with what became of it and offers Retry failed. One widget serves
both entry points: the Images page shows it under its job card, the assistant in the place of the conversation (with
Back to conversation). Both ask the same question before a retry, so a run never starts on a route the user has not
been told about.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QMessageBox, QScrollArea, QVBoxLayout, QWidget

from ...ai.ai_profile import Route
from ...batch_result import CANCELLED, DONE, DRAFT, FAILED, KEPT, TRANSLATE, BatchResult, display_name
from ..kit import kit_qss as q
from ..kit.flow import FlowLayout
from ..kit.widgets import Button, IconLabel, Surface, clear_layout, set_property

# What each kind of batch sends when the route is Cloud, how long it takes, and what the user is told besides.
SENDS = {DRAFT: "sends each image and its slide text to the cloud", TRANSLATE: "sends each description to the cloud"}
SECONDS = {DRAFT: "10–60 s per image", TRANSLATE: "a few seconds per image"}
HOURS = {DRAFT: "expect this to take hours", TRANSLATE: ""}       # the estimate on Local, where the code has one
NOTES = {DRAFT: "Reviewed descriptions are never overwritten.",
         TRANSLATE: "These are unreviewed translations, like a drafted description: check them before relying on them."}
SAVED = ("Each image is written to disk as it finishes, so you can stop any time and resume later: the queue is "
         "recomputed from the files.")
LOOK = {DONE: ("check_circle", "ok"), KEPT: ("warning", "warning"), FAILED: ("error", "error"),
        CANCELLED: ("remove_circle_outline", "muted")}     # the icon and the tone of an outcome
MAX_LIST_HEIGHT = 240


def question(kind: str, count: int, project: str, route: Route) -> tuple[str, str]:
    """(the question, the line under it) of a batch over `count` images of `project` on `route`: the model and, on
    Cloud, what is sent and how long one image takes; on Local the estimate there is."""
    what = "image description" if kind == DRAFT else "description"
    text = f"{'Draft' if kind == DRAFT else 'Translate'} {count} {what}{'' if count == 1 else 's'} in {project}"
    text += "?" if kind == DRAFT else " to German?"
    parts = [route.label, *([SENDS[kind], SECONDS[kind]] if not route.is_local else [HOURS[kind]])]
    return text, " · ".join(part for part in parts if part) + "."


def confirm(parent: QWidget, kind: str, count: int, project: str, route: Route, also: str = "") -> tuple[bool, bool]:
    """Ask before a batch that takes long: (whether to start, whether the extra checkbox `also`, if there is one, is
    ticked)."""
    text, details = question(kind, count, project, route)
    box = QMessageBox(parent)
    box.setWindowTitle("Draft all descriptions" if kind == DRAFT else "Translate all images")
    box.setText(text)
    box.setInformativeText(f"{details}\n\n{SAVED}\n\n{NOTES[kind]}")
    checkbox = QCheckBox(also) if also else None
    if checkbox is not None:
        box.setCheckBox(checkbox)
    box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
    box.button(QMessageBox.StandardButton.Ok).setText("Start")
    return box.exec() == QMessageBox.StandardButton.Ok, checkbox is not None and checkbox.isChecked()


class BatchResultView(Surface):
    """What became of each image of a batch (BatchResult): title with the route, summary, one row per image,
    Retry failed (n) and Close. `back` adds ← Back to conversation above it, for the assistant."""

    retry_clicked = Signal()        # Retry failed: the owner starts a new batch of `result.failed`
    closed = Signal()               # Close, or Back to conversation

    def __init__(self, *, back: bool = False) -> None:
        super().__init__()
        self.result: BatchResult | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        if back:
            self.back = Button("← Back to conversation", "ghost", compact=True)
            self.back.clicked.connect(self.closed)
            layout.addWidget(self.back, 0, Qt.AlignmentFlag.AlignLeft)
        frame = Surface()
        frame.setObjectName(q.TASK_CARD)
        body = QVBoxLayout(frame)
        body.setContentsMargins(14, 14, 14, 14)
        body.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.title = QLabel()
        self.title.setObjectName(q.TASK_TITLE)
        self.title.setWordWrap(True)
        head.addWidget(self.title, 1)
        self.route_icon = IconLabel("computer", 15)
        head.addWidget(self.route_icon)
        self.route = QLabel()
        self.route.setObjectName(q.TASK_ROUTE)
        self.route.setWordWrap(True)
        head.addWidget(self.route)
        body.addLayout(head)
        self.summary = QLabel()
        self.summary.setObjectName(q.TASK_STATE)
        self.summary.setWordWrap(True)
        set_property(self.summary, "tone", "muted")
        body.addWidget(self.summary)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setMaximumHeight(MAX_LIST_HEIGHT)
        self.scroll.setObjectName(q.SURFACE)
        self.scroll.viewport().setObjectName(q.SURFACE)
        body.addWidget(self.scroll)
        self._buttons = FlowLayout(spacing=8)
        body.addLayout(self._buttons)
        layout.addWidget(frame)
        self.retry = self.close_button = None
        self.hide()

    def show_result(self, result: BatchResult) -> None:
        self.result = result
        self.title.setText(result.title)
        cloud = not result.route.is_local
        self.route_icon.set_icon("cloud" if cloud else "computer")
        self.route_icon.set_tone("cloud" if cloud else "local")
        self.route.setText(result.route.label)
        set_property(self.route, "cloud", cloud)
        self.summary.setText(result.summary)
        frame = QFrame()
        frame.setObjectName(q.LIST_BOX)
        rows = QVBoxLayout(frame)
        rows.setContentsMargins(4, 4, 4, 4)
        rows.setSpacing(0)
        for image, outcome in result.items:
            line = QHBoxLayout()
            line.setContentsMargins(8, 6, 8, 6)
            line.setSpacing(8)
            icon, tone = LOOK[outcome.kind]
            mark = IconLabel(icon, 16)
            mark.set_tone(tone)
            line.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
            words = QVBoxLayout()
            words.setSpacing(1)
            name = QLabel(display_name(image))
            name.setObjectName(q.PANEL_MONO)
            name.setToolTip(image)
            words.addWidget(name)
            label = QLabel(result.label(outcome))
            label.setObjectName(q.TASK_STATE)
            label.setWordWrap(True)
            set_property(label, "tone", tone)
            words.addWidget(label)
            line.addLayout(words, 1)
            row = QWidget()
            row.setLayout(line)
            rows.addWidget(row)
        self.scroll.setWidget(frame)
        clear_layout(self._buttons)
        failed = result.failed
        self.retry = Button(f"Retry failed ({len(failed)})", "primary") if failed else None
        if self.retry is not None:
            self.retry.clicked.connect(self.retry_clicked)
            self._buttons.addWidget(self.retry)
        self.close_button = Button("Close", "secondary" if failed else "primary")
        self.close_button.clicked.connect(self.closed)
        self._buttons.addWidget(self.close_button)
        self.show()

    def clear(self) -> None:
        self.result = None
        self.hide()
