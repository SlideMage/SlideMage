"""What every side panel is, and the few pieces its content is built from.

A panel shows one aspect of the focused slide (WorkspaceState.focused_slide in the
open deck): where it is used, its versions, its visibility. The host
(side_panels.py) calls `refresh()` when the deck, the slide, the view or the
language changed, or an edit was made, and only for the panel that is shown, so
a panel reads what it needs from the project when asked and keeps no copy.

A panel that lets the user type keeps the edit as pending (`set_dirty`) until it is saved;
the host asks every panel to `flush()` before the slide, the deck or the panel changes, so that
a pending edit is saved, never lost, and counts for the close prompt.

To add a panel: a subclass with `key`, `title` and `build()`, listed in
panels/__init__.py. The content goes into grey boxes (`box()`) whose rows
(`row()`) are separated by hairlines; the colors come from kit_qss.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, NamedTuple, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QLayout, QVBoxLayout

from ....deck_editor import SlideCall
from .... import deck_outline
from ....slide_language import current_id_slug_for_bare_id, current_path_for_bare_id
from ...kit import kit_qss as q
from ...kit.widgets import ClickFrame, Surface, clear_layout
from ..state import WorkspaceState


class PanelActions(NamedTuple):
    """What the side panels ask of the rest of the window: the Source view's buffers and the deck
    edits of the slide list. Passed in, so that no panel reaches through the window to its siblings."""
    slide_text: Callable[[Path], str]                     # the text of a slide file, unsaved edits included
    is_dirty: Callable[[Path], bool]                      # the Source view holds unsaved edits of this file
    edit_slide_text: Callable[..., bool]                  # change a slide's text through the Source view
    save_source: Callable[[], object]
    restore_version: Callable[[Path], object]
    freeze_version: Callable[[str, str], object]
    edit_deck: Callable[..., bool]                        # an edit of the open deck (SlideList.edit)
    add_slide: Callable[..., object]                      # SlideList.add_slide
    translate: Callable[[], object]                       # the assistant's Translate task, on its task card
    add_reference: Callable[[str], object]


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


class Row(ClickFrame):
    """One row of a box: a QVBoxLayout with the prototype's padding. Clickable after `make_clickable`
    (the pointer shows it)."""

    def __init__(self, layout: QLayout) -> None:
        super().__init__()
        self.setObjectName(q.PANEL_ROW)
        inner = QVBoxLayout(self)
        inner.setContentsMargins(14, 10, 14, 10)
        inner.setSpacing(4)
        self.body = inner
        layout.addWidget(self)

    def add_text(self, string: str, name: str = q.DETAILS_VALUE) -> QLabel:
        label = text(string, name)
        self.body.addWidget(label)
        return label

    def make_clickable(self, on_click: Callable[[], None]) -> None:
        self.clicked.connect(on_click)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


def empty_row(layout: QLayout, string: str) -> None:
    """A row that says there is nothing to show ("No images on this slide.")."""
    Row(layout).add_text(string, q.DETAILS_LABEL)


class SidePanel(Surface):
    key = ""      # what the host remembers and the picker's menu returns
    title = ""    # the picker's text

    dirty_changed = Signal(bool)   # the panel has (no) pending edits

    def __init__(self, app, state: WorkspaceState, actions: PanelActions) -> None:
        """`app` is the window: it logs and opens files in the Source view; `actions` are the
        edits the panel asks for; `state` says which slide, view and language."""
        super().__init__()
        self.app = app
        self.state = state
        self.actions = actions
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(10)
        self.dirty = False

    def meta(self) -> str:
        """A few words about the focused slide for the picker's menu ("3 frozen")."""
        return ""

    def suffix(self) -> str:
        """Grey text next to the picker ("in Instructor")."""
        return ""

    def set_dirty(self, dirty: bool) -> None:
        if dirty != self.dirty:
            self.dirty = dirty
            self.dirty_changed.emit(dirty)

    def flush(self) -> None:
        """Save the pending edits, if the panel has any (called before the slide, the deck or the
        panel changes)."""

    def place(self, frame: QFrame, caption: str = "") -> None:
        """Put a finished box into the panel, with a grey line under it, and push the rest up."""
        self.body.addWidget(frame)
        if caption:
            self.body.addWidget(text(caption, q.PANEL_CAPTION))
        self.body.addStretch(1)

    def refresh_route(self) -> None:
        """The AI route changed: say so on what sends content to the AI ("Redraft… · cloud")."""

    def refresh(self) -> None:
        clear_layout(self.body)
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
        return [(r.position, r.deck_call)
                for section in deck_outline.build_outline(self.app.project, deck, self.state.view, self.state.language)
                for r in section.rows if r.matches(slide)]

    def _focused_row(self):
        deck, slide = self.state.deck, self.state.focused_slide
        if deck is None or deck.is_test_deck or slide is None:
            return None
        return deck_outline.slide_row(self.app.project, deck, slide, self.state.view, self.state.language)

    def id_slug(self) -> str:
        """The focused slide's full id-slug: as the open deck calls it, else its current file's; "" for none."""
        row = self._focused_row()
        if row is not None:
            return row.call.id_slug
        slide = self.state.focused_slide
        return current_id_slug_for_bare_id(self.app.project, slide) or "" if slide else ""

    def slide_path(self) -> Optional[Path]:
        """The file of the focused slide: what the open deck calls (a pinned version is its own
        file), else the slide's current file."""
        row = self._focused_row()
        slide = self.state.focused_slide
        path = self.app.project.slides_dir / row.call.source_filename if row else (current_path_for_bare_id(self.app.project, slide) if slide else None)
        return path if path is not None and path.is_file() else None

    def slide_text(self) -> str:
        """The text of that file, with unsaved edits of the Source view (`CentreColumn.slide_text`)."""
        path = self.slide_path()
        return self.actions.slide_text(path) if path is not None else ""
