# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The debug log's tools for finding a freeze: the stall monitor, the call-stack lines and the timing spans."""
from __future__ import annotations

from conftest import pause

import logging
import os
import threading
import time

from PySide6.QtCore import QObject

from slidemage import stall_monitor, timing


def test_a_blocked_gui_thread_is_logged_with_where_every_thread_was(qapp, caplog):
    caplog.set_level(logging.DEBUG, logger=timing.log.name)
    parent = QObject()
    worker_stop = threading.Event()
    worker = threading.Thread(target=worker_stop.wait, name="probe-worker", daemon=True)
    worker.start()
    try:
        monitor = stall_monitor.StallMonitor(parent)
        pause(120)
        time.sleep(0.5)                                # the GUI thread is busy and cannot beat
        pause(150)
        stalls = [m for m in caplog.messages if m.startswith("stall ")]
        assert stalls, caplog.messages
        assert all(part in stalls[0] for part in ("late=", "GUI@", "probe-worker@"))
        del monitor
    finally:
        worker_stop.set()


def test_the_call_stack_line_names_the_callers_and_the_span_its_seconds(caplog):
    caplog.set_level(logging.DEBUG, logger=timing.log.name)

    def inner():
        timing.caller("probe", why="test")

    inner()
    with timing.span("probe.span", file="x"):
        pass
    assert any(m.startswith("probe why=test stack=") and "test_the_call_stack_line" in m for m in caplog.messages)
    assert any(m.startswith("probe.span seconds=") and m.endswith("file=x") for m in caplog.messages)


def test_translation_listing_logs_the_scan_and_cache_hit(tmp_path, caplog):
    from slidemage import slide_language

    slides = tmp_path / "slides"
    slides.mkdir()
    for slug in ("aaa-EN-One", "bbb-EN-Two"):
        path = slides / f"{slug}-current.tex"
        path.write_text("%% Included in decks: x\n", encoding="utf-8")
        os.utime(path, (1_000_000, 1_000_000))
    for logger in (timing.log.name, "slidemage.perf"):
        caplog.set_level(logging.DEBUG, logger=logger)
    slide_language.clear_cache()
    try:
        for _ in range(2):
            slide_language.TranslationLinks(slides, ("EN", "DE")).group("aaa-EN-One")
        first, cached = [m for m in caplog.messages if m.startswith("slide_language.scan ")]
        assert all(s in first for s in ("cached=False", "files=2", "gui=", "slowest_read_s="))
        assert "cached=True" in cached
        assert all("listing_s=" in m and "settled=True" in m and "caller='test_stall_monitor.py:" in m
                   for m in (first, cached))
    finally:
        slide_language.clear_cache()


def test_a_thread_report_keeps_one_frame_of_an_idle_thread_and_many_of_one_waiting_for_a_lock(qapp):
    held = threading.Condition()
    started = threading.Event()

    def waits_for_the_lock():
        def deeper():
            started.set()
            with held:
                pass
        deeper()

    idle_stop = threading.Event()
    idle = threading.Thread(target=idle_stop.wait, name="idle-one", daemon=True)
    idle.start()
    with held:                                         # taken here, so the worker blocks on it
        worker = threading.Thread(target=waits_for_the_lock, name="blocked-one", daemon=True)
        worker.start()
        started.wait(2)
        time.sleep(0.1)
        report = stall_monitor.thread_report(threading.get_ident())
    idle_stop.set()
    worker.join(timeout=2)
    idle.join(timeout=2)
    part = {p.split("@")[0]: p for p in report.split("; ")}
    assert part["idle-one"].count(" < ") == 0
    assert "deeper" in part["blocked-one"] and "waits_for_the_lock" in part["blocked-one"]
