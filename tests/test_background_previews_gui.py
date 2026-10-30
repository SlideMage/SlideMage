# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The window's side of background rendering: the input watcher, the deck usage, the chip and its menu, the settings."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QApplication

from slidemage import app_settings, background_renders
from slidemage.background_renders import DeckProgress, Progress
from slidemage.ui.dialogs.settings import SettingsSheet
from slidemage.ui.workspace import background_previews
from conftest import build_window, qapp as qapp
from test_settings_gui import FakeApp


@pytest.fixture
def window(qapp, monkeypatch):
    window = build_window(monkeypatch)
    if window.background.renderer is not None:
        window.background.renderer.gate.in_front = None     # as without a window that reports its focus; the tests
    return window                                           # of the focus rules report it themselves


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
    window.topbar.setMouseTracking(True)
    # Qt's own mouse moves (widgets appearing under a still cursor) are not the user: the sent event is not spontaneous
    QApplication.sendEvent(window.topbar, QMouseEvent(
        QEvent.Type.MouseMove, QPointF(3, 3), Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
    assert gate.last_input == -1000.0

    class Move:                       # a real mouse move: spontaneous, with a position
        def __init__(self, x):
            self.x = x

        def type(self):
            return QEvent.Type.MouseMove

        def spontaneous(self):
            return True

        def globalPosition(self):
            return QPointF(self.x, 5)

    watcher = window.background._watcher
    watcher.eventFilter(window.topbar, Move(10))
    assert gate.last_input > -1000.0
    gate.last_input = -1000.0
    watcher.eventFilter(window.topbar, Move(10))        # the cursor did not move
    assert gate.last_input == -1000.0
    watcher.eventFilter(window.topbar, Move(11))
    assert gate.last_input > -1000.0
    gate.last_input = -1000.0
    QApplication.sendEvent(window.topbar, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Shift, Qt.KeyboardModifier.NoModifier))
    assert gate.last_input > -1000.0


def test_input_watcher_tracks_new_dialogs_but_not_private_qobjects(qapp, monkeypatch):
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QDialog, QLineEdit

    monkeypatch.setattr(background_previews, "USE_WIDGET_INPUT_WATCHER", True)
    window = build_window(monkeypatch)
    gate = window.background.renderer.gate
    dialog = QDialog(window)
    edit = QLineEdit(dialog)
    dialog.show()
    QTest.qWait(300)  # discover widgets created after the watcher started
    try:
        gate.last_input = -1000.0
        QTest.keyClick(edit, Qt.Key.Key_A)
        assert gate.last_input > -1000.0

        gate.last_input = -1000.0
        internal = QObject()
        QApplication.sendEvent(internal, QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier))
        assert gate.last_input == -1000.0

        window.background.stop()
        QTest.keyClick(edit, Qt.Key.Key_B)
        assert gate.last_input == -1000.0
    finally:
        dialog.close()
        dialog.deleteLater()


def test_application_input_watcher_needs_no_widget_polling_and_is_removed_on_stop(qapp, monkeypatch):
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QLineEdit

    monkeypatch.setattr(background_previews, "USE_WIDGET_INPUT_WATCHER", False)

    def unexpected_widget_scan():
        raise AssertionError("The application filter must not scan widgets")

    monkeypatch.setattr(QApplication, "allWidgets", unexpected_widget_scan)
    inputs = []
    parent = QObject()
    watcher = background_previews._InputWatcher(lambda: inputs.append(True), parent)
    try:
        assert watcher._timer is None
        receiver = QObject()
        QApplication.sendEvent(receiver, QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier))
        assert inputs

        inputs.clear()
        edit = QLineEdit()  # created after the watcher: input is covered immediately
        QApplication.sendEvent(edit, QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_B, Qt.KeyboardModifier.NoModifier, "b"))
        assert inputs and edit.text() == "b"

        watcher.stop()
        inputs.clear()
        QApplication.sendEvent(receiver, QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_C, Qt.KeyboardModifier.NoModifier))
        QApplication.sendEvent(edit, QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_D, Qt.KeyboardModifier.NoModifier, "d"))
        assert not inputs and edit.text() == "bd"
    finally:
        watcher.stop()


def test_the_chip_says_what_is_going_on_and_when_all_is_done(window):
    controller = window.background
    window.show()
    progress = Progress([DeckProgress("a", total=10, fresh=4), DeckProgress("b", total=5)], scanned_at=1.0)
    controller.renderer.progress = progress
    assert controller.summary() == ("Previews · 11 left", "muted")
    rendering(controller.renderer, True)                             # a render runs (the scheduler's, not stopping)
    assert controller.summary() == ("Preparing previews · 11 left", "info")
    rendering(controller.renderer, False)
    progress.paused_because = "you are working"
    assert controller.summary() == ("Preview rendering paused (you are working) · 11 left", "muted")
    controller.refresh()
    assert controller.chip.isVisible() and "paused" in controller.chip.text()
    controller.renderer.progress = Progress([DeckProgress("a", total=3, fresh=3)], failures=2, scanned_at=1.0)
    assert controller.summary() == ("2 slides cannot be rendered", "warning")
    controller.renderer.progress = Progress([DeckProgress("a", total=3, fresh=3)], scanned_at=1.0)
    assert controller.summary() == ("All previews are up to date.", "ok_text")      # green text, no background
    controller.refresh()
    assert controller.chip.isVisible() and controller.dial.isVisible()
    app_settings.set(window.project, background_renders.ENABLED_KEY, False)
    controller.renderer.progress = progress
    assert controller.summary()[0] == ""


def test_the_chip_opens_the_status_window_which_pauses_renders_now_and_leaves_decks_out(window, monkeypatch):
    # The chip had a menu of its own that said less than the window; both open the window now (v8.66.0).
    controller = window.background
    name = window.state.deck.name
    # The renderer's planning thread replaces its progress at any time; this one stays for the test.
    progress = Progress([DeckProgress(name, total=10, fresh=4, failed=1)], failures=1, scanned_at=1.0)
    monkeypatch.setattr(type(controller.renderer), "progress", property(lambda _self: progress, lambda _self, _value: None),
                        raising=False)
    controller.chip.clicked.emit()
    dialog = controller._status_dialog
    assert dialog is not None and dialog.isVisible()
    assert "Stored previews:" in dialog.summary.text() and "Click for" not in dialog.summary.text()
    assert dialog.dial.text() == "40%"                                       # the large dial, top right
    assert not dialog.failures.isHidden() and not dialog.retry.isHidden()
    dialog.pause.click()
    assert controller.renderer.gate.paused and controller.renderer.gate.reason() == "paused"
    assert dialog.pause.text() == "Resume"
    dialog.render_now.click()
    assert not controller.renderer.gate.paused
    item = dialog.tree.topLevelItem(0)
    assert item.text(0) == name and item.checkState(0) == Qt.CheckState.Checked
    item.setCheckState(0, Qt.CheckState.Unchecked)                          # leave the deck out
    assert name in app_settings.get(window.project, background_renders.DECKS_OFF_KEY)
    assert name not in [d.name for d in controller.renderer.ordered_decks()]
    dialog.refresh()
    assert dialog.tree.topLevelItem(0).checkState(0) == Qt.CheckState.Unchecked   # the setting, before the next plan
    dialog.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Checked)
    assert name in [d.name for d in controller.renderer.ordered_decks()]
    dialog.reject()


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
    monkeypatch.setattr(__import__("slidemage.archive", fromlist=["archive_deck"]), "archive_deck", lambda *a: None)
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
    assert general.bg_profile.currentData() == background_renders.DEFAULT_PROFILE == "fast"
    general.bg_profile.setCurrentIndex(general.bg_profile.findData("normal"))
    assert app_settings.get(project, background_renders.ENABLED_KEY) is False
    assert app_settings.get(project, background_renders.ONLY_MAINS_KEY) is False
    assert app_settings.get(project, background_renders.LIMIT_GB_KEY) == 12.5
    assert app_settings.get(project, background_renders.PROFILE_KEY) == "normal"
    assert len(changed) >= 4


# -- the Preview ------------------------------------------------------------------------------

def test_the_preview_shows_a_current_stored_render_and_not_an_outdated_one(window, tmp_path):
    import os
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
    assert controller.stored_page(target, "instructor", "EN", deck.name) is None
    preview = window.centre.preview
    preview.show_slide(target, None, "One", "")
    assert preview._stored_pixmap(target, "instructor", "EN") is None
    renderer.render_unit(unit, background_renders.ORIGIN_BACKGROUND, CancelToken())
    deadline = time.monotonic() + 5
    while preview._lookups and time.monotonic() < deadline:       # the first lookup (before the render) answers
        QApplication.processEvents()
        time.sleep(0.01)
    preview._stored_asked = None                   # as at a poll: the store is asked again, on the display worker
    deadline = time.monotonic() + 5
    while preview._stored_pixmap(target, "instructor", "EN") is None and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    pixmap = preview._stored_pixmap(target, "instructor", "EN")
    assert pixmap is not None and pixmap.width() == background_renders.STORE_WIDTH
    shown = preview._image(target)
    assert shown is not None and shown[1] is True and shown[2] == ""
    path = target.source_path
    try:
        original = path.read_bytes()
        path.write_bytes(original + b"\n% edited\n")
        os.utime(path, (old, old))
        assert controller.stored_page(target, "instructor", "EN", deck.name) is None      # the slide changed: never shown as current
    finally:
        path.write_bytes(original)
        os.utime(path, (old, old))
        controller.store.clear()


# -- the dial and the status window ---------------------------------------------------------------

def rendering(renderer, on: bool) -> None:
    """Make the scheduler report one render running (that has not been told to stop), or none."""
    if on:
        renderer.scheduler.running_jobs = lambda: [object()]
    else:
        renderer.scheduler.__dict__.pop("running_jobs", None)


def progress_of(*decks, **kwargs):
    return Progress(list(decks), scanned_at=1.0, **kwargs)


def test_the_dial_shows_the_share_of_up_to_date_renders_and_explains_it(window):
    controller = window.background
    window.show()
    assert controller.dial.isHidden()                                    # before the first look at the decks
    a = DeckProgress("a", total=10, fresh=10)
    b = DeckProgress("b", total=30, fresh=10)
    off = DeckProgress("c", off=True)
    controller.renderer.progress = progress_of(a, b, off)
    controller.refresh()
    assert controller.dial.isVisible() and controller.dial.text() == "50" and controller.dial.state == "waiting"
    tip = controller.dial.toolTip()
    assert "50 % of the previews" in tip and "20 of 40 renders" in tip and "1 of 2 decks complete" in tip
    assert "20 outstanding" in tip and "Click for the decks" in tip
    controller.renderer.progress = progress_of(DeckProgress("a", total=4, fresh=4))
    controller.refresh()
    assert controller.dial.text() == "100" and controller.dial.state == "done" and "Everything is ready" in controller.dial.toolTip()
    controller.renderer.progress = progress_of(DeckProgress("a", total=4, fresh=3, failed=1), failures=1)
    controller.refresh()
    assert controller.dial.state == "failed" and "1 slide cannot be rendered" in controller.dial.toolTip()
    controller.renderer.progress = progress_of(DeckProgress("a", total=4, fresh=1))
    rendering(controller.renderer, True)
    controller.refresh()
    assert controller.dial.state == "working" and "Rendering now" in controller.dial.toolTip()
    rendering(controller.renderer, False)
    app_settings.set(window.project, background_renders.ENABLED_KEY, False)
    controller.refresh()
    assert controller.dial.isHidden()


def test_the_dial_sits_at_the_bottom_left_and_a_click_opens_the_status_window(window):
    window.resize(1200, 800)
    window.show()
    controller = window.background
    controller.renderer.progress = progress_of(DeckProgress("a", total=4, fresh=1))
    controller.refresh()
    QApplication.processEvents()                                             # the status row is laid out
    corner = controller.dial.mapTo(window, QPoint(0, 0))
    assert corner.x() > 100 and corner.y() > 500                             # in the centre column, clear of the slide list
    dial = QRect(corner, controller.dial.size())
    slide_id = window.centre.preview._id
    assert not dial.intersects(QRect(slide_id.mapTo(window, QPoint(0, 0)), slide_id.size()))  # nor over the slide id
    controller.dial.clicked.emit()
    dialog = controller._status_dialog
    assert dialog is not None and dialog.isVisible()
    dialog.reject()


def test_the_status_window_lists_every_deck_with_its_versions_and_state(window):
    controller = window.background
    ready = DeckProgress("ready", total=6, fresh=6, views={"instructor": [2, 2, 0], "during-course": [2, 2, 0], "after-course": [2, 2, 0]})
    todo = DeckProgress("todo", total=6, fresh=2, views={"instructor": [2, 2, 0], "during-course": [2, 0, 0], "after-course": [2, 0, 0]})
    broken = DeckProgress("broken", total=2, fresh=1, failed=1, views={"instructor": [2, 1, 1]})
    off = DeckProgress("aside", off=True)
    controller.renderer.progress = progress_of(ready, todo, broken, off, working="todo:x:during-course:EN")
    controller.renderer.progress.failures = 1
    from slidemage.ui.workspace.background_previews import StatusDialog
    dialog = StatusDialog(controller, window)
    rows = {dialog.tree.topLevelItem(i).text(0): [dialog.tree.topLevelItem(i).text(c) for c in range(1, 5)] for i in range(dialog.tree.topLevelItemCount())}
    assert list(rows) == ["ready", "todo", "broken", "aside"]                       # in the order they are worked through
    assert rows["ready"] == ["2 / 2", "2 / 2", "2 / 2", "up to date"]
    assert rows["todo"] == ["2 / 2", "0 / 2", "0 / 2", "4 outstanding · rendering"]
    assert rows["broken"][0] == "1 / 2  (1 failed)" and rows["broken"][3] == "1 failed"
    assert rows["aside"] == ["–", "–", "–", "left out"]
    assert dialog.overall.value() == int(100 * 9 / 14)
    assert not dialog.failures.isHidden() or dialog.isHidden()
    dialog.pause.click()
    assert controller.renderer.gate.paused and dialog.pause.text() == "Resume"
    dialog.reject()



def test_the_status_window_lists_every_render_running_now(window, monkeypatch):
    controller = window.background
    controller.renderer.progress = progress_of(DeckProgress("todo", total=6, fresh=2), working="todo:a:instructor:EN")
    monkeypatch.setattr(controller.renderer, "running", lambda: [
        dict(deck="todo", slide="aaa-EN-One", view="instructor", language="EN", kind="background", seconds=75.4),
        dict(deck="todo", slide="bbb-DE-Zwei", view="during-course", language="DE", kind="reveal steps", seconds=3.0)])
    monkeypatch.setattr(controller.renderer, "capacity", lambda: (12, 0.83))
    from slidemage.ui.workspace.background_previews import StatusDialog
    dialog = StatusDialog(controller, window)
    rows = [[dialog.running.topLevelItem(i).text(c) for c in range(6)] for i in range(dialog.running.topLevelItemCount())]
    assert rows == [["todo", "aaa-EN-One", "Instructor", "EN", "background", "1:15"],
                    ["todo", "bbb-DE-Zwei", "During course", "DE", "reveal steps", "0:03"]]
    assert dialog.running_title.text() == "Running now: 2 of up to 12 · processor 83% busy (more start below 70%)"
    monkeypatch.setattr(controller.renderer, "running", lambda: [])
    monkeypatch.setattr(controller.renderer, "capacity", lambda: (12, None))
    dialog.refresh()
    assert dialog.running.isHidden() and dialog.running_title.text() == "Running now: 0 of up to 12"
    dialog.reject()


def test_working_names_a_running_unit_while_any_runs(window):
    renderer = window.background.renderer
    renderer._set_working("d:a:instructor:EN", True)
    renderer._set_working("d:b:instructor:EN", True)
    renderer._set_working("d:a:instructor:EN", False)        # the first one ends: the second still renders
    assert renderer.progress.working == "d:b:instructor:EN"
    renderer._set_working("d:b:instructor:EN", False)
    assert renderer.progress.working is None


def test_the_chip_stays_blue_between_two_jobs_of_one_sweep(window):
    controller = window.background
    renderer = controller.renderer
    renderer.progress = Progress([DeckProgress("a", total=10, fresh=4)], scanned_at=1.0)
    assert controller.summary() == ("Previews · 6 left", "muted")          # nothing has started
    renderer.gate.note_started()                                           # a job started a moment ago ...
    assert renderer.progress.working is None                               # ... and has ended, the next is not yet running
    assert controller.summary() == ("Preparing previews · 6 left", "info")
    assert controller.dial_state() == "working"
    renderer.progress.paused_because = "waiting for a compile"             # something holds it back: now it is waiting
    assert controller.summary() == ("Preview rendering paused (waiting for a compile) · 6 left", "muted")
    assert controller.dial_state() == "waiting"


def test_the_window_in_front_stops_background_renders_and_the_chip_says_why(window, monkeypatch):
    from slidemage import idle_gate
    controller = window.background
    renderer = controller.renderer
    stopped = []
    monkeypatch.setattr(renderer.scheduler, "interrupt", lambda priority: stopped.append(priority) or 1)
    app = QApplication.instance()
    app.applicationStateChanged.emit(Qt.ApplicationState.ApplicationInactive)
    assert renderer.gate.in_front is False and stopped == []
    app.applicationStateChanged.emit(Qt.ApplicationState.ApplicationActive)
    assert renderer.gate.in_front is True and renderer.gate.reason() == idle_gate.IN_USE
    assert stopped == [background_renders.P_IDLE]               # the running renders stop and go back in the queue
    renderer.gate.force(60)                                      # "Render now" keeps them going
    app.applicationStateChanged.emit(Qt.ApplicationState.ApplicationActive)
    assert stopped == [background_renders.P_IDLE]
    progress = Progress([DeckProgress("a", total=10, fresh=4)], scanned_at=1.0, paused_because=idle_gate.IN_USE)
    monkeypatch.setattr(type(renderer), "progress", property(lambda _self: progress, lambda _self, _value: None),
                        raising=False)
    assert controller.summary() == ("Preview rendering waits while you use SlideMage · 6 left", "muted")
    assert idle_gate.IN_USE_EXPLAINED in controller.hover_text()
    assert "switch to another window" in idle_gate.IN_USE_EXPLAINED


def test_input_in_front_and_a_presentation_stop_background_renders(window, monkeypatch):
    from slidemage import idle_gate
    renderer = window.background.renderer
    stopped = []
    monkeypatch.setattr(renderer.scheduler, "interrupt", lambda priority: stopped.append(priority) or 1)
    renderer.gate.note_focus(False)
    renderer.user_active()                                      # the mouse over the window behind: nothing stops
    assert stopped == []
    renderer.gate.note_focus(True)
    renderer.user_active()                                      # a scroll after a minute of reading
    assert stopped == [background_renders.P_IDLE]
    renderer.gate.force(60)
    renderer.user_active()                                      # "Render now" keeps them going
    assert stopped == [background_renders.P_IDLE]
    window.presentation = object()
    renderer.presentation_started()
    assert stopped == [background_renders.P_IDLE] * 2 and renderer.waiting_because() == idle_gate.PRESENTING
    window.presentation = None
    assert renderer.waiting_because() != idle_gate.PRESENTING


def test_the_chip_says_the_renders_wait_as_soon_as_the_user_is_back_not_a_planner_step_later(window):
    # The chip took its reason from the planner, a step (and a rescan of every deck) late: it said "Preparing
    # previews" for that long after the renders had stopped.
    from slidemage import idle_gate
    controller = window.background
    renderer = controller.renderer
    progress = renderer.progress = Progress([DeckProgress("a", total=10, fresh=4)], scanned_at=1.0)
    renderer.gate.note_started()                                 # a sweep was under way
    renderer.gate.note_focus(False)
    renderer.gate.left_at -= idle_gate.LEAVE_GRACE + 1
    assert renderer.sweeping() and controller.summary()[0].startswith("Preparing previews")
    renderer.gate.note_focus(True)                               # back; the planner has not stepped yet
    assert progress.paused_because is None
    assert not renderer.sweeping() and renderer.waiting_because() == idle_gate.IN_USE
    assert controller.summary() == ("Preview rendering waits while you use SlideMage · 6 left", "muted")
    assert controller.dial_state() == "waiting"


def test_a_deck_compile_gives_the_preview_and_the_thumbnails_its_pages_with_background_rendering_switched_off(
        qapp, monkeypatch, tmp_path):
    # 2026-10-30, direct request: a full Instructor render still left 'Shared Instructor reference' on the slides.
    import os
    import shutil
    import time

    from conftest import EXAMPLE, build_window
    from slidemage import compile_records, deck_outline, deck_scan, preview_target, preview_thumbnails
    from slidemage.compiler import CompileJob
    from slidemage.preview_raster_client import RasterClient
    from slidemage.project import ProjectContext
    from test_background_renders import _compiled_pdf, _record

    root = tmp_path / "proj"
    shutil.copytree(EXAMPLE, root)
    old = time.time() - 3600
    for path in root.rglob("*"):
        if path.is_file():
            os.utime(path, (old, old))
    ctx = ProjectContext.at(root)
    window = build_window(monkeypatch, ctx)
    controller = window.background
    renderer = controller.renderer
    raster = renderer._raster = RasterClient()
    try:
        app_settings.set(ctx, background_renders.ENABLED_KEY, False)
        assert not renderer.enabled
        deck = next(d for d in deck_scan.scan_decks(ctx) if d.name == "slidemage-manual")
        units = background_renders.deck_units(ctx, deck, "instructor", "EN")[:6]
        pdf = _compiled_pdf(tmp_path, units)
        job = CompileJob(deck, "instructor", None)
        monkeypatch.setattr(compile_records, "read_record", lambda *args: _record(pdf, deck, units, ctx))
        told = []
        controller.ingested.connect(lambda: told.append(True))
        controller._on_compiled(ctx, job, pdf)                  # ingest happens although the feature is off
        assert told and not renderer.scheduler._threads         # ... and nothing started rendering
        outline = deck_outline.build_outline(ctx, deck, "instructor", "EN")
        row = next(r for s in outline for r in s.rows if r.call.source_filename == units[0].source_path.name)
        target = preview_target.for_call(ctx, deck, row.call, row.position, frame_number=row.frame_number)
        assert controller.stored_page(target, "instructor", "EN", deck.name)     # the Preview's page
        assert controller.stored_pages(target, "instructor", "EN", deck.name) is None      # not a list of steps
        result = preview_thumbnails.for_outline(ctx, deck, outline, "instructor", "EN",
                                                stored_page=controller.stored_page_path)
        shown = next(r for s in result for r in s.rows if r.key == row.key)
        assert shown.thumbnail_verified and shown.thumbnail.is_file()
        assert "reference" not in shown.thumbnail_note.lower()
        # what the slide depends on changing takes the page away again
        units[0].source_path.write_text(units[0].source_path.read_text(encoding="utf-8") + "\n% edited\n", encoding="utf-8")
        assert controller.stored_page(target, "instructor", "EN", deck.name) is None
    finally:
        raster.close()
