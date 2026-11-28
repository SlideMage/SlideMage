# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The terminal's edit watch scans the project on a thread of its own once a second (2026-11-16: on a synced
project folder each scan took 1 to 4 s on the GUI thread and the window froze again and again)."""
from __future__ import annotations

import threading
import time

from PySide6.QtTest import QTest

from slidemage.ai import project_watch
from slidemage.ui.workspace.terminal import sync


def wait_for(condition, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        QTest.qWait(10)
    return condition()


def test_the_timed_scans_run_off_the_gui_thread_and_report_the_changes(qapp, tmp_path, monkeypatch):
    (tmp_path / "slides").mkdir()
    real_scan, threads = project_watch.scan, []

    def scan(root):
        threads.append(threading.current_thread().name)
        return real_scan(root)

    monkeypatch.setattr(project_watch, "scan", scan)
    monkeypatch.setattr(sync, "POLL_MS", 20)
    seen = []
    watch = sync.ExternalEditWatch(tmp_path, seen.append)
    watch.start()
    assert threads == [threading.current_thread().name]          # the baseline: at once
    new = tmp_path / "slides" / "abc-EN-New-current.tex"
    new.write_text("x", encoding="utf-8")
    assert wait_for(lambda: bool(seen))
    assert seen[0].added == (new,) and any(name != threading.main_thread().name for name in threads)
    watch.stop(last_look=False)


def test_a_scan_on_the_spot_wins_over_one_still_running(qapp, tmp_path, monkeypatch):
    (tmp_path / "slides").mkdir()
    release, real_scan = threading.Event(), project_watch.scan

    def scan(root):
        if threading.current_thread() is not threading.main_thread():
            stale = real_scan(root)                  # what the disk held when this slow scan began
            release.wait(5)
            return stale
        return real_scan(root)

    monkeypatch.setattr(project_watch, "scan", scan)
    seen = []
    watch = sync.ExternalEditWatch(tmp_path, seen.append)
    watch.start()
    watch._poll_in_background()                       # a slow background scan is out ...
    QTest.qWait(50)
    new = tmp_path / "slides" / "abc-EN-New-current.tex"
    new.write_text("x", encoding="utf-8")
    watch.poll()                                      # ... and a poll on the spot sees the new file first
    assert [c.added for c in seen] == [(new,)]
    release.set()
    assert wait_for(lambda: not watch._scanning)
    assert len(seen) == 1                             # the stale result does not report the file as removed
    watch.stop(last_look=False)
