# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The "Present deck" command (plan 4.9): find the PDF, ask what to do when there is none or it is old,
then start the presentation."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from PySide6.QtWidgets import QMessageBox

from ... import deck_editor, deck_outline
from ...compiler import DeckPdf
from ...deck_scan import Deck
from ...presentation import frames as frames_mod
from ...presentation.locate import find_presenter_pdf
from ...presentation.pdf_source import PresentationDeck
from ...presentation.settings import PresentationSettings
from ...presentation import resume
from ...presentation.frame_map import FrameMap
from . import resume_ui
from .controller import PresentationController


@dataclass(frozen=True)
class StartSlide:
    """Where "Present from current slide" starts: the slide's place among the frames the presenter PDF has (its
    `ordinal`, 1-based, counted over the slides the Instructor view typesets), `slides` of them in all, and its title
    to recognise it by. `ordinal` None: no slide to start at (`note` says why); the talk then starts at page 1."""
    ordinal: Optional[int]
    slides: int = 0
    title: str = ""
    note: str = ""


def selected_slide(window, deck: Deck) -> StartSlide:
    """The slide chosen in the slide list, as a place among the presenter PDF's frames. The presenter PDF is the
    Instructor view: a slide only other views typeset has no frame (the next one that does is taken), and slides
    in front of it that the Instructor view leaves out do not count."""
    state = window.state
    if state.focused_slide is None:
        return StartSlide(None, note="No slide is selected, so the presentation starts at the beginning.")
    row = deck_outline.slide_row(window.project, deck, state.focused_slide, state.view, state.language,
                                 occurrence_key=state.focused_occurrence, outline=state.outline)
    if row is None:
        return StartSlide(None, note="The selected slide is not in this deck, so the presentation starts at the beginning.")
    slots = deck_outline.resolve_slots(window.project, deck, deck_editor.VIEW_INSTRUCTOR, state.language)
    typeset = [slot for slot in slots if not slot.hidden]
    index = next((i for i, slot in enumerate(slots) if slot.key == row.key), None)
    if index is None or not typeset:
        return StartSlide(None, note="The selected slide is not in the presenter PDF, so the presentation starts at the beginning.")
    ahead = [slot for slot in slots[index:] if not slot.hidden]
    if not ahead:
        return StartSlide(None, note="The selected slide and those after it are not in the presenter PDF, so the "
                                     "presentation starts at the beginning.")
    chosen = ahead[0]
    ordinal = typeset.index(chosen) + 1
    title = row.title if chosen.key == row.key else ""
    note = "" if chosen.key == row.key else "The selected slide is not in the presenter PDF; starting at the next one that is."
    return StartSlide(ordinal, len(typeset), title, note)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def start_page_for(slide: StartSlide, deck: PresentationDeck, frames: Optional[FrameMap]) -> tuple[int, str]:
    """(page, message): the first page of `slide` in the PDF; message is a note for the toast ("" for none).
    The slide's place in the list is trusted when the PDF has as many frames as the list has slides; otherwise (a
    generated appendix or agenda in the PDF, a PDF older than the deck) the slide is looked for by its title."""
    if slide.ordinal is None:
        return 0, slide.note
    pages = resume_ui.slide_pages(deck, frames)
    guess = min(slide.ordinal, len(pages)) - 1
    title = _norm(slide.title)

    def shows_title(index: int) -> bool:
        try:
            return bool(title) and title in _norm(deck.slide_text(pages[index]))
        except (RuntimeError, ValueError):
            return False
    if len(pages) == slide.slides or shows_title(guess):
        return pages[guess], slide.note
    found = sorted((i for i in range(len(pages)) if shows_title(i)), key=lambda i: abs(i - guess))
    if found:
        return pages[found[0]], slide.note
    return 0, "The presenter PDF does not match the deck's slide list (compile it again), so the presentation starts at the beginning."


def on_present_here(window, deck: Deck) -> None:
    """Present, starting at the slide chosen in the slide list (and without offering to continue an earlier talk)."""
    on_present(window, deck, start_slide=selected_slide(window, deck))


def on_present(window, deck: Deck, after_compile: bool = False, start_slide: Optional[StartSlide] = None) -> None:
    if getattr(window, "presentation", None) is not None:
        return                                    # one presentation at a time
    found = find_presenter_pdf(window.project, deck)
    if found.presenter is None:
        if after_compile:
            QMessageBox.information(window, "Present", "No presenter PDF was created, so there is nothing to present.")
            return
        choice = _ask(window, "No presenter PDF yet",
                      f"{deck.name} has no presenter PDF (the one with the notes). Compile it now?",
                      "Compile and present", "Present the normal PDF (no notes)" if found.plain else None)
        if choice == 0:
            _compile_then_present(window, deck, start_slide)
        elif choice == 1 and found.plain is not None:
            _start(window, found.plain, deck, start_slide)
        return
    if found.stale and not after_compile:
        choice = _ask(window, "Presenter PDF is older than the deck",
                      f"{found.presenter.path.name} is older than the deck's files.",
                      "Recompile first", "Present anyway")
        if choice == 0:
            _compile_then_present(window, deck, start_slide)
            return
        if choice != 1:
            return
    _start(window, found.presenter, deck, start_slide)


def _start(window, pdf: DeckPdf, deck: Deck, start_slide: Optional[StartSlide]) -> Optional[PresentationController]:
    return start(window, pdf, deck) if start_slide is None else start(window, pdf, deck, start_slide=start_slide)


def _ask(window, title: str, text: str, first: str, second: Optional[str]) -> int:
    """0 for the first button, 1 for the second, -1 for Cancel."""
    box = QMessageBox(QMessageBox.Icon.Question, title, text, parent=window)
    buttons = [box.addButton(first, QMessageBox.ButtonRole.AcceptRole)]
    if second:
        buttons.append(box.addButton(second, QMessageBox.ButtonRole.ActionRole))
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.exec()
    return buttons.index(box.clickedButton()) if box.clickedButton() in buttons else -1


def _compile_then_present(window, deck: Deck, start_slide: Optional[StartSlide] = None) -> None:
    from ..workspace import compile_actions
    compile_actions.compile_current(window, "presenter")
    if not window.compile.running:
        return                                    # it did not start (busy, cancelled, nothing to typeset)

    def settled(_run) -> None:
        window.compile.settled.disconnect(settled)
        on_present(window, deck, after_compile=True, start_slide=start_slide)
    window.compile.settled.connect(settled)


def start(window, pdf: DeckPdf, deck: Optional[Deck] = None, *,
          start_slide: Optional[StartSlide] = None) -> Optional[PresentationController]:
    """Presents `pdf`. With `start_slide` the talk starts at that slide and no earlier talk is offered to continue."""
    try:
        presentation_deck = PresentationDeck(pdf.path)
    except (ValueError, RuntimeError, OSError) as exc:
        QMessageBox.warning(window, "Present", f"{pdf.path.name} could not be opened: {exc}")
        return None
    settings = PresentationSettings.load()
    frames = frames_mod.load_for(window.project, deck, pdf.path, presentation_deck.page_count) if deck is not None else None
    if frames is None:
        frames = presentation_deck.frame_map()      # no .nav kept: the page labels, if the PDF has usable ones
    key = resume.deck_key_for_deck(deck.path) if deck is not None else resume.deck_key_for_pdf(pdf.path)
    note = ""
    if start_slide is not None:
        page, note = start_page_for(start_slide, presentation_deck, frames)
    else:
        page = resume_ui.start_page(window, presentation_deck, frames, key, settings)
    controller = PresentationController(
        presentation_deck, settings, main_screen=window.screen(), frames=frames, start_page=page,
        save_settings=lambda changed: changed.save())
    resume_ui.remember(controller, presentation_deck, frames, key)
    window.presentation = controller
    controller.finished.connect(lambda: setattr(window, "presentation", None))
    renderer = getattr(getattr(window, "background", None), "renderer", None)
    if renderer is not None:
        renderer.presentation_started()          # no background render during the talk
    controller.start()
    if note:
        controller._toast(note, 6000)
    return controller
