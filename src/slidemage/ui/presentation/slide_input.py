"""What the mouse does on a slide view (plan 4.7, 4.8), decided at the press and free of widgets.

Ctrl + left button is the laser (never a link, never a stroke); else with the pen the button draws, with
the eraser it erases; else a press and release that did not move is a click on a link.
"""
from __future__ import annotations

from typing import Optional

from ...presentation.pdf_source import Link, PresentationDeck
from ...presentation.session import TOOL_ERASER, TOOL_PEN, PresentationSession
from ...presentation.settings import PresentationSettings

CLICK_SLOP = 0.01     # a click that moves more than this fraction of the slide is not a click

IDLE, LASER, PEN, ERASE, CLICK, IGNORE = "idle", "laser", "pen", "erase", "click", "ignore"


class SlideInput:
    def __init__(self, session: PresentationSession, deck: PresentationDeck, settings: PresentationSettings) -> None:
        self.session, self.deck, self.settings = session, deck, settings
        self.mode = IDLE
        self._press: tuple[float, float] = (0.0, 0.0)

    def press(self, x: float, y: float, ctrl: bool) -> None:
        session = self.session
        self._press = (x, y)
        if ctrl:
            self.mode = LASER
            session.set_pointer((x, y))
        elif session.tool == TOOL_PEN:
            self.mode = PEN
            session.begin_stroke(self.settings.pen_color, self.settings.pen_width, (x, y))
        elif session.tool == TOOL_ERASER:
            self.mode = ERASE
            session.erase_at((x, y))
        else:
            self.mode = CLICK

    def move(self, x: float, y: float, ctrl: bool) -> None:
        mode, session = self.mode, self.session
        if mode == LASER:
            if ctrl:
                session.set_pointer((x, y))
            else:                          # Ctrl let go while the button is down: the laser ends
                session.set_pointer(None)
                self.mode = IGNORE
        elif mode == PEN:
            session.extend_stroke((x, y))
        elif mode == ERASE:
            session.erase_at((x, y))
        elif mode == CLICK and max(abs(x - self._press[0]), abs(y - self._press[1])) > CLICK_SLOP:
            self.mode = IGNORE

    def release(self, x: float, y: float) -> Optional[Link]:
        """Ends the press; the link that was clicked, if the press was a click on one."""
        mode, self.mode = self.mode, IDLE
        if mode == LASER:
            self.session.set_pointer(None)
        elif mode == PEN:
            self.session.end_stroke()
        elif mode == CLICK:
            link = self.deck.link_at(self.session.page, x, y)
            if link is not None:
                if link.page is not None:
                    self.session.jump_to(link.page)
                elif link.uri:
                    self.session.request_link(link.uri)
                return link
        return None

    def leave(self) -> None:
        """The mouse left the view: a laser dot must not stay behind."""
        if self.mode == LASER:
            self.session.set_pointer(None)
            self.mode = IGNORE

    def over_link(self, x: float, y: float) -> bool:
        return self.deck.link_at(self.session.page, x, y) is not None
