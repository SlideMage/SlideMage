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
