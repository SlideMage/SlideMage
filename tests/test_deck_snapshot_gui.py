"""The Decks menu, the "Create deck snapshot" dialog, the snapshot run on the
compile slot and the archive question that offers a snapshot first."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QWidget

from slidemage import app_settings, compile_progress, deck_snapshot, qt_gui, qt_snapshot_dialog
from slidemage.deck_snapshot import ExistingSnapshot, SnapshotOptions, SnapshotResult


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(monkeypatch):
    store: dict = {}
    monkeypatch.setattr(app_settings, "get", lambda key, default=None: store.get(key, default))
    monkeypatch.setattr(app_settings, "set", lambda key, value: store.__setitem__(key, value))
    return store


def deck(name: str, archived: bool = False):
    return SimpleNamespace(name=name, archived=archived, path=Path(f"decks/{name}.tex"),
                           supports_version=False, appendix_toc=False)


def press_on_exec(monkeypatch, label: str, seen: list | None = None):
    """Make every QMessageBox.exec() 'click' the button labelled `label`."""
    def fake_exec(box):
        if seen is not None:
            seen.append((box.text(), [b.text() for b in box.buttons()]))
        for button in box.buttons():
            if button.text().replace("&", "") == label:
                button.click()
                return 0
        raise AssertionError(f"no button {label!r} in {[b.text() for b in box.buttons()]}")
    monkeypatch.setattr(QMessageBox, "exec", fake_exec)


# ---------------------------------------------------------------- menu

def test_decks_menu_sits_after_system_and_holds_snapshot_and_import(qapp):
    window = qt_gui.SlideMageWindow(qt_gui.ThemeManager())
    menus = {a.text(): a.menu() for a in window.menuBar().actions()}
    assert list(menus) == ["System", "Decks", "Tabs", "Housekeeping", "Info"]
    decks = [a.text() for a in menus["Decks"].actions()]
    assert decks == ["Create deck snapshot…", "Import PPTX/ODP…"]
    assert "Import PPTX/ODP…" not in [a.text() for a in menus["System"].actions()]
    window.close()


def test_snapshot_banner_only_in_a_snapshot(qapp, monkeypatch, tmp_path):
    import json

    from slidemage import project

    proj = tmp_path / "Proj"
    project.write_project_json(proj, {"format": 1, "snapshot": {
        "deck_name": "t-A", "created": "2026-10-07T14:12:30+02:00", "read_only": True}})
    (tmp_path / "snapshot.json").write_text(json.dumps({"slidemage": {"version": "v5.33.0"}}),
                                            encoding="utf-8")
    banner = qt_gui.SlideMageWindow._build_snapshot_banner
    monkeypatch.setattr(qt_gui, "PROJECT_ROOT", proj)
    label = banner(None)
    assert label.text().startswith(
        "Deck snapshot of t-A, taken 2026-10-07 14:12 with SlideMage v5.33.0.")
    monkeypatch.setattr(qt_gui, "PROJECT_ROOT", tmp_path)   # an ordinary folder
    assert banner(None) is None


# ---------------------------------------------------------------- dialog

def test_dialog_lists_decks_preselects_and_remembers_settings(qapp, settings):
    decks = [deck("t-A"), deck("t-B"), deck("t-Old", archived=True)]
    dialog = qt_snapshot_dialog.SnapshotDialog(None, decks, preselected={"t-B"})
    items = [dialog.deck_list.item(i) for i in range(dialog.deck_list.count())]
    assert [i.isHidden() for i in items] == [False, False, True]      # archived hidden
    assert [d.name for d in dialog.selected_decks()] == ["t-B"]
    assert dialog.folder_radio.isChecked() and not dialog.texmf_checkbox.isChecked()
    dialog.show_archived.setChecked(True)
    items[2].setCheckState(Qt.CheckState.Checked)
    assert [d.name for d in dialog.selected_decks()] == ["t-B", "t-Old"]
    dialog.zip_radio.setChecked(True)
    dialog.texmf_checkbox.setChecked(True)
    dialog.create_button.click()
    assert dialog.result() == 1
    assert settings == {"snapshot_output": "zip", "snapshot_texmf": True, "snapshot_app": False}
    again = qt_snapshot_dialog.SnapshotDialog(None, decks, preselected=set())
    assert again.zip_radio.isChecked() and again.texmf_checkbox.isChecked()
    assert not again.create_button.isEnabled()                         # nothing checked


def test_dialog_select_all_and_busy(qapp, settings):
    decks = [deck("t-A"), deck("t-B")]
    dialog = qt_snapshot_dialog.SnapshotDialog(None, decks, preselected=set(), busy=True)
    next(b for b in dialog.findChildren(QPushButton) if b.text() == "Select all").click()
    assert len(dialog.selected_decks()) == 2
    assert not dialog.create_button.isEnabled()                        # a compile is running
    assert not dialog.busy_label.isHidden()


def test_describe_options_for_the_archive_question():
    assert qt_snapshot_dialog.describe_options(SnapshotOptions()) == \
        "folder, without LaTeX package files"
    assert qt_snapshot_dialog.describe_options(SnapshotOptions(zip=True, texmf=True)) == \
        ".zip file, with LaTeX package files"


# ---------------------------------------------------------------- archive question

def archive_window(monkeypatch, settings):
    calls: list = []
    win = QWidget()   # a parent for the message boxes, carrying the real handlers
    win._do_archive_deck = lambda d: calls.append(("archive", d.name))
    win._start_snapshots = lambda decks, options, after=None: calls.append(
        ("snapshot", [d.name for d in decks], options, after)) or True
    for name in ("_archive_deck", "_archive_after_snapshot"):
        setattr(win, name, getattr(qt_gui.SlideMageWindow, name).__get__(win))
    return win, calls


def test_archive_offers_a_snapshot_first(qapp, monkeypatch, settings):
    win, calls = archive_window(monkeypatch, settings)
    seen: list = []
    press_on_exec(monkeypatch, "Archive only", seen)
    win._archive_deck(deck("t-A"))
    assert calls == [("archive", "t-A")]
    text, buttons = seen[0]
    assert text == "Move t-A.tex to decks/archive/?"
    assert buttons[:2] == ["Snapshot, then archive", "Archive only"]


def test_snapshot_then_archive_archives_only_after_the_snapshot(qapp, monkeypatch, settings):
    win, calls = archive_window(monkeypatch, settings)
    press_on_exec(monkeypatch, "Snapshot, then archive")
    win._archive_deck(deck("t-A"))
    assert len(calls) == 1 and calls[0][:2] == ("snapshot", ["t-A"])   # not archived yet
    after = calls[0][3]
    after([SnapshotResult("t-A", ok=True, path=Path("snapshots/t-A_x"))])
    assert calls[-1] == ("archive", "t-A")


def test_failed_snapshot_archives_only_after_a_second_yes(qapp, monkeypatch, settings):
    win, calls = archive_window(monkeypatch, settings)
    press_on_exec(monkeypatch, "Snapshot, then archive")
    win._archive_deck(deck("t-A"))
    after = calls[0][3]
    failed = [SnapshotResult("t-A", ok=False, error="t-A did not compile")]
    asked: list = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: asked.append(a[2]) or QMessageBox.StandardButton.No)
    after(failed)
    assert calls[-1][0] == "snapshot" and "did not compile" in asked[0]
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    after(failed)
    assert calls[-1] == ("archive", "t-A")


# ---------------------------------------------------------------- the run

def run_window(monkeypatch, settings, compiling=False):
    emitted: list = []
    signal = lambda name: SimpleNamespace(emit=lambda *a: emitted.append((name, *a)))  # noqa: E731
    table = SimpleNamespace(set_compiling=lambda on: emitted.append(("compiling", on)))
    win = SimpleNamespace(
        compiling=compiling, cancel_token=None, _after_snapshots=None,
        _job_status_map={"x": 1}, _job_progress_texts={}, _progress=compile_progress.BatchProgress(),
        footer_timestamp_checkbox=SimpleNamespace(isChecked=lambda: True),
        appendix_toc_checkbox=SimpleNamespace(isChecked=lambda: False),
        active_table=table, archived_table=table,
        signals=SimpleNamespace(log=signal("log"), batch_done=signal("batch_done"),
                                snapshots_done=signal("snapshots_done")),
    )
    for name in ("_start_snapshots", "_run_snapshots_thread"):
        setattr(win, name, getattr(qt_gui.SlideMageWindow, name).__get__(win))

    class SyncThread:
        def __init__(self, target, args=(), daemon=None):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(qt_gui.threading, "Thread", SyncThread)
    monkeypatch.setattr(compile_progress, "spec_for_job", lambda job: compile_progress.JobSpec(3, 1))
    return win, emitted


def test_run_asks_about_old_snapshots_and_passes_the_answer_on(qapp, monkeypatch, settings, tmp_path):
    win, emitted = run_window(monkeypatch, settings)
    old = [ExistingSnapshot(tmp_path / "t-A_2026-09-30_10-05", "t-A", "2026-09-30T10:05", False, 1)]
    monkeypatch.setattr(deck_snapshot, "find_snapshots", lambda names: old)
    monkeypatch.setattr(qt_snapshot_dialog, "ask_about_old_snapshots",
                        lambda parent, existing: qt_snapshot_dialog.DELETE_OLD)
    seen = {}

    def fake_snapshot_decks(decks, options, log, cancel=None, delete_old=None):
        seen.update(decks=[d.name for d in decks], options=options, delete_old=delete_old)
        return [SnapshotResult(d.name, ok=True, path=tmp_path / d.name) for d in decks]

    monkeypatch.setattr(deck_snapshot, "snapshot_decks", fake_snapshot_decks)
    assert win._start_snapshots([deck("t-A"), deck("t-B")], SnapshotOptions())
    assert seen["decks"] == ["t-A", "t-B"] and seen["delete_old"] == old
    assert seen["options"].footer_timestamp is True and seen["options"].appendix_toc is None
    # progress knows every reference and verification compile up front
    assert set(win._job_progress_texts) == {
        "snapshot~t-A", "verify~t-A", "snapshot~t-A-presenter", "verify~t-A-presenter",
        "snapshot~t-B", "verify~t-B", "snapshot~t-B-presenter", "verify~t-B-presenter"}
    assert win._job_status_map == {}
    assert win.compiling is False and win.cancel_token is None       # slot freed again
    assert ("log", "==== Done: 2 of 2 snapshot(s) created ====") in emitted
    assert emitted[-1][0] == "snapshots_done"


def test_run_cancelled_at_the_old_snapshot_question(qapp, monkeypatch, settings, tmp_path):
    win, emitted = run_window(monkeypatch, settings)
    old = [ExistingSnapshot(tmp_path / "x", "t-A", "", True, 1)]
    monkeypatch.setattr(deck_snapshot, "find_snapshots", lambda names: old)
    monkeypatch.setattr(qt_snapshot_dialog, "ask_about_old_snapshots",
                        lambda parent, existing: qt_snapshot_dialog.CANCEL_RUN)
    assert not win._start_snapshots([deck("t-A")], SnapshotOptions())
    assert emitted == [] and win.compiling is False


def test_run_refused_while_compiling(qapp, monkeypatch, settings):
    win, emitted = run_window(monkeypatch, settings, compiling=True)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    assert not win._start_snapshots([deck("t-A")], SnapshotOptions())
    assert emitted == []


def test_summary_text_lists_each_deck(tmp_path):
    text = qt_snapshot_dialog.summary_text([
        SnapshotResult("t-A", ok=True, path=tmp_path / "t-A_2026-10-07_14-12", size=2048,
                       deleted=[tmp_path / "old"]),
        SnapshotResult("t-B", ok=False, error="t-B did not compile"),
        SnapshotResult("t-C", ok=False, skipped=True),
    ])
    assert "✓  t-A: t-A_2026-10-07_14-12  (2 KB) -- 1 older snapshot(s) moved to the trash" in text
    assert "✗  t-B: t-B did not compile" in text
    assert "–  t-C: skipped (stopped)" in text
