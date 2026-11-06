# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The "Present deck" command: which PDF it starts with, and what it asks when there is none or it is old."""
from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from slidemage.compiler import DeckPdf
from slidemage.presentation.frame_map import FrameMap
from slidemage.presentation.locate import Found
from slidemage.ui.presentation import launch
from slidemage.ui.workspace import compile_actions
from slidemage.ui.workspace.actions import build_registry

DECK = SimpleNamespace(name="deck")


def pdf(label="Presenter"):
    return DeckPdf(label, Path("deck-presenter.pdf"), time.time(), preferred=False)


@pytest.fixture
def calls(monkeypatch):
    calls = SimpleNamespace(started=[], compiled=[], asked=[], answers=[], slides=[])
    monkeypatch.setattr(launch, "start", lambda window, found, deck=None, **kw: calls.started.append(found) or calls.slides.append(kw.get("start_slide")))
    monkeypatch.setattr(compile_actions, "compile_current", lambda window, kind: calls.compiled.append(kind))
    monkeypatch.setattr(launch, "_ask", lambda *args: calls.asked.append(args[1]) or calls.answers.pop(0))
    monkeypatch.setattr(launch.QMessageBox, "information", lambda *args: calls.asked.append("info"))
    return calls


def window():
    connected = []
    compile_controller = SimpleNamespace(running=False, settled=SimpleNamespace(connect=connected.append))
    return SimpleNamespace(project=None, presentation=None, compile=compile_controller, connected=connected)


def test_a_current_presenter_pdf_starts_at_once(monkeypatch, calls):
    presenter = pdf()
    monkeypatch.setattr(launch, "find_presenter_pdf", lambda ctx, deck: Found(presenter, False, None))
    launch.on_present(window(), DECK)
    assert calls.started == [presenter] and calls.asked == []


def test_no_presenter_pdf_offers_to_compile_or_to_present_the_normal_pdf(monkeypatch, calls):
    plain = pdf("Instructor")
    monkeypatch.setattr(launch, "find_presenter_pdf", lambda ctx, deck: Found(None, False, plain))
    calls.answers[:] = [1, 0, -1]
    launch.on_present(window(), DECK)
    assert calls.started == [plain] and calls.compiled == []
    shown = window()
    shown.compile.running = True
    launch.on_present(shown, DECK)                      # "Compile and present"
    assert calls.compiled == ["presenter"] and len(shown.connected) == 1
    launch.on_present(window(), DECK)                   # Cancel
    assert calls.started == [plain] and calls.compiled == ["presenter"]


def test_an_old_presenter_pdf_asks_to_recompile_or_present_anyway(monkeypatch, calls):
    presenter = pdf()
    monkeypatch.setattr(launch, "find_presenter_pdf", lambda ctx, deck: Found(presenter, True, None))
    calls.answers[:] = [1, 0]
    launch.on_present(window(), DECK)
    assert calls.started == [presenter]
    launch.on_present(window(), DECK)
    assert calls.compiled == ["presenter"] and calls.started == [presenter]    # the compile did not start here: nothing waits


def test_after_a_compile_that_made_no_pdf_the_user_is_told(monkeypatch, calls):
    monkeypatch.setattr(launch, "find_presenter_pdf", lambda ctx, deck: Found(None, False, None))
    launch.on_present(window(), DECK, after_compile=True)
    assert calls.asked == ["info"] and calls.started == []


def test_only_one_presentation_runs_at_a_time(monkeypatch, calls):
    monkeypatch.setattr(launch, "find_presenter_pdf", lambda ctx, deck: pytest.fail("looked for a PDF"))
    busy = window()
    busy.presentation = object()
    launch.on_present(busy, DECK)


def test_the_command_is_in_the_palette_with_f5_and_needs_a_deck():
    command = build_registry()["present"]
    assert command.shortcut == "F5" and command.title(None) == "Present deck"
    assert not command.enabled(SimpleNamespace(state=SimpleNamespace(deck=None)))


# -- Present from current slide (Shift+F5) --------------------------------------------------

def slot(key, hidden=False):
    return SimpleNamespace(key=key, hidden=hidden)


def chosen_window(focused="aaa"):
    state = SimpleNamespace(focused_slide=focused, focused_occurrence=None, view="instructor", language="EN", outline=None)
    shown = window()
    shown.state = state
    return shown


def rows_and_slots(monkeypatch, slots, row_key, title="Second"):
    monkeypatch.setattr(launch.deck_outline, "slide_row",
                        lambda *a, **k: SimpleNamespace(key=row_key, title=title) if row_key is not None else None)
    monkeypatch.setattr(launch.deck_outline, "resolve_slots", lambda *a, **k: slots)


def test_the_command_is_in_the_palette_with_shift_f5_and_needs_a_deck():
    command = build_registry()["present_here"]
    assert command.shortcut == "Shift+F5" and command.title(None) == "Present from current slide"
    assert not command.enabled(SimpleNamespace(state=SimpleNamespace(deck=None)))


def test_shift_f5_is_in_the_shortcuts_dialog():
    from slidemage.ui.dialogs.shortcuts import shortcut_rows
    rows = [pair for _heading, keys in shortcut_rows(build_registry()) for pair in keys]
    assert any("Present from current slide" in str(pair) and "Shift+F5" in str(pair) for pair in rows), rows


def test_the_start_slide_is_the_selected_ones_place_among_the_frames_the_instructor_pdf_has(monkeypatch):
    rows_and_slots(monkeypatch, [slot("a"), slot("x", hidden=True), slot("b"), slot("c")], "b")
    found = launch.selected_slide(chosen_window(), DECK)
    assert (found.ordinal, found.slides, found.title, found.note) == (2, 3, "Second", "")      # the hidden one has no frame


def test_a_selected_slide_without_a_frame_starts_at_the_next_one_that_has_one(monkeypatch):
    rows_and_slots(monkeypatch, [slot("a"), slot("x", hidden=True), slot("c")], "x")
    found = launch.selected_slide(chosen_window(), DECK)
    assert found.ordinal == 2 and found.title == "" and "next one" in found.note
    rows_and_slots(monkeypatch, [slot("a"), slot("x", hidden=True)], "x")
    found = launch.selected_slide(chosen_window(), DECK)
    assert found.ordinal is None and found.note


def test_no_selected_slide_starts_at_the_beginning_with_a_note(monkeypatch):
    found = launch.selected_slide(chosen_window(focused=None), DECK)
    assert found.ordinal is None and "beginning" in found.note
    rows_and_slots(monkeypatch, [slot("a")], None)
    assert launch.selected_slide(chosen_window(), DECK).ordinal is None


class Pages:
    def __init__(self, texts):
        self.texts = texts

    def slide_text(self, page):
        return self.texts[page]


def test_the_start_page_is_the_first_page_of_the_frame(monkeypatch):
    frames = FrameMap(((0, 0), (1, 3), (4, 4)))
    deck = Pages(["one", "two", "two", "two", "three"])
    assert launch.start_page_for(launch.StartSlide(2, 3, "Two"), deck, frames) == (1, "")
    assert launch.start_page_for(launch.StartSlide(3, 3, "Three"), deck, frames) == (4, "")
    assert launch.start_page_for(launch.StartSlide(None, note="why"), deck, frames) == (0, "why")


def test_a_pdf_with_other_frames_than_the_list_is_searched_by_title():
    frames = FrameMap(((0, 0), (1, 1), (2, 2), (3, 3)))                 # an agenda frame came first
    deck = Pages(["Agenda", "Intro", "Method", "Results"])
    assert launch.start_page_for(launch.StartSlide(2, 3, "Method"), deck, frames) == (2, "")
    page, note = launch.start_page_for(launch.StartSlide(2, 3, "Gone"), deck, frames)
    assert page == 0 and "does not match" in note


def test_present_from_here_carries_the_slide_through_every_path(monkeypatch, calls):
    rows_and_slots(monkeypatch, [slot("a"), slot("b")], "b")
    presenter = pdf()
    monkeypatch.setattr(launch, "find_presenter_pdf", lambda ctx, deck: Found(presenter, False, None))
    launch.on_present_here(chosen_window(), DECK)
    assert calls.started == [presenter] and calls.slides[0].ordinal == 2
    monkeypatch.setattr(launch, "find_presenter_pdf", lambda ctx, deck: Found(presenter, True, None))
    calls.answers[:] = [1]
    launch.on_present_here(chosen_window(), DECK)                       # "Present anyway"
    assert calls.slides[1].ordinal == 2
    # after a compile the same slide is used
    monkeypatch.setattr(launch, "find_presenter_pdf", lambda ctx, deck: Found(None, False, None))
    calls.answers[:] = [0]
    shown = chosen_window()
    shown.compile.running = True
    launch.on_present_here(shown, DECK)
    monkeypatch.setattr(launch, "find_presenter_pdf", lambda ctx, deck: Found(presenter, False, None))
    shown.compile.settled.disconnect = lambda f: None
    shown.connected[0](None)
    assert calls.slides[2].ordinal == 2


def test_an_explicit_start_slide_skips_the_resume_offer(monkeypatch, tmp_path, qapp):
    from presentation_fixtures import make_pdf
    seen = {}

    class Controller:
        def __init__(self, deck, settings, **kw):
            seen.update(kw)
            self.session = SimpleNamespace(page_changed=SimpleNamespace(connect=lambda f: None))
            self.finished = SimpleNamespace(connect=lambda f: None)

        def start(self):
            pass

        def _toast(self, *a):
            seen["toast"] = a

    monkeypatch.setattr(launch, "PresentationController", Controller)
    monkeypatch.setattr(launch.resume_ui, "remember", lambda *a: None)
    monkeypatch.setattr(launch.resume_ui, "start_page", lambda *a: pytest.fail("offered to continue"))
    monkeypatch.setattr(launch.frames_mod, "load_for", lambda *a: FrameMap(((0, 0), (1, 2), (3, 5))))
    monkeypatch.setattr(launch.resume, "deck_key_for_deck", lambda path: "k")
    shown = chosen_window()
    shown.screen = lambda: None
    shown.project = None
    launch.start(shown, DeckPdf("Presenter", make_pdf(tmp_path / "d.pdf"), time.time(), preferred=False),
                 SimpleNamespace(path=Path("d.tex")), start_slide=launch.StartSlide(3, 3, "Slide 4"))
    assert seen["start_page"] == 3
