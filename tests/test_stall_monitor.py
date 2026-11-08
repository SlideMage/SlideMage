# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The debug log's tools for finding a freeze: the stall monitor, the call-stack lines and the timing spans."""
from __future__ import annotations

import logging
import threading
import time

from PySide6.QtCore import QObject
from PySide6.QtTest import QTest

from slidemage import stall_monitor, timing


class Records(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def with_debug_log():
    handler = Records()
    timing.log.addHandler(handler)
    timing.log.setLevel(logging.DEBUG)
    return handler


def test_a_blocked_gui_thread_is_logged_with_where_every_thread_was(qapp):
    handler = with_debug_log()
    parent = QObject()
    worker_stop = threading.Event()
    worker = threading.Thread(target=worker_stop.wait, name="probe-worker", daemon=True)
    worker.start()
    try:
        monitor = stall_monitor.StallMonitor(parent)
        QTest.qWait(120)
        time.sleep(0.5)                                # the GUI thread is busy and cannot beat
        QTest.qWait(150)
        stalls = [m for m in handler.messages if m.startswith("stall ")]
        assert stalls, handler.messages
        assert "late=0.4" in stalls[0] or "late=0.5" in stalls[0]
        assert "GUI@" in stalls[0] and "probe-worker@" in stalls[0]
        del monitor
    finally:
        worker_stop.set()
        timing.log.removeHandler(handler)
        timing.log.setLevel(logging.NOTSET)


def test_the_call_stack_line_names_the_callers_and_the_span_its_seconds():
    handler = with_debug_log()
    try:
        def inner():
            timing.caller("probe", why="test")

        def outer():
            inner()

        outer()
        with timing.span("probe.span", file="x"):
            pass
        assert any(m.startswith("probe why=test stack=") and "outer" in m for m in handler.messages)
        assert any(m.startswith("probe.span seconds=") and m.endswith("file=x") for m in handler.messages)
    finally:
        timing.log.removeHandler(handler)
        timing.log.setLevel(logging.NOTSET)


def test_a_translation_scan_logs_how_many_slide_files_it_read_and_for_how_long(tmp_path):
    from slidemage import slide_language

    slides = tmp_path / "slides"
    slides.mkdir()
    for slug in ("aaa-EN-One", "bbb-EN-Two"):
        (slides / f"{slug}-current.tex").write_text("%% Included in decks: x\n", encoding="utf-8")
    handler = with_debug_log()
    perf = logging.getLogger("slidemage.perf")
    perf.addHandler(handler)
    perf.setLevel(logging.DEBUG)
    try:
        slide_language.TranslationLinks(slides, ("EN", "DE")).group("aaa-EN-One")
        scans = [m for m in handler.messages if m.startswith("slide_language.scan ")]
        assert len(scans) == 1 and "files=2" in scans[0] and "gui=" in scans[0] and "slowest_read_s=" in scans[0]
    finally:
        perf.removeHandler(handler)
        perf.setLevel(logging.NOTSET)
        timing.log.removeHandler(handler)
        timing.log.setLevel(logging.NOTSET)


def test_a_thread_report_keeps_one_frame_of_an_idle_thread_and_many_of_one_waiting_for_a_lock(qapp):
    held = threading.Condition()
    started = threading.Event()

    def waits_for_the_lock():
        def deeper():
            started.set()
            with held:
                pass
        deeper()

    idle = threading.Thread(target=threading.Event().wait, name="idle-one", daemon=True)
    idle.start()
    with held:                                         # taken here, so the worker blocks on it
        worker = threading.Thread(target=waits_for_the_lock, name="blocked-one", daemon=True)
        worker.start()
        started.wait(2)
        time.sleep(0.1)
        report = stall_monitor.thread_report(threading.get_ident())
    part = {p.split("@")[0]: p for p in report.split("; ")}
    assert part["idle-one"].count(" < ") == 0
    assert "deeper" in part["blocked-one"] and "waits_for_the_lock" in part["blocked-one"]
