"""The ⋮ menu's Decks section, the "Create deck snapshot" dialog, the snapshot run on the
compile slot and the archive question that offers a snapshot first."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton, QWidget

from slidemage import app_settings, compile_progress, deck_snapshot
from slidemage.deck_snapshot import ExistingSnapshot, SnapshotOptions, SnapshotResult
from slidemage.ui.dialogs import snapshot as snapshot_sheets
from slidemage.ui.workspace import compile_jobs
from slidemage.ui.workspace import window as window_module
from slidemage.ui.workspace.compile_jobs import CompileJobsMixin
from slidemage.ui.workspace.deck_actions import DeckActionsMixin
from conftest import command_context
from slidemage.ui.workspace.menus import build_more_menu


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

def test_decks_section_holds_snapshot_and_import(qapp):
    menu = build_more_menu(None, command_context())
    menu._build()
    entries = [(e[0], e[2] if e[0] == "item" else e[-1]) for e in menu._entries]
    start = entries.index(("header", "Decks"))
    assert entries[start:start + 4] == [
        ("header", "Decks"), ("item", "Create deck snapshot…"), ("item", "Import PPTX/ODP…"),
        ("item", "Refresh decks")]


def test_snapshot_banner_only_in_a_snapshot(qapp, monkeypatch, tmp_path):
    import json

    from slidemage import project

    proj = tmp_path / "Proj"
    project.write_project_json(proj, {"format": 1, "snapshot": {
        "deck_name": "t-A", "created": "2026-10-07T14:12:30+02:00", "read_only": True}})
    (tmp_path / "snapshot.json").write_text(json.dumps({"slidemage": {"version": "v5.33.0"}}),
                                            encoding="utf-8")
    banner = window_module.WorkspaceWindow._build_snapshot_banner
    monkeypatch.setattr(window_module, "PROJECT_ROOT", proj)
    label = banner(None)
    assert label.text().startswith(
        "Deck snapshot of t-A, taken 2026-10-07 14:12 with SlideMage v5.33.0.")
    monkeypatch.setattr(window_module, "PROJECT_ROOT", tmp_path)   # an ordinary folder
    assert banner(None) is None


@pytest.mark.parametrize("button, expected", [
    ("Compile anyway", ["t-A-instructor", "t-A-during-course"]),
    ("Skip unchanged", ["t-A-during-course"]),
    ("Cancel", []),
])
def test_unchanged_versions_are_compiled_only_after_asking(qapp, monkeypatch, button, expected):
    jobs = [SimpleNamespace(jobname="t-A-instructor"), SimpleNamespace(jobname="t-A-during-course")]
    monkeypatch.setattr(compile_jobs.compiler, "unchanged_jobs",
                        lambda jobs, dests: [(jobs[0], "2026-10-08T07:51:00+02:00")])
    seen: list = []
    press_on_exec(monkeypatch, button, seen)
    win = QWidget()
    win._log = lambda line: None
    result = CompileJobsMixin._confirm_unchanged_jobs(win, jobs, {})
    assert [j.jobname for j in result] == expected
    assert "t-A-instructor (compiled 2026-10-08 07:51)" in seen[0][0]


def test_nothing_unchanged_no_question(qapp, monkeypatch):
    jobs = [SimpleNamespace(jobname="t-A-instructor")]
    monkeypatch.setattr(compile_jobs.compiler, "unchanged_jobs", lambda jobs, dests: [])
    monkeypatch.setattr(QMessageBox, "exec", lambda box: pytest.fail("asked"))
    win = QWidget()
    assert CompileJobsMixin._confirm_unchanged_jobs(win, jobs, {}) == jobs


# ---------------------------------------------------------------- sheet

def test_sheet_lists_decks_preselects_and_remembers_settings(qapp, settings):
    decks = [deck("t-A"), deck("t-B"), deck("t-Old", archived=True)]
    dialog = snapshot_sheets.SnapshotSheet(None, decks, preselected={"t-B"})
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
    again = snapshot_sheets.SnapshotSheet(None, decks, preselected=set())
    assert again.output.current() == "zip" and again.texmf_checkbox.isChecked()
    assert not again.create_button.isEnabled()                         # nothing checked


def test_sheet_select_all_and_busy(qapp, settings):
    decks = [deck("t-A"), deck("t-B")]
    dialog = snapshot_sheets.SnapshotSheet(None, decks, preselected=set(), busy=True)
    next(b for b in dialog.findChildren(QPushButton) if b.text() == "Select all").click()
    assert len(dialog.selected_decks()) == 2
    assert not dialog.create_button.isEnabled()                        # a compile is running
    assert not dialog.busy_label.isHidden()


def test_describe_options_for_the_archive_question():
    assert deck_snapshot.describe_options(SnapshotOptions()) == \
        "folder, without LaTeX package files"
    assert deck_snapshot.describe_options(SnapshotOptions(zip=True, texmf=True)) == \
        ".zip file, with LaTeX package files"


# ---------------------------------------------------------------- archive question

def archive_window(monkeypatch, settings):
    calls: list = []
    win = QWidget()   # a parent for the message boxes, carrying the real handlers
    win._do_archive_deck = lambda d: calls.append(("archive", d.name))
    win._start_snapshots = lambda decks, options, after=None: calls.append(
        ("snapshot", [d.name for d in decks], options, after)) or True
    for name in ("_archive_deck", "_archive_after_snapshot"):
        setattr(win, name, getattr(DeckActionsMixin, name).__get__(win))
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
    topbar = SimpleNamespace(set_compiling=lambda on: emitted.append(("compiling", on)))
    win = SimpleNamespace(
        compiling=compiling, cancel_token=None, _after_snapshots=None, begun=None, _worker=None,
        build_options=SimpleNamespace(
            footer_timestamp_checkbox=SimpleNamespace(isChecked=lambda: True),
            appendix_toc_checkbox=SimpleNamespace(isChecked=lambda: False)),
        topbar=topbar,
        signals=SimpleNamespace(log=signal("log"), batch_done=signal("batch_done"),
                                snapshots_done=signal("snapshots_done")),
    )

    def begin_run(labels, specs, **kwargs):
        win.begun = labels
        win.compiling, win.cancel_token = True, object()

    win._begin_run = begin_run
    for name in ("_start_snapshots", "_run_snapshots_thread", "_start_worker"):
        setattr(win, name, getattr(CompileJobsMixin, name).__get__(win))

    class SyncThread:
        def __init__(self, target, args=(), daemon=None):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(compile_jobs.threading, "Thread", SyncThread)
    monkeypatch.setattr(compile_progress, "spec_for_job", lambda job: compile_progress.JobSpec(3, 1))
    return win, emitted


def test_run_asks_about_old_snapshots_and_passes_the_answer_on(qapp, monkeypatch, settings, tmp_path):
    win, emitted = run_window(monkeypatch, settings)
    old = [ExistingSnapshot(tmp_path / "t-A_2026-09-30_10-05", "t-A", "2026-09-30T10:05", False, 1)]
    monkeypatch.setattr(deck_snapshot, "find_snapshots", lambda names: old)
    monkeypatch.setattr(snapshot_sheets, "ask_about_old_snapshots",
                        lambda parent, existing: snapshot_sheets.DELETE_OLD)
    seen = {}

    def fake_snapshot_decks(decks, options, log, cancel=None, delete_old=None):
        seen.update(decks=[d.name for d in decks], options=options, delete_old=delete_old)
        return [SnapshotResult(d.name, ok=True, path=tmp_path / d.name) for d in decks]

    monkeypatch.setattr(deck_snapshot, "snapshot_decks", fake_snapshot_decks)
    assert win._start_snapshots([deck("t-A"), deck("t-B")], SnapshotOptions())
    assert seen["decks"] == ["t-A", "t-B"] and seen["delete_old"] == old
    assert seen["options"].footer_timestamp is True and seen["options"].appendix_toc is None
    # progress knows every reference and verification compile up front
    assert set(win.begun) == {
        "snapshot~t-A", "verify~t-A", "snapshot~t-A-presenter", "verify~t-A-presenter",
        "snapshot~t-B", "verify~t-B", "snapshot~t-B-presenter", "verify~t-B-presenter"}
    assert win.compiling is False and win.cancel_token is None       # slot freed again
    assert ("log", "==== Done: 2 of 2 snapshot(s) created ====") in emitted
    assert emitted[-1][0] == "snapshots_done"


def test_run_cancelled_at_the_old_snapshot_question(qapp, monkeypatch, settings, tmp_path):
    win, emitted = run_window(monkeypatch, settings)
    old = [ExistingSnapshot(tmp_path / "x", "t-A", "", True, 1)]
    monkeypatch.setattr(deck_snapshot, "find_snapshots", lambda names: old)
    monkeypatch.setattr(snapshot_sheets, "ask_about_old_snapshots",
                        lambda parent, existing: snapshot_sheets.CANCEL_RUN)
    assert not win._start_snapshots([deck("t-A")], SnapshotOptions())
    assert emitted == [] and win.compiling is False


def test_run_refused_while_compiling(qapp, monkeypatch, settings):
    win, emitted = run_window(monkeypatch, settings, compiling=True)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    assert not win._start_snapshots([deck("t-A")], SnapshotOptions())
    assert emitted == []


def test_summary_text_lists_each_deck(tmp_path):
    text = deck_snapshot.summary_text([
        SnapshotResult("t-A", ok=True, path=tmp_path / "t-A_2026-10-07_14-12", size=2048,
                       deleted=[tmp_path / "old"]),
        SnapshotResult("t-B", ok=False, error="t-B did not compile"),
        SnapshotResult("t-C", ok=False, skipped=True),
    ])
    assert "✓  t-A: t-A_2026-10-07_14-12  (2 KB) -- 1 older snapshot(s) moved to the trash" in text
    assert "✗  t-B: t-B did not compile" in text
    assert "–  t-C: skipped (stopped)" in text


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
    snapshot_sheets.show_summary(None, [SnapshotResult("t-A", ok=True, path=tmp_path / "t-A_x", size=10),
                                        SnapshotResult("t-B", ok=False, error="t-B did not compile")])
    assert "1 of 2 snapshot(s) created." in shown["texts"]
    assert any("✗  t-B: t-B did not compile" in text for text in shown["texts"])
    assert shown["buttons"] == ["Open folder", "Close"]
