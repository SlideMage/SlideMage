"""What each kind of canvas shows of the session (see slide_canvas.View)."""
from __future__ import annotations

from typing import Optional

from ...presentation.session import Point, PresentationSession, Stroke


class AudienceView:
    """The projector: black, or the frozen slide, or the current one, with the laser and drawings that
    are mirrored (none while frozen or black)."""
    def __init__(self, session: PresentationSession) -> None:
        self.session = session

    def page(self) -> Optional[int]:
        return None if self.session.black else self.session.audience_page

    def strokes(self) -> list[Stroke]:
        return self.session.audience_strokes()

    def pointer(self) -> Optional[Point]:
        return self.session.audience_pointer()

    def status(self) -> None:
        return None


class CurrentView(AudienceView):
    """The presenter's current slide: always the current page, the laser and drawings as they are, and the
    badge that says what the projector shows."""
    def page(self) -> Optional[int]:
        return self.session.page

    def strokes(self) -> list[Stroke]:
        return self.session.strokes.get(self.session.page, [])

    def pointer(self) -> Optional[Point]:
        return self.session.pointer

    def status(self) -> Optional[tuple[str, str]]:
        return self.session.status()


class NextView(AudienceView):
    def page(self) -> Optional[int]:
        following = self.session.page + 1
        return following if following < self.session.page_count else None

    def strokes(self) -> list[Stroke]:
        return []

    def pointer(self) -> None:
        return None


class NotesView(NextView):
    def page(self) -> Optional[int]:
        return self.session.page
