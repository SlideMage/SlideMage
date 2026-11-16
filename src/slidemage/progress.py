# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""What a long operation tells the user (BusyIndicator.show_progress). Free of Qt, so the back ends can report it."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Progress:
    text: str
    fraction: float | None = None          # 0..1; None while the number of steps is not known
