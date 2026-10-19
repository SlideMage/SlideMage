# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which screen is for the presenter and which for the audience (plan 4.3). Pure data in, a plan out, so it
is tested with made-up screens; the window code turns QScreens into ScreenInfos."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ScreenInfo:
    name: str
    x: int
    y: int
    width: int
    height: int
    serial: str = ""
    primary: bool = False

    @property
    def geometry(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.width, self.height

    @property
    def key(self) -> str:
        """What the "Audience screen" setting stores."""
        return f"{self.name}|{self.serial}" if self.serial else self.name


@dataclass(frozen=True)
class ScreenPlan:
    presenter: int               # index into the screen list
    audience: Optional[int]      # None: only one screen to show (single or mirrored)


def choose_screens(screens: list[ScreenInfo], main: int = -1, preferred: str = "") -> ScreenPlan:
    """`main`: the screen the SlideMage window is on (the presenter's; -1 is the primary one), `preferred`:
    ScreenInfo.key of the audience screen from the settings ("" is automatic). Screens with identical
    geometry are one mirrored screen (on Windows and macOS Qt already reports a duplicated display as one)."""
    if not screens:
        raise ValueError("no screens")
    if not 0 <= main < len(screens):
        main = next((i for i, s in enumerate(screens) if s.primary), 0)
    others = [i for i, s in enumerate(screens) if s.geometry != screens[main].geometry]
    if not others:
        return ScreenPlan(main, None)
    chosen = next((i for i in others if preferred and screens[i].key == preferred), others[0])
    return ScreenPlan(main, chosen)
