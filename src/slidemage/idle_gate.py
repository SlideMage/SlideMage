# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""When may background rendering start? (docs/plans/idle-background-rendering.md, 5.6)

All of these must hold to START background rendering: the feature is on; no presentation is running; the start-up
delay is over; SlideMage's window has been out of focus for LEAVE_GRACE seconds, or in front without input for
IN_FRONT_IDLE seconds (where the window reports its focus, note_focus(); else: the user has not touched SlideMage for
IDLE_AFTER seconds); nothing keeps the machine busy (a compile, an AI job, an export:
busy.py); the machine is not on battery (a setting); the CPU is below CPU_LIMIT; there is room on the disk.
Input and CPU load only decide whether a job may start: once rendering is under way (SWEEP_SECONDS after the last
start) neither stops the next job, and nothing running is interrupted by them. The window coming to the front, input
while it is in front and a presentation starting do both (v8.52.0): no job starts, and the renderer stops the running
ones (BackgroundRenderer.window_focus, user_active, presentation_started), so the app answers at once. `reason()` says what holds it back,
for the status chip. Free of Qt: the window forwards input events to
note_input().
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from . import busy, power_status

IDLE_AFTER = 30.0
STARTUP_DELAY = 20.0
CPU_LIMIT = 0.7
SWEEP_SECONDS = 60.0     # after a job started, input and CPU load no longer hold back the next one
MIN_FREE_BYTES = 5 * 1024 ** 3
LEAVE_GRACE = 3.0        # after the window lost the focus: a quick look elsewhere starts nothing
IN_FRONT_IDLE = 60.0     # in front: rendering may start after this long without input (any input stops it)
PRESENTING = "you are presenting"
IN_USE = "you are using SlideMage"     # reason(): the window is in front (or was a moment ago)
IN_USE_EXPLAINED = ("Background previews wait while you use SlideMage, so that it answers at once. They render "
                    "when you switch to another window, or after a minute without using it; they stop when you "
                    "come back.")


class IdleGate:
    def __init__(self, *, enabled: Callable[[], bool] = lambda: True, only_on_mains: Callable[[], bool] = lambda: True,
                 idle_after: float = IDLE_AFTER, startup_delay: float = STARTUP_DELAY,
                 clock: Callable[[], float] = time.monotonic,
                 on_battery: Callable[[], Optional[bool]] = power_status.on_battery,
                 cpu_load: Optional[Callable[[], Optional[float]]] = None,
                 free_bytes: Callable[[], Optional[int]] = lambda: None, min_free: int = MIN_FREE_BYTES,
                 is_busy: Callable[[], list] = busy.reasons) -> None:
        self.enabled, self.only_on_mains = enabled, only_on_mains
        self.idle_after, self.startup_delay = idle_after, startup_delay
        self._clock = clock
        self._on_battery = on_battery
        self._cpu_load = cpu_load or power_status.CpuMeter().load
        self._free_bytes, self._min_free = free_bytes, min_free
        self._busy = is_busy
        self.started = clock()
        self.last_input = clock()
        self.forced_until = 0.0           # "Render now": the idle rules are skipped until then
        self.paused = False               # "Pause" in the status chip
        self.sweep_until = 0.0            # rendering is under way until then
        self.in_front: Optional[bool] = None    # the window has the focus; None: not reported (no window)
        self.presenting: Callable[[], bool] = lambda: False
        self.left_at = clock()

    def note_focus(self, active: bool) -> None:
        """SlideMage's window got (True) or lost (False) the focus."""
        if not active and self.in_front is not False:
            self.left_at = self._clock()
        if active:
            self.last_input = self._clock()      # coming back counts as input: the minute starts again
        self.in_front = active

    def in_use(self) -> bool:
        """The window is in front and was used in the last IN_FRONT_IDLE seconds, or lost the focus a moment ago
        (no "Render now" in effect)."""
        if self.in_front is None or self.forced():
            return False
        now = self._clock()
        if self.in_front:
            return now - self.last_input < IN_FRONT_IDLE
        return now - self.left_at < LEAVE_GRACE

    def forced(self) -> bool:
        """"Render now" is in effect."""
        return self._clock() < self.forced_until

    def note_input(self) -> None:
        self.last_input = self._clock()

    def sweeping(self) -> bool:
        """Rendering is under way: a job started less than SWEEP_SECONDS ago."""
        return self._clock() < self.sweep_until

    def note_started(self) -> None:
        """A background job starts: rendering is under way, the idle and CPU rules wait until it stops."""
        self.sweep_until = self._clock() + SWEEP_SECONDS

    def force(self, seconds: float = 3600.0) -> None:
        self.forced_until = self._clock() + seconds

    def reason(self) -> Optional[str]:
        """Why background rendering may not start now, or None when it may."""
        if not self.enabled():
            return "switched off"
        if self.paused:
            return "paused"
        if self.presenting():
            return PRESENTING                    # never during a talk, not even after "Render now"
        now = self._clock()
        if self.in_use():
            return IN_USE                        # first, even during a sweep: the user at the window comes first
        busy_with = self._busy()
        if busy_with:
            return "waiting for " + ", ".join(busy_with)
        free = self._free_bytes()
        if free is not None and free < self._min_free:
            return "low disk space"
        if now < self.forced_until:
            return None
        sweeping = now < self.sweep_until
        if now - self.started < self.startup_delay:
            return "starting up"
        if self.in_front is None and not sweeping and now - self.last_input < self.idle_after:
            return "you are working"
        if self.only_on_mains() and self._on_battery():
            return "on battery"
        if not sweeping:
            load = self._cpu_load()
            if load is not None and load > CPU_LIMIT:
                return "the computer is busy"
        return None

    def allowed(self) -> bool:
        return self.reason() is None
