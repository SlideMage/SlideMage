"""Focused offscreen regressions for GUI data-loss cases from the 2026-09 review."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QMessageBox

from slidemage import alt_images, housekeeping
from slidemage.ui.workspace import window as window_module
from slidemage.ai.providers import OllamaProvider
from slidemage.ui.dialogs.open_project import OpenProjectSheet

from conftest import build_window


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _mock_ollama_lists(monkeypatch) -> None:
    monkeypatch.setattr(OllamaProvider, "list_models", lambda self, vision_only=False: [])


def _make_window(monkeypatch, qapp):
    _mock_ollama_lists(monkeypatch)
    return build_window(monkeypatch)


def _write_slide(path: Path, text: str = "\\slide{abc-EN-Test}\nBODY\n") -> Path:
    path.write_text(text, encoding="utf-8", newline="")
    return path


def _open_dirty_source(window, path: Path, monkeypatch):
    monkeypatch.setattr(alt_images, "load_slide_notes", lambda: {})
    window.open_slide_editor(path)
    file = window.centre.source.current
    cursor = file.editor.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    cursor.insertText("\n% unsaved edit")
    file.editor.setTextCursor(cursor)
    assert file.dirty
    return file


def test_main_window_cancel_keeps_dirty_source_open(monkeypatch, qapp, tmp_path):
    window = _make_window(monkeypatch, qapp)
    file = _open_dirty_source(window, _write_slide(tmp_path / "abc-EN-Test-current.tex"), monkeypatch)
    saved = []
    file.save = lambda: saved.append(True)  # must not run after Cancel
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Cancel,
    )

    assert window.close() is False
    assert file.dirty
    assert not saved


def test_main_window_saves_dirty_source_before_close(monkeypatch, qapp, tmp_path):
    window = _make_window(monkeypatch, qapp)
    file = _open_dirty_source(window, _write_slide(tmp_path / "abc-EN-Test-current.tex"), monkeypatch)
    calls = []

    def save_without_disk_write():
        calls.append(file.path)
        file.editor.mark_saved()
        return True

    file.save = save_without_disk_write
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    assert window.close() is True
    assert calls == [file.path]
    assert not file.dirty


def test_main_window_stays_open_when_source_save_is_cancelled(monkeypatch, qapp, tmp_path):
    window = _make_window(monkeypatch, qapp)
    file = _open_dirty_source(window, _write_slide(tmp_path / "abc-EN-Test-current.tex"), monkeypatch)
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    file.save = lambda: False

    assert window.close() is False
    assert file.dirty


def test_open_project_resolves_dirty_source_before_relaunch(monkeypatch, qapp, tmp_path):
    window = _make_window(monkeypatch, qapp)
    file = _open_dirty_source(window, _write_slide(tmp_path / "abc-EN-Test-current.tex"), monkeypatch)
    chosen = tmp_path / "another-project"
    monkeypatch.setattr(OpenProjectSheet, "exec", lambda sheet: sheet.choose(chosen))
    relaunched = []
    monkeypatch.setattr(window_module.project, "relaunch_with_project", relaunched.append)
    titles = []

    def answer(_parent, title, *_args, **_kwargs):
        titles.append(title)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", answer)
    window._on_open_project()

    assert titles == ["Unsaved source edits"]
    assert relaunched == [chosen]
    assert file.dirty  # the explicit Discard choice applies to this relaunch
    assert window.isHidden()


def test_temp_cleanup_removes_only_helper_returned_build_items(monkeypatch, qapp, tmp_path):
    window = _make_window(monkeypatch, qapp)
    build_root = tmp_path / "build"
    build_root.mkdir()
    old_file = build_root / "legacy.log"
    old_file.write_text("old", encoding="utf-8")
    old_run = build_root / "old-run"
    old_run.mkdir()
    (old_run / "output.pdf").write_bytes(b"old")
    monkeypatch.setattr(housekeeping.compiler, "removable_build_entries", lambda: [old_file, old_run])
    monkeypatch.setattr(housekeeping, "DECKS_DIR", tmp_path / "decks")
    monkeypatch.setattr(housekeeping, "TEMP_DIR", tmp_path / ".temp")
    housekeeping.DECKS_DIR.mkdir()
    housekeeping.TEMP_DIR.mkdir()
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    window._remove_temp_files()

    assert not old_file.exists()
    assert not old_run.exists()
    assert "2 build item(s)" in window.log_drawer.text.toPlainText()
