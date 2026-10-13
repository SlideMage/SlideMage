"""The AI switch of the top bar (workspace v6 handoff, section 1): one Local | Cloud control for every AI task of
the project, the connection Cloud means, and the ▾ that opens AI setup.

The switch only asks: moving it emits `requested(mode)` and shows the real mode again at once; ai_route.py runs
the request flow (busy work, the Claude Code session, the cloud warnings) and commits through
`WorkspaceState.set_ai_route`, which this widget follows. It is a radio group for the keyboard (roving tab stop,
←/→, Enter/Space), and it announces each commit to assistive technology.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QWidget

from ...ai import ai_profile
from ..kit import kit_qss as q
from ..kit.widgets import IconButton, SegmentedControl, set_property
from .state import WorkspaceState

LOCAL, CLOUD = ai_profile.LOCAL, ai_profile.CLOUD
SEGMENTS = ((LOCAL, "Local"), (CLOUD, "Cloud"))
CONNECTION_NAMES = {ai_profile.CLAUDE_CODE: "Claude Code", ai_profile.API: "API"}
SETUP_TIP = "AI setup: models per task, cloud connection, project setting"
ANNOUNCEMENTS = {LOCAL: "All AI tasks now use Local", CLOUD: "All AI tasks now use Cloud"}


class AiSwitch(QFrame):
    requested = Signal(str)         # LOCAL or CLOUD: the user asked for it (the switch has not moved yet)
    setup_requested = Signal()      # the ▾

    def __init__(self, state: WorkspaceState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._running = self._stopping = False
        self._shrink = 0                # 0: as designed; 1: no connection name (below 1320 px); 2: icons only
        self.announcement = ""          # what the last commit told assistive technology
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
        self.caret = IconButton("expand_more", SETUP_TIP, size=16)
        self.caret.setFixedSize(24, 28)
        self.caret.setAccessibleName("AI setup")
        self.caret.clicked.connect(self.setup_requested)
        layout.addWidget(self.caret)
        state.ai_route_changed.connect(lambda _route: self.refresh())
        self.refresh()

    def _on_segment(self, mode: str) -> None:
        focus = QApplication.focusWidget()
        focused = focus is not None and self.segments.isAncestorOf(focus)
        self.requested.emit(mode)
        self.refresh()
        if focused:
            self.segments.focus_current()

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
        self.segments.set_current(state.ai_mode)
        set_property(self, "cloud", cloud)
        if self._stopping:
            text = "stopping…"
        elif cloud:
            text = " · ".join(part for part in (CONNECTION_NAMES[conn] if self._shrink == 0 else "",
                                                "running" if self._running else "") if part)
        else:
            text = ""
        self.state_label.setText(text)
        self.state_label.setVisible(bool(text))
        set_property(self.state_label, "cloud", cloud)
        set_property(self.caret, "cloud", cloud)
        route = ai_profile.Route(state.ai_route, ai_profile.CHAT)
        self.setToolTip(f"{route.name} · " + ("AI requests send content to the cloud" if cloud
                                              else "All AI tasks use your Ollama setup"))

    def announce(self, mode: str) -> None:
        """Tell assistive technology that the switch has moved (a live region, politely)."""
        self.announcement = ANNOUNCEMENTS[mode]
        event = QAccessibleAnnouncementEvent(self.segments, self.announcement)
        event.setPoliteness(QAccessible.AnnouncementPoliteness.Polite)
        QAccessible.updateAccessibility(event)
