"""Cross-platform "open in the OS's default app" helper. os.startfile()
(used everywhere this project opens a compiled PDF/PPTX/image) is a
Windows-only stdlib attribute -- calling it on Linux raises AttributeError,
not caught by the existing `except OSError` handlers at each call site.
Windows behavior is unchanged (still literally os.startfile); Linux uses
xdg-open, the desktop-environment-agnostic standard (part of xdg-utils,
present by default on Ubuntu 24.04)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def open_in_default_app(path: Path) -> None:
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(
            ["xdg-open", str(path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
