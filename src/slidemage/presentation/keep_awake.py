"""Keep the computer awake and the screensaver off while presenting (plan 4.3).

One small backend per platform, none needing a new dependency:
- Windows: SetThreadExecutionState asks for the display and the system to stay on. That alone does not
  stop a configured screensaver (found in the public discussion of the same problem in pympress's tracker,
  read as prose only), so the screensaver is also switched off for the session -- not saved to the user's
  profile -- and restored to what it was.
- macOS: a `caffeinate` process that keeps the display and the system awake and ends with this process.
- Linux (X11 and Wayland): the session bus's screensaver inhibit (KDE, GNOME and others), else GNOME's
  session manager. Released by number when the show ends.
Closing a laptop lid or pressing the power button still suspends the machine; nothing can prevent that.
Every failure is swallowed: presenting must never fail because the inhibit did.
"""
from __future__ import annotations

import atexit
import subprocess
import sys
from typing import Callable, Optional

REASON = "Presenting a deck"


class _Windows:
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x00000001, 0x00000002
    SPI_GETSCREENSAVEACTIVE, SPI_SETSCREENSAVEACTIVE = 0x0010, 0x0011

    def __init__(self) -> None:
        import ctypes
        self._ctypes = ctypes
        self._screensaver_was_on: Optional[bool] = None

    def start(self) -> None:
        ctypes = self._ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(
            self.ES_CONTINUOUS | self.ES_SYSTEM_REQUIRED | self.ES_DISPLAY_REQUIRED)
        active = ctypes.c_int(0)
        if ctypes.windll.user32.SystemParametersInfoW(self.SPI_GETSCREENSAVEACTIVE, 0, ctypes.byref(active), 0):
            self._screensaver_was_on = bool(active.value)
            if self._screensaver_was_on:      # flags 0: this session only, nothing written to the profile
                ctypes.windll.user32.SystemParametersInfoW(self.SPI_SETSCREENSAVEACTIVE, 0, None, 0)

    def stop(self) -> None:
        ctypes = self._ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(self.ES_CONTINUOUS)
        if self._screensaver_was_on:
            ctypes.windll.user32.SystemParametersInfoW(self.SPI_SETSCREENSAVEACTIVE, 1, None, 0)
        self._screensaver_was_on = None


class _Mac:
    def __init__(self) -> None:
        self._process: Optional[subprocess.Popen] = None

    def start(self) -> None:
        import os
        self._process = subprocess.Popen(["caffeinate", "-d", "-i", "-w", str(os.getpid())],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def stop(self) -> None:
        if self._process is not None:
            self._process.terminate()
            self._process = None


class _Linux:
    # (service, path, interface, inhibit arguments, release method)
    TARGETS = (
        ("org.freedesktop.ScreenSaver", "/org/freedesktop/ScreenSaver", "org.freedesktop.ScreenSaver",
         lambda: ["SlideMage", REASON], "UnInhibit"),
        ("org.gnome.SessionManager", "/org/gnome/SessionManager", "org.gnome.SessionManager",
         lambda: ["SlideMage", 0, REASON, 8], "Uninhibit"),
    )

    def __init__(self) -> None:
        self._held: list[tuple[str, str, str, str, int]] = []

    def start(self) -> None:
        from PySide6.QtDBus import QDBusConnection, QDBusInterface
        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            return
        for service, path, interface, arguments, release in self.TARGETS:
            iface = QDBusInterface(service, path, interface, bus)
            if not iface.isValid():
                continue
            reply = iface.call("Inhibit", *arguments())
            values = reply.arguments()
            if values and isinstance(values[0], int):
                self._held.append((service, path, interface, release, values[0]))
                return

    def stop(self) -> None:
        from PySide6.QtDBus import QDBusConnection, QDBusInterface
        bus = QDBusConnection.sessionBus()
        for service, path, interface, release, cookie in self._held:
            QDBusInterface(service, path, interface, bus).call(release, cookie)
        self._held.clear()


def default_backend() -> Optional[object]:
    if sys.platform == "win32":
        return _Windows()
    if sys.platform == "darwin":
        return _Mac()
    if sys.platform.startswith("linux"):
        return _Linux()
    return None


class KeepAwake:
    """start() when the presentation opens, stop() when it ends; both are safe to call twice."""

    def __init__(self, backend: Optional[object] = None, factory: Callable[[], Optional[object]] = default_backend) -> None:
        self._backend = backend if backend is not None else factory()
        self.active = False

    def start(self) -> None:
        if self.active or self._backend is None:
            return
        try:
            self._backend.start()
            self.active = True
            atexit.register(self.stop)      # a crash path still lets go
        except Exception:    # noqa: BLE001 -- never fail the presentation for this
            self.active = False

    def stop(self) -> None:
        if not self.active:
            return
        self.active = False
        try:
            self._backend.stop()
        except Exception:    # noqa: BLE001
            pass
