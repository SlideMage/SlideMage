# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Continuing a talk where it stopped (docs/plans/presenter-app.md, 5c): finding the slide again, the store, and the
question and saving in the Qt layer. The layout store is isolated by conftest."""
from __future__ import annotations

import time
from dataclasses import asdict

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from presentation_fixtures import make_pdf
from slidemage.presentation import resume
from slidemage.presentation.frame_map import FrameMap
from slidemage.presentation.pdf_source import PresentationDeck
from slidemage.presentation.resume import Offer, Place
from slidemage.presentation.settings import PresentationSettings
from slidemage.ui import layout_settings
from slidemage.ui.presentation import resume_ui
from slidemage.ui.presentation.controller import PresentationController

NOW = 1_000_000_000.0
DAY = 86400
FPS = ["a", "b", "c", "d", "e", "f"]
TITLES = list("ABCDEF")


def place(slide=3, count=6, fp="c", saved=NOW):
    return Place(slide, count, "T", fp, saved)


def test_offer_the_same_slide():
    assert resume.offer(place(), FPS, TITLES, NOW) == Offer(3, "C")


def test_offer_finds_a_moved_slide_and_the_nearest_copy_wins():
    assert resume.offer(place(3), ["a", "x", "b", "c", "d", "e"], TITLES, NOW) == Offer(4, "D", moved_from=3)
    twice = ["c", "a", "b", "x", "y", "c"]          # slides 1 and 6; stored 4 -> 6 is nearer
    assert resume.offer(place(4), twice, TITLES, NOW) == Offer(6, "F", moved_from=4)
    tie = ["a", "c", "b", "c", "e", "f"]            # stored 3: 2 and 4 are equally near, the earlier wins
    assert resume.offer(place(3), tie, TITLES, NOW) == Offer(2, "B", moved_from=3)


def test_offer_for_a_changed_slide_is_clamped():
    assert resume.offer(place(5, count=9), ["a", "b", "x", "y"], TITLES, NOW) == Offer(4, "D", changed=True)
    assert resume.offer(place(3), ["a", "b", "x", "y"], TITLES, NOW) == Offer(3, "C", changed=True)
    assert resume.offer(place(5, count=9), ["a"], ["A"], NOW) is None      # clamps to the first slide


def test_nothing_is_offered_at_the_start_the_end_when_old_or_unknown():
    assert resume.offer(None, FPS, TITLES, NOW) is None
    assert resume.offer(place(1), FPS, TITLES, NOW) is None
    assert resume.offer(place(6, count=6), FPS, TITLES, NOW) is None
    assert resume.offer(place(saved=NOW - 31 * DAY), FPS, TITLES, NOW) is None
    assert resume.offer(place(saved=NOW - 29 * DAY), FPS, TITLES, NOW) is not None
    assert resume.offer(place(), [], [], NOW) is None


def test_fingerprint_ignores_digits_case_and_spacing_but_not_words():
    base = resume.fingerprint("Results", "Mean 4\nSlide 7  of 20")
    assert base == resume.fingerprint("results", "Mean   9\n\nslide 8 of 21")
    assert base != resume.fingerprint("Results", "Median 4\nSlide 7 of 20")
    assert len(base) == 16


def test_places_round_trip_ignore_bad_entries_and_keep_the_newest():
    assert resume.load("k") is None
    resume.save("k", place())
    assert resume.load("k") == place()
    layout_settings.set(resume.STORE_KEY, {"k": {**asdict(place()), "slide": "x"}, "bad": 5, "worse": {"slide": 1}})
    assert resume.load("k") is None and resume.load("bad") is None and resume.load("worse") is None
    layout_settings.set(resume.STORE_KEY, "nonsense")
    assert resume.load("k") is None
    for number in range(resume.MAX_PLACES + 5):
        resume.save(f"d{number}", place(saved=NOW + number))
    stored = layout_settings.get(resume.STORE_KEY)
    assert len(stored) == resume.MAX_PLACES
    assert "d0" not in stored and f"d{resume.MAX_PLACES + 4}" in stored


def test_deck_keys_differ_by_kind():
    assert resume.deck_key_for_pdf("a.pdf").startswith("pdf:") and resume.deck_key_for_deck("a.tex").startswith("deck:")


# -- the Qt side -------------------------------------------------------------------------------

@pytest.fixture
def deck(tmp_path, qapp):
    deck = PresentationDeck(make_pdf(tmp_path / "p.pdf"))
    yield deck
    try:
        deck.close()                                     # a test may have ended a presentation, which closes it
    except ValueError:
        pass


def store_place(deck, slide, page=None):
    page = slide - 1 if page is None else page
    title = deck.title(page)
    resume.save("k", Place(slide, deck.page_count, title, resume.fingerprint(title, deck.slide_text(page)), time.time()))


def test_continue_returns_the_first_page_of_the_slide(deck, monkeypatch):
    store_place(deck, 4)
    asked = []
    monkeypatch.setattr(resume_ui, "_ask", lambda parent, offer: asked.append(offer) or True)
    assert resume_ui.start_page(None, deck, None, "k", PresentationSettings()) == 3
    assert asked == [Offer(4, "Slide 4")]
    monkeypatch.setattr(resume_ui, "_ask", lambda parent, offer: False)
    assert resume_ui.start_page(None, deck, None, "k", PresentationSettings()) == 0


def test_continue_uses_the_first_reveal_step_of_a_frame(deck, monkeypatch):
    frames = FrameMap(((0, 0), (1, 2), (3, 3), (4, 5)))
    store_place(deck, 2, page=1)                         # slide 2 is pages 1-2 and starts on page 1
    monkeypatch.setattr(resume_ui, "_ask", lambda parent, offer: True)
    assert resume_ui.start_page(None, deck, frames, "k", PresentationSettings()) == 1
    assert resume_ui.slide_pages(deck, frames) == [0, 1, 3, 4]


def test_nothing_is_asked_when_switched_off_or_nothing_is_stored(deck, monkeypatch):
    monkeypatch.setattr(resume_ui, "_ask", lambda parent, offer: pytest.fail("must not ask"))
    assert resume_ui.start_page(None, deck, None, "k", PresentationSettings()) == 0
    store_place(deck, 4)
    assert resume_ui.start_page(None, deck, None, "k", PresentationSettings(offer_resume=False)) == 0


def test_the_question_names_the_slide_and_the_buttons(monkeypatch, qapp):
    seen = {}

    def fake_exec(box):
        seen["text"], seen["info"] = box.text(), box.informativeText()
        seen["buttons"] = [button.text() for button in box.buttons()]
        seen["default"] = box.defaultButton().text()
        return 0
    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    assert resume_ui._ask(None, Offer(23, "Results", moved_from=22)) is False       # nothing clicked: the beginning
    assert seen["text"] == "Continue at slide 23 (Results)?" and "slide 22" in seen["info"]
    assert seen["buttons"] == ["Continue", "Start from the beginning"] and seen["default"] == "Continue"
    resume_ui._ask(None, Offer(5, "", changed=True))
    assert seen["text"] == "Continue at slide 5?" and "changed" in seen["info"]


def test_remember_saves_the_place_when_the_talk_ends(deck, qapp):
    controller = PresentationController(deck, PresentationSettings(), frames=None, save_settings=lambda s: None)
    resume_ui.remember(controller, deck, None, "k")
    controller.session.goto(2)
    controller.session.goto(4)
    controller.end()
    saved = resume.load("k")
    assert saved is not None and saved.slide == 5 and saved.count == 6 and saved.title == "Slide 5"
    assert saved.fingerprint == resume.fingerprint("Slide 5", "Slide 5")


def test_remember_saves_after_a_rest_and_never_raises(deck, qapp, monkeypatch):
    controller = PresentationController(deck, PresentationSettings(), frames=None, save_settings=lambda s: None)
    resume_ui.remember(controller, deck, None, "k")
    controller.session.goto(3)
    (timer,) = [t for t in controller.findChildren(QTimer) if t.interval() == resume_ui.SAVE_DELAY_MS]
    assert timer.isActive() and resume.load("k") is None
    timer.timeout.emit()
    assert resume.load("k").slide == 4

    def broken(key, value):
        raise OSError("disk")
    monkeypatch.setattr(resume, "save", broken)
    controller.session.goto(4)
    timer.timeout.emit()
    controller.end()
