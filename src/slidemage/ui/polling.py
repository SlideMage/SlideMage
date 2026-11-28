# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Repeating timers that poll state (review D2): `PollTimer` is a QTimer that

- **pauses** while SlideMage cannot be seen (every window minimized, or the application hidden), and, when the
  timer asks for it (`inactive_after_ms`), after the application has been inactive that long;
- **resumes** at once, with one immediate `timeout`, when it can be seen again, so a change missed meanwhile is
  picked up before the user looks;
- runs **slower** (its interval times `battery_factor`) while the computer is on battery power, unless the user
  turned the setting "Only on mains power" off (`set_battery_setting`): then battery behaves like mains.

"Inactive" alone does not pause a timer by default: the window may sit on a second monitor, where the background
renders (which run exactly when SlideMage is not in front) are meant to be watched.

The owner keeps using the QTimer API: `start()`, `stop()` and `isActive()` speak for the owner's intent (a paused timer
is still "active"), `setInterval()` sets the interval on mains power, `interval()` is the one in effect now.
The power state is read when the window comes back and on a slow timer while it is seen, never per tick;
`power_status.on_battery()` returning None (unknown, no battery) counts as mains.
"""
from __future__ import annotations

import time
import weakref
from typing import Optional

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtWidgets import QApplication, QWidget

from .. import power_status

BATTERY_FACTOR = 3
POWER_CHECK_MS = 120_000        # how often the power state is read while the window is seen


class _Monitor(QObject):
    """What the application looks like from outside: seen or not, active or not, on battery or not. One per
    QApplication; tests set the state by hand with `set_seen`, `set_active` and `set_battery`."""

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self.app = app
        self.seen = True
        self.active = True
        self.on_battery = False
        self.stretch_on_battery = lambda: True      # the window sets it: the setting "Only on mains power"
        self.inactive_since: Optional[float] = None
        self._polls: "weakref.WeakSet[PollTimer]" = weakref.WeakSet()
        self._app_hidden = False
        app.installEventFilter(self)
        app.applicationStateChanged.connect(self._on_application_state)
        self._power = QTimer(self)
        self._power.setInterval(POWER_CHECK_MS)
        self._power.timeout.connect(self.refresh_power)
        self._power.start()

    # -- what the application says -------------------------------------------------------------

    def eventFilter(self, obj, event) -> bool:
        kind = event.type()
        if kind in (QEvent.Type.WindowStateChange, QEvent.Type.Show, QEvent.Type.Hide) \
                and isinstance(obj, QWidget) and obj.isWindow():
            self._look_at_windows()
        return False

    def _look_at_windows(self) -> None:
        windows = [w for w in self.app.topLevelWidgets() if w.isWindow()]
        showing = any(w.isVisible() and not w.isMinimized() for w in windows)
        minimized = any(w.isVisible() and w.isMinimized() for w in windows)
        # Only a minimized window makes it "unseen": nothing shown at all is how a test or a closing app looks.
        self.set_seen(showing or not minimized)

    def _on_application_state(self, state) -> None:
        self._app_hidden = state == Qt.ApplicationState.ApplicationHidden
        self.set_active(state == Qt.ApplicationState.ApplicationActive)
        if self._app_hidden:
            self.set_seen(False)
        else:
            self._look_at_windows()

    # -- the state -----------------------------------------------------------------------------

    def set_seen(self, seen: bool) -> None:
        seen = bool(seen) and not self._app_hidden
        if seen == self.seen:
            return
        self.seen = seen
        if seen:
            self.refresh_power(update=False)
            self._power.start()
        else:
            self._power.stop()
        self._update_all(tick=seen)

    def set_active(self, active: bool) -> None:
        if active == self.active:
            return
        self.active = active
        self.inactive_since = None if active else time.monotonic()
        self._each(lambda poll: poll._on_activity())

    def set_battery(self, on_battery: bool) -> None:
        if on_battery != self.on_battery:
            self.on_battery = on_battery
            self._update_all(tick=False)

    def refresh_power(self, update: bool = True) -> None:
        """Read the power state (None, unknown, counts as mains) and retime the timers if it changed."""
        try:
            state = bool(power_status.on_battery()) and bool(self.stretch_on_battery())
        except Exception:  # noqa: BLE001 -- a power query must never break the app
            state = False
        if update:
            self.set_battery(state)
        else:
            self.on_battery = state

    def _update_all(self, tick: bool) -> None:
        self._each(lambda poll: poll._update(tick))

    def _each(self, call) -> None:
        for poll in list(self._polls):
            try:
                call(poll)
            except RuntimeError:        # its C++ side is gone (the owner was deleted): forget it
                self._polls.discard(poll)

    def add(self, poll: "PollTimer") -> None:
        self._polls.add(poll)


_monitor: Optional[_Monitor] = None


def set_battery_setting(stretch) -> None:
    """`stretch()` says whether battery power slows the polls (the setting "Only on mains power", on by default). It is
    asked where the power state is read (on resume, on the slow check), never per tick."""
    monitor().stretch_on_battery = stretch
    monitor().refresh_power()


def monitor() -> _Monitor:
    global _monitor
    app = QApplication.instance()
    if _monitor is None or _monitor.app is not app:
        _monitor = _Monitor(app)
        _monitor.refresh_power(update=False)
    return _monitor


class PollTimer(QTimer):
    """A repeating QTimer that follows the window and the power state (see the module's text)."""

    def __init__(self, parent: QObject | None = None, interval_ms: int = 0, *, pause_hidden: bool = True,
                 inactive_after_ms: int | None = None, battery_factor: int = BATTERY_FACTOR) -> None:
        super().__init__(parent)
        self._base = interval_ms
        self._pause_hidden = pause_hidden
        self._inactive_after = inactive_after_ms
        self._factor = max(1, battery_factor)
        self._wanted = False        # the owner started it and has not stopped it
        self._paused = False        # started, but held back now
        self._idle = False          # inactive for longer than the grace time
        self._grace = QTimer(self)
        self._grace.setSingleShot(True)
        self._grace.timeout.connect(self._grace_over)
        super().setInterval(self._effective())
        self._monitor = monitor()
        self._monitor.add(self)

    # -- the QTimer API, as the owner sees it ----------------------------------------------------

    def setInterval(self, msec: int) -> None:
        self._base = msec
        super().setInterval(self._effective())

    def base_interval(self) -> int:
        return self._base

    def isActive(self) -> bool:
        return self._wanted

    def running(self) -> bool:
        """Whether the timer is ticking right now (not paused)."""
        return QTimer.isActive(self)

    def paused(self) -> bool:
        return self._paused

    def start(self, msec: int | None = None) -> None:
        if msec is not None:
            self._base = msec
        self._wanted = True
        self._update(tick=False)

    def stop(self) -> None:
        self._wanted = False
        self._paused = False
        super().stop()

    # -- following the window ------------------------------------------------------------------

    def _effective(self) -> int:
        return self._base * self._factor if self._factor > 1 and self._monitor_on_battery() else self._base

    def _monitor_on_battery(self) -> bool:
        monitor_ = getattr(self, "_monitor", None)
        return bool(monitor_ and monitor_.on_battery)

    def _should_pause(self) -> bool:
        mon = self._monitor
        return (self._pause_hidden and not mon.seen) or self._idle

    def _update(self, tick: bool) -> None:
        if not self._wanted:
            return
        if self._should_pause():
            if not self._paused:
                self._paused = True
                super().stop()
            return
        was_paused = self._paused
        self._paused = False
        wanted_interval = self._effective()
        if not QTimer.isActive(self) or super().interval() != wanted_interval:
            super().setInterval(wanted_interval)
            QTimer.start(self)
        if was_paused and tick:
            QTimer.singleShot(0, self, self._tick_now)       # with the timer as context: gone with it

    def _tick_now(self) -> None:
        if self._wanted and not self._paused:
            self.timeout.emit()

    def _on_activity(self) -> None:
        if self._inactive_after is None:
            return
        if self._monitor.active:
            self._grace.stop()
            if self._idle:
                self._idle = False
                self._update(tick=True)
        else:
            self._grace.start(self._inactive_after)

    def _grace_over(self) -> None:
        if not self._monitor.active:
            self._idle = True
            self._update(tick=False)
