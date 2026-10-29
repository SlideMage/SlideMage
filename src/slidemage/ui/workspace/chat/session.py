# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""One chat conversation: its history and the agent thread that answers a request (which model answers is
ai_profile.resolve's: the view asks it for each request).

`ChatSession.start()` runs one `Agent` (ai/agent.py) on a worker thread; everything the agent reports
arrives as the `event` signal on the GUI thread, `Done` last. The history list is extended by the agent
in place and stays valid after Stop or an error, so the conversation goes on with the next request.

The session owns the captured route lease for the life of the run: taken in `start()`,
given back once the agent thread has really ended (after Done, or after the window closed), never
earlier.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal

from ....ai.agent import Agent
from ....ai.ai_profile import Route
from ....ai.agent_types import EDIT_ASK, AgentEvent, AgentMessage, Done
from ....ai.providers import ChatProvider
from ... import background
from .gui_workspace import GuiWorkspace


class _AgentThread(QThread):
    def __init__(self, agent: Agent, history: list[AgentMessage], request: str, scope: str) -> None:
        super().__init__()
        self.agent, self.history, self.request, self.scope = agent, history, request, scope

    def run(self) -> None:
        self.agent.run(self.history, self.request, self.scope)      # never raises; Done is its last event


class ChatSession(QObject):
    event = Signal(object)      # an AgentEvent, on the GUI thread

    def __init__(self, workspace: GuiWorkspace, app, parent: QObject | None = None) -> None:
        """`app` is the window that hands out route leases."""
        super().__init__(parent)
        self.workspace = workspace
        self._app = app
        self.history: list[AgentMessage] = []
        self.mode = EDIT_ASK
        self._agent: Agent | None = None
        self._thread: _AgentThread | None = None
        self._provider: ChatProvider | None = None
        self.route: Route | None = None     # of the request under way
        self._lease = None
        self._closed = False
        self.event.connect(self._watch)     # first in line: the thread is released before the chat hears Done

    @property
    def running(self) -> bool:
        return self._thread is not None

    def start(self, provider: ChatProvider, request: str, scope: str, route: Route) -> bool:
        """Answer `request` with `provider`, which is `route` resolved, on a thread of its own. False (the window
        says why) when the route is already leased by another task."""
        lease = self._app.acquire_route_task(route.route, "answering in the chat")
        if lease is None:
            return False
        self._lease = lease
        try:
            self.workspace.begin_request()
            self._agent = Agent(provider, self.workspace, on_event=self._emit, mode=self.mode)
            self._thread = _AgentThread(self._agent, self.history, request, scope)
            self._provider, self.route = provider, route
            self._thread.start()
        except BaseException:
            self._agent = self._thread = self._provider = None
            self._lease = None
            lease.release()
            raise
        return True

    def set_mode(self, mode: str) -> None:
        """"ask" / "auto"; a run under way takes it for its next edit."""
        self.mode = mode
        if self._agent is not None:
            self._agent.mode = mode

    def stop(self) -> None:
        """Stop the run; an edit that waits for the user is rejected."""
        if self._agent is not None:
            self._agent.stop()
        self.workspace.reject_pending()

    def new_chat(self) -> None:
        if not self.running:
            self.history.clear()

    def shutdown(self) -> None:
        """The window closes: end the run, release what waits for the GUI, and let the thread finish
        (background.stop_worker keeps it until it has, and the application waits for it at quit)."""
        self._closed = True
        self.workspace.close()
        thread, agent = self._thread, self._agent
        if thread is not None:
            background.stop_worker(thread, agent.stop, wait_ms=500, on_done=self._take_release())
        self._thread = self._agent = self._provider = None

    def _take_release(self):
        lease, self._lease = self._lease, None
        return lease.release if lease is not None else None

    def _emit(self, event: AgentEvent) -> None:
        """The agent's callback, on its thread."""
        if not self._closed:
            try:
                self.event.emit(event)
            except RuntimeError:       # this object is gone with the window
                pass

    def _watch(self, event: AgentEvent) -> None:
        if isinstance(event, Done) and self._thread is not None:
            thread = self._thread
            self._thread = self._agent = self._provider = None
            background.stop_worker(thread, wait_ms=500, on_done=self._take_release())
