# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""What every side panel is, and the few pieces its content is built from.

A panel shows one aspect of the focused slide (WorkspaceState.focused_slide in the
open deck), or of the slide file tab on show in the centre (PanelActions.tab_slide): where it is used, its versions, its visibility. The host
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
from ....slide_language import bare_id, call_for_slide_path, current_id_slug_for_bare_id, current_path_for_bare_id
from ...kit.tokens import SPACE
from ...kit import kit_qss as q
from ...kit.widgets import ClickFrame, Surface, clear_layout
from ..state import WorkspaceState


class PanelActions(NamedTuple):
    """What the side panels ask of the rest of the window: the Source view's buffers and the deck
    edits of the slide list. Passed in, so that no panel reaches through the window to its siblings."""
    slide_text: Callable[[Path], str]                     # the text of a slide file, edits not yet written included
    is_dirty: Callable[[Path], bool]                      # the Source view holds edits of this file that could not be saved
    edit_slide_text: Callable[..., bool]                  # change a slide's text through the Source view (show=True: and show it there)
    save_source: Callable[[], object]                     # Ctrl+S: write the Source view's file now and render it
    restore_version: Callable[[Path], object]
    freeze_version: Callable[[str, str], object]
    edit_deck: Callable[..., bool]                        # an edit of the open deck (SlideList.edit)
    add_slide: Callable[..., object]                      # SlideList.add_slide
    translate: Callable[..., object]                      # the assistant's Translate task, on its task card (a language: into that)
    add_reference: Callable[[str], object]
    # (path, row) of the slide file tab on show in the centre (row: CentreColumn._tab_row, None when the deck does not
    # use the slide or the file is a frozen version); None for the slide tab, a file that is no slide, or no centre yet.
    # The panels then show that slide instead of the focused one (centre-tabs.md, D9).
    tab_slide: Callable[[], Optional[tuple]] = lambda: None
    slide_renamed: Callable[[str, str], object] = lambda old, new: None   # (old, new id-slug): the slide's tabs follow it


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
        inner.setContentsMargins(SPACE.xl, SPACE.lg, SPACE.xl, SPACE.lg)
        inner.setSpacing(SPACE.xs)
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
        self.body.setSpacing(SPACE.lg)
        self.dirty = False
        self._row_now: tuple | None = None      # (row,) while a refresh builds: it resolves the focused row once

    def offered(self) -> bool:
        """Whether the picker offers this panel now (a plugin's box only where its when() says so)."""
        return True

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
        self._row_now = (self._focused_row(),)
        try:
            slide = self.id_slug()
            if slide:
                self.build(slide)
            else:
                self.body.addWidget(text(
                    "This deck has no slide list." if self.state.deck is not None and self.state.deck.is_test_deck
                    else "Select a slide in the list.", q.DETAILS_LABEL))
        finally:
            self._row_now = None

    def build(self, id_slug: str) -> None:
        """Fill `self.body` for the slide `id_slug` (the full id-slug, e.g. "1y8-EN-Intro")."""
        raise NotImplementedError

    # -- the slide: the focused one, or the slide file tab's on show ----------------------

    def _tab(self) -> Optional[tuple]:
        """(path, row) of the slide file tab on show, None when the panels follow the focused slide."""
        return self.actions.tab_slide()

    def _slide_id(self) -> Optional[str]:
        """The bare id of the slide the panel is for."""
        tab = self._tab()
        return bare_id(tab[0].name) if tab is not None else self.state.focused_slide

    def deck_calls(self) -> list[tuple[int, SlideCall]]:
        """(1-based place, call) of every call of the slide in the open deck."""
        state, slide = self.state, self._slide_id()
        if state.deck is None or state.deck.is_test_deck or slide is None:
            return []
        return [(r.position, r.deck_call)
                for r in deck_outline.outline_rows(self.app.project, state.deck, state.view, state.language, outline=state.outline)
                if r.matches(slide)]

    def _focused_row(self):
        """The row of the slide in the open deck (the one a refresh resolved, while it builds): the focused occurrence's,
        or the slide file tab's."""
        if self._row_now is not None:
            return self._row_now[0]
        tab = self._tab()
        if tab is not None:
            return tab[1]
        state = self.state
        if state.deck is None or state.deck.is_test_deck or state.focused_slide is None:
            return None
        return deck_outline.slide_row(self.app.project, state.deck, state.focused_slide, state.view, state.language,
                                      occurrence_key=state.focused_occurrence, outline=state.outline)

    def id_slug(self) -> str:
        """The slide's full id-slug: as the open deck calls it, else its file's (the tab's, or the focused slide's
        current file); "" for none."""
        row = self._focused_row()
        if row is not None:
            return row.call.id_slug
        tab = self._tab()
        if tab is not None:
            try:
                return call_for_slide_path(tab[0])[1]
            except ValueError:
                return ""
        slide = self.state.focused_slide
        return current_id_slug_for_bare_id(self.app.project, slide) or "" if slide else ""

    def slide_path(self) -> Optional[Path]:
        """The file of the slide: the slide file tab's, else what the open deck calls for the focused slide (a pinned
        version is its own file), else the slide's current file."""
        tab = self._tab()
        if tab is not None:
            path = tab[0]
        else:
            row = self._focused_row()
            slide = self.state.focused_slide
            path = self.app.project.slides_dir / row.call.source_filename if row else (current_path_for_bare_id(self.app.project, slide) if slide else None)
        return path if path is not None and path.is_file() else None

    def slide_text(self) -> str:
        """The text of that file, with the edits of the Source view not yet written (`CentreColumn.slide_text`)."""
        path = self.slide_path()
        return self.actions.slide_text(path) if path is not None else ""
