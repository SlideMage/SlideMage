"""The header of the assistant card (workspace v6 handoff, section 3), four rows:

1. the route (icon, name in amber on Cloud, what the conversation runs on), Focus and New conversation;
2. the scope (This slide | Whole deck) and its target: "1y8 · Title", " · unsaved" with unsaved edits in the Source
   view; for the deck "name · 80 slides";
3. at most two task buttons that fit the scope, the slide and what the route can run (terminal/tasks.py
   `contextual`), and "All actions…" (⌘K);
4. a pill with what a task is doing and Open: the task card that was left with Back to conversation ("Update DE
   translation · generating"), or a running batch or image task, which have no card.

The header only shows and asks: the card around it (assistant.py) acts. The task offers are the bubbles of
terminal/tasks.py, worked out for the scope when the slide, its text or the route changes; the command palette
reads the same list (`offers`).
"""
from __future__ import annotations

from functools import partial

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QHideEvent, QShowEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

from ... import app_settings, deck_outline, slide_language
from ...ai import ai_profile
from ...ai.claude_scope import DECK
from ..kit import kit_qss as q
from ..kit.flow import FlowLayout
from ..kit.widgets import Button, ClickFrame, ElidedLabel, IconButton, IconLabel, SegmentedControl, Surface, set_property
from ..text import plural
from .state import WorkspaceState
from .task_card_model import PILL_WORDS
from .terminal.tasks import Bubble, TaskRunner, bubbles, contextual, deck_bubbles, deck_slides

POLL_MS = 400       # how often the file shown and its unsaved state are looked at (neither has a signal)
TYPING_MS = 500     # the offers follow the text a moment after the last keystroke
SUBTITLES = {ai_profile.CLAUDE_CODE: "Terminal · permissions are handled in Claude Code"}


class RunningPill(ClickFrame):
    """A grey line with what the running task is doing; a click, like its Open, asks to see it."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName(q.TASK_PILL)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(6)
        layout.addWidget(IconLabel("assignment", 16))
        self.label = ElidedLabel()
        layout.addWidget(self.label, 1)
        self.open_label = QLabel("Open")
        layout.addWidget(self.open_label)
        self.hide()


class AssistantHeader(Surface):
    focus_toggled = Signal(bool)        # Focus was pressed: the side panels give way (True) or come back
    new_conversation = Signal()
    task_chosen = Signal(object)        # a Bubble
    task_opened = Signal()              # the pill's Open

    def __init__(self, app, state: WorkspaceState, scope: SegmentedControl, tasks: TaskRunner, blocked) -> None:
        """`scope` is the card's; `blocked()` says the route cannot run tasks now (Claude Code needs setup)."""
        super().__init__()
        self.app, self.state, self.scope, self.tasks, self._blocked = app, state, scope, tasks, blocked
        self.focused = False
        self._offers: dict[str, list[Bubble]] = {}
        self.shown: list[Bubble] = []      # the task buttons on show
        self._seen: tuple = ()
        self._soon = QTimer(self)               # the content follows what changed in the same event loop turn
        self._soon.setSingleShot(True)
        self._soon.timeout.connect(self.refresh_content)
        self._typing = QTimer(self)
        self._typing.setSingleShot(True)
        self._typing.setInterval(TYPING_MS)
        self._typing.timeout.connect(self.refresh_content)
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self._look)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addLayout(self._build_route_row())
        layout.addLayout(self._build_scope_row())
        self._actions = FlowLayout()
        layout.addLayout(self._actions)
        self.pill = RunningPill()
        self.pill.clicked.connect(self.task_opened)
        layout.addWidget(self.pill)
        self.all_actions = Button("All actions…", "ghost", compact=True)
        self.all_actions.setToolTip("Every command: the command palette")
        self.all_actions.clicked.connect(lambda: self.app.palette.open())
        self._actions.addWidget(self.all_actions)

        scope.changed.connect(lambda _scope: self.refresh_content())
        tasks.busy_changed.connect(self._on_busy)
        tasks.card_changed.connect(self._on_busy)
        for signal in (state.deck_changed, state.focused_slide_changed, state.view_changed, state.language_changed,
                       state.mode_changed, state.dirty_changed, state.lint_errors_changed, state.ai_route_changed):
            signal.connect(lambda _value: self.schedule())

    # -- building ---------------------------------------------------------------------------

    def _build_route_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.route_icon = IconLabel("computer", 20)
        row.addWidget(self.route_icon)
        words = QVBoxLayout()
        words.setSpacing(0)
        self.title = QLabel()
        self.title.setObjectName(q.ASSISTANT_TITLE)
        words.addWidget(self.title)
        self.subtitle = ElidedLabel()
        self.subtitle.setObjectName(q.ASSISTANT_SUB)
        words.addWidget(self.subtitle)
        row.addLayout(words, 1)
        self.focus_button = IconButton("open_in_full", "Focus assistant: hide the side panels")
        self.focus_button.clicked.connect(self.toggle_focus)
        row.addWidget(self.focus_button)
        self.new_button = IconButton("add_comment", "New conversation (this route only)", size=20)
        self.new_button.clicked.connect(self.new_conversation)
        row.addWidget(self.new_button)
        return row

    def _build_scope_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.scope)
        self.target = ElidedLabel()
        self.target.setObjectName(q.ASSISTANT_TARGET)
        row.addWidget(self.target, 1)
        return row

    # -- the route (row 1) ------------------------------------------------------------------

    def show_route(self, route: ai_profile.Route) -> None:
        """Name `route` and what its conversation runs on (the chat's model, or Claude Code's terminal)."""
        cloud = not route.is_local
        self.route_icon.set_icon("cloud" if cloud else "computer")
        self.route_icon.set_tone("cloud" if cloud else "local")
        self.title.setText(route.name)
        set_property(self.title, "cloud", cloud)
        if route.route in SUBTITLES:
            subtitle = SUBTITLES[route.route]
        else:
            subtitle = f"Chat with {route.model or 'no model chosen'}"
            if route.is_local:
                host = app_settings.get_ollama_host(self.state.project)
                subtitle += f" · {host.split('://', 1)[-1].rstrip('/')}"
        self.subtitle.set_full_text(subtitle)

    def toggle_focus(self) -> None:
        self.focused = not self.focused
        self.focus_button.set_icon("close_fullscreen" if self.focused else "open_in_full")
        self.focus_button.setToolTip("Show the side panels again" if self.focused
                                     else "Focus assistant: hide the side panels")
        self.focus_toggled.emit(self.focused)

    # -- what changed (rows 2 to 4) -----------------------------------------------------------

    def schedule(self) -> None:
        """Something the offers or the target depend on changed: look again before the next paint."""
        self._offers.clear()
        self._soon.start(0)

    def _on_busy(self, _busy: bool = False) -> None:
        """A task started, moved on or ended: its pill and the buttons (none while it runs or waits) now, not a turn
        later."""
        self._offers.clear()
        self.refresh_actions()

    def on_typing(self) -> None:
        self._offers.clear()
        self._typing.start()

    def offers(self, scope: str) -> list[Bubble]:
        """The tasks that fit `scope` now, as terminal/tasks.py finds them (kept until something changes)."""
        if scope not in self._offers:
            self._offers[scope] = deck_bubbles(self.app) if scope == DECK else bubbles(self.app)
        return self._offers[scope]

    def refresh_content(self) -> None:
        self.target.set_full_text(self.target_text())
        self._seen = self._now()
        self.refresh_actions()

    def refresh_actions(self) -> None:
        """Row 3: the two most relevant tasks the route can run, then All actions…; row 4: the running pill."""
        tasks = self.tasks
        found = [] if tasks.occupied or self._blocked() else contextual(self.offers(self.scope.current()), tasks)
        if found != self.shown:
            self.shown = found
            while self._actions.count():
                widget = self._actions.takeAt(0).widget()
                if widget is not self.all_actions:
                    widget.setParent(None)
                    widget.deleteLater()
            for bubble in found:
                button = Button(bubble.label, "secondary", compact=True)
                button.clicked.connect(partial(self.task_chosen.emit, bubble))
                self._actions.addWidget(button)
        if self._actions.indexOf(self.all_actions) < 0:
            self._actions.addWidget(self.all_actions)
        card = tasks.card
        left = card is not None and card.hidden
        self.pill.setVisible(left or (card is None and tasks.busy))
        if left:
            self.pill.label.set_full_text(f"{card.title} · {PILL_WORDS[card.phase]}")
        elif card is None and tasks.busy:
            self.pill.label.set_full_text(tasks.describe())

    def target_text(self) -> str:
        """What the scope points at: the slide in the Source view (and whether it has unsaved edits), or the deck."""
        if self.scope.current() == DECK:
            deck = self.state.deck
            return "No deck is open" if deck is None else f"{deck.name} · {plural(len(deck_slides(self.app)), 'slide')}"
        centre = self.app.centre
        path = centre.path
        if path is None:
            return "No slide in view"
        text = path.name
        if path.parent == self.state.project.slides_dir and slide_language.is_current_file(path):
            id_slug = path.name.removesuffix(slide_language.CURRENT_SUFFIX)
            title = deck_outline.slide_file_title(path, id_slug)
            text = f"{slide_language.bare_id(id_slug)} · {title}" if title else slide_language.bare_id(id_slug)
        return text + (" · unsaved" if centre.is_dirty(path) else "")

    def _now(self) -> tuple:
        centre = self.app.centre
        path = centre.path
        return path, path is not None and centre.is_dirty(path)

    def _look(self) -> None:
        """The file shown and its unsaved state have no signal: compare them now and then."""
        if self._now() != self._seen:
            self.schedule()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.schedule()
        self._poll.start()

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        self._poll.stop()
