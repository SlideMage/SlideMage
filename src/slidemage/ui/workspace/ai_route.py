# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Moving the AI switch (workspace v6 handoff, section 2): `request(mode, conn)` is the one way the route of all
AI work changes in the running app (the switch, the palette, AI setup's cloud connection).

The checks run in this order and at most one popover shows for a request:

1. AI work is running: the busy popover. "Stop and switch" cancels what can be cancelled (a file write that has
   started finishes first), the switch reads "stopping…", and when everything has ended the request starts over,
   so the checks below still apply. If the work ends by itself while the popover is open, it says so.
2. Leaving a route whose conversation surface (the terminal of Claude Code) is alive: the session popover.
3. To Cloud while the project setting is Local: the warning, every time.
4. To Cloud for the first time in this project: asked once (`cloud_seen`).
5. Otherwise the route is committed: `WorkspaceState.set_ai_route` tells every label, picker and conversation, and a
   toast and the switch's announcement say so. A request sends nothing.

The "running" word of the switch follows the same query (`window.running_ai_work`).
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication

from ...ai import ai_profile, routes
from . import ai_popups
from .ai_popups import DecisionPopover, PopupSpec

LOCAL, CLOUD = ai_profile.LOCAL, ai_profile.CLOUD
POLL_MS = 200           # how often the work is looked at while a popover waits for it, or while stopping
RUNNING_MS = 1000       # and for the switch's "running"
LOCAL_AGAIN = "All AI tasks use Local · Ollama again. Your Ollama models are restored."


class AiRoute(QObject):
    def __init__(self, window) -> None:
        super().__init__(window)
        self._window, self._state = window, window.state
        self._target: tuple[str, str] | None = None     # (mode, connection) a request waits to commit
        self._from_switch = False                       # the request came from the keyboard on the switch
        self._popover: DecisionPopover | None = None
        self.setup = None                               # AI setup (ai_setup.py), created on first use
        self._stopping = False
        self._watch = QTimer(self)
        self._watch.setInterval(POLL_MS)
        self._watch.timeout.connect(self._on_watch)
        self._running = QTimer(self)
        self._running.setInterval(RUNNING_MS)
        self._running.timeout.connect(self._show_running)
        self._running.start()

    @property
    def switch(self):
        return self._window.ai_switch

    @property
    def popover_kind(self) -> str:
        """Which popover is up ("busy", "finished", "session", "policy", "first"), or ""."""
        return self._popover.spec.kind if self._popover is not None and self._popover.isVisible() else ""

    @property
    def stopping(self) -> bool:
        return self._stopping

    # -- the request ---------------------------------------------------------------------------

    def request(self, mode: str, conn: str | None = None) -> None:
        """Ask for `mode` (and, for Cloud, the connection `conn`, else the one in use)."""
        project = self._window.project
        current = ai_profile.cloud_conn(project)
        conn = conn or current
        if not routes.on_side(mode == LOCAL):         # that side has no route installed: its half is disabled
            return
        if self._stopping or (mode == self._state.ai_mode and (mode == LOCAL or conn == current)):
            return
        self._close_popover()
        focus = QApplication.focusWidget()
        self._from_switch = focus is not None and self.switch.segments.isAncestorOf(focus)
        self._target = (mode, conn)
        self._advance()

    def _advance(self) -> None:
        """The checks, in order: the first that has something to say shows its popover; none, and it commits."""
        mode, conn = self._target
        state, project = self._state, self._window.project
        if work := self._window.running_ai_work():
            return self._show(ai_popups.busy_spec(work, self._cancel, self._stop_and_switch))
        surface = self._window.assistant.surface_for(state.ai_route)      # a route with its own conversation surface
        if surface is not None and (mode == LOCAL or conn != state.ai_route) and getattr(surface, "session_live", True):
            route = routes.get(state.ai_route)
            return self._show(ai_popups.session_spec(self._cancel, self._end_session,
                                                     route.service if route else state.ai_route))
        if mode == CLOUD and state.ai_mode == LOCAL:
            if ai_profile.policy(project) == LOCAL:
                return self._show(ai_popups.policy_spec(conn, self._cancel, self._commit, self._change_setting))
            if not ai_profile.cloud_seen(project):
                return self._show(ai_popups.first_use_spec(conn, self._cancel, self._commit))
        self._commit()

    def _commit(self) -> None:
        mode, conn = self._target
        self._target = None
        self._close_popover()
        project = self._window.project
        if mode == CLOUD:
            ai_profile.mark_cloud_seen(project)      # the popovers above were the question
        self._state.set_ai_route(mode, conn)
        route = ai_profile.Route(self._state.ai_route, ai_profile.CHAT)
        message = LOCAL_AGAIN if mode == LOCAL and route.route == ai_profile.OLLAMA else f"All AI tasks now use {route.name}"
        self._window.toast.show_message(message)
        self.switch.announce(mode)
        self.switch.refresh()
        if self._from_switch:           # a request that began on the switch ends there, on the segment selected now
            self._from_switch = False
            self.switch.segments.focus_current()

    # -- the popovers --------------------------------------------------------------------------

    def _show(self, spec: PopupSpec) -> None:
        if self.setup is not None:
            self.setup.close()
        if self._popover is None:
            self._popover = DecisionPopover(self._window)
        popover = self._popover
        popover.show_spec(spec)
        if not popover.isVisible():
            popover.popup_below(self.switch)
        self._sync_watch()

    def _close_popover(self) -> None:
        if self._popover is not None:
            self._popover.close()
        self._sync_watch()

    def _cancel(self) -> None:
        self._target = None
        self._sync_watch()

    def _end_session(self) -> None:
        self._window.assistant.surface_for(self._state.ai_route).stop()
        self._advance()

    def _change_setting(self) -> None:
        self._cancel()
        self.open_setup()

    # -- stopping --------------------------------------------------------------------------------

    def _stop_and_switch(self) -> None:
        for work in self._window.running_ai_work():
            if work.stop is not None:
                work.stop()
        self._stopping = True
        self.switch.set_stopping(True)
        self._sync_watch()
        self._on_watch()

    def _sync_watch(self) -> None:
        if self._stopping or self.popover_kind in ("busy", "finished"):
            self._watch.start()
        else:
            self._watch.stop()

    def _on_watch(self) -> None:
        """While stopping, wait for the end of the work and start the request over; while the busy popover waits,
        follow its list, and say so when the work has ended by itself."""
        work = self._window.running_ai_work()
        if self._stopping:
            if not work:
                self._stopping = False
                self.switch.set_stopping(False)
                self._sync_watch()
                self._advance()
        elif self.popover_kind == "busy" and not work:
            self._show(ai_popups.finished_spec(self._cancel, self._advance))
        elif self.popover_kind == "busy":
            lines = tuple(w.line for w in work)
            if lines != self._popover.spec.lines:
                self._show(ai_popups.busy_spec(work, self._cancel, self._stop_and_switch))

    def _show_running(self) -> None:
        self.switch.set_running(self._state.ai_mode == CLOUD and bool(self._window.running_ai_work()))

    # -- AI setup --------------------------------------------------------------------------------

    def open_setup(self) -> None:
        """The ▾: AI setup under the switch (again, to close it)."""
        from .ai_setup import AiSetup

        if self.setup is None:
            self.setup = AiSetup(self._window, self)
        if self.setup.isVisible():
            self.setup.close_and_return()
            return
        self._cancel()
        self._close_popover()
        self.setup.focus_return = self.switch.caret
        self.setup.popup_below(self.switch)
