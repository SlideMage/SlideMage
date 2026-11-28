# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Unexpected background errors are logged and delivered to the caller."""
from __future__ import annotations

import logging
from types import SimpleNamespace

from conftest import wait_until
from PySide6.QtCore import QObject, Signal

from slidemage import project_access, updater
from slidemage.ui.presentation import presenter_window
from slidemage.ui.workspace import maintenance


class _Window(QObject):
    project_access_checked = Signal(object)
    update_check_done = Signal(object)

    def __init__(self, project) -> None:
        super().__init__()
        self.project = project
        self.received: list = []
        self.project_access_checked.connect(lambda found: self.received.append(("access", found)))
        self.update_check_done.connect(lambda result: self.received.append(("update", result)))


def test_the_startup_update_check_reports_an_unexpected_error(qapp, monkeypatch, caplog):
    def boom(**_kw):
        raise KeyError("an error type the check never expected")

    monkeypatch.setattr(updater, "fetch_releases", boom)
    window = _Window(SimpleNamespace())
    with caplog.at_level(logging.ERROR):
        maintenance.startup_update_check(window)
        wait_until(lambda: window.received)
    kind, result = window.received[0]
    assert kind == "update" and isinstance(result, KeyError)
    assert "Startup update check failed" in caplog.text
    logged = []
    maintenance.on_startup_update_check_done(SimpleNamespace(log=logged.append), result)
    assert logged and logged[0].startswith("Update check failed")


def test_the_project_access_check_reports_an_unexpected_error(qapp, monkeypatch, tmp_path):
    def boom(_ctx):
        raise ValueError("a probe that fails oddly")

    monkeypatch.setattr(project_access, "problems", boom)
    ctx = SimpleNamespace(root=tmp_path)
    window = _Window(ctx)
    monkeypatch.setattr(maintenance.project, "is_snapshot", lambda _root: False)
    maintenance.check_project_access(window)
    wait_until(lambda: window.received)
    kind, found = window.received[0]
    assert kind == "access" and found == [(tmp_path, "a probe that fails oddly")]


def test_the_presenter_background_helper_logs_what_work_raises(qapp, caplog):
    def boom():
        raise RuntimeError("not an update error")

    with caplog.at_level(logging.ERROR):
        presenter_window.run_in_background(boom)
        wait_until(lambda: "Background work of the Presenter failed" in caplog.text)


def test_a_failing_talk_still_returns_the_window_and_quits_for_a_waiting_update(qapp, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QApplication

    from slidemage.ui.presentation import standalone

    def boom(_path):
        raise RuntimeError("the talk crashed")

    quit_calls = []
    monkeypatch.setattr(standalone, "present_pdf_file", boom)
    monkeypatch.setattr(QApplication, "quit", staticmethod(lambda: quit_calls.append(1)))
    monkeypatch.setattr(presenter_window, "run_in_background", lambda work: None)
    window = presenter_window.PresenterStartWindow()
    window.update_ready = True
    window.present(tmp_path / "talk.pdf")
    assert quit_calls == [1] and not window.presenting
