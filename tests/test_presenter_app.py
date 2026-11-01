# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""SlideMage Presenter's entry point and start window (docs/plans/presenter-app.md, step 2). The layout store is
isolated by conftest."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPoint, QUrl, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication

import slidemage
from slidemage import presenter_app
from slidemage.presentation import recent
from slidemage.ui import layout_settings
from slidemage.ui.presentation import presenter_window
from slidemage.ui.presentation.presenter_window import PresenterStartWindow


def pdfs(tmp_path: Path, count: int) -> list[Path]:
    made = []
    for index in range(count):
        path = tmp_path / f"talk{index}.pdf"
        path.write_bytes(b"%PDF-1.4\n")
        made.append(path)
    return made


# -- presentation/recent.py -------------------------------------------------------------------

def test_add_moves_to_front_and_dedupes(tmp_path):
    a, b = pdfs(tmp_path, 2)
    recent.add(a)
    recent.add(b)
    assert recent.load() == [b, a]
    recent.add(a)
    assert recent.load() == [a, b]
    recent.add(Path(str(a).upper()) if os.name == "nt" else a)
    assert len(recent.load()) == 2


def test_only_ten_are_kept(tmp_path):
    files = pdfs(tmp_path, 12)
    for path in files:
        recent.add(path)
    assert recent.load() == list(reversed(files))[:10]
    assert len(layout_settings.get(recent.STORE_KEY)) == 10


def test_missing_files_are_left_out_when_listed(tmp_path):
    a, b = pdfs(tmp_path, 2)
    recent.add(a)
    recent.add(b)
    a.unlink()
    assert recent.load() == [b]


@pytest.mark.parametrize("junk", ["text", 5, {"a": 1}, [1, None, ""], None])
def test_a_malformed_store_is_ignored(junk, tmp_path):
    layout_settings.set(recent.STORE_KEY, junk)
    assert recent.load() == []
    (a,) = pdfs(tmp_path, 1)
    recent.add(a)
    assert recent.load() == [a]


# -- the program -------------------------------------------------------------------------------

def test_self_test_in_a_subprocess():
    env = {**os.environ, "PYTHONPATH": str(Path(slidemage.__file__).resolve().parents[1]),
           "QT_QPA_PLATFORM": "offscreen"}
    done = subprocess.run([sys.executable, "-m", "slidemage.presenter_app", "--self-test"],
                          capture_output=True, text=True, timeout=120, env=env)
    assert done.returncode == 0, done.stderr[-2000:]
    assert "SlideMage Presenter self-test: ok" in done.stdout


def test_pdf_arguments_keep_only_pdfs():
    assert presenter_app.pdf_arguments(["a.pdf", "--x", "B.PDF", "c.txt"]) == [Path("a.pdf"), Path("B.PDF")]


# -- the start window -------------------------------------------------------------------------

@pytest.fixture
def presented(monkeypatch):
    """present_pdf_file replaced: records the path and whether the window was hidden meanwhile."""
    calls: list[tuple[Path, bool]] = []
    result = {"value": True}
    window: dict = {}

    def fake(path):
        calls.append((path, window["w"].isHidden()))
        return result["value"]

    monkeypatch.setattr(presenter_window.standalone, "present_pdf_file", fake)
    return calls, result, window


def test_empty_state(qapp):
    win = PresenterStartWindow()
    assert win.windowTitle() == "SlideMage Presenter"
    assert win.rows == [] and win.empty_note is not None
    assert "appear here" in win.empty_note.text()


def test_recent_entries_are_listed(qapp, tmp_path):
    a, b = pdfs(tmp_path, 2)
    recent.add(a)
    recent.add(b)
    win = PresenterStartWindow()
    assert [row.path for row in win.rows] == [b, a]
    assert win.empty_note is None


def test_choosing_an_entry_presents_it(qapp, tmp_path, presented):
    calls, _result, window = presented
    a, b = pdfs(tmp_path, 2)
    recent.add(a)
    recent.add(b)
    win = window["w"] = PresenterStartWindow()
    win.show()
    win.rows[1].clicked.emit()
    assert calls == [(a, True)]               # the window was hidden during the talk
    assert win.isVisible()                    # and is back
    assert recent.load() == [a, b]
    assert [row.path for row in win.rows] == [a, b]


def test_a_pdf_that_could_not_be_opened_is_not_remembered(qapp, tmp_path, presented):
    calls, result, window = presented
    (a,) = pdfs(tmp_path, 1)
    result["value"] = False
    win = window["w"] = PresenterStartWindow()
    win.present(a)
    assert calls == [(a, True)]
    assert recent.load() == []
    assert win.isVisible()


def test_dropping_a_pdf_presents_it(qapp, tmp_path, presented):
    calls, _result, window = presented
    a, = pdfs(tmp_path, 1)
    win = window["w"] = PresenterStartWindow()
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(tmp_path / "notes.txt")), QUrl.fromLocalFile(str(a))])
    win.dropEvent(QDropEvent(QPoint(5, 5), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.NoModifier))
    QApplication.processEvents()
    assert [call[0] for call in calls] == [a]


# -- macOS: a file opened from Finder ---------------------------------------------------------

def test_file_open_event_presents_a_pdf_and_ignores_others(qapp, tmp_path, presented):
    from PySide6.QtGui import QFileOpenEvent

    calls, _result, window = presented
    a, = pdfs(tmp_path, 1)
    win = window["w"] = PresenterStartWindow()
    flt = presenter_app.make_filter(qapp)
    try:
        flt.pending.clear()
        qapp.sendEvent(qapp, QFileOpenEvent(str(a)))             # before the window exists: queued
        assert flt.pending == [a] and calls == []
        flt.pending.clear()
        flt.window = win
        qapp.sendEvent(qapp, QFileOpenEvent(str(tmp_path / "x.txt")))
        qapp.sendEvent(qapp, QFileOpenEvent(str(a)))
        QApplication.processEvents()
        assert [call[0] for call in calls] == [a]
    finally:
        qapp.removeEventFilter(flt)
        flt.deleteLater()


def test_a_pdf_opened_during_a_talk_waits_until_the_talk_has_ended(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QCoreApplication
    a, b = pdfs(tmp_path, 2)
    win = PresenterStartWindow()
    calls = []

    def fake(path):
        calls.append(path)
        if path == a:
            win.present(b)                    # macOS's "open this file" while the first talk runs
            assert calls == [a]               # not on top of the running talk
        return True

    monkeypatch.setattr(presenter_window.standalone, "present_pdf_file", fake)
    win.present(a)
    QCoreApplication.processEvents()
    assert calls == [a, b] and not win.presenting and win.waiting == []
