# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""A selection of a slide's text, captured for an AI task (Claude Code reviews plan, step R1): the file, its whole text
at that moment and the range that was selected. The task works on the range only and the proposal goes back into
exactly it, so a selection that touches a protected part of the slide (protected_regions: the header comment, the
\\setSlideVersion line, a \\vbox to 0pt block) is refused here, before anything is sent. Pure: no Qt."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .protected_regions import protected_spans

CONTEXT_CHARS = 800      # what a request carries of the text on either side of a selection
NO_SELECTION = "Select some text of the slide in the Source view first."
PROTECTED = ("The selection touches a protected part of the slide (the comment block at the top, the \\setSlideVersion "
             "line or a \\vbox to 0pt{...} block). Select ordinary text only.")


class SelectionError(ValueError):
    """Why a selection cannot be worked on; the message is for the user."""


@dataclass(frozen=True)
class Selection:
    path: Path
    text: str          # the whole file as the editor had it
    start: int         # the selected range, as offsets into `text`
    end: int

    @property
    def selected(self) -> str:
        return self.text[self.start:self.end]


def capture(path: Path, text: str, start: int, end: int) -> Selection:
    """The range `start`..`end` of `text`; SelectionError when it is empty or blank, or reaches into a protected part."""
    if not text[start:end].strip():
        raise SelectionError(NO_SELECTION)
    if any(first < end and start < last for first, last in protected_spans(text)):
        raise SelectionError(PROTECTED)
    return Selection(path, text, start, end)
