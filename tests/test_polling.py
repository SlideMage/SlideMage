# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Polling timers (review D2): pause while SlideMage cannot be seen, resume with one tick, slow down on battery."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtTest import QTest

from slidemage import power_status
from slidemage.ui import polling
from slidemage.ui.polling import PollTimer
from slidemage.ui.workspace import ai_route, background_previews, maintenance
from slidemage.ui.workspace.assistant_header import AssistantHeader
from slidemage.ui.workspace.terminal import sync
from conftest import build_window, qapp as qapp


@pytest.fixture
def mon(qapp, monkeypatch):
    """The monitor with a state of its own: seen, in front, on mains power."""
    monitor = polling.monitor()
    monkeypatch.setattr(power_status, "on_battery", lambda: False)
    monitor.set_seen(True)
    monitor.set_active(True)
    monitor.set_battery(False)
    yield monitor
    monitor.stretch_on_battery = lambda: True
    monitor.set_seen(True)
    monitor.set_active(True)
    monitor.set_battery(False)


def make(parent=None, ms=1000, **kw):
    timer = PollTimer(parent, ms, **kw)
    ticks = []
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    return timer, ticks


def test_a_timer_runs_at_its_interval_while_seen_on_mains(mon):
    timer, _ = make(ms=1000)
    assert timer.running() and timer.isActive() and timer.interval() == 1000


def test_minimizing_pauses_and_coming_back_ticks_at_once(mon):
    timer, ticks = make(ms=60_000)
    mon.set_seen(False)
    assert not timer.running() and timer.isActive() and timer.paused()      # still "started" for its owner
    mon.set_seen(True)
    assert timer.running() and ticks == []                                   # the tick comes from the event loop
    QTest.qWait(20)
    assert ticks == [1]


def test_a_stopped_timer_stays_stopped_when_the_window_comes_back(mon):
    timer, ticks = make(ms=60_000)
    timer.stop()
    mon.set_seen(False)
    mon.set_seen(True)
    QTest.qWait(20)
    assert not timer.running() and not timer.isActive() and ticks == []


def test_a_timer_started_while_hidden_waits(mon):
    mon.set_seen(False)
    timer, ticks = make(ms=60_000)
    assert not timer.running() and timer.isActive()
    mon.set_seen(True)
    QTest.qWait(20)
    assert timer.running()
    assert ticks in ([], [1])       # nothing was held back, so no catch-up tick is owed


def test_inactive_pauses_only_after_the_grace_time_and_only_when_asked(mon):
    patient, patient_ticks = make(ms=60_000, inactive_after_ms=40)
    plain, _ = make(ms=60_000)
    mon.set_active(False)
    assert patient.running()                       # within the grace time
    QTest.qWait(150)
    assert not patient.running() and patient.isActive()
    assert plain.running()                         # no grace asked: inactive does not pause it
    mon.set_active(True)
    QTest.qWait(20)
    assert patient.running() and patient_ticks == [1]


def test_a_short_inactive_spell_pauses_nothing(mon):
    timer, ticks = make(ms=60_000, inactive_after_ms=300)
    mon.set_active(False)
    QTest.qWait(20)
    mon.set_active(True)
    QTest.qWait(350)
    assert timer.running() and ticks == []


@pytest.mark.parametrize("state, factor", [(True, 3), (False, 1), (None, 1)])
def test_the_interval_is_stretched_on_battery_only(mon, monkeypatch, state, factor):
    monkeypatch.setattr(power_status, "on_battery", lambda: state)
    timer, _ = make(ms=1000)
    mon.refresh_power()
    assert timer.interval() == 1000 * factor and timer.base_interval() == 1000 and timer.running()


@pytest.mark.parametrize("setting, factor", [(True, 3), (False, 1)])
def test_the_setting_only_on_mains_power_decides_whether_battery_slows_the_polls(mon, monkeypatch, setting, factor):
    monkeypatch.setattr(power_status, "on_battery", lambda: True)
    timer, _ = make(ms=1000)
    polling.set_battery_setting(lambda: setting)
    assert timer.interval() == 1000 * factor
    mon.set_seen(False)                 # pausing while hidden does not depend on the setting
    assert not timer.running()


def test_the_window_hands_the_setting_over(mon, monkeypatch):
    from slidemage import app_settings, background_renders
    window = build_window(monkeypatch)
    monkeypatch.setattr(power_status, "on_battery", lambda: True)
    timer = window.ai_route._running
    base = timer.base_interval()
    app_settings.set(window.project, background_renders.ONLY_MAINS_KEY, False)
    mon.refresh_power()
    assert timer.interval() == base
    app_settings.set(window.project, background_renders.ONLY_MAINS_KEY, True)
    mon.refresh_power()
    assert timer.interval() == base * 3


def test_the_power_state_is_read_on_resume_not_per_tick(mon, monkeypatch):
    calls = []
    monkeypatch.setattr(power_status, "on_battery", lambda: calls.append(1) or True)
    timer, _ = make(ms=10)
    QTest.qWait(80)
    assert calls == []                              # ticking reads nothing
    mon.set_seen(False)
    mon.set_seen(True)
    assert calls == [1] and timer.interval() == 30


def test_a_timer_that_must_not_stretch_keeps_its_interval(mon):
    timer, _ = make(ms=60_000, battery_factor=1)
    mon.set_battery(True)
    assert timer.interval() == 60_000


def test_back_on_mains_the_interval_is_the_normal_one(mon):
    timer, _ = make(ms=1000)
    mon.set_battery(True)
    mon.set_battery(False)
    assert timer.interval() == 1000


def test_setinterval_and_start_with_a_value_change_the_base(mon):
    timer, _ = make(ms=1000)
    timer.setInterval(500)
    assert timer.base_interval() == 500 and timer.interval() == 500
    timer.start(200)
    assert timer.base_interval() == 200


def test_a_failing_power_query_counts_as_mains(mon, monkeypatch):
    def broken():
        raise OSError

    monkeypatch.setattr(power_status, "on_battery", broken)
    mon.refresh_power()
    assert mon.on_battery is False


# -- the timers that use it --------------------------------------------------------------------

def test_the_edit_watch_pauses_while_hidden(mon, tmp_path):
    watch = sync.ExternalEditWatch(tmp_path, lambda changes: None)
    watch.start()
    assert watch._timer.running()
    mon.set_seen(False)
    assert not watch._timer.running() and watch._timer.isActive()
    watch.stop(last_look=False)
    assert not watch._timer.isActive()


def test_the_access_check_pauses_while_hidden_and_keeps_its_interval_on_battery(mon, qapp, monkeypatch):
    monkeypatch.setattr(maintenance, "check_project_access", lambda window: None)
    class Window(QObject):
        project_access_checked = Signal(object)

    window = Window()
    maintenance.schedule_access_check(window)
    timer, = window.findChildren(PollTimer)
    assert timer.base_interval() == maintenance.ACCESS_CHECK_INTERVAL_MS and timer.running()
    mon.set_battery(True)
    assert timer.interval() == maintenance.ACCESS_CHECK_INTERVAL_MS
    mon.set_seen(False)
    assert not timer.running()


def _header_poll(window):
    headers = window.findChildren(AssistantHeader)
    assert headers
    return headers[0]._poll


def test_the_timers_of_the_window_pause_while_hidden(mon, monkeypatch):
    window = build_window(monkeypatch)
    expected = {"ai_route running": window.ai_route._running,
                "preview validation": window.centre.preview._validation_poll,
                "background chip": window.background._timer,
                "assistant header": _header_poll(window)}
    for name, timer in expected.items():
        assert isinstance(timer, PollTimer), name
        timer.start()                               # as the owner does when its widget is shown
    mon.set_seen(False)
    for name, timer in expected.items():
        assert not timer.running() and timer.isActive(), name
    mon.set_seen(True)
    QTest.qWait(20)
    for name, timer in expected.items():
        assert timer.running(), name
    assert expected["ai_route running"].base_interval() == ai_route.RUNNING_MS


def test_the_ai_route_watch_while_stopping_is_not_paused(mon, monkeypatch):
    window = build_window(monkeypatch)
    watch = window.ai_route._watch
    assert not isinstance(watch, PollTimer)         # it reports the end of the work being stopped: it keeps running
    watch.start()
    mon.set_seen(False)
    assert watch.isActive()
    watch.stop()


def test_the_status_dialog_refresh_pauses_while_hidden(mon, monkeypatch):
    window = build_window(monkeypatch)
    dialog = background_previews.StatusDialog(window.background, window)
    assert isinstance(dialog._timer, PollTimer) and dialog._timer.running()
    mon.set_seen(False)
    assert not dialog._timer.running()
    dialog.close()
