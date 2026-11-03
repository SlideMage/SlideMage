# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The pieces a compat.py registry entry is made of (split off so that an
entry module can import them without importing compat.py itself)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

BREAKS = "breaks"
LAYOUT = "layout"
APPEARANCE = "appearance"


@dataclass(frozen=True)
class Finding:
    file: str          # relative to the project root, forward slashes
    line: int          # 1-based; 0 = the file as a whole
    message: str


@dataclass(frozen=True)
class Change:
    id: str
    since: str
    severity: str
    title: str
    description: str
    fix: str = ""
    detect: Optional[Callable[[Path], list[Finding]]] = None
    migrate: Optional[Callable[[Path], dict[Path, Optional[bytes]]]] = None
    # SlideMage made the change itself when it opened the project and nothing is left to do: a one-time notice
    # that older versions can no longer read the project, not the compatibility sheet. `detect` finds it done.
    automatic: bool = False
