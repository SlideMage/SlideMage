# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Qt side of continuing a talk (presentation/resume.py): the question when presenting starts, and saving the
place while the talk runs. Used by SlideMage and the Presenter alike, so it imports only presentation modules."""
from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from ...presentation import resume
from ...presentation.frame_map import FrameMap
from ...presentation.pdf_source import PresentationDeck
from ...presentation.settings import PresentationSettings
from .controller import PresentationController

SAVE_DELAY_MS = 1500        # a place is saved when the presenter has rested on a slide, not on every key press


def slide_pages(deck: PresentationDeck, frames: Optional[FrameMap]) -> list[int]:
    """The first page of every slide: of each frame, or every page when the PDF has no frame map."""
    return [first for first, _last in frames.frames] if frames is not None else list(range(deck.page_count))


def start_page(parent, deck: PresentationDeck, frames: Optional[FrameMap], key: str,
               settings: PresentationSettings) -> int:
    """The page to start on: 0, or the first page of the slide the presenter chooses to continue at."""
    if not settings.offer_resume:
        return 0
    place = resume.load(key)
    now = time.time()
    if not resume.worth_offering(place, now):
        return 0
    pages = slide_pages(deck, frames)
    try:
        texts = [(deck.title(page), deck.slide_text(page)) for page in pages]
    except (RuntimeError, ValueError):
        return 0
    found = resume.offer(place, [resume.fingerprint(title, text) for title, text in texts],
                         [title for title, _text in texts], now)
    if found is None or not _ask(parent, found):
        return 0
    return pages[found.slide - 1]


def _ask(parent, offer: resume.Offer) -> bool:
    """True for "Continue", False for "Start from the beginning" (also Escape)."""
    where = f"slide {offer.slide} ({offer.title})" if offer.title else f"slide {offer.slide}"
    box = QMessageBox(QMessageBox.Icon.Question, "Present", f"Continue at {where}?", parent=parent)
    if offer.moved_from is not None:
        box.setInformativeText(f"It was slide {offer.moved_from} when you stopped; slides were added or removed since.")
    elif offer.changed:
        box.setInformativeText("The slide you stopped at has changed since.")
    go = box.addButton("Continue", QMessageBox.ButtonRole.AcceptRole)
    begin = box.addButton("Start from the beginning", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(go)
    box.setEscapeButton(begin)
    box.exec()
    return box.clickedButton() is go


def remember(controller: PresentationController, deck: PresentationDeck, frames: Optional[FrameMap], key: str) -> None:
    """Save the place when the presenter rests on a slide and when the talk ends. The deck is closed by then, so the
    place is worked out as the talk moves (one slide's text, only when the slide changes), not when it is saved."""
    pages = slide_pages(deck, frames)
    latest: list[Optional[resume.Place]] = [None]
    shown = [0]
    timer = QTimer(controller)
    timer.setSingleShot(True)
    timer.setInterval(SAVE_DELAY_MS)

    def save() -> None:
        if latest[0] is not None:
            try:
                resume.save(key, latest[0])
            except (OSError, ValueError):
                pass                                # losing a place must never disturb the talk

    def changed(page: int) -> None:
        slide = frames.frame_of(page)[0] if frames is not None else page + 1
        if slide != shown[0]:
            shown[0] = slide
            try:
                first = pages[min(slide, len(pages)) - 1]
                title = deck.title(first)
                latest[0] = resume.Place(slide, len(pages), title,
                                         resume.fingerprint(title, deck.slide_text(first)), time.time())
            except (RuntimeError, ValueError):
                return
        timer.start()

    def finished() -> None:
        timer.stop()
        save()

    timer.timeout.connect(save)
    controller.session.page_changed.connect(changed)
    controller.finished.connect(finished)
