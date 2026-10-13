"""The agent's window into the main window (UI_REDESIGN_PLAN.md, step 10b): the `Workspace` of ai/workspace.py
answered from the real editor buffers, dialogs and job panel.

Threading. The agent loop runs on its own thread and calls every method here on that thread, but widgets
may only be touched on the GUI thread. `on_gui(function)` hands a function to the GUI thread through a
queued signal and waits for its result in short steps, so that closing the window can release a call
that would otherwise never be answered (a blocking queued connection would deadlock there). Calls that
wait for the user -- `confirm_edit`, `confirm_cloud`, a compile -- do their waiting on the agent thread:
the GUI thread only shows the question (`EditAsk`, a dialog) and goes on with its event loop.
Called on the GUI thread itself (the chat's Undo button) a method simply runs.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal, Slot

from .... import compiler, deck_editor
from ....ai.agent_types import EditApplied
from ....ai.providers import ChatProvider
from ....ai.tools import undo_edit
from ....ai.workspace import Workspace, WorkspaceContext
from ....compile_status import DONE
from ....deck_scan import Deck
from ....slide_language import bare_id
from .. import compile_actions
from ...ai_models import confirm_cloud_request

POLL_S = 0.05      # how often a waiting call looks whether the window has closed
CLOUD_SENDS = ("the slide you are working on, the project files the model reads and rendered previews "
               "of slides")


class EditAsk:
    """An edit waiting for Apply or Reject; answered on the GUI thread, awaited on the agent's."""

    def __init__(self, call_id: str, path: Path, before: str, after: str) -> None:
        self.call_id, self.path, self.before, self.after = call_id, path, before, after
        self.approved = False
        self._answered = threading.Event()

    @property
    def answered(self) -> bool:
        return self._answered.is_set()

    def answer(self, approved: bool) -> None:
        if not self._answered.is_set():
            self.approved = approved
            self._answered.set()

    def wait(self, timeout: float) -> bool:
        return self._answered.wait(timeout)


class _Job:
    def __init__(self, function: Callable[[], Any]) -> None:
        self.function = function
        self.done = threading.Event()
        self.result: Any = None
        self.error: Exception | None = None

    def run(self) -> None:
        try:
            self.result = self.function()
        except Exception as exc:  # noqa: BLE001 -- handed back to the thread that asked
            self.error = exc
        finally:
            self.done.set()


class _Bridge(QObject):
    """Lives on the GUI thread: runs the jobs the agent thread queues, and tells the chat about asks."""

    job = Signal(object)
    edit_asked = Signal(object)    # an EditAsk

    def __init__(self) -> None:
        super().__init__()
        self.job.connect(self._run, Qt.ConnectionType.QueuedConnection)

    @Slot(object)
    def _run(self, job: _Job) -> None:
        job.run()


class GuiWorkspace(Workspace):
    def __init__(self, window) -> None:
        """`window` is the main window: its state, centre column, slide list and compile flow."""
        super().__init__(window.project)
        self.window = window
        self._bridge = _Bridge()
        self.edit_asked = self._bridge.edit_asked
        self._gui_thread = threading.get_ident()
        self._closed = False
        self._stopping = False                 # Stop was pressed: no edit is asked about until the next request
        self._pending: EditAsk | None = None   # the tools run one after the other: at most one edit waits
        self.translate: Callable[[Path], str] | None = None    # the Claude Code tab's Translate bubble, if any
        self.widen: Callable[[], str] | None = None            # its Slide / Deck switch, set to Deck

    # -- crossing threads ----------------------------------------------------------------

    def on_gui(self, function: Callable[[], Any], default: Any = None) -> Any:
        """Run `function()` on the GUI thread and return what it returns (an exception it raises is
        raised here); `default` once the window is closing."""
        if threading.get_ident() == self._gui_thread:
            return function()
        if self._closed:
            return default
        job = _Job(function)
        try:
            self._bridge.job.emit(job)
        except RuntimeError:       # the bridge is gone with the window
            return default
        while not job.done.wait(POLL_S):
            if self._closed:
                return default
        if job.error is not None:
            raise job.error
        return job.result

    def close(self) -> None:
        """The window is closing: no more questions, and every call that waits returns."""
        self._closed = True
        self.reject_pending()

    def reject_pending(self) -> None:
        """Stop pressed (or closing): the edit that waits for an answer is rejected, and so is any that is
        asked about before the next request."""
        self._stopping = True
        if self._pending is not None:
            self._pending.answer(False)
            self._pending = None

    # -- the focus ----------------------------------------------------------------------------

    def begin_request(self) -> None:
        """Take the focus for the request about to start (GUI thread)."""
        self._stopping = False
        window, state = self.window, self.window.state
        self._context = WorkspaceContext(
            deck=state.deck, slide_id=state.focused_slide, path=window.centre.path, view=state.view,
            language=state.language, footer_timestamp=state.footer_timestamp)

    # -- editor buffers ---------------------------------------------------------------------

    def _local(self, path: Path) -> Path:
        """`path` as the application spells it (the project folder is not always resolved)."""
        try:
            return self.window.project.root / path.relative_to(self.root)
        except ValueError:
            return path

    def _file(self, path: Path):
        return self.window.centre.source.file_for(self._local(path))

    def is_open(self, path: Path) -> bool:
        return self.on_gui(lambda: self._file(path) is not None, False)

    def is_dirty(self, path: Path) -> bool:
        return self.on_gui(lambda: (file := self._file(path)) is not None and file.dirty, False)

    def buffer_text(self, path: Path) -> str:
        return self.buffer_snapshot(path)[0]

    def buffer_snapshot(self, path: Path) -> tuple[str, bool]:
        def read() -> tuple[str, bool]:
            file = self._file(path)
            if file is None:
                raise FileNotFoundError(path)
            if not file.dirty:
                self.window.centre.disk_changed(self._local(path))
            return file.editor.text(), file.dirty

        return self.on_gui(read, ("", False))

    def apply_to_buffer(self, path: Path, expected_text: str, new_text: str) -> str | None:
        def apply() -> str | None:
            file = self._file(path)
            if file is None:
                return "it is not open for editing"
            if file.editor.is_read_only():
                return "it is read-only (a frozen version)"
            if file.editor.text() != expected_text:
                return "it changed while the edit waited for your answer"
            file.editor.patch_text(new_text)     # one undo step; cursor and scroll position stay
            return None

        return self.on_gui(apply, "the window is closing")

    def undo_in_buffer(self, applied: EditApplied) -> str:
        """Undo for the chat's card (GUI thread). "" when done, else why not: an edit made in the
        editor is taken back with the editor's own undo, so the file is clean again when nothing else
        was changed; anything else goes through `ai.tools.undo_edit`."""
        file = self._file(applied.path) if applied.via_buffer else None
        if file is None:
            return undo_edit(self, applied)
        editor = file.editor
        if editor.text() != applied.after:
            return f"{applied.path.name} has changed since, so the edit cannot be undone automatically."
        editor.undo()
        if editor.text() != applied.before:     # the edit was not the last thing in the undo history
            editor.redo()
            return f"{applied.path.name} cannot be undone from the chat any more; use Ctrl+Z in the editor."
        return ""

    # -- asking and telling the user ---------------------------------------------------------

    def confirm_edit(self, call_id: str, path: Path, before: str, after: str) -> bool:
        ask = EditAsk(call_id, path, before, after)

        def show() -> None:
            if self._stopping:      # Stop came while this edit was on its way to the window
                ask.answer(False)
                return
            self._pending = ask
            self.edit_asked.emit(ask)

        self.on_gui(show)
        while not ask.wait(POLL_S):
            if self._closed:
                return False
        return ask.approved

    def confirm_cloud(self, provider: ChatProvider) -> bool:
        return self.on_gui(lambda: confirm_cloud_request(self.window, self.project, provider, CLOUD_SENDS), False)

    def file_changed(self, path: Path, previous_text: str | None) -> None:
        self.on_gui(lambda: self._show_written(self._local(path)))

    def review_changed(self) -> None:
        self.on_gui(self.window.refresh_ai_review)

    def show_slide(self, path: Path) -> None:
        def show() -> None:
            window, slide_id = self.window, bare_id(path.name)
            deck = window.state.deck
            if deck is not None and any(call.id == slide_id for call in deck_editor.parse_slide_calls(deck)):
                window.state.set_focused_slide(slide_id)     # as "Go to slide": the preview follows
            else:
                window.open_slide_editor(self._local(path))

        self.on_gui(show)

    def translate_slide(self, path: Path) -> str:
        return self.on_gui(lambda: self.translate(self._local(path)) if self.translate else
                           "SlideMage cannot translate now: the Claude Code tab has no task runner.", "")

    def switch_to_deck_mode(self) -> str:
        return self.on_gui(lambda: self.widen() if self.widen else "There is no scope switch to set.", "")

    def _show_written(self, path: Path) -> None:
        """Bring the views up to date with a file the agent wrote on disk."""
        window = self.window
        if any(deck.path == path for deck in window.decks):
            window.centre.sync_source(path)
            window.after_deck_edit(path, f"The chat changed {path.name}")
        else:
            window.centre.file_written(path)
            window.slide_list.rebuild()      # lint dots, stale previews
            window.side_panels.refresh()

    # -- compiling -------------------------------------------------------------------------

    def compile_deck(
        self, deck: Deck, kind: str, cancel: compiler.CancelToken, log: Callable[[str], None],
    ) -> dict[str, bool]:
        """The window's own compile flow: its prompts, its job panel and Log drawer. Returns when the
        run has settled; the chat's Stop ends it (without the window's "Stop creation?" question)."""
        window = self.window
        settled = threading.Event()
        outcome: dict[str, bool] = {}

        def on_settled(run) -> None:
            outcome.update({name: row.state == DONE for name, row in run.rows.items()})
            settled.set()

        def forward(line: str) -> None:
            log(line)

        def start() -> bool:
            window.compile.settled.connect(on_settled)
            window.compile.log.connect(forward)
            return compile_actions.compile_jobs(window, compiler.build_jobs(deck, kind))

        def detach() -> None:
            window.compile.settled.disconnect(on_settled)
            window.compile.log.disconnect(forward)

        started = False
        try:
            started = self.on_gui(start, False)
            stopping = False
            while started and not settled.wait(POLL_S):
                if self._closed:
                    return {}
                if cancel.is_set() and not stopping:
                    stopping = True
                    self.on_gui(lambda: compile_actions.stop_now(window))
        finally:
            if not self._closed:
                self.on_gui(detach)
        return outcome
