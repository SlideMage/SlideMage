# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Power, CPU and disk facts for background rendering, without new dependencies. Each returns None when
the platform does not say, which the idle gate treats as "fine"."""
from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Optional


def on_battery() -> Optional[bool]:
    """True on battery power (or in battery saver), False on mains, None when unknown or no battery."""
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class Status(ctypes.Structure):
                _fields_ = [("ACLineStatus", wintypes.BYTE), ("BatteryFlag", wintypes.BYTE),
                            ("BatteryLifePercent", wintypes.BYTE), ("SystemStatusFlag", wintypes.BYTE),
                            ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]

            status = Status()
            if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
                return None
            if status.BatteryFlag & 0xFF == 128:          # no system battery
                return None
            return status.ACLineStatus == 0 or status.SystemStatusFlag == 1     # offline, or battery saver on
        if sys.platform == "darwin":
            from .processes import command_output
            text = command_output(["pmset", "-g", "batt"]) or ""
            if not text:
                return None
            return "Battery Power" in text
        for supply in Path("/sys/class/power_supply").glob("*"):
            kind = (supply / "type").read_text().strip() if (supply / "type").exists() else ""
            if kind == "Mains" and (supply / "online").exists():
                return (supply / "online").read_text().strip() == "0"
    except Exception:  # noqa: BLE001 -- a power query must never break the app
        return None
    return None


class CpuMeter:
    """The share of the CPU busy since the previous measurement (None the first time or when unknown). Safe to ask
    from several threads: a call within `min_interval` seconds of the last measurement gets that value again, so
    workers asking at once do not measure meaninglessly short spans."""

    def __init__(self, min_interval: float = 0.0, clock=time.monotonic) -> None:
        self._last: Optional[tuple[int, int]] = None
        self._min_interval, self._clock = min_interval, clock
        self._value: Optional[float] = None
        self._measured_at: Optional[float] = None
        self._lock = threading.Lock()

    def _times(self) -> Optional[tuple[int, int]]:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
            if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
                return None

            def value(t):
                return (t.dwHighDateTime << 32) | t.dwLowDateTime

            return value(kernel) + value(user), value(idle)       # kernel time includes idle time
        if sys.platform.startswith("linux"):
            numbers = [int(f) for f in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
            return sum(numbers), numbers[3] + (numbers[4] if len(numbers) > 4 else 0)
        return None

    def load(self) -> Optional[float]:
        with self._lock:
            at = self._clock()
            if self._measured_at is not None and at - self._measured_at < self._min_interval:
                return self._value
            value = self._measure()
            if value is not None:
                self._value, self._measured_at = value, at
            return value

    def _measure(self) -> Optional[float]:
        try:
            now = self._times()
        except Exception:  # noqa: BLE001
            return None
        if now is None:
            if hasattr(os, "getloadavg"):
                try:
                    return min(1.0, os.getloadavg()[0] / (os.cpu_count() or 1))
                except OSError:
                    return None
            return None
        last, self._last = self._last, now
        if last is None or now[0] <= last[0]:
            return None
        return 1.0 - (now[1] - last[1]) / (now[0] - last[0])


_SHARED: Optional[CpuMeter] = None
_SHARED_LOCK = threading.Lock()


def shared_cpu_meter() -> CpuMeter:
    """The one meter every "may one more render start?" question uses (measured at most once a second)."""
    global _SHARED
    with _SHARED_LOCK:
        if _SHARED is None:
            _SHARED = CpuMeter(min_interval=1.0)
        return _SHARED


def free_bytes(path: Path) -> Optional[int]:
    try:
        probe = Path(path)
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        return shutil.disk_usage(probe).free
    except OSError:
        return None
