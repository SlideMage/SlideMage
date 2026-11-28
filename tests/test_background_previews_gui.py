# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The window's side of background rendering: the input watcher, the deck usage, the chip and its menu, the settings."""
from __future__ import annotations

import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QImage, QKeyEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit

from slidemage import app_settings, background_renders, idle_gate, preview_target, render_lookup
from slidemage.background_renders import DeckProgress, Progress
from slidemage.preview_requests import PreviewRequest, SourceRevision
from slidemage.render_scheduler import P_IDLE
from slidemage.ui.dialogs.settings import SettingsSheet
from slidemage.ui.workspace import background_previews
from slidemage.ui.workspace.background_previews import StatusDialog
from conftest import build_window, qapp as qapp, wait_until
from test_background_renders import FakeTeX, _compiled_pdf, _edit, _record, render_unit
from test_background_renders import project as project
from test_settings_gui import FakeApp


@pytest.fixture
def window(qapp, monkeypatch):
    window = build_window(monkeypatch)
    window.background.renderer.gate.in_front = None
    return window


def test_user_input_anywhere_in_the_application_resets_the_idle_clock(window):
    gate = window.background.renderer.gate
    gate.last_input = -1000.0
    window.topbar.setMouseTracking(True)
    # Qt's own mouse moves (widgets appearing under a still cursor) are not the user: the sent event is not spontaneous
    QApplication.sendEvent(window.topbar, QMouseEvent(
        QEvent.Type.MouseMove, QPointF(3, 3), QPointF(3, 3),
        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
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


def test_widget_input_watcher_tracks_new_widgets_and_stops_with_the_window(qapp, monkeypatch):
    monkeypatch.setattr(background_previews, "USE_WIDGET_INPUT_WATCHER", True)
    monkeypatch.setattr(QApplication, "allWidgets", lambda: pytest.fail("the watcher must not walk allWidgets"))
    window = build_window(monkeypatch)
    controller = window.background
    gate = controller.renderer.gate
    child = QLineEdit(window)
    gate.last_input = -1000.0
    QTest.keyClick(child, Qt.Key.Key_A)
    assert gate.last_input > -1000.0

    dialog = QDialog()
    edit = QLineEdit(dialog)
    dialog.show()
    try:
        QTest.qWait(300)
        gate.last_input = -1000.0
        QTest.keyClick(edit, Qt.Key.Key_A)
        assert gate.last_input > -1000.0
        gate.last_input = -1000.0
        QApplication.sendEvent(QObject(), QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier))
        assert gate.last_input == -1000.0
        controller.stop()
        QTest.keyClick(edit, Qt.Key.Key_B)
        assert gate.last_input == -1000.0 and controller.store is None
    finally:
        dialog.close()
        dialog.deleteLater()


def test_application_input_watcher_needs_no_widget_polling_and_is_removed_on_stop(qapp, monkeypatch):
    monkeypatch.setattr(background_previews, "USE_WIDGET_INPUT_WATCHER", False)
    monkeypatch.setattr(QApplication, "allWidgets", lambda: pytest.fail("the watcher must not walk allWidgets"))
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


def test_the_chip_and_dial_report_waiting_working_failed_and_done(window):
    controller = window.background
    renderer = controller.renderer
    window.show()
    controller.refresh()
    assert not renderer.scheduler._threads and controller.chip.isHidden() and controller.dial.isHidden()

    progress = renderer.progress = progress_of(DeckProgress("a", total=10, fresh=10),
                                               DeckProgress("b", total=30, fresh=10), DeckProgress("c", off=True))
    controller.refresh()
    assert controller.summary()[1] == "muted"
    assert controller.dial.isVisible() and controller.dial.text() == "50" and controller.dial.state == "waiting"
    rendering(renderer, True)
    controller.refresh()
    assert controller.summary()[1] == "info" and controller.dial.state == "working"
    rendering(renderer, False)
    renderer.gate.note_started()
    assert renderer.progress.working is None and controller.dial_state() == "working"
    progress.paused_because = "waiting for a compile"
    controller.refresh()
    assert controller.chip.isVisible() and "paused" in controller.chip.text()
    assert controller.dial.state == "waiting"

    first, second = "a:x:instructor:EN", "b:y:instructor:EN"
    renderer._set_working(first, True)
    renderer._set_working(second, True)
    renderer._set_working(first, False)
    assert renderer.progress.working == second
    renderer._set_working(second, False)
    assert renderer.progress.working is None

    renderer.gate.sweep_until = 0.0
    renderer.progress = progress_of(DeckProgress("a", total=4, fresh=3, failed=1), failures=1)
    controller.refresh()
    assert controller.summary()[1] == "warning" and controller.dial.state == "failed"
    renderer.progress = progress_of(DeckProgress("a", total=4, fresh=4))
    controller.refresh()
    assert controller.summary()[1] == "ok_text" and controller.chip.isVisible()
    assert controller.dial.text() == "100" and controller.dial.state == "done"
    app_settings.set(window.project, background_renders.ENABLED_KEY, False)
    controller.refresh()
    assert controller.chip.isHidden() and controller.dial.isHidden()


def test_a_missing_template_turns_the_chip_red_and_the_status_window_says_why(window):
    controller = window.background
    window.show()
    blocked = DeckProgress("t-Uni-IA2", total=8, blocked=8, views={"instructor": [8, 0, 0]})
    controller.renderer.progress = Progress([blocked, DeckProgress("b", total=4, fresh=1)], scanned_at=1.0,
                                            missing_templates={"uni-graz": ["t-Uni-IA2"]})
    rendering(controller.renderer, True)
    assert controller.summary() == ("Template uni-graz not found · previews can't be rendered", "error")
    assert "No theme for the template \"uni-graz\" is installed" in controller.hover_text()
    rendering(controller.renderer, False)
    controller.refresh()
    assert controller.chip.isVisible() and "uni-graz" in controller.chip.text()
    dialog = StatusDialog(controller, window)
    row = next(dialog.tree.topLevelItem(i) for i in range(dialog.tree.topLevelItemCount())
               if dialog.tree.topLevelItem(i).text(0) == "t-Uni-IA2")
    assert row.text(4) == "template not found"
    assert "SlideMage_template_uni-graz.tex" in dialog.note.text() and "Settings → Plugins → Themes" in dialog.note.text()
    dialog.reject()
    controller.renderer.progress = Progress([DeckProgress("t-Uni-IA2", total=8, blocked=8)], scanned_at=1.0,
                                            missing_templates={"uni-graz": ["t-Uni-IA2"], "mci": ["x"]})
    assert controller.summary()[0].startswith("Templates mci, uni-graz not found")
    assert controller.dial_state() == "failed"


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
    assert dialog.dial.text() == "40%"
    assert not dialog.failures.isHidden() and not dialog.retry.isHidden()
    dialog.pause.click()
    assert controller.renderer.gate.paused and controller.renderer.gate.reason() == "paused"
    dialog.render_now.click()
    assert not controller.renderer.gate.paused
    assert controller.renderer.gate.forced()
    assert 'Render now is on' in dialog.note.text()
    dialog.render_now.click()
    assert not controller.renderer.gate.forced()
    assert 'Render now is on' not in dialog.note.text()
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


def test_retrying_failed_slides_clears_failures_and_replans_by_slide(window, monkeypatch):
    shown = []
    monkeypatch.setattr(background_previews.QMessageBox, "information", lambda *a, **k: shown.append(a))
    controller = window.background
    renderer = controller.renderer
    replanned = []
    monkeypatch.setattr(renderer, "replan", lambda: replanned.append(True))
    renderer._failure_slides = {key * 64: {("d", slide)} for key, slide in zip("abc", ("s1", "s1", "s2"), strict=True)}
    renderer._failure_keys = set(renderer._failure_slides)
    for key in renderer._failure_keys:
        controller.store.record_failure(key, "deterministic", "boom", [])
    controller.retry_failed()
    assert [a[2] for a in shown] == ["2 failed slides added to the render queue."]
    assert not controller.store.failures() and replanned


def test_the_gate_waits_for_a_compile_a_dialog_and_the_preview(window, monkeypatch):
    controller = window.background
    assert controller._busy_reasons() == []
    with monkeypatch.context() as patch:
        patch.setattr(type(window.compile), "running", property(lambda self: True))
        assert controller._busy_reasons() == ["a compile"]
    window.centre.preview._busy = True
    assert controller._busy_reasons() == ["the Preview"]


def test_opening_a_deck_records_usage_and_archiving_it_notifies_the_renderer(window, monkeypatch):
    deck = window.state.deck
    assert next(u for u in window.background.store.deck_usage() if u["deck"] == deck.name)["open_count"] >= 1
    window.state.set_focused_slide("tnb")
    window.state.set_view("after-course")
    window.state.set_language("DE")
    usage = next(u for u in window.background.store.deck_usage() if u["deck"] == deck.name)
    assert (usage["last_slide"], usage["last_view"], usage["last_language"]) == ("tnb", "after-course", "DE")
    told = []
    monkeypatch.setattr(window.background, "deck_archived", told.append)
    monkeypatch.setattr(__import__("slidemage.archive", fromlist=["archive_deck"]), "archive_deck", lambda *a: None)
    from slidemage.ui.workspace import deck_actions
    reloaded = []
    monkeypatch.setattr(window, "reload_decks", lambda closing=frozenset(): reloaded.append(closing))
    deck_actions.do_archive_deck(window, window.state.deck)
    assert told == [window.state.deck] and reloaded == [{window.state.deck.name}]


def test_the_settings_save_the_background_controls(qapp):
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


def rendering(renderer, on: bool) -> None:
    """Make the scheduler report one render running (that has not been told to stop), or none."""
    if on:
        renderer.scheduler.running_jobs = lambda: [object()]
    else:
        renderer.scheduler.__dict__.pop("running_jobs", None)


def progress_of(*decks, **kwargs):
    return Progress(list(decks), scanned_at=1.0, **kwargs)


def test_the_status_row_keeps_its_layout_on_refresh_and_the_dial_opens_status(window):
    window.resize(1200, 800)
    window.show()
    controller = window.background
    controller.renderer.progress = progress_of(DeckProgress("a", total=4, fresh=1))
    controller.refresh()
    for _ in range(4):
        QApplication.processEvents()
    laid_out = controller.chip.geometry()
    assert laid_out.height() > controller.chip.sizeHint().height()
    controller.refresh()
    assert controller.chip.geometry() == laid_out
    corner = controller.dial.mapTo(window, QPoint(0, 0))
    assert corner.y() > window.height() // 2
    dial = QRect(corner, controller.dial.size())
    slide_id = window.centre.preview._id
    assert not dial.intersects(QRect(slide_id.mapTo(window, QPoint()), slide_id.size()))
    controller.dial.clicked.emit()
    dialog = controller._status_dialog
    assert dialog is not None and dialog.isVisible()
    dialog.reject()


def test_the_status_window_lists_deck_progress_and_running_renders(window, monkeypatch):
    controller = window.background
    ready = DeckProgress("ready", total=6, fresh=6, views=dict.fromkeys(("instructor", "during-course", "after-course"), [2, 2, 0]))
    todo = DeckProgress("todo", total=6, fresh=2, views={"instructor": [2, 2, 0], "during-course": [2, 0, 0]})
    other = DeckProgress("other", total=2, fresh=1)
    broken = DeckProgress("broken", total=2, fresh=1, failed=1, views={"instructor": [2, 1, 1]})
    controller.renderer.progress = progress_of(ready, todo, other, broken, DeckProgress("aside", off=True),
                                               failures=1, working="todo:a:instructor:EN")
    running = [
        dict(deck="todo", slide="aaa-EN-One", view="instructor", language="EN", kind="background", seconds=75.4),
        dict(deck="other", slide="bbb-DE-Zwei", view="during-course", language="DE", kind="reveal steps", seconds=3.0),
    ]
    monkeypatch.setattr(controller.renderer, "running", lambda: running)
    monkeypatch.setattr(controller.renderer, "capacity", lambda: (12, 0.83))
    dialog = StatusDialog(controller, window)
    rows = [dialog.tree.topLevelItem(i) for i in range(dialog.tree.topLevelItemCount())]
    assert [row.text(0) for row in rows] == ["ready", "todo", "other", "broken", "aside"]
    assert [rows[0].text(col) for col in range(1, 5)] == ["2 / 2", "2 / 2", "2 / 2", "up to date"]
    assert all("rendering" in row.text(4) for row in rows[1:3])
    assert rows[3].text(1) == "1 / 2  (1 failed)" and rows[3].text(4) == "1 failed"
    assert rows[4].text(4) == "left out"
    assert dialog.overall.value() == int(100 * 10 / 16)
    assert dialog.running.topLevelItemCount() == 2
    assert [dialog.running.topLevelItem(1).text(col) for col in range(6)] == [
        "other", "bbb-DE-Zwei", "During course", "DE", "reveal steps", "0:03"]
    assert "2 of up to 12" in dialog.running_title.text()

    running.clear()
    monkeypatch.setattr(controller.renderer, "capacity", lambda: (12, None))
    dialog.refresh()
    assert dialog.running.isHidden() and "0 of up to 12" in dialog.running_title.text()
    dialog.reject()


def test_input_scroll_and_presenting_interrupt_background_renders(window, monkeypatch):
    renderer = window.background.renderer
    stopped = []
    monkeypatch.setattr(renderer.scheduler, "interrupt", lambda priority: stopped.append(priority) or 1)
    renderer.gate.note_focus(False)
    renderer.user_active()
    assert not stopped
    renderer.user_active(scroll=True)
    assert stopped == [P_IDLE] and renderer.waiting_because() == idle_gate.IN_USE

    renderer.gate.note_focus(True)
    renderer.user_active()
    assert stopped == [P_IDLE] * 2
    renderer.gate.force(60)
    renderer.user_active()
    assert stopped == [P_IDLE] * 2
    window.presentation = object()
    renderer.presentation_started()
    assert stopped == [P_IDLE] * 3 and renderer.waiting_because() == idle_gate.PRESENTING
    window.presentation = None
    assert renderer.waiting_because() != idle_gate.PRESENTING

    seen = []
    watcher = window.background._watcher
    monkeypatch.setattr(watcher, "_on_input", lambda **kwargs: seen.append(kwargs))
    for kind in (QEvent.Type.Wheel, QEvent.Type.KeyPress):
        watcher.eventFilter(window.topbar, QEvent(kind))
    assert seen == [{"scroll": True}, {}]


def test_returning_focus_interrupts_the_sweep_and_updates_the_chip_before_the_next_plan(window, monkeypatch):
    # The chip once stayed in the running state until the planner rescanned the decks.
    controller = window.background
    renderer = controller.renderer
    progress = renderer.progress = Progress([DeckProgress("a", total=10, fresh=4)], scanned_at=1.0)
    renderer.gate.note_started()                                 # a sweep was under way
    renderer.gate.note_focus(False)
    renderer.gate.left_at -= idle_gate.LEAVE_GRACE + 1
    assert renderer.sweeping() and controller.summary()[0].startswith("Preparing previews")
    stopped = []
    monkeypatch.setattr(renderer.scheduler, "interrupt", lambda priority: stopped.append(priority) or 1)
    app = QApplication.instance()
    app.applicationStateChanged.emit(Qt.ApplicationState.ApplicationActive)
    assert stopped == [P_IDLE]
    assert progress.paused_because is None
    assert not renderer.sweeping() and renderer.waiting_because() == idle_gate.IN_USE
    assert controller.summary() == ("Preview rendering waits while you use SlideMage · 6 left", "muted")
    assert controller.dial_state() == "waiting"
    renderer.gate.force(60)
    app.applicationStateChanged.emit(Qt.ApplicationState.ApplicationActive)
    assert stopped == [P_IDLE]


def test_a_deck_compile_gives_the_preview_and_the_thumbnails_its_pages_with_background_rendering_switched_off(
        qapp, monkeypatch, tmp_path, project):
    # A full instructor compile once left shared-reference thumbnails behind.
    from slidemage import compile_records, deck_outline, preview_thumbnails
    from slidemage.compiler import CompileJob
    from slidemage.preview_raster_client import RasterClient

    window = build_window(monkeypatch, project)
    controller = window.background
    renderer = controller.renderer
    raster = renderer._raster = RasterClient()
    try:
        app_settings.set(project, background_renders.ENABLED_KEY, False)
        assert not renderer.enabled
        deck = next(d for d in window.decks if d.name == "slidemage-manual")
        units = background_renders.deck_units(project, deck, "instructor", "EN")[:2]
        pdf = _compiled_pdf(tmp_path, units)
        job = CompileJob(deck, "instructor", None)
        record = _record(pdf, job, units, project)
        monkeypatch.setattr(compile_records, "read_record", lambda *args: record)
        told = []
        controller.ingested.connect(lambda: told.append(True))
        controller._on_compiled(project, job, pdf)
        assert told and not renderer.scheduler._threads
        outline = deck_outline.build_outline(project, deck, "instructor", "EN")
        row = next(r for s in outline for r in s.rows if r.call.source_filename == units[0].source_path.name)
        target = preview_target.for_call(project, deck, row.call, row.position, frame_number=row.frame_number)
        spec = PreviewRequest(target, SourceRevision.capture(target.source_path), "instructor", "EN")
        request = dict(resolver=renderer.resolver, unit=spec.unit, spec=spec)
        state, found = render_lookup.select(request, strict=True)
        assert state == 'current' and len(renderer.store.pages(found)) == 2
        result = preview_thumbnails.for_outline(project, deck, outline, "instructor", "EN", resolver=renderer.resolver)
        shown = next(r for s in result for r in s.rows if r.key == row.key)
        assert shown.thumbnail_verified and shown.thumbnail.is_file()
        assert "reference" not in shown.thumbnail_note.lower()
        _edit(units[0].source_path)
        request.pop('spec')
        state, found = render_lookup.select(request, strict=False)
        assert state == 'previous' and renderer.store.page(found, found['pages'])
    finally:
        raster.close()


def test_interrupting_the_sweep_keeps_the_build_the_pane_waits_for(window, monkeypatch):
    started, release = threading.Event(), threading.Event()
    r = window.background.renderer
    service = window.centre.preview._renders
    assert r.renders is service and service.renderer(window.project) is r and r.store is window.background.store
    tex = FakeTeX(window.project)

    def render(unit, cancel):
        started.set()
        assert release.wait(5)
        assert not cancel.is_set()
        return tex(unit, cancel)

    monkeypatch.setattr(r, 'render_override', render)
    deck = next(deck for deck in window.decks if deck.name == 'slidemage-manual')
    unit = background_renders.deck_units(window.project, deck, 'instructor', 'EN')[0]
    target = r.request_for(unit).target
    monkeypatch.setattr(r.scheduler, '_can_start', lambda job: True)
    r.scheduler.submit(unit.label, ((unit,), ()), P_IDLE)
    sweep = threading.Thread(target=r.scheduler.run_next)
    sweep.start()
    pane = None
    try:
        assert started.wait(5)
        request = service.request(target, unit.source_path.read_text(encoding='utf-8'), 'instructor', 'EN', lambda _: None)
        pixels = []
        pane = threading.Thread(target=lambda: pixels.append(request.wait(pixels_only=True)))
        pane.start()
        wait_until(lambda: len(request._consumers) == 2)
        r.gate.in_front = True
        r.user_active()
        sweep.join(5)
        assert not sweep.is_alive() and not request.cancel.is_set()
        assert len(request._consumers) == 1 and not tex.calls
        release.set()
        pane.join(5)
        assert not pane.is_alive() and isinstance(pixels[0][1], Path)
        assert not QImage(str(pixels[0][1])).isNull()
        assert request.done.wait(5) and len(tex.calls) == 1
        assert r.resolver.lookup(unit).final
    finally:
        release.set()
        sweep.join(5)
        if pane is not None:
            pane.join(5)
        r.stop()


def test_the_pane_shows_the_choosers_current_and_previous_page(window, monkeypatch, tmp_path):
    from slidemage import deck_editor

    deck = window.state.deck
    target = next(t for i, call in enumerate(deck_editor.parse_slide_calls(deck), 1)
                  if (t := preview_target.for_call(window.project, deck, call, i)) is not None
                  and PreviewRequest(t, SourceRevision.capture(t.source_path), "instructor", "EN").complete)
    target = replace(target, deck=deck, needs_context=('contents',))
    renderer = window.background.renderer
    preview = window.centre.preview
    assert preview._renders is renderer.renders
    unit = background_renders.render_key.unit_for(target, "instructor", "EN")
    dependency = tmp_path / 'picture.tex'
    dependency.write_text('original')
    tex = FakeTeX(window.project, pages=1, inputs=[dependency])
    monkeypatch.setattr(renderer, 'render_override', tex)
    monkeypatch.setattr(preview_target, 'render_text', lambda *a, **kw: tex(unit, kw['cancel']))
    select, calls = render_lookup.select, []

    def choose(request, *, strict=False):
        calls.append((strict, threading.current_thread() is threading.main_thread()))
        return select(request, strict=strict)

    def temporary_pages_ready():
        if preview.model.adhoc.value is None or preview._busy:
            return False
        steps_key = preview._current_steps(target)[0]
        return steps_key in preview.model.steps.pages and not preview._steps.pending(steps_key)

    monkeypatch.setattr(render_lookup, 'select', choose)
    preview.show_slide(target, None, "One", "")
    wait_until(temporary_pages_ready, seconds=10)
    assert preview._record is None
    temporary = preview._page.pixmap.toImage()
    source = target.source_path.read_text(encoding='utf-8')
    try:
        for state, count in (('current', 2), ('previous', 2), ('current', 3)):
            if state == 'previous':
                dependency.write_text('changed')
            else:
                tex.pages = count
                assert render_unit(renderer, unit)
            preview.model.lookups.asked = None
            preview._refresh()
            expected_state, record = select(dict(resolver=renderer.resolver, unit=unit), strict=True)
            assert expected_state == state and record['unit'] == unit.label
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if (preview._record == record and not preview._checking()
                        and preview._reveal.track.stops == list(range(1, count + 1))):
                    break
                QApplication.processEvents()
                time.sleep(.01)
            assert preview._record == record
            pages = renderer.store.pages(record)
            preview._reveal.track.selected.emit(count)
            assert preview._page.pixmap.toImage() == QImage.fromData(pages[-1])
            assert preview._page.pixmap.toImage() != temporary
            assert ('Previous render' in preview._status_chip.text()) == (state == 'previous')
            preview._reveal.track.selected.emit(1)
            assert preview._page.pixmap.toImage() == QImage.fromData(pages[0])
        assert target.source_path.read_text(encoding='utf-8') == source
        assert any(strict for strict, _on_main in calls) and not any(on_main for _strict, on_main in calls)
    finally:
        renderer.store.clear()


def test_the_status_window_remembers_its_size_and_divider_per_computer(window, monkeypatch):
    from slidemage.ui import layout_settings
    from slidemage.ui.workspace.background_previews import LAYOUT_KEY
    store = {}
    monkeypatch.setattr(layout_settings, "get", lambda key, default=None: store.get(key, default))
    monkeypatch.setattr(layout_settings, "set", lambda key, value: store.__setitem__(key, value))
    controller = window.background
    monkeypatch.setattr(controller.renderer, "running", lambda: [
        dict(deck="todo", slide="aaa-EN-One", view="instructor", language="EN", kind="background", seconds=5.0)])
    first = StatusDialog(controller, window)
    first.resize(760, 500)
    first.show()
    first.split.setSizes([150, 250])
    first.reject()
    assert store[LAYOUT_KEY]["split"] and "geometry" in store[LAYOUT_KEY]
    second = StatusDialog(controller, window)
    second.show()
    assert second.width() == 760 and second.height() == 500
    assert second.split.sizes()[1] > second.split.sizes()[0] * 0.8
    second.reject()
