"""The ⋮ menu's Decks section, the "Create deck snapshot" dialog, the snapshot run on the
compile slot and the archive question that offers a snapshot first."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton, QWidget

from conftest import EXAMPLE_PROJECT
from slidemage import app_settings, compile_progress, deck_snapshot
from slidemage.project import ProjectContext
from slidemage.deck_snapshot import ExistingSnapshot, SnapshotOptions, SnapshotResult
from slidemage.ui.dialogs import snapshot as snapshot_sheets
from slidemage.ui.workspace import compile_actions, deck_actions
from slidemage.ui.workspace import window as window_module


@pytest.fixture
def settings(monkeypatch):
    store: dict = {}
    monkeypatch.setattr(app_settings, "get", lambda _ctx, key, default=None: store.get(key, default))
    monkeypatch.setattr(app_settings, "set", lambda _ctx, key, value: store.__setitem__(key, value))
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

def test_snapshot_banner_only_in_a_snapshot(qapp, monkeypatch, tmp_path):
    import json

    from slidemage import project

    proj = tmp_path / "Proj"
    project.write_project_json(proj, {"format": 1, "snapshot": {
        "deck_name": "t-A", "created": "2026-10-07T14:12:30+02:00", "read_only": True}})
    (tmp_path / "snapshot.json").write_text(json.dumps({"slidemage": {"version": "v5.33.0"}}),
                                            encoding="utf-8")
    banner = window_module.WorkspaceWindow._build_snapshot_banner
    label = banner(SimpleNamespace(project=ProjectContext.at(proj)))
    assert label.text().startswith(
        "Deck snapshot of t-A, taken 2026-10-07 14:12 with SlideMage v5.33.0.")
    assert banner(SimpleNamespace(project=ProjectContext.at(tmp_path))) is None     # an ordinary folder


@pytest.mark.parametrize("button, expected", [
    ("Compile anyway", ["t-A-instructor", "t-A-during-course"]),
    ("Skip unchanged", ["t-A-during-course"]),
    ("Cancel", []),
    (None, ["t-A-instructor"]),
])
def test_unchanged_versions_are_compiled_only_after_asking(ctx, qapp, monkeypatch, button, expected):
    names = ["t-A-instructor", "t-A-during-course"] if button else ["t-A-instructor"]
    jobs = [SimpleNamespace(jobname=name) for name in names]
    monkeypatch.setattr(compile_actions.compiler, "unchanged_jobs",
                        lambda ctx, jobs, dests: [(jobs[0], "2026-10-08T07:51:00+02:00")] if button else [])
    seen: list = []
    if button:
        press_on_exec(monkeypatch, button, seen)
    else:
        monkeypatch.setattr(QMessageBox, "exec", lambda box: pytest.fail("asked"))
    win = QWidget()
    win.log = lambda line: None
    win.project = None
    result = compile_actions._confirm_unchanged_jobs(win, jobs, {})
    assert [j.jobname for j in result] == expected
    if button:
        assert "t-A-instructor (compiled 2026-10-08 07:51)" in seen[0][0]
    else:
        assert result == jobs


# ---------------------------------------------------------------- sheet

def test_sheet_lists_decks_preselects_and_remembers_settings(qapp, settings):
    decks = [deck("t-A"), deck("t-B"), deck("t-Old", archived=True)]
    dialog = snapshot_sheets.SnapshotSheet(None, EXAMPLE_PROJECT, decks, preselected={"t-B"})
    items = [dialog.deck_list.item(i) for i in range(dialog.deck_list.count())]
    assert [i.isHidden() for i in items] == [False, False, True]      # archived hidden
    assert [d.name for d in dialog.selected_decks()] == ["t-B"]
    assert dialog.output.current() == "folder" and not dialog.texmf_checkbox.isChecked()
    dialog.show_archived.setChecked(True)
    items[2].setCheckState(Qt.CheckState.Checked)
    assert [d.name for d in dialog.selected_decks()] == ["t-B", "t-Old"]
    dialog.output.set_current("zip")
    dialog.texmf_checkbox.setChecked(True)
    dialog.create_button.click()
    assert dialog.result() == 1
    assert settings == {"snapshot_output": "zip", "snapshot_texmf": True, "snapshot_app": False}
    again = snapshot_sheets.SnapshotSheet(None, EXAMPLE_PROJECT, decks, preselected=set())
    assert again.output.current() == "zip" and again.texmf_checkbox.isChecked()
    assert not again.create_button.isEnabled()                         # nothing checked


def test_sheet_select_all_and_busy(qapp, settings):
    decks = [deck("t-A"), deck("t-B")]
    dialog = snapshot_sheets.SnapshotSheet(None, EXAMPLE_PROJECT, decks, preselected=set(), busy=True)
    next(b for b in dialog.findChildren(QPushButton) if b.text() == "Select all").click()
    assert len(dialog.selected_decks()) == 2
    assert not dialog.create_button.isEnabled()                        # a compile is running
    assert not dialog.busy_label.isHidden()


# ---------------------------------------------------------------- archive question

def archive_window(monkeypatch, settings):
    calls: list = []
    win = QWidget()   # a parent for the message boxes
    win.project = EXAMPLE_PROJECT
    monkeypatch.setattr(deck_actions, "do_archive_deck", lambda _window, d: calls.append(("archive", d.name)))
    monkeypatch.setattr(compile_actions, "start_snapshots", lambda _window, decks, options, after=None: calls.append(
        ("snapshot", [d.name for d in decks], options, after)) or True)
    return win, calls


@pytest.mark.parametrize("button, snapshot_ok", [
    ("Archive only", None), ("Snapshot, then archive", True), ("Snapshot, then archive", False),
])
def test_archive_with_or_without_a_snapshot(qapp, monkeypatch, settings, button, snapshot_ok):
    win, calls = archive_window(monkeypatch, settings)
    press_on_exec(monkeypatch, button)
    deck_actions.archive_deck(win, deck("t-A"))
    if snapshot_ok is None:
        assert calls == [("archive", "t-A")]
        return
    assert len(calls) == 1 and calls[0][:2] == ("snapshot", ["t-A"])   # not archived yet
    after = calls[0][3]
    if snapshot_ok:
        after([SnapshotResult("t-A", ok=True, path=Path("snapshots/t-A_x"))])
    else:
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

def run_window(monkeypatch, settings, running=False, ctx=EXAMPLE_PROJECT):
    """A window whose compile controller only records the run it is asked to start."""
    started: list = []
    win = SimpleNamespace(
        project=ctx,
        build_options=SimpleNamespace(
            footer_timestamp_checkbox=SimpleNamespace(isChecked=lambda: True),
            appendix_toc_checkbox=SimpleNamespace(isChecked=lambda: False)),
        compile=SimpleNamespace(running=running, start=lambda *args, **kwargs: started.append((args, kwargs))))
    monkeypatch.setattr(compile_actions, "_confirm_changed_slides", lambda *_a: True)   # fake decks
    monkeypatch.setattr(compile_progress, "spec_for_job", lambda ctx, job: compile_progress.JobSpec(3, 1))
    return win, started


def test_run_asks_about_old_snapshots_and_passes_the_answer_on(qapp, monkeypatch, settings, tmp_path):
    win, started = run_window(monkeypatch, settings)
    old = [ExistingSnapshot(tmp_path / "t-A_2026-09-30_10-05", "t-A", "2026-09-30T10:05", False, 1)]
    monkeypatch.setattr(deck_snapshot, "find_snapshots", lambda names, root: old)
    monkeypatch.setattr(snapshot_sheets, "ask_about_old_snapshots",
                        lambda parent, existing: snapshot_sheets.DELETE_OLD)
    seen = {}

    def fake_snapshot_decks(decks, options, log, cancel=None, delete_old=None, ctx=None):
        seen.update(decks=[d.name for d in decks], options=options, delete_old=delete_old)
        return [SnapshotResult(d.name, ok=True, path=tmp_path / d.name) for d in decks]

    monkeypatch.setattr(deck_snapshot, "snapshot_decks", fake_snapshot_decks)
    assert compile_actions.start_snapshots(win, [deck("t-A"), deck("t-B")], SnapshotOptions())
    (labels, _specs, work), _kwargs = started[0]
    logged: list = []
    results = work(logged.append, None)
    assert seen["decks"] == ["t-A", "t-B"] and seen["delete_old"] == old
    assert seen["options"].footer_timestamp is True and seen["options"].appendix_toc is None
    assert logged == ["==== Done: 2 of 2 snapshot(s) created ===="] and [r.deck_name for r in results] == ["t-A", "t-B"]
    # progress knows every reference and verification compile up front
    assert set(labels) == {
        "snapshot~t-A", "verify~t-A", "snapshot~t-A-presenter", "verify~t-A-presenter",
        "snapshot~t-B", "verify~t-B", "snapshot~t-B-presenter", "verify~t-B-presenter"}


def test_run_cancelled_at_the_old_snapshot_question(qapp, monkeypatch, settings, tmp_path):
    win, started = run_window(monkeypatch, settings)
    old = [ExistingSnapshot(tmp_path / "x", "t-A", "", True, 1)]
    monkeypatch.setattr(deck_snapshot, "find_snapshots", lambda names, root: old)
    monkeypatch.setattr(snapshot_sheets, "ask_about_old_snapshots",
                        lambda parent, existing: snapshot_sheets.CANCEL_RUN)
    assert not compile_actions.start_snapshots(win, [deck("t-A")], SnapshotOptions())
    assert started == []


def test_run_refused_while_compiling(qapp, monkeypatch, settings):
    win, started = run_window(monkeypatch, settings, running=True)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    assert not compile_actions.start_snapshots(win, [deck("t-A")], SnapshotOptions())
    assert started == []


# ---------------------------------------------------------------- the questions around a run

def test_old_snapshot_question_returns_the_button_pressed(qapp, tmp_path):
    old = [ExistingSnapshot(tmp_path / "t-A_2026-09-30_10-05", "t-A", "2026-09-30T10:05", False, 1)]
    answers = {}
    for label, expected in (("Delete old snapshots", snapshot_sheets.DELETE_OLD),
                            ("Keep them", snapshot_sheets.KEEP_OLD), ("Cancel", snapshot_sheets.CANCEL_RUN)):
        sheet = snapshot_sheets._OldSnapshotsSheet(None, old)
        assert "t-A  2026-09-30 10:05  folder" in "\n".join(w.text() for w in sheet.findChildren(QLabel))
        next(b for b in sheet.findChildren(QPushButton) if b.text() == label).click()
        answers[label] = sheet.choice
        assert sheet.choice == expected
    assert snapshot_sheets._OldSnapshotsSheet(None, old).choice == snapshot_sheets.CANCEL_RUN   # Esc


def test_summary_sheet_counts_and_lists_the_results(qapp, monkeypatch, tmp_path):
    shown = {}
    monkeypatch.setattr(snapshot_sheets.ModalSheet, "exec", lambda sheet: shown.update(
        texts=[w.text() for w in sheet.findChildren(QLabel)], buttons=[b.text() for b in sheet.findChildren(QPushButton)]))
    snapshot_sheets.show_summary(None, EXAMPLE_PROJECT, [
        SnapshotResult("t-A", ok=True, path=tmp_path / "t-A_2026-10-07_14-12", size=2048,
                       deleted=[tmp_path / "old"]),
        SnapshotResult("t-B", ok=False, error="t-B did not compile"),
        SnapshotResult("t-C", ok=False, skipped=True),
    ])
    assert "1 of 3 snapshot(s) created." in shown["texts"]
    text = "\n".join(shown["texts"])
    assert "✓  t-A: t-A_2026-10-07_14-12  (2 KB) -- 1 older snapshot(s) moved to the trash" in text
    assert "✗  t-B: t-B did not compile" in text
    assert "–  t-C: skipped (stopped)" in text
    assert shown["buttons"] == ["Open folder", "Close"]
