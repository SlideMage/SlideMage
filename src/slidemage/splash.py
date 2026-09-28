"""Closing the one-file build's splash screen.

packaging/slidemage.spec gives the Windows one-file build a PyInstaller
Splash (splash.png): the bootloader shows it in its own bundled Tk runtime
while it unpacks itself, which takes several seconds before any Python
code runs. It has to be closed explicitly -- as soon as the main window
is up (qt_gui.main), or earlier if cli.py needs a dialog first (the
project picker), which the always-on-top splash would otherwise cover.
"""
from __future__ import annotations

_closed = False


def close() -> None:
    """Close the splash screen if there is one. A no-op when running from
    source, or in a build without a Splash (`pyi_splash` only exists
    inside a frozen build that has one), and on every call after the
    first."""
    global _closed
    if _closed:
        return
    _closed = True
    try:
        import pyi_splash
    except ImportError:
        return
    pyi_splash.close()
