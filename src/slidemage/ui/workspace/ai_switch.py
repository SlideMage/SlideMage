# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The AI switch, the first row of the assistant card since v8.61.0 (until then in the top bar; workspace v6
handoff, section 1): one Local | Cloud control for every AI task of
the project, the connection Cloud means, and the ▾ that opens AI setup.

The switch only asks: moving it emits `requested(mode)` and shows the real mode again at once; ai_route.py runs
the request flow (busy work, the Claude Code session, the cloud warnings) and commits through
`WorkspaceState.set_ai_route`, which this widget follows. It is a radio group for the keyboard (roving tab stop,
←/→, Enter/Space), and it announces each commit and the start of stopping to assistive technology.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from ...ai import ai_profile, routes
from ..kit import kit_qss as q
from ..kit.widgets import Button, IconButton, SegmentedControl, announce, set_property
from .state import WorkspaceState

LOCAL, CLOUD = ai_profile.LOCAL, ai_profile.CLOUD
SEGMENTS = ((LOCAL, "Local"), (CLOUD, "Cloud"))
INSTALL = "Install a plugin…"
NO_SIDE = {LOCAL: "No local AI route is installed", CLOUD: "No cloud AI route is installed"}


def connection_name(route_id: str) -> str:
    """The cloud route as the switch names it next to "Cloud": its short name, else its service."""
    route = routes.get(route_id)
    return ai_profile.services().get(route_id) or (route.service if route is not None else route_id)
SETUP_TIP = "AI setup: models per task, cloud connection, project setting"
ANNOUNCEMENTS = {LOCAL: "All AI tasks now use Local", CLOUD: "All AI tasks now use Cloud"}
STOPPING = "Stopping AI work before switching"


class AiSwitch(QFrame):
    requested = Signal(str)         # LOCAL or CLOUD: the user asked for it (the switch has not moved yet)
    setup_requested = Signal()      # the ▾
    install_requested = Signal()    # "Install a plugin…": a side has no route (Settings → Extensions)

    def __init__(self, state: WorkspaceState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._running = self._stopping = False
        self._shrink = 0                # 0: as designed; 1: no connection name (a narrow assistant); 2: icons only
        self._note = ""                 # what the conversation runs on (the assistant's header), in the tooltip
        self.setObjectName(q.AI_SWITCH)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(6)
        self.segments = SegmentedControl(SEGMENTS, current=state.ai_mode, tones={CLOUD: "cloud"},
                                         icons={LOCAL: "computer", CLOUD: "cloud"}, roving=True)
        self.segments.setAccessibleName("AI for all tasks")
        self.segments.changed.connect(self._on_segment)
        layout.addWidget(self.segments)
        self.state_label = QLabel()
        self.state_label.setObjectName(q.AI_SWITCH_STATE)
        layout.addWidget(self.state_label)
        self.install = Button(INSTALL, "ghost", compact=True)
        self.install.setToolTip("A side of the switch has no AI route: plugins add routes (Settings → Extensions)")
        self.install.clicked.connect(self.install_requested)
        layout.addWidget(self.install)
        self.caret = IconButton("expand_more", SETUP_TIP, size=16)
        self.caret.setFixedSize(24, 28)
        self.caret.setAccessibleName("AI setup")
        self.caret.clicked.connect(self.setup_requested)
        layout.addWidget(self.caret)
        state.ai_route_changed.connect(lambda _route: self.refresh())
        self.refresh()

    def _on_segment(self, mode: str) -> None:
        self.requested.emit(mode)
        self.refresh()

    # -- what the switch shows ---------------------------------------------------------------

    def set_running(self, running: bool) -> None:
        """AI work is running: Cloud says so next to the connection."""
        if running != self._running:
            self._running = running
            self.refresh()

    def set_stopping(self, stopping: bool) -> None:
        if stopping != self._stopping:
            self._stopping = stopping
            self.refresh()
            if stopping:
                announce(self.segments, STOPPING)

    def set_shrink(self, level: int) -> None:
        """The last item of the top bar to shrink: at 1 (below 1320 px) the connection's name goes, "running" and
        "stopping…" stay; at 2, in the narrowest window, the segments are their icons."""
        if level == self._shrink:
            return
        self._shrink = level
        names = {mode: "" if level > 1 else label for mode, label in SEGMENTS}
        self.segments.set_labels(names, tooltips=dict(SEGMENTS), compact=level > 1)
        self.refresh()

    def refresh(self) -> None:
        state = self._state
        cloud = state.ai_mode == CLOUD
        conn = ai_profile.cloud_conn(state.project)
        empty = {mode: not routes.on_side(mode == LOCAL) for mode in (LOCAL, CLOUD)}
        for mode, button in zip((LOCAL, CLOUD), self.segments.buttons()):
            button.setEnabled(not empty[mode])
            if empty[mode]:
                button.setToolTip(NO_SIDE[mode])
        self.install.setVisible(any(empty.values()) and not all(empty.values()))
        self.segments.set_current(state.ai_mode)
        set_property(self, "cloud", cloud)
        if self._stopping:
            text = "stopping…"
        elif cloud:
            text = " · ".join(part for part in (connection_name(conn) if self._shrink == 0 else "",
                                                "running" if self._running else "") if part)
        else:
            text = ""
        self.state_label.setText(text)
        self.state_label.setVisible(bool(text))
        set_property(self.state_label, "cloud", cloud)
        set_property(self.caret, "cloud", cloud)
        route = ai_profile.Route(state.ai_route, ai_profile.CHAT)
        service = routes.get(state.ai_route)
        self.setToolTip(f"{route.name} · " + ("AI requests send content to the cloud" if cloud
                                              else f"All AI tasks use your {service.service if service else 'local'} setup")
                        + (f"\n{self._note}" if self._note else ""))

    def set_note(self, note: str) -> None:
        """What the conversation runs on ("Chat with qwen3:8b · localhost:11434"): the second line of the tooltip."""
        if note != self._note:
            self._note = note
            self.refresh()

    def announce(self, mode: str) -> None:
        """Tell assistive technology that the switch has moved."""
        announce(self.segments, ANNOUNCEMENTS[mode])
