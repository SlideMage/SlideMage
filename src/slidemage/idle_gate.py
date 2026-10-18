"""When may background rendering start? (docs/plans/idle-background-rendering.md, 5.6)

All of these must hold: the feature is on; the start-up delay is over; the user has not touched SlideMage
for IDLE_AFTER seconds; nothing keeps the machine busy (a compile, an AI job, an export: busy.py); the
machine is not on battery (a setting); the CPU is not busy with something else; there is room on the disk.
`reason()` says what holds it back, for the status chip. Free of Qt: the window forwards input events to
note_input().
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from . import busy, power_status

IDLE_AFTER = 30.0
STARTUP_DELAY = 20.0
CPU_LIMIT = 0.7
MIN_FREE_BYTES = 5 * 1024 ** 3


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

    def note_input(self) -> None:
        self.last_input = self._clock()

    def force(self, seconds: float = 3600.0) -> None:
        self.forced_until = self._clock() + seconds

    def reason(self) -> Optional[str]:
        """Why background rendering may not start now, or None when it may."""
        if not self.enabled():
            return "switched off"
        if self.paused:
            return "paused"
        now = self._clock()
        busy_with = self._busy()
        if busy_with:
            return "waiting for " + ", ".join(busy_with)
        free = self._free_bytes()
        if free is not None and free < self._min_free:
            return "low disk space"
        if now < self.forced_until:
            return None
        if now - self.started < self.startup_delay:
            return "starting up"
        if now - self.last_input < self.idle_after:
            return "you are working"
        if self.only_on_mains() and self._on_battery():
            return "on battery"
        load = self._cpu_load()
        if load is not None and load > CPU_LIMIT:
            return "the computer is busy"
        return None

    def allowed(self) -> bool:
        return self.reason() is None
