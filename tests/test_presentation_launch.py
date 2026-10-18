"""The "Present deck" command: which PDF it starts with, and what it asks when there is none or it is old."""
from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from slidemage.compiler import DeckPdf
from slidemage.presentation.locate import Found
from slidemage.ui.presentation import launch
from slidemage.ui.workspace import compile_actions
from slidemage.ui.workspace.actions import build_registry

DECK = SimpleNamespace(name="deck")


def pdf(label="Presenter"):
    return DeckPdf(label, Path("deck-presenter.pdf"), time.time(), preferred=False)


@pytest.fixture
def calls(monkeypatch):
    calls = SimpleNamespace(started=[], compiled=[], asked=[], answers=[])
    monkeypatch.setattr(launch, "start", lambda window, found: calls.started.append(found))
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
