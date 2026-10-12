"""The Chat view: the conversation with the agent of ai/agent.py about the focused slide or the whole deck.

The user asks in the composer (Enter sends, Shift+Enter breaks the line); the answer streams in as text,
with a card for every tool the agent runs and a diff card for every edit. In "Ask before edits" mode an
edit waits for Apply / Reject; in "Edit automatically" mode it is applied at once and its card offers
Undo. Stop ends a run. The conversation (history) lasts for the session; New chat starts afresh.

Threading is in session.py (the agent thread, `ChatSession.event` on the GUI thread) and
gui_workspace.py (what the agent may ask of the main window).
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget

from .... import app_settings
from ....ai import credentials, resolver
from ....ai.agent_context import SCOPE_DECK, SCOPE_SLIDE
from ....ai.agent_types import (
    EDIT_ASK,
    EDIT_AUTO,
    AgentEvent,
    Done,
    EditApplied,
    EditProposed,
    EditRejected,
    TextDelta,
    ToolFinished,
    ToolStarted,
)
from ....ai.providers import ANTHROPIC_FALLBACK_MODELS, ChatProvider, ProviderError
from ... import background
from ...kit import kit_qss as q
from ...kit.widgets import Button, Chip, DropdownButton, IconButton, PopoverMenu, SegmentedControl, Surface, caption, clear_layout
from ..state import WorkspaceState
from .cards import AssistantText, DiffCard, Notice, Status, ToolCard, UserBubble, suggestion_button, text_label
from .gui_workspace import EditAsk, GuiWorkspace
from .session import ChatSession, LocalModels, current_route

MODE_SETTING = "chat_edit_mode"
MODES = ((EDIT_ASK, "Ask before edits", "each change is shown first"),
         (EDIT_AUTO, "Edit automatically", "applied at once, with Undo"))
SCOPES = ((SCOPE_SLIDE, "This slide"), (SCOPE_DECK, "Whole deck"))
SUGGESTIONS = {
    SCOPE_SLIDE: ("Make this slide more concise", "Suggest a better title", "Add speaker notes to this slide"),
    SCOPE_DECK: ("Summarise the structure of this deck", "Which slides have LaTeX errors?",
                 "Add a slide after the current one"),
}
FIX_SUGGESTION = "Fix the LaTeX errors on this slide"
COMPOSER_LINES = (2, 6)


class Composer(QPlainTextEdit):
    """The message box: Enter sends, Shift+Enter breaks the line; grows with its text."""

    submitted = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.document().documentLayout().documentSizeChanged.connect(lambda _size: self._fit())
        self._fit()

    def _fit(self) -> None:
        line = self.fontMetrics().lineSpacing()
        lines = min(max(round(self.document().size().height()), COMPOSER_LINES[0]), COMPOSER_LINES[1])
        self.setFixedHeight(lines * line + 18)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.submitted.emit()
        else:
            super().keyPressEvent(event)


class _Column(Surface):
    """The message list's content: no minimum height of its own. Word-wrapped labels would report
    the height they need at their narrowest, which the scroll area would then keep as empty space."""

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 0)


class ChatView(Surface):
    def __init__(self, app, state: WorkspaceState) -> None:
        super().__init__()
        self.app = app
        self.state = state
        self.workspace = GuiWorkspace(app)
        self.session = ChatSession(self.workspace, app, self)
        mode = app_settings.get(state.project, MODE_SETTING)
        self.session.set_mode(mode if mode in (EDIT_ASK, EDIT_AUTO) else EDIT_ASK)
        self._text: Optional[AssistantText] = None      # the answer being streamed
        self._tools: dict[str, ToolCard] = {}
        self._diffs: dict[str, DiffCard] = {}
        self._asking: dict[DiffCard, EditAsk] = {}      # the cards whose Apply / Reject the agent waits for
        self._stick = True                             # the list follows the newest content
        self._local_models: Optional[list[str]] = None  # the tool-capable Ollama models; None until Ollama has answered
        self._local_loader: Optional[LocalModels] = None  # the question to Ollama that is out, if any

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        top = QHBoxLayout()
        self.scope = SegmentedControl(SCOPES, current=SCOPE_SLIDE)
        self.scope.changed.connect(lambda _scope: self._fill_empty())
        top.addWidget(self.scope)
        top.addStretch(1)
        self.new_button = IconButton("add_comment", "New chat: forget the conversation so far")
        self.new_button.clicked.connect(lambda: self.new_chat())
        top.addWidget(self.new_button)
        layout.addLayout(top)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setObjectName(q.SURFACE)
        self._scroll.viewport().setObjectName(q.SURFACE)
        content = _Column()
        self._messages = QVBoxLayout(content)
        self._messages.setContentsMargins(0, 0, 4, 0)
        self._messages.setSpacing(10)
        self._empty = Surface()
        self._ideas = QVBoxLayout(self._empty)
        self._ideas.setContentsMargins(0, 0, 0, 0)
        self._ideas.setSpacing(6)
        self._messages.addWidget(self._empty)
        self.status = Status()
        self._messages.addWidget(self.status)
        self._messages.addStretch(1)
        self._scroll.setWidget(content)
        bar = self._scroll.verticalScrollBar()
        bar.rangeChanged.connect(lambda _low, high: bar.setValue(high) if self._stick else None)
        bar.valueChanged.connect(lambda value: setattr(self, "_stick", value >= bar.maximum() - 8))
        layout.addWidget(self._scroll, 1)

        self.composer = Composer()
        self.composer.submitted.connect(self.send)
        layout.addWidget(self.composer)
        controls = QHBoxLayout()
        controls.setSpacing(6)
        self.mode_picker = DropdownButton(q.PANEL_PICKER)
        self.mode_picker.clicked.connect(self._open_mode_menu)
        controls.addWidget(self.mode_picker)
        controls.addStretch(1)
        self.send_button = Button("Send", "primary", compact=True)
        self.send_button.clicked.connect(lambda: self.send())
        self.stop_button = Button("Stop", "secondary", compact=True)
        self.stop_button.clicked.connect(lambda: self.stop())
        controls.addWidget(self.send_button)
        controls.addWidget(self.stop_button)
        layout.addLayout(controls)
        model = QHBoxLayout()
        self.route_chip = Chip("", "muted", "smart_toy")
        self.route_chip.clicked.connect(self._open_route_menu)
        model.addWidget(self.route_chip)
        model.addStretch(1)
        layout.addLayout(model)
        self.route_note = caption("", "warning")
        layout.addWidget(self.route_note)

        self.session.event.connect(self._on_event)
        self.workspace.edit_asked.connect(self._on_edit_asked)
        state.deck_changed.connect(self._on_deck_changed)
        state.lint_errors_changed.connect(lambda _count: self._fill_empty())
        self._set_running(False)
        self._fill_empty()
        self._show_mode()
        self.refresh_route()
        self._load_local_models()
        self._scroll.viewport().installEventFilter(self)

    # -- the message list ---------------------------------------------------------------

    def _add(self, widget: QWidget) -> None:
        self._messages.insertWidget(self._messages.count() - 2, widget)     # above the status and the stretch

    def _fill_empty(self) -> None:
        """The first screen: what to ask, as buttons. Gone once the conversation has started."""
        clear_layout(self._ideas)
        box, scope = self._ideas, self.scope.current()
        self._suggestion_widgets = [caption("Describe a change to this slide, or try:" if scope == SCOPE_SLIDE
                                            else "Ask about the whole deck, or try:")]
        ideas = list(SUGGESTIONS[scope])
        if scope == SCOPE_SLIDE and self.state.lint_errors:
            ideas.insert(0, FIX_SUGGESTION)
        for idea in ideas:
            button = suggestion_button(idea)
            button.clicked.connect(lambda _checked=False, text=idea: self.ask(text))
            self._suggestion_widgets.append(button)
        for widget in self._suggestion_widgets:
            box.addWidget(widget)
        self._suggestions = ideas
        self._suggestion_picker = DropdownButton(q.PANEL_PICKER)
        self._suggestion_picker.set_text("Suggestions")
        self._suggestion_picker.clicked.connect(self._open_suggestions)
        box.addWidget(self._suggestion_picker)
        self._fit_suggestions()

    def eventFilter(self, watched, event) -> bool:
        if watched is self._scroll.viewport() and event.type() == QEvent.Type.Resize:
            self._fit_suggestions()
        return super().eventFilter(watched, event)

    def _fit_suggestions(self) -> None:
        width = self._scroll.viewport().width() - self._messages.contentsMargins().right()
        height = sum(widget.heightForWidth(width) if widget.hasHeightForWidth() else widget.sizeHint().height()
                     for widget in self._suggestion_widgets)
        height += self._ideas.spacing() * (len(self._suggestion_widgets) - 1)
        compact = height > self._scroll.viewport().height()
        for widget in self._suggestion_widgets:
            widget.setVisible(not compact)
        self._suggestion_picker.setVisible(compact)

    def _open_suggestions(self) -> None:
        menu = PopoverMenu(self, min_width=270)
        for idea in self._suggestions:
            menu.add_item(idea, idea)
        menu.triggered.connect(self.ask)
        menu.closed.connect(lambda: self._suggestion_picker.set_active(False))
        menu.closed.connect(menu.deleteLater)
        self._suggestion_picker.set_active(True)
        menu.popup_below(self._suggestion_picker)

    def _begin_conversation(self) -> None:
        self._empty.hide()

    def _start_turn(self, label: str) -> None:
        self._text = None
        self._add(text_label(label, q.CHAT_MODEL))

    def new_chat(self) -> None:
        if self.session.running:
            return
        self.session.new_chat()
        self._text, self._stick = None, True
        self._tools.clear()
        self._diffs.clear()
        self._asking.clear()
        while self._messages.count() > 3:
            widget = self._messages.takeAt(1).widget()
            widget.setParent(None)
            widget.deleteLater()
        self._empty.show()
        self._fill_empty()

    # -- asking ------------------------------------------------------------------------------

    def ask(self, text: str, scope: str = "") -> None:
        """Put `text` to the agent now (a suggestion, the command palette); while it is busy the text
        waits in the message box instead."""
        if self.session.running:
            self.composer.setPlainText(text)
            return
        if scope:
            self.scope.set_current(scope)
            self._fill_empty()
        self.send(text)

    def focus_composer(self, scope: str) -> None:
        """Ready the message box for a question about `scope`."""
        if not self.session.running:
            self.scope.set_current(scope)
            self._fill_empty()
        self.composer.setFocus()

    def send(self, text: str | None = None) -> None:
        text = (self.composer.toPlainText() if text is None else text).strip()
        if not text or self.session.running:
            return
        provider = self._provider_for_send()
        if provider is None or not self.session.start(provider, text, self.scope.current()):
            if self.composer.toPlainText().strip() != text:
                self.composer.setPlainText(text)        # a suggestion that could not be sent is kept
            return
        self.composer.clear()
        self._begin_conversation()
        self._add(UserBubble(text))
        self._start_turn(provider.label)
        self._stick = True
        self._set_running(True)
        self.status.run()

    def _provider_for_send(self) -> Optional[ChatProvider]:
        """The model that answers the next request; None (and the reason shown) when it cannot be used now."""
        route = current_route(self.state.project)
        if route.problem:       # the note under the message box says why
            return None
        try:
            return resolver.provider_for(route.spec)
        except ProviderError as exc:
            self._add(Notice(str(exc), "error"))
            return None

    def stop(self) -> None:
        self.session.stop()
        self._reject_asks()         # the edit cards stop waiting now, not when the run has ended

    def shutdown(self) -> None:
        self.status.stop()
        self.session.shutdown()

    def _on_deck_changed(self, _deck) -> None:
        if self.session.running:
            self.stop()

    def _set_running(self, running: bool) -> None:
        self.send_button.setVisible(not running)
        self.stop_button.setVisible(running)
        self.new_button.setEnabled(not running)
        self.scope.setEnabled(not running)
        self.route_chip.setEnabled(not running)         # the model of a run under way does not change
        if not running:
            self.status.stop()

    # -- what the agent reports --------------------------------------------------------------

    def _on_event(self, event: AgentEvent) -> None:
        if isinstance(event, TextDelta):
            if self._text is None:
                self._text = AssistantText()
                self._add(self._text)
            self._text.append(event.text)
        elif isinstance(event, ToolStarted):
            self._text = None
            card = self._tools[event.call.id] = ToolCard(event.call)
            self._add(card)
            self.status.run(f"Running {event.call.name}")
        elif isinstance(event, ToolFinished):
            if (card := self._tools.get(event.call.id)) is not None:
                card.finish(event.result)
            self.status.run("Thinking")
        elif isinstance(event, EditProposed):
            self._text = None
            self._new_diff(event.call_id, event.path, event.before, event.after, event.note)
        elif isinstance(event, EditApplied):
            self._edit_applied(event)
        elif isinstance(event, EditRejected):
            if (card := self._diffs.get(event.call_id)) is not None:
                card.rejected()
                self._asking.pop(card, None)
            self.status.run("Thinking")
        elif isinstance(event, Done):
            self._done(event)

    def _title(self, path) -> str:
        try:
            return path.relative_to(self.workspace.root).as_posix()
        except ValueError:
            return path.name

    def _new_diff(self, key: str, path, before: str, after: str, note: str = "") -> DiffCard:
        card = self._diffs[key] = DiffCard(self._title(path), before, after, note)
        card.apply_clicked.connect(lambda: self._answer(card, True))
        card.reject_clicked.connect(lambda: self._answer(card, False))
        self._add(card)
        return card

    def _edit_applied(self, event: EditApplied) -> None:
        card = self._diffs.get(event.call_id) or self._new_diff(event.call_id, event.path, event.before, event.after, event.note)
        card.applied(event.via_buffer, event.undoable, new_file=not event.before and not event.via_buffer)
        card.undo_clicked.connect(lambda: self._undo(card, event))
        self.status.run("Thinking")

    def _undo(self, card: DiffCard, event: EditApplied) -> None:
        if self.session.running:
            card.undo_failed("Wait for the answer to finish, or press Stop, before undoing.")
            return
        problem = self.workspace.undo_in_buffer(event)
        if problem:
            card.undo_failed(problem)
        else:
            card.undone()

    def _on_edit_asked(self, ask: EditAsk) -> None:
        """confirm_edit is waiting: the card of that tool call asks for Apply / Reject."""
        card = self._diffs.get(ask.call_id) or self._new_diff(ask.call_id, ask.path, ask.before, ask.after)
        card.ask()
        self._asking[card] = ask
        self.status.run("Waiting for your answer")

    def _answer(self, card: DiffCard, approved: bool) -> None:
        if (ask := self._asking.pop(card, None)) is not None:
            ask.answer(approved)
            if approved:
                card.working()      # its buttons go now; EditApplied (or EditRejected) says how it ended
            else:
                card.rejected()
        self.status.run("Thinking")

    def _reject_asks(self) -> None:
        for card in self._asking:
            card.rejected()
        self._asking.clear()

    def _done(self, event: Done) -> None:
        self._set_running(False)
        self._text = None
        self._reject_asks()
        if event.reason == "stopped":
            self._add(Notice("Stopped."))
        elif event.reason == "max_turns":
            self._add(Notice(event.message, "warning"))
        elif event.reason == "error":
            self._add(Notice(event.message or "The request failed.", "error"))

    # -- permission and model ---------------------------------------------------------------

    def refresh_route(self) -> None:
        """The model that answers, named under the message box (also after Settings changed it)."""
        route = current_route(self.state.project)
        self.route_chip.set_text(route.label)
        self.route_chip.set_tone("warning" if route.problem else "muted")
        self.route_chip.setToolTip("The model that answers. Click to choose another (Settings → AI models → Chat assistant).")
        self.route_note.setText(route.problem)
        self.route_note.setVisible(bool(route.problem))

    def _open_mode_menu(self) -> None:
        menu = PopoverMenu(self, min_width=250)
        for key, text, meta in MODES:
            menu.add_item(key, text, meta=meta, icon="check" if key == self.session.mode else "")
        menu.triggered.connect(self._set_mode)
        menu.closed.connect(lambda: self.mode_picker.set_active(False))
        menu.closed.connect(menu.deleteLater)
        self.mode_picker.set_active(True)
        menu.popup_below(self.mode_picker)

    def _set_mode(self, mode: str) -> None:
        self.session.set_mode(mode)
        app_settings.set(self.state.project, MODE_SETTING, mode)
        self._show_mode()

    def _show_mode(self) -> None:
        self.mode_picker.set_text(next(text for key, text, _meta in MODES if key == self.session.mode))

    def _load_local_models(self) -> None:
        """Ask Ollama which installed models can call tools (one question at a time)."""
        if self._local_loader is not None:
            return
        self._local_loader = loader = LocalModels()
        loader.loaded.connect(self._on_local_models)
        background.start_detached(loader)

    def _on_local_models(self, names: list[str]) -> None:
        self._local_models, self._local_loader = names, None

    def _open_route_menu(self) -> None:
        """The cloud models on offer, greyed with the reason while "Local AI only" is on or no key is set,
        and the local models that can call tools (as of the last time Ollama was asked: when the menu
        opens, for the next time)."""
        current = current_route(self.state.project).spec
        self._load_local_models()
        local_only, has_key = resolver.local_only(), credentials.get_api_key() is not None
        menu = PopoverMenu(self, min_width=270)
        menu.add_header("Cloud")
        for model in ANTHROPIC_FALLBACK_MODELS:
            spec = f"anthropic:{model}"
            menu.add_item(spec, model, icon="check" if spec == current else "", enabled=has_key and not local_only,
                          meta="Local AI only is on" if local_only else "" if has_key else "needs an API key")
        menu.add_header("Local")
        known = self._local_models
        local = list(known or [])
        if current.startswith("ollama:") and current.removeprefix("ollama:") not in local:
            local.insert(0, current.removeprefix("ollama:"))      # the chosen one stays visible, with a reason
        for model in local:
            spec = f"ollama:{model}"
            menu.add_item(spec, model, icon="check" if spec == current else "",
                          meta="not installed, or cannot call tools" if known is not None and model not in known else "")
        if not local:
            menu.add_item("", "Looking for local models…" if known is None else "No installed model can call tools",
                          enabled=False)
        menu.add_separator()
        menu.add_item("settings", "More in Settings…")
        menu.triggered.connect(self._set_route)
        menu.closed.connect(menu.deleteLater)
        menu.popup_below(self.route_chip)

    def _set_route(self, key: str) -> None:
        if key == "settings":
            self.app.commands.run("settings", self.app)
        elif key != current_route(self.state.project).spec:
            app_settings.set(self.state.project, app_settings.MODEL_SETTINGS["chat"], key)
        self.refresh_route()
