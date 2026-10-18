"""The window's side of background rendering: the input watcher, the deck usage, the chip and its menu, the settings."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from slidemage import app_settings, background_renders
from slidemage.background_renders import DeckProgress, Progress
from slidemage.ui.dialogs.settings import GENERAL, SettingsSheet
from conftest import EXAMPLE_PROJECT, build_window, qapp as qapp
from test_settings_gui import FakeApp


@pytest.fixture
def window(qapp, monkeypatch):
    return build_window(monkeypatch)


def test_nothing_is_started_by_a_window_under_test_and_the_chip_is_hidden(window):
    controller = window.background
    assert controller.renderer is not None and controller.store is not None
    assert not controller.renderer.scheduler._threads
    controller.refresh()
    assert controller.chip.isHidden()


def test_opening_a_deck_and_focusing_a_slide_are_remembered_for_the_order(window):
    window.state.set_deck(window.decks[0]) if window.state.deck is None else None
    deck = window.state.deck
    usage = {u["deck"]: u for u in window.background.store.deck_usage()}
    assert deck.name in usage and usage[deck.name]["open_count"] >= 1
    window.state.set_focused_slide("tnb")
    window.state.set_view("after-course")
    window.state.set_language("DE")
    usage = {u["deck"]: u for u in window.background.store.deck_usage()}[deck.name]
    assert (usage["last_slide"], usage["last_view"], usage["last_language"]) == ("tnb", "after-course", "DE")


def test_user_input_anywhere_in_the_application_resets_the_idle_clock(window):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QKeyEvent, QMouseEvent
    from PySide6.QtWidgets import QApplication

    gate = window.background.renderer.gate
    gate.last_input = -1000.0
    QApplication.sendEvent(window.topbar, QMouseEvent(
        QEvent.Type.MouseMove, QPointF(3, 3), Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
    assert gate.last_input > -1000.0
    gate.last_input = -1000.0
    QApplication.sendEvent(window.topbar, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Shift, Qt.KeyboardModifier.NoModifier))
    assert gate.last_input > -1000.0


def test_the_chip_says_what_is_going_on_and_only_then(window):
    controller = window.background
    window.show()
    progress = Progress([DeckProgress("a", total=10, fresh=4), DeckProgress("b", total=5)])
    controller.renderer.progress = progress
    assert controller.summary() == ("Previews · 11 left", "muted")
    progress.working = "a:1jh:instructor:EN"
    assert controller.summary() == ("Preparing previews · 11 left", "info")
    progress.working = None
    progress.paused_because = "you are working"
    assert controller.summary() == ("Previews paused (you are working) · 11 left", "muted")
    controller.refresh()
    assert controller.chip.isVisible() and "paused" in controller.chip.text()
    controller.renderer.progress = Progress([DeckProgress("a", total=3, fresh=3)], failures=2)
    assert controller.summary() == ("2 slides cannot be rendered", "warning")
    controller.renderer.progress = Progress([DeckProgress("a", total=3, fresh=3)])
    controller.refresh()
    assert controller.chip.isHidden()
    app_settings.set(window.project, background_renders.ENABLED_KEY, False)
    controller.renderer.progress = progress
    assert controller.summary()[0] == ""


def test_the_menu_lists_the_decks_and_pauses_renders_now_and_skips_the_open_deck(window):
    controller = window.background
    controller.renderer.progress = Progress([DeckProgress("slidemage-manual", total=10, fresh=4, failed=1)], failures=1)
    texts = [a.text() for a in controller.menu().actions()]
    assert "slidemage-manual: 4 of 10 ready, 1 failed" in texts
    assert any(t.startswith("Stored:") for t in texts) and "Pause" in texts and "Render now" in texts
    assert "Show the 1 failed slides…" in texts
    controller.toggle_pause()
    assert controller.renderer.gate.paused and controller.renderer.gate.reason() == "paused"
    assert "Resume" in [a.text() for a in controller.menu().actions()]
    controller.render_now()
    assert not controller.renderer.gate.paused
    name = window.state.deck.name
    controller.set_deck_enabled(name, False)
    assert name in app_settings.get(window.project, background_renders.DECKS_OFF_KEY)
    assert name not in [d.name for d in controller.renderer.ordered_decks()]
    controller.set_deck_enabled(name, True)
    assert name in [d.name for d in controller.renderer.ordered_decks()]


def test_retrying_failed_slides_forgets_the_failures(window):
    controller = window.background
    controller.store.record_failure("k" * 64, "deterministic", "boom", [])
    assert controller.store.failures()
    controller.retry_failed()
    assert not controller.store.failures()


def test_the_gate_waits_for_a_compile_a_dialog_and_the_preview(window, monkeypatch):
    controller = window.background
    assert controller._busy_reasons() == []
    monkeypatch.setattr(type(window.compile), "running", property(lambda self: True))
    assert controller._busy_reasons() == ["a compile"]
    monkeypatch.undo()
    window.centre.preview._busy = True
    assert controller._busy_reasons() == ["the Preview"]


def test_archiving_a_deck_tells_the_renderer(window, monkeypatch):
    told = []
    monkeypatch.setattr(window.background, "deck_archived", told.append)
    monkeypatch.setattr(deck_archive := __import__("slidemage.archive", fromlist=["archive_deck"]), "archive_deck", lambda *a: None)
    from slidemage.ui.workspace import deck_actions
    monkeypatch.setattr(window, "reload_decks", lambda: None)
    deck_actions.do_archive_deck(window, window.state.deck)
    assert told == [window.state.deck]


def test_stopping_the_window_closes_the_store(window):
    window.background.stop()
    assert window.background.store is None


# -- the settings --------------------------------------------------------------------------

def test_the_settings_have_the_background_controls_and_save_them(qapp, monkeypatch):
    app = FakeApp()
    changed = []
    app.background = type("C", (), {"store": None, "settings_changed": lambda self: changed.append(1)})()
    sheet = SettingsSheet(app)
    project = app.project
    general = next(w for w in sheet.findChildren(object) if hasattr(w, "bg_check"))
    assert general.bg_check.isChecked() and general.bg_mains_check.isChecked()
    assert general.bg_limit.value() == background_renders.DEFAULT_LIMIT_GB
    general.bg_check.setChecked(False)
    general.bg_mains_check.setChecked(False)
    general.bg_limit.setValue(12.5)
    general.bg_limit.editingFinished.emit()
    general.bg_profile.setCurrentIndex(general.bg_profile.findData("fast"))
    assert app_settings.get(project, background_renders.ENABLED_KEY) is False
    assert app_settings.get(project, background_renders.ONLY_MAINS_KEY) is False
    assert app_settings.get(project, background_renders.LIMIT_GB_KEY) == 12.5
    assert app_settings.get(project, background_renders.PROFILE_KEY) == "fast"
    assert len(changed) >= 4


# -- the Preview ------------------------------------------------------------------------------

def test_the_preview_shows_a_current_stored_render_and_not_an_outdated_one(window, tmp_path):
    import os
    import shutil
    import time

    from slidemage import deck_editor, preview_target
    from slidemage.compiler import CancelToken
    from test_background_renders import FakeTeX

    deck = window.state.deck
    call = deck_editor.parse_slide_calls(deck)[0]
    target = preview_target.for_call(window.project, deck, call, 1)
    controller = window.background
    renderer = controller.renderer
    renderer._render = FakeTeX(window.project, pages=2)
    old = time.time() - 3600
    for path in (target.source_path, *target.source_path.parent.glob("*")):
        os.utime(path, (old, old))
    unit = background_renders.render_key.unit_for(target, "instructor", "EN", deck.name)
    assert controller.stored_page(target, "instructor", "EN") is None
    assert window.centre.preview._stored_pixmap(target, "instructor", "EN") is None
    renderer.render_unit(unit, background_renders.ORIGIN_BACKGROUND, CancelToken())
    pixmap = window.centre.preview._stored_pixmap(target, "instructor", "EN")
    assert pixmap is not None and pixmap.width() == background_renders.STORE_WIDTH
    shown = window.centre.preview._image(target)
    assert shown is not None and shown[1] is True and shown[2] == ""
    path = target.source_path
    try:
        original = path.read_bytes()
        path.write_bytes(original + b"\n% edited\n")
        os.utime(path, (old, old))
        assert controller.stored_page(target, "instructor", "EN") is None      # the slide changed: never shown as current
    finally:
        path.write_bytes(original)
        os.utime(path, (old, old))
        shutil.rmtree(controller.store.root, ignore_errors=True)       # the example project is shared by the tests
