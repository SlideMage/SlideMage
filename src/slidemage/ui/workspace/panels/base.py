"""What every side panel is, and the few pieces its content is built from.

A panel shows one aspect of the focused slide (WorkspaceState.focused_slide in the
open deck): where it is used, its versions, its visibility. The host
(side_panels.py) calls `refresh()` when the deck, the slide, the view or the
language changed, or an edit was made, and only for the panel that is shown, so
a panel reads what it needs from the project when asked and keeps no copy.

To add a panel: a subclass with `key`, `title` and `build()`, listed in
panels/__init__.py. The content goes into grey boxes (`box()`) whose rows
(`row()`) are separated by hairlines; the colors come from kit_qss.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QFrame, QLabel, QLayout, QVBoxLayout

from ....deck_editor import SlideCall, parse_slide_calls
from ....slide_language import current_id_slug_for_bare_id
from ...kit import kit_qss as q
from ...kit.widgets import Surface
from ..state import WorkspaceState


def text(string: str, name: str = q.DETAILS_VALUE) -> QLabel:
    """A wrapped label in one of the kit's text styles (DETAILS_VALUE, DETAILS_LABEL, PANEL_MONO, PANEL_CAPTION)."""
    label = QLabel(string)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


def box() -> tuple[QFrame, QVBoxLayout]:
    """A grey rounded box; add rows to the layout."""
    frame = QFrame()
    frame.setObjectName(q.PANEL_BOX)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    return frame, layout


class Row(QFrame):
    """One row of a box: a QVBoxLayout with the prototype's padding. Clickable when `activated` is
    connected (the pointer shows it)."""

    activated = Signal()

    def __init__(self, layout: QLayout) -> None:
        super().__init__()
        self.setObjectName(q.PANEL_ROW)
        inner = QVBoxLayout(self)
        inner.setContentsMargins(14, 10, 14, 10)
        inner.setSpacing(4)
        self.body = inner
        layout.addWidget(self)

    def make_clickable(self, on_click: Callable[[], None]) -> None:
        self.activated.connect(on_click)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.activated.emit()
        super().mouseReleaseEvent(event)


def clear(layout: QLayout) -> None:
    while (item := layout.takeAt(0)) is not None:
        if (widget := item.widget()) is not None:
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout() is not None:
            clear(item.layout())


class SidePanel(Surface):
    key = ""      # what the host remembers and the picker's menu returns
    title = ""    # the picker's text

    def __init__(self, app, state: WorkspaceState) -> None:
        """`app` is the window: it logs, opens files in the Source view and edits the deck
        through the slide list; `state` says which slide, view and language."""
        super().__init__()
        self.app = app
        self.state = state
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(10)

    def meta(self) -> str:
        """A few words about the focused slide for the picker's menu ("3 frozen")."""
        return ""

    def suffix(self) -> str:
        """Grey text next to the picker ("in Instructor")."""
        return ""

    def refresh(self) -> None:
        clear(self.body)
        slide = self.id_slug()
        if slide:
            self.build(slide)
        else:
            self.body.addWidget(text(
                "This deck has no slide list." if self.state.deck is not None and self.state.deck.is_test_deck
                else "Select a slide in the list.", q.DETAILS_LABEL))

    def build(self, id_slug: str) -> None:
        """Fill `self.body` for the slide `id_slug` (the full id-slug, e.g. "1y8-EN-Intro")."""
        raise NotImplementedError

    # -- the focused slide ----------------------------------------------------------

    def deck_calls(self) -> list[tuple[int, SlideCall]]:
        """(1-based place, call) of every call of the focused slide in the open deck."""
        deck, slide = self.state.deck, self.state.focused_slide
        if deck is None or deck.is_test_deck or slide is None:
            return []
        return [(i, c) for i, c in enumerate(parse_slide_calls(deck), start=1) if c.id == slide]

    def id_slug(self) -> str:
        """The focused slide's full id-slug: as the open deck calls it, else its current file's; "" for none."""
        calls = self.deck_calls()
        if calls:
            return calls[0][1].id_slug
        slide = self.state.focused_slide
        return current_id_slug_for_bare_id(slide) or "" if slide else ""
