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
