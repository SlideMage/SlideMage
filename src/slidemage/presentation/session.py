# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the presentation shows: one object both windows read (plan 4.8, 4.12).

The page the presenter is on, the projector's own state (black, frozen), the laser dot and the drawings.
Coordinates are slide fractions (0..1), so any window size or aspect shows the same spot.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtCore import QObject, Signal

Point = tuple[float, float]
TOOL_NONE, TOOL_PEN, TOOL_ERASER = "none", "pen", "eraser"


@dataclass
class Stroke:
    color: str            # QColor name, may carry alpha (#AARRGGBB)
    width: float          # fraction of the slide height
    points: list[Point] = field(default_factory=list)


class PresentationSession(QObject):
    changed = Signal()               # anything on either screen may look different
    page_changed = Signal(int)
    link_requested = Signal(str)     # an external address was clicked

    def __init__(self, page_count: int, start_page: int = 0, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.page_count = page_count
        self.page = max(0, min(start_page, page_count - 1))
        self.black = False
        self.frozen_page: Optional[int] = None
        self._frozen_strokes: list[Stroke] = []
        self.pointer: Optional[Point] = None
        self.strokes: dict[int, list[Stroke]] = {}
        self.tool = TOOL_NONE
        self._history: list[int] = []
        self._drawing: Optional[Stroke] = None

    # -- navigation -------------------------------------------------------------------

    def goto(self, page: int) -> bool:
        """Show `page` (clamped). Any navigation ends a black screen, never a freeze."""
        page = max(0, min(page, self.page_count - 1))
        was_black = self.black
        self.black = False
        self.pointer = None
        if page == self.page:
            if was_black:
                self.changed.emit()
            return False
        self.page = page
        self.page_changed.emit(page)
        self.changed.emit()
        return True

    def next(self) -> bool:
        return self.goto(self.page + 1)

    def previous(self) -> bool:
        return self.goto(self.page - 1)

    def first(self) -> bool:
        return self.goto(0)

    def last(self) -> bool:
        return self.goto(self.page_count - 1)

    def jump_to(self, page: int) -> None:
        """A link jump: remembers where it started, for back()."""
        origin = self.page
        if self.goto(page):
            self._history.append(origin)

    def back(self) -> bool:
        return bool(self._history) and self.goto(self._history.pop())

    # -- the projector ----------------------------------------------------------------

    def toggle_black(self) -> None:
        self.black = not self.black
        self.pointer = None
        self.changed.emit()

    def toggle_freeze(self) -> None:
        """Freeze the projector on the slide (and drawings) it shows now, or jump it to the current page."""
        if self.frozen_page is None:
            self.frozen_page = self.audience_page
            self._frozen_strokes = deepcopy(self.strokes.get(self.frozen_page, []))
        else:
            self.frozen_page = None
            self._frozen_strokes = []
        self.changed.emit()

    @property
    def frozen(self) -> bool:
        return self.frozen_page is not None

    @property
    def audience_page(self) -> int:
        return self.page if self.frozen_page is None else self.frozen_page

    def audience_strokes(self) -> list[Stroke]:
        if self.black:
            return []
        return self._frozen_strokes if self.frozen else self.strokes.get(self.page, [])

    def audience_pointer(self) -> Optional[Point]:
        return None if self.black or self.frozen else self.pointer

    def status(self) -> Optional[tuple[str, str]]:
        """(badge text, "black"/"frozen"/"both") for the presenter's current-slide view; None when live."""
        parts = []
        if self.black:
            parts.append("PROJECTOR BLACK")
        if self.frozen:
            parts.append(f"PROJECTOR FROZEN: page {self.frozen_page + 1}")
        if not parts:
            return None
        return " · ".join(parts), "both" if len(parts) == 2 else ("black" if self.black else "frozen")

    # -- laser and drawing ------------------------------------------------------------

    def set_pointer(self, point: Optional[Point]) -> None:
        if point != self.pointer:
            self.pointer = point
            self.changed.emit()

    def set_tool(self, tool: str) -> None:
        self.tool = tool if tool != self.tool else TOOL_NONE
        self.changed.emit()

    def begin_stroke(self, color: str, width: float, point: Point) -> None:
        self._drawing = Stroke(color, width, [point])
        self.strokes.setdefault(self.page, []).append(self._drawing)
        self.changed.emit()

    def extend_stroke(self, point: Point) -> None:
        if self._drawing is not None:
            self._drawing.points.append(point)
            self.changed.emit()

    def end_stroke(self) -> None:
        self._drawing = None

    def erase_at(self, point: Point, radius: float = 0.02) -> None:
        strokes = self.strokes.get(self.page, [])
        kept = [s for s in strokes
                if not any(abs(x - point[0]) <= radius and abs(y - point[1]) <= radius for x, y in s.points)]
        if len(kept) != len(strokes):
            self.strokes[self.page] = kept
            self.changed.emit()

    def undo_stroke(self) -> None:
        strokes = self.strokes.get(self.page)
        if strokes:
            strokes.pop()
            self.changed.emit()

    def clear_page(self) -> None:
        if self.strokes.pop(self.page, None):
            self.changed.emit()

    def clear_all(self) -> None:
        if self.strokes:
            self.strokes.clear()
            self.changed.emit()

    def request_link(self, uri: str) -> None:
        self.link_requested.emit(uri)
