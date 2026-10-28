# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The header of the assistant card (workspace v6 handoff, section 3), four rows:

1. the AI switch (ai_switch.py: Local | Cloud for every AI task, the connection, the ▾ of AI setup; its tooltip says
   what the conversation runs on), Focus and New conversation. The switch was in the top bar until v8.61.0: here
   every AI control is in one place;
2. the scope (This slide | Whole deck) and its target: "1y8 · Title", " · not saved" with edits that could not be saved in the Source
   view; for the deck "name · 80 slides";
3. at most two task buttons that fit the scope, the slide (with a selection in the Source view: Rewrite selection and
   Proofread selection, which then come first) and what the route can run (task_bubbles.py
   `contextual`), and "All actions…" (⌘K). When no task is on show the row offers "Check readability" (the slide or
   the deck; no AI, so on every route) instead: with a task the row would no longer fit one line of the column, and the
   command is always in ⌘K;
4. a pill with what a task is doing and Open: the task card that was left with Back to conversation ("Update DE
   translation · generating"), or a running batch or image task, which have no card.

The header only shows and asks: the card around it (assistant.py) acts. The task offers are the bubbles of
task_bubbles.py, worked out for the scope when the slide, its text or the route changes; the command palette
reads the same list (`offers`).
"""
from __future__ import annotations

from functools import partial

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QHideEvent, QShowEvent
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ... import app_settings, deck_outline, slide_language
from ...ai import ai_profile
from ...ai.focus_scope import DECK, SLIDE
from ..kit import kit_qss as q
from ..kit.flow import FlowLayout
from ..kit.widgets import Button, ClickFrame, ElidedLabel, IconButton, IconLabel, SegmentedControl, Surface
from ..text import plural
from .ai_switch import AiSwitch
from .state import SETTLE_MS, WorkspaceState
from .task_card_model import PILL_WORDS
from .task_bubbles import Bubble, TaskRunner, bubbles, contextual, deck_bubbles, deck_slides, selection_of

POLL_MS = 400       # how often the file shown and its unsaved state are looked at (neither has a signal)
TYPING_MS = 500     # the offers follow the text a moment after the last keystroke
# The header's width below which the switch drops the connection's name (the subtitle says it), and its icons only.
SWITCH_NAMED_WIDTH, SWITCH_LABELS_WIDTH = 360, 280


class RunningPill(ClickFrame):
    """A grey line with what the running task is doing; a click, like its Open button (the keyboard's way), asks to
    see it."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName(q.TASK_PILL)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(6)
        layout.addWidget(IconLabel("assignment", 16))
        self.label = ElidedLabel()
        layout.addWidget(self.label, 1)
        self.open_button = Button("Open", "ghost", compact=True)
        self.open_button.clicked.connect(self.clicked)
        layout.addWidget(self.open_button)
        self.hide()

    def set_text(self, text: str) -> None:
        self.label.set_full_text(text)
        self.open_button.setAccessibleName(f"Open: {text}")


class AssistantHeader(Surface):
    focus_toggled = Signal(bool)        # Focus was pressed: the side panels give way (True) or come back
    new_conversation = Signal()
    task_chosen = Signal(object)        # a Bubble
    check_chosen = Signal(str)          # Check readability: the scope it was offered for
    task_opened = Signal()              # the pill's Open

    def __init__(self, app, state: WorkspaceState, scope: SegmentedControl, tasks: TaskRunner, blocked) -> None:
        """`scope` is the card's; `blocked()` says the route cannot run tasks now (Claude Code needs setup)."""
        super().__init__()
        self.app, self.state, self.scope, self.tasks, self._blocked = app, state, scope, tasks, blocked
        scope.setAccessibleName("Scope of the assistant")
        self.focused = False
        self._offers: dict[str, list[Bubble]] = {}
        self.shown: list[Bubble] = []      # the task buttons on show
        self.check_shown = ""              # the scope of the Check readability button on show, else ""
        self._seen: tuple = ()
        self._soon = QTimer(self)               # the content follows what changed in the same event loop turn
        self._soon.setSingleShot(True)
        self._soon.timeout.connect(self.refresh_content)
        self._settle = QTimer(self)             # ... but after a change of slide, view or language once that has rested
        self._settle.setSingleShot(True)
        self._settle.setInterval(SETTLE_MS)
        self._settle.timeout.connect(self._settled)
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
        for signal in (state.deck_changed, state.mode_changed, state.dirty_changed, state.lint_errors_changed,
                       state.ai_route_changed):
            signal.connect(lambda _value: self.schedule())
        for signal in (state.focused_slide_changed, state.view_changed, state.language_changed):
            signal.connect(lambda _value: self._on_focus())

    # -- building ---------------------------------------------------------------------------

    def _build_route_row(self) -> QHBoxLayout:
        # One row, so that the card keeps its height for the conversation (640 px windows): what the conversation
        # runs on is the switch's tooltip (the model is also under the message box).
        row = QHBoxLayout()
        row.setSpacing(8)
        self.ai_switch = AiSwitch(self.state)
        self.route_note = ""
        row.addWidget(self.ai_switch)
        row.addStretch(1)
        self.focus_button = IconButton("open_in_full", "Focus assistant: hide the side panels")
        self.focus_button.clicked.connect(self.toggle_focus)
        row.addWidget(self.focus_button)
        self.new_button = IconButton("add_comment", "New conversation (this route only)", size=20)
        self.new_button.clicked.connect(self.new_conversation)
        row.addWidget(self.new_button)
        return row

    def resizeEvent(self, event) -> None:          # noqa: N802 -- Qt's name
        super().resizeEvent(event)
        width = event.size().width()
        self.ai_switch.set_shrink(0 if width >= SWITCH_NAMED_WIDTH else 1 if width >= SWITCH_LABELS_WIDTH else 2)

    def _build_scope_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.scope)
        self.target = ElidedLabel()
        self.target.setObjectName(q.ASSISTANT_TARGET)
        row.addWidget(self.target, 1)
        return row

    # -- the route (row 1) ------------------------------------------------------------------

    def show_route(self, route: ai_profile.Route, surface_subtitle: str = "") -> None:
        """Say what `route`'s conversation runs on (the chat's model, or what the route's own surface says, as
        Claude Code's terminal does: `surface_subtitle`), in the switch's tooltip (`route_note`); the switch names the route."""
        if surface_subtitle:
            subtitle = surface_subtitle
        else:
            subtitle = f"Chat with {route.model or 'no model chosen'}"
            if route.route == ai_profile.OLLAMA:
                host = app_settings.get_ollama_host(self.state.project)
                subtitle += f" · {host.split('://', 1)[-1].rstrip('/')}"
        self.route_note = subtitle
        self.ai_switch.set_note(subtitle)

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

    def _on_focus(self) -> None:
        """The slide, view or language changed: working out the offers (a lint of the slide, of every slide for the
        deck) waits for the selection to rest, so a held arrow key does not do it per row. The task buttons
        belong to the slide that was left: they do nothing until then (`_choose`), without greying out per click."""
        self._offers.clear()
        self._settle.start()

    def _choose(self, emit, value) -> None:
        if not self._settle.isActive():     # else a button of the slide that was left: its offers come afresh
            emit(value)

    def _settled(self) -> None:
        self._offers.clear()    # worked out for the state of now, not of a reader that came in meanwhile
        self.refresh_content()

    def _on_busy(self, _busy: bool = False) -> None:
        """A task started, moved on or ended: its pill and the buttons (none while it runs or waits) now, not a turn
        later."""
        self._offers.clear()
        self.refresh_actions()

    def on_typing(self) -> None:
        self._offers.clear()
        self._typing.start()

    def offers(self, scope: str) -> list[Bubble]:
        """The tasks that fit `scope` now, as task_bubbles.py finds them (kept until something changes)."""
        if scope not in self._offers:
            self._offers[scope] = deck_bubbles(self.app) if scope == DECK else bubbles(self.app)
        return self._offers[scope]

    def _task_buttons(self) -> list[QWidget]:
        return [w for i in range(self._actions.count()) if (w := self._actions.itemAt(i).widget()) is not self.all_actions]

    def refresh_content(self) -> None:
        self._settle.stop()
        self.target.set_full_text(self.target_text())
        self._seen = self._now()
        self.refresh_actions()

    def refresh_actions(self) -> None:
        """Row 3: the two most relevant tasks the route can run, then All actions…; row 4: the running pill."""
        tasks = self.tasks
        scope = self.scope.current()
        found = [] if tasks.occupied or self._blocked() else contextual(self.offers(scope), tasks)
        check = scope if not found and self.can_check(scope) else ""
        if (found, check) != (self.shown, self.check_shown):
            self.shown, self.check_shown = found, check
            while self._actions.count():
                widget = self._actions.takeAt(0).widget()
                if widget is not self.all_actions:
                    widget.setParent(None)
                    widget.deleteLater()
            for bubble in found:
                button = Button(bubble.label, "secondary", compact=True)
                button.clicked.connect(partial(self._choose, self.task_chosen.emit, bubble))
                self._actions.addWidget(button)
            if check:
                button = Button("Check readability" if check == SLIDE else "Check deck readability", "secondary",
                                compact=True)
                button.setToolTip("Measure whether the text and images can be read by an audience (no AI)")
                button.clicked.connect(partial(self._choose, self.check_chosen.emit, check))
                self._actions.addWidget(button)
        if self._actions.indexOf(self.all_actions) < 0:
            self._actions.addWidget(self.all_actions)
        # Tab: Focus, New conversation, the scope, the task buttons, All actions…, the pill's Open (buttons made later
        # would otherwise come last in the window).
        order = [self.scope.current_button(), *(self._actions.itemAt(i).widget() for i in range(self._actions.count())),
                 self.pill.open_button]
        for before, after in zip(order, order[1:]):
            QWidget.setTabOrder(before, after)
        card = tasks.card
        left = card is not None and card.hidden
        self.pill.setVisible(left or (card is None and tasks.busy))
        if left:
            self.pill.set_text(f"{card.title} · {PILL_WORDS[card.phase]}")
        elif card is None and tasks.busy:
            self.pill.set_text(tasks.describe())

    def can_check(self, scope: str) -> bool:
        """Whether the readability check has something to read: the deck open, or a slide in the Source view."""
        if scope == DECK:
            return self.state.deck is not None
        path = self.app.centre.path
        return path is not None and path.parent == self.state.project.slides_dir and slide_language.is_current_file(path)

    def target_text(self) -> str:
        """What the scope points at: the slide in the Source view (and whether it has edits that could not be saved), or the deck."""
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
        return text + (" · not saved" if centre.is_blocked(path) else "")

    def _now(self) -> tuple:
        centre = self.app.centre
        path = centre.path
        return path, path is not None and centre.is_blocked(path), selection_of(self.app) is not None

    def _look(self) -> None:
        """The file shown and whether it could not be saved have no signal: compare them now and then."""
        if not self._settle.isActive() and self._now() != self._seen:
            self.schedule()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.schedule()
        self._poll.start()

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        self._poll.stop()
