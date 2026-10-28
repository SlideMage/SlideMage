# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Public operations supplied to a plugin conversation surface."""
from __future__ import annotations

from pathlib import Path

from .... import plugin_api
from ....ai import ai_profile, tasks
from .. import attachments
from ..task_bubbles import bubbles
from ..terminal.sync import DiskSync
from .gui_workspace import GuiWorkspace


class ToolWorkspace:
    """Opaque handle used only with Host.ai_tools."""

    def __init__(self, window) -> None:
        self._workspace = GuiWorkspace(window)

    def close(self) -> None:
        self._workspace.close()


class ChatSurfaceContext:
    def __init__(self, app, state, scope, tasks_runner) -> None:
        self._app, self._state, self._scope, self._tasks = app, state, scope, tasks_runner
        self._sync = DiskSync(app, state.project.root)
        self._workspace = ToolWorkspace(app)
        self._workspace._workspace.translate = self.translate_slide
        self._workspace._workspace.widen = self._switch_to_deck

    @property
    def project_root(self) -> Path:
        return self._state.project.root

    def selected_route(self, route_id: str, task: str, choice: str = ""):
        return ai_profile.route_for(self._state.project, route_id, task, choice)

    def focus_details(self):
        state, centre = self._state, self._app.centre
        slide = centre.path
        deck = state.deck.path if state.deck is not None and not state.deck.is_test_deck else None
        return plugin_api.ChatFocus(state.focused_slide, slide, deck, state.view, state.language,
                                    slide is not None and centre.is_dirty(slide))

    def build_tools(self, host, scope, cancel):
        workspace = self._workspace._workspace
        def build():
            workspace.begin_request()
            return host.ai_tools(scope, focus_slide=workspace.context().path, mode="auto", cancel=cancel,
                                 workspace=self._workspace)
        return workspace.on_gui(build, None)

    def scope(self) -> str:
        return self._scope.current()

    def set_scope(self, value: str) -> bool:
        if value not in ("slide", "deck"):
            raise ValueError(value)
        if value == "deck" and self._state.deck is None:
            return False
        self._scope.set_current(value)
        self._scope.changed.emit(value)
        return True

    def on_scope_changed(self, callback) -> None:
        self._scope.changed.connect(callback)

    def open_ai_setup(self) -> None:
        self._app.ai_route.open_setup()

    def attach_file(self, path: Path) -> str | None:
        return attachments.place_file(self._state.project, path, dash_spaces=True)

    def attach_image(self, image) -> str | None:
        return attachments.save_image(self._state.project, image)

    def apply_external_edits(self, changes) -> None:
        self._sync._apply(changes)

    def tool_workspace(self) -> ToolWorkspace:
        return self._workspace

    def translate_slide(self, path: Path) -> str:
        self._workspace._workspace.show_slide(path)
        bubble = next((b for b in bubbles(self._app) if b.task is tasks.TRANSLATE), None)
        if bubble is None:
            return f"{path.name} has a translation already, or is not EN or DE: there is nothing to translate."
        if self._tasks.occupied:
            return "SlideMage is busy with another task; ask the user to try again when its card is done."
        if reason := self._tasks.refusal(bubble.task):
            return reason
        self._tasks.start(bubble.task, bubble.paths, bubble.label)
        return f"SlideMage is translating it ({bubble.label}); the task card in the assistant shows the proposed slide."

    def _switch_to_deck(self) -> str:
        if not self.set_scope("deck"):
            return "No deck is open in SlideMage: ask the user to open one."
        return "SlideMage is in Deck Mode now: go on with the request."

    def close(self) -> None:
        self._workspace.close()

