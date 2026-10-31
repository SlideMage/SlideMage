# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The "Present deck" command (plan 4.9): find the PDF, ask what to do when there is none or it is old,
then start the presentation."""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QMessageBox

from ...compiler import DeckPdf
from ...deck_scan import Deck
from ...presentation import frames as frames_mod
from ...presentation.locate import find_presenter_pdf
from ...presentation.pdf_source import PresentationDeck
from ...presentation.settings import PresentationSettings
from ...presentation import resume
from . import resume_ui
from .controller import PresentationController


def on_present(window, deck: Deck, after_compile: bool = False) -> None:
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
            _compile_then_present(window, deck)
        elif choice == 1 and found.plain is not None:
            start(window, found.plain, deck)
        return
    if found.stale and not after_compile:
        choice = _ask(window, "Presenter PDF is older than the deck",
                      f"{found.presenter.path.name} is older than the deck's files.",
                      "Recompile first", "Present anyway")
        if choice == 0:
            _compile_then_present(window, deck)
            return
        if choice != 1:
            return
    start(window, found.presenter, deck)


def _ask(window, title: str, text: str, first: str, second: Optional[str]) -> int:
    """0 for the first button, 1 for the second, -1 for Cancel."""
    box = QMessageBox(QMessageBox.Icon.Question, title, text, parent=window)
    buttons = [box.addButton(first, QMessageBox.ButtonRole.AcceptRole)]
    if second:
        buttons.append(box.addButton(second, QMessageBox.ButtonRole.ActionRole))
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.exec()
    return buttons.index(box.clickedButton()) if box.clickedButton() in buttons else -1


def _compile_then_present(window, deck: Deck) -> None:
    from ..workspace import compile_actions
    compile_actions.compile_current(window, "presenter")
    if not window.compile.running:
        return                                    # it did not start (busy, cancelled, nothing to typeset)

    def settled(_run) -> None:
        window.compile.settled.disconnect(settled)
        on_present(window, deck, after_compile=True)
    window.compile.settled.connect(settled)


def start(window, pdf: DeckPdf, deck: Optional[Deck] = None) -> Optional[PresentationController]:
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
    controller = PresentationController(
        presentation_deck, settings, main_screen=window.screen(), frames=frames,
        start_page=resume_ui.start_page(window, presentation_deck, frames, key, settings),
        save_settings=lambda changed: changed.save())
    resume_ui.remember(controller, presentation_deck, frames, key)
    window.presentation = controller
    controller.finished.connect(lambda: setattr(window, "presentation", None))
    renderer = getattr(getattr(window, "background", None), "renderer", None)
    if renderer is not None:
        renderer.presentation_started()          # no background render during the talk
    controller.start()
    return controller
