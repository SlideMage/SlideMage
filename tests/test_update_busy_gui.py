# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Updating SlideMage itself: the check and the download run behind a BusySheet, off the GUI thread."""
from __future__ import annotations

import threading

from PySide6.QtWidgets import QMessageBox, QPushButton, QWidget

from conftest import wait_until
from slidemage import updater
from slidemage.ui.kit.widgets import BusySheet
from slidemage.ui.workspace import maintenance


def _window(logged):
    win = QWidget()
    win.log = logged.append
    return win


def test_the_check_fetches_off_the_gui_thread_and_answers_in_done(monkeypatch, qapp):
    threads, boxes, gate = [], [], threading.Event()

    def fetch_releases():
        threads.append(threading.current_thread())
        gate.wait(5)
        return []

    monkeypatch.setattr(updater, "fetch_releases", fetch_releases)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: boxes.append(a[2]))
    win = _window([])
    maintenance.on_check_for_updates(win)
    wait_until(lambda: threads)
    sheet = win.findChild(BusySheet)
    assert sheet.isVisible() and boxes == []
    gate.set()
    wait_until(lambda: boxes)
    assert threads[0] is not threading.main_thread() and "up to date" in boxes[0]


def test_cancel_during_the_download_stops_it_without_an_error_box(monkeypatch, qapp):
    started, boxes, logged, installed = threading.Event(), [], [], []

    def download(release, dest, on_progress):
        started.set()
        while on_progress(1, 10):                  # a slow download, until Cancel
            threading.Event().wait(0.005)
        raise updater.UpdateError("Download canceled.")

    monkeypatch.setattr(updater, "download", download)
    monkeypatch.setattr(updater, "install_zip", lambda *a: installed.append(a))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: boxes.append(a))
    win = _window(logged)
    maintenance.download_and_install_update(win, updater.Release("v0.9.9.9", "https://example.invalid", "a", 1, ""))
    wait_until(started.is_set)
    sheet = win.findChild(BusySheet)
    next(b for b in sheet.findChildren(QPushButton) if b.text() == "Cancel").click()
    wait_until(lambda: logged)
    assert "canceled" in logged[0] and boxes == [] and installed == []
