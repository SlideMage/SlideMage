"""The compatibility dialog and the main window's handling of its choices."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from slidemage import compat, qt_compat_dialog
from slidemage import version as version_mod
from slidemage.qt_compat_dialog import CompatDialog
from slidemage.ui.workspace import maintenance
from slidemage.ui.workspace.maintenance import MaintenanceMixin

from test_compat import BREAKING, LOOK, MANUAL_FIX, make_project


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def click(dialog, text):
    next(b for b in dialog.findChildren(QPushButton) if b.text() == text).click()


def test_startup_dialog_offers_the_four_choices_and_not_now_is_the_default(tmp_path, qapp):
    root = make_project(tmp_path)
    ev = compat.evaluate(root, "v5.30.0", [BREAKING, LOOK])
    dialog = CompatDialog(None, ev, "v5.30.0")
    labels = [b.text() for b in dialog.findChildren(QPushButton)]
    assert labels == ["Update project", "Show report", "Not now", "Don't ask again"]
    assert dialog.choice == qt_compat_dialog.NOT_NOW          # closing it counts as Not now
    click(dialog, "Don't ask again")
    assert dialog.choice == qt_compat_dialog.DONT_ASK


def test_review_dialog_lists_quiet_changes_and_has_no_not_now(tmp_path, qapp):
    root = make_project(tmp_path)
    ev = compat.evaluate(root, "v5.30.0", [BREAKING, LOOK])
    html = qt_compat_dialog.render_html(ev, "v5.30.0")
    assert "Looks different" in html and "decks/#workdeck.tex:1" in html
    dialog = CompatDialog(None, ev, "v5.30.0", review=True)
    assert [b.text() for b in dialog.findChildren(QPushButton)] == [
        "Update project", "Show report", "Mark all as read", "Close"]
    assert not any(p.change.migrate for p in ev.quiet)
    assert "Looks different" not in qt_compat_dialog.render_html(ev, "v5.30.0", include_quiet=False)


def window(root, monkeypatch, changes, choice, logged):
    """A stand-in main window running the real handlers."""
    monkeypatch.setattr(maintenance, "PROJECT_ROOT", root)
    monkeypatch.setattr(version_mod, "VERSION_NUMBER", "v5.30.0")
    monkeypatch.setattr(compat, "CHANGES", changes)

    class FakeDialog:
        def __init__(self, *_args, **_kwargs):
            self.choice = choice

        def exec(self):
            return 1

    monkeypatch.setattr(maintenance, "CompatDialog", FakeDialog)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    win = SimpleNamespace(
        log=logged.append, _slide_source_tabs={}, _deck_editor_tabs={},
        refresh_open_deck_editors=lambda: None)
    for name in ("check_project_compat", "_show_compat", "_compat_update", "_compat_report",
                 "_compat_newer_notice"):
        setattr(win, name, getattr(MaintenanceMixin, name).__get__(win))
    return win


def test_not_now_keeps_the_warning_dont_ask_again_ends_it(tmp_path, monkeypatch, qapp):
    root = make_project(tmp_path)
    logged = []
    win = window(root, monkeypatch, [BREAKING, MANUAL_FIX], qt_compat_dialog.NOT_NOW, logged)
    win.check_project_compat()
    assert compat.evaluate(root, "v5.30.0", [BREAKING, MANUAL_FIX]).loud       # still there

    win = window(root, monkeypatch, [BREAKING, MANUAL_FIX], qt_compat_dialog.DONT_ASK, logged)
    win.check_project_compat()
    assert not compat.evaluate(root, "v5.30.0", [BREAKING, MANUAL_FIX]).everything


def test_update_project_migrates_and_moves_the_baseline_when_all_is_fixed(tmp_path, monkeypatch, qapp):
    root = make_project(tmp_path)
    logged = []
    win = window(root, monkeypatch, [BREAKING], qt_compat_dialog.UPDATE, logged)
    win.check_project_compat()
    assert b"\\new" in (root / "decks" / "course.tex").read_bytes()
    assert any(line.startswith("  backup:") for line in logged)
    assert compat.checked_version(root) == "v5.30.0"


def test_update_project_with_work_left_does_not_move_the_baseline(tmp_path, monkeypatch, qapp):
    root = make_project(tmp_path)
    logged = []
    win = window(root, monkeypatch, [BREAKING, MANUAL_FIX], qt_compat_dialog.UPDATE, logged)
    opened = []
    monkeypatch.setattr(maintenance.open_path, "open_in_default_app", opened.append)
    win.check_project_compat()
    assert compat.checked_version(root) == "v5.28.1"          # the manual-only change is still open
    assert opened and opened[0].name == "compat-report.md"


def test_update_is_refused_while_a_source_editor_is_open(tmp_path, monkeypatch, qapp):
    root = make_project(tmp_path)
    win = window(root, monkeypatch, [BREAKING], qt_compat_dialog.UPDATE, [])
    win._slide_source_tabs = {root / "decks" / "course.tex": object()}
    win.check_project_compat()
    assert b"\\old" in (root / "decks" / "course.tex").read_bytes()
