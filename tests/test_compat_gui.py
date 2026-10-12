"""The compatibility sheet and the main window's handling of its choices."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton

from slidemage import compat
from slidemage import version as version_mod
from slidemage.ui.dialogs import project_compat
from slidemage.ui.dialogs.project_compat import CompatSheet
from slidemage.ui.workspace import maintenance
from slidemage.ui.workspace.maintenance import MaintenanceMixin

from test_compat import BREAKING, LOOK, MANUAL_FIX, make_project


def click(dialog, text):
    next(b for b in dialog.findChildren(QPushButton) if b.text() == text).click()


def texts(sheet):
    return "\n".join(label.text() for label in sheet.findChildren(QLabel))


@pytest.mark.parametrize("review, labels, default, action", [
    (False, ["Don't ask again", "Not now", "Show report", "Update project"],
     project_compat.NOT_NOW, project_compat.DONT_ASK),
    (True, ["Mark all as read", "Close", "Show report", "Update project"],
     project_compat.CLOSE, project_compat.MARK_READ),
])
def test_compatibility_sheet_modes(tmp_path, qapp, review, labels, default, action):
    root = make_project(tmp_path)
    ev = compat.evaluate(root, "v5.30.0", [BREAKING, LOOK])
    sheet = CompatSheet(None, ev, "v5.30.0", "finance-2025", review=review)
    assert [b.text() for b in sheet.findChildren(QPushButton)] == labels
    assert sheet.choice == default
    text = texts(sheet)
    if review:
        assert "Looks different" in text and "decks/#workdeck.tex:1" in text
        assert not any(p.change.migrate for p in ev.quiet)
    else:
        assert "finance-2025" in text and "1 more change(s) only affect how slides look" in text
        assert "Looks different" not in text
        ev.loud[0].findings = [compat.Finding("decks/a.tex", n, f"message {n}") for n in range(1, 10)]
        overflow = texts(CompatSheet(None, ev, "v5.30.0", "course"))
        assert "decks/a.tex:6: message 6" in overflow and "message 7" not in overflow and "and 3 more" in overflow
    click(sheet, labels[0])
    assert sheet.choice == action


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


@pytest.mark.parametrize("manual_work", [False, True])
def test_update_project_only_acknowledges_when_all_is_fixed(tmp_path, monkeypatch, qapp, manual_work):
    root = make_project(tmp_path)
    changes = [BREAKING, MANUAL_FIX] if manual_work else [BREAKING]
    opened = []
    monkeypatch.setattr(maintenance.open_path, "open_in_default_app", opened.append)
    win = window(root, monkeypatch, changes, project_compat.UPDATE, [])
    win.check_project_compat()
    assert b"\\new" in (root / "decks" / "course.tex").read_bytes()
    if manual_work:
        assert compat.checked_version(root) == "v5.28.1"
        assert opened and opened[0].name == "compat-report.md"
    else:
        assert compat.checked_version(root) == "v5.30.0"


def test_update_is_refused_while_a_source_has_unsaved_edits(tmp_path, monkeypatch, qapp):
    root = make_project(tmp_path)
    win = window(root, monkeypatch, [BREAKING], project_compat.UPDATE, [])
    win.centre.source.dirty_files = lambda: [object()]
    win.check_project_compat()
    assert b"\\old" in (root / "decks" / "course.tex").read_bytes()
