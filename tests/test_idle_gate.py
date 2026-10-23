# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The idle gate and the busy registry (no Qt)."""
from slidemage import busy, idle_gate


def gate(**kwargs):
    t = {"now": 0.0}
    defaults = dict(clock=lambda: t["now"], on_battery=lambda: False, cpu_load=lambda: 0.1, is_busy=lambda: [],
                    startup_delay=20, idle_after=30)
    defaults.update(kwargs)
    g = idle_gate.IdleGate(**defaults)
    g.t = t
    return g


def test_idle_means_thirty_seconds_without_input_after_the_start_up_delay():
    g = gate()
    assert g.reason() == "starting up"
    g.t["now"] = 25
    assert g.reason() == "you are working"
    g.t["now"] = 31
    assert g.allowed()
    g.note_input()
    assert g.reason() == "you are working"
    g.t["now"] = 62
    assert g.allowed()


def test_input_and_cpu_load_only_keep_a_job_from_starting_not_the_next_one_once_rendering_is_under_way():
    g = gate()
    g.t["now"] = 31
    assert g.allowed()
    g.note_started()
    g.note_input()
    g._cpu_load = lambda: 0.95
    g.t["now"] = 40
    assert g.allowed()                       # a sweep is under way: neither input nor load stops it
    g.t["now"] = 31 + idle_gate.SWEEP_SECONDS + 1
    assert g.reason() == "the computer is busy"


def test_battery_cpu_disk_busy_and_switch():
    g = gate(on_battery=lambda: True)
    g.t["now"] = 100
    assert g.reason() == "on battery"
    g.only_on_mains = lambda: False
    assert g.allowed()
    g._cpu_load = lambda: 0.95
    assert g.reason() == "the computer is busy"
    g._cpu_load = lambda: None
    g._free_bytes = lambda: 1024
    assert g.reason() == "low disk space"
    g._free_bytes = lambda: None
    g._busy = lambda: ["a compile"]
    assert g.reason() == "waiting for a compile"
    g._busy = lambda: []
    g.enabled = lambda: False
    assert g.reason() == "switched off"


def test_render_now_skips_the_idle_rules_but_not_busy_or_the_switch():
    g = gate(on_battery=lambda: True)
    g.force(60)
    assert g.allowed()
    g._busy = lambda: ["an export"]
    assert g.reason() == "waiting for an export"
    g._busy = lambda: []
    g.t["now"] = 70
    assert g.reason() in ("you are working", "on battery")


def test_busy_registry_counts_holders():
    with busy.working("a compile"):
        with busy.working("a compile"):
            assert busy.reasons() == ["a compile"]
        assert busy.is_busy()
    assert not busy.is_busy()


def test_in_front_a_minute_without_input_lets_rendering_start_and_a_sweep_does_not_skip_that():
    g = gate()
    g.t["now"] = 100
    g.note_started()                             # a sweep is under way
    g.note_focus(True)                           # coming back counts as input
    assert g.reason() == idle_gate.IN_USE
    g.t["now"] = 100 + idle_gate.IN_FRONT_IDLE - 1
    assert g.reason() == idle_gate.IN_USE
    g.t["now"] = 100 + idle_gate.IN_FRONT_IDLE + 1
    assert g.allowed()                           # a minute in front without input
    g.note_input()
    assert g.reason() == idle_gate.IN_USE
    g.note_focus(False)                          # switched to another program
    assert g.reason() == idle_gate.IN_USE        # a quick look elsewhere starts nothing
    g.t["now"] += idle_gate.LEAVE_GRACE + 0.1
    g.note_input()                               # the mouse over the window behind does not count
    assert g.allowed()
    g.note_focus(True)
    g.force(60)                                  # "Render now" in the window
    assert g.allowed() and g.forced() and not g.in_use()


def test_nothing_renders_during_a_presentation_not_even_after_render_now():
    g = gate()
    g.t["now"] = 100
    g.force(60)
    g.presenting = lambda: True
    assert g.reason() == idle_gate.PRESENTING
    g.presenting = lambda: False
    assert g.allowed()


def test_without_a_window_reporting_its_focus_the_input_rule_holds():
    g = gate()
    assert g.in_front is None
    g.t["now"] = 25
    assert g.reason() == "you are working"


def test_in_front_is_the_reason_given_before_what_else_keeps_the_machine_busy():
    g = gate(is_busy=lambda: ["a dialog"])
    g.note_focus(True)
    assert g.reason() == idle_gate.IN_USE
    g.note_focus(False)
    g.t["now"] = 100
    assert g.reason() == "waiting for a dialog"
