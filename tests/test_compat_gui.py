"""The compatibility sheet and the main window's handling of its choices."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton

from slidemage import compat
from slidemage import version as version_mod
from slidemage.ui.dialogs import project_compat
from slidemage.ui.dialogs.project_compat import CompatSheet
from slidemage.ui.workspace import maintenance
from slidemage.ui.workspace.maintenance import MaintenanceMixin

from test_compat import BREAKING, LOOK, MANUAL_FIX, make_project


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def click(dialog, text):
    next(b for b in dialog.findChildren(QPushButton) if b.text() == text).click()


def texts(sheet):
    return "\n".join(label.text() for label in sheet.findChildren(QLabel))


def test_startup_sheet_offers_the_four_choices_and_not_now_is_the_default(tmp_path, qapp):
    root = make_project(tmp_path)
    ev = compat.evaluate(root, "v5.30.0", [BREAKING, LOOK])
    sheet = CompatSheet(None, ev, "v5.30.0", "finance-2025")
    labels = [b.text() for b in sheet.findChildren(QPushButton)]
    assert labels == ["Don't ask again", "Not now", "Show report", "Update project"]
    assert sheet.choice == project_compat.NOT_NOW          # closing it counts as Not now
    text = texts(sheet)
    assert "finance-2025" in text and "1 more change(s) only affect how slides look" in text
    assert "Looks different" not in text                  # the quiet ones are only in the review
    click(sheet, "Don't ask again")
    assert sheet.choice == project_compat.DONT_ASK


def test_review_sheet_lists_quiet_changes_and_has_no_not_now(tmp_path, qapp):
    root = make_project(tmp_path)
    ev = compat.evaluate(root, "v5.30.0", [BREAKING, LOOK])
    sheet = CompatSheet(None, ev, "v5.30.0", "course", review=True)
    assert "Looks different" in texts(sheet) and "decks/#workdeck.tex:1" in texts(sheet)
    assert [b.text() for b in sheet.findChildren(QPushButton)] == [
        "Mark all as read", "Close", "Show report", "Update project"]
    assert sheet.choice == project_compat.CLOSE
    assert not any(p.change.migrate for p in ev.quiet)
    click(sheet, "Mark all as read")
    assert sheet.choice == project_compat.MARK_READ


def test_findings_are_listed_up_to_a_few_and_the_rest_counted(tmp_path, qapp):
    root = make_project(tmp_path)
    ev = compat.evaluate(root, "v5.30.0", [BREAKING])
    ev.loud[0].findings = [compat.Finding("decks/a.tex", n, f"message {n}") for n in range(1, 10)]
    text = texts(CompatSheet(None, ev, "v5.30.0", "course"))
    assert "decks/a.tex:6: message 6" in text and "message 7" not in text and "and 3 more" in text


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

    monkeypatch.setattr(maintenance, "CompatSheet", FakeDialog)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    win = SimpleNamespace(
        log=logged.append, centre=SimpleNamespace(source=SimpleNamespace(dirty_files=lambda: [])),
        refresh_open_deck_editors=lambda: None)
    for name in ("check_project_compat", "_show_compat", "_compat_update", "_compat_report",
                 "_compat_newer_notice"):
        setattr(win, name, getattr(MaintenanceMixin, name).__get__(win))
    return win


def test_not_now_keeps_the_warning_dont_ask_again_ends_it(tmp_path, monkeypatch, qapp):
    root = make_project(tmp_path)
    logged = []
    win = window(root, monkeypatch, [BREAKING, MANUAL_FIX], project_compat.NOT_NOW, logged)
    win.check_project_compat()
    assert compat.evaluate(root, "v5.30.0", [BREAKING, MANUAL_FIX]).loud       # still there

    win = window(root, monkeypatch, [BREAKING, MANUAL_FIX], project_compat.DONT_ASK, logged)
    win.check_project_compat()
    assert not compat.evaluate(root, "v5.30.0", [BREAKING, MANUAL_FIX]).everything


def test_update_project_migrates_and_moves_the_baseline_when_all_is_fixed(tmp_path, monkeypatch, qapp):
    root = make_project(tmp_path)
    logged = []
    win = window(root, monkeypatch, [BREAKING], project_compat.UPDATE, logged)
    win.check_project_compat()
    assert b"\\new" in (root / "decks" / "course.tex").read_bytes()
    assert any(line.startswith("  backup:") for line in logged)
    assert compat.checked_version(root) == "v5.30.0"


def test_update_project_with_work_left_does_not_move_the_baseline(tmp_path, monkeypatch, qapp):
    root = make_project(tmp_path)
    logged = []
    win = window(root, monkeypatch, [BREAKING, MANUAL_FIX], project_compat.UPDATE, logged)
    opened = []
    monkeypatch.setattr(maintenance.open_path, "open_in_default_app", opened.append)
    win.check_project_compat()
    assert compat.checked_version(root) == "v5.28.1"          # the manual-only change is still open
    assert opened and opened[0].name == "compat-report.md"


def test_update_is_refused_while_a_source_has_unsaved_edits(tmp_path, monkeypatch, qapp):
    root = make_project(tmp_path)
    win = window(root, monkeypatch, [BREAKING], project_compat.UPDATE, [])
    win.centre.source.dirty_files = lambda: [object()]
    win.check_project_compat()
    assert b"\\old" in (root / "decks" / "course.tex").read_bytes()
