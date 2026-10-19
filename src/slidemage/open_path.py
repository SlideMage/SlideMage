# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
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
import sys
from pathlib import Path


def open_in_default_app(path: Path | str) -> None:
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        env = os.environ.copy()
        if sys.platform == "linux" and getattr(sys, "frozen", False):
            # PyInstaller's private libraries can delay or prevent an
            # external viewer from starting when inherited by xdg-open.
            original = env.get("LD_LIBRARY_PATH_ORIG")
            if original is None:
                env.pop("LD_LIBRARY_PATH", None)
            else:
                env["LD_LIBRARY_PATH"] = original
        subprocess.Popen(
            ["open" if sys.platform == "darwin" else "xdg-open", str(path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=env,
        )
