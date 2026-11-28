# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Closing the one-file build's splash screen.

packaging/slidemage.spec gives the Windows one-file build a PyInstaller
Splash (splash.png): the bootloader shows it in its own bundled Tk runtime
while it unpacks itself, which takes several seconds before any Python
code runs. It has to be closed explicitly -- as soon as the main window
is up (ui/app.main), or earlier if cli.py needs a dialog first (the
project picker), which the always-on-top splash would otherwise cover.
"""
from __future__ import annotations

import sys

_closed = False


def close() -> None:
    """Close the splash screen if there is one. A no-op when running from
    source, or in a build without a Splash (packaging/slidemage.spec has
    one on Windows only; elsewhere PyInstaller's `pyi_splash` stub exists
    but prints a traceback on import), and on every call after the first."""
    global _closed
    if _closed or sys.platform != "win32":
        return
    _closed = True
    try:
        import pyi_splash
    except ImportError:
        return
    pyi_splash.close()


def release_topmost() -> None:
    """Let other windows be put in front of the splash screen.

    PyInstaller's bootloader makes the splash a Tk window that is always on
    top; loading can take a long time, and the user could not work in another
    window meanwhile. Clears the topmost flag and gives it a taskbar button
    (so Alt+Tab and the taskbar reach it), without activating it. Best effort:
    a no-op from source, in a build without a Splash, or after close().
    (2026-10-29, direct request: the splash stayed in front of every window.)"""
    if _closed or sys.platform != "win32":
        return
    try:
        import pyi_splash  # noqa: F401  (only to know there is a splash)
    except ImportError:
        return
    try:
        import ctypes
        import os
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        # In a one-file build the bootloader process that owns the splash is our parent.
        pids = {os.getpid(), os.getppid()}
        found: list[int] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def visit(hwnd, _):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            name = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, name, 64)
            if pid.value in pids and name.value == "TkTopLevel" and user32.IsWindowVisible(hwnd):
                found.append(hwnd)
            return True

        user32.EnumWindows(visit, 0)
        GWL_EXSTYLE, WS_EX_TOOLWINDOW, WS_EX_APPWINDOW = -20, 0x80, 0x40000
        HWND_NOTOPMOST = wintypes.HWND(-2)
        flags = 0x0001 | 0x0002 | 0x0010 | 0x0020  # NOSIZE, NOMOVE, NOACTIVATE, FRAMECHANGED
        for hwnd in found:
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW)
            user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, flags)
    except Exception:
        pass  # cosmetic only; the splash stays as it was
