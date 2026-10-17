"""The project picker, the "Made with a newer SlideMage" sheet, and the recent-projects list and
status they show (project.py)."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QFileDialog, QPushButton

from slidemage import cli, project
from slidemage.ui.dialogs.open_project import NewerProjectSheet, OpenProjectSheet


@pytest.fixture(autouse=True)
def config(monkeypatch, tmp_path):
    """Recent projects and the last-project pointer go to a throwaway folder."""
    monkeypatch.setattr(project, "config_dir", lambda: tmp_path / "config")


def make_project(root: Path, **info) -> Path:
    root.mkdir(parents=True)
    (root / project.MARKER).write_text('"id"\r\n', encoding="utf-8")
    if info:
        project.write_project_json(root, {"format": project.PROJECT_FORMAT, **info})
    return root


def button(sheet, text):
    return next(b for b in sheet.findChildren(QPushButton) if b.text() == text)


def chips(sheet):
    return {row.status.name: row.chip.text() if row.chip else "" for row in sheet.rows}


# -- recent projects and their status (project.py) -----------------------------------------------

def test_recent_projects_are_newest_first_without_duplicates_and_limited(tmp_path):
    folders = [tmp_path / f"p{i}" for i in range(project.RECENT_LIMIT + 2)]
    for folder in folders:
        project.save_last_project(folder)
    project.save_last_project(folders[5])
    recent = project.recent_projects()
    assert recent[0] == folders[5] and recent.count(folders[5]) == 1
    assert len(recent) == project.RECENT_LIMIT
    assert folders[0] not in recent


def test_status_tells_missing_older_and_newer_projects(tmp_path):
    older = make_project(tmp_path / "older", last_app_version="v5.20.0", highest_app_version="v5.20.0")
    by_version = make_project(tmp_path / "by-version", last_app_version="v5.20.0", highest_app_version="v6.0.2")
    by_format = make_project(tmp_path / "by-format", format=project.PROJECT_FORMAT + 1, last_app_version="v6.0.0")
    assert not project.project_status(older, "v5.35.0").newer
    assert project.project_status(by_version, "v5.35.0").newer
    assert project.project_status(by_format, "v5.35.0").newer
    gone = project.project_status(tmp_path / "gone", "v5.35.0")
    assert not gone.exists and gone.name == "gone"
    assert project.project_status(older, "v5.35.0").last_version == "v5.20.0"


# -- the picker --------------------------------------------------------------------------------

def test_picker_lists_recent_projects_with_a_chip_each(tmp_path, qapp):
    current = make_project(tmp_path / "current", last_app_version="v5.35.0")
    checked = make_project(tmp_path / "checked", last_app_version="v5.21.0")
    newer = make_project(tmp_path / "newer", last_app_version="v6.0.2", highest_app_version="v6.0.2")
    plain = make_project(tmp_path / "plain", last_app_version="v5.35.0")
    for folder in (plain, newer, checked, current, tmp_path / "gone"):
        project.save_last_project(folder)
    sheet = OpenProjectSheet(None, current=current, app_version="v5.35.0",
                             needs_check=lambda path: path == checked)
    assert [row.status.name for row in sheet.rows] == ["gone", "current", "checked", "newer", "plain"]
    assert chips(sheet) == {"gone": "not found", "current": "open now", "checked": "made with 5.21.0 · check",
                            "newer": "made with 6.0.2 · newer", "plain": "made with 5.35.0"}
    assert not sheet.rows[0].isEnabled()                    # a folder that is gone cannot be opened
    sheet.rows[-1].clicked.emit()
    assert sheet.chosen == plain.resolve() and sheet.result() == 1


def test_first_run_has_no_cancel_and_an_empty_list_says_so(qapp):
    sheet = OpenProjectSheet(None, first_run=True)
    labels = [b.text() for b in sheet.findChildren(QPushButton)]
    assert {"New project…", "Open folder…"} <= set(labels)
    assert sheet.rows == [] and sheet.chosen is None
    # the New project form has a Cancel of its own; the sheet's is the second
    assert labels.count("Cancel") + 1 == [b.text() for b in OpenProjectSheet(None).findChildren(QPushButton)].count("Cancel")


def test_open_folder_chooses_a_project_and_offers_to_create_in_any_other_folder(tmp_path, monkeypatch, qapp):
    folder = make_project(tmp_path / "mine")
    other = tmp_path / "notes"
    other.mkdir()
    answers = iter([str(other), str(folder)])
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: next(answers))
    sheet = OpenProjectSheet(None)
    button(sheet, "Open folder…").click()
    assert not sheet.form.isHidden() and sheet.folder_edit.text() == str(other)
    assert "not a project yet" in sheet.status.text() and sheet.chosen is None
    button(sheet, "Open folder…").click()
    assert sheet.chosen == folder.resolve()


def test_new_project_in_a_folder_with_a_collision_says_so(tmp_path, monkeypatch, qapp):
    def refuse(path, copy_example=True):
        raise project.ProjectCreationError(path, [path / "decks" / "demo.tex"])

    monkeypatch.setattr(project, "init_project", refuse)
    sheet = OpenProjectSheet(None)
    button(sheet, "New project…").click()
    sheet.folder_edit.clear()
    sheet.create_button.click()
    assert "Give the folder" in sheet.status.text()
    sheet.folder_edit.setText(str(tmp_path / "talks"))
    sheet.create_button.click()
    assert "demo.tex" in sheet.status.text() and sheet.chosen is None


def test_new_project_really_scaffolds_an_empty_project(tmp_path, qapp):
    sheet = OpenProjectSheet(None)
    button(sheet, "New project…").click()
    sheet.folder_edit.setText(str(tmp_path / "empty"))
    sheet.with_manual.setChecked(False)
    sheet.create_button.click()
    target = tmp_path / "empty"
    assert sheet.chosen == target.resolve()
    assert project.is_project(target)
    # Regression: the first-run picker originally refused an empty folder.
    assert (target / "slide_ids.csv").read_bytes() == b'"id"\r\n'
    for sub in ("slides", "decks", "media"):
        assert (target / sub).is_dir()


# -- Made with a newer SlideMage ---------------------------------------------------------------

def test_newer_project_notice_after_opening_can_check_for_updates(qapp):
    called = []
    sheet = NewerProjectSheet(None, "econ", "v6.0.2", "v5.35.0", opening=False, on_update=lambda: called.append(1))
    assert [b.text() for b in sheet.findChildren(QPushButton)] == ["Don't ask again", "Not now", "Check for updates"]
    assert sheet.choice == NewerProjectSheet.NOT_NOW
    button(sheet, "Check for updates").click()
    assert called == [1] and sheet.choice == NewerProjectSheet.UPDATE
    assert [b.text() for b in NewerProjectSheet(None, "econ", "v6", "v5", opening=False).findChildren(QPushButton)] == [
        "Don't ask again", "Not now"]


@pytest.mark.parametrize("press, expected", [("Open anyway", True), (None, False)])
def test_the_start_up_guard_for_a_newer_format_follows_the_sheet(tmp_path, monkeypatch, qapp, press, expected):
    monkeypatch.setattr(cli, "_prepare_gui", lambda root: None)

    def choose(sheet):
        assert [b.text() for b in sheet.findChildren(QPushButton)] == ["Cancel", "Open anyway"]
        assert sheet.choice == NewerProjectSheet.CANCEL
        if press:
            button(sheet, press).click()
            assert sheet.choice == NewerProjectSheet.OPEN

    monkeypatch.setattr(NewerProjectSheet, "exec", choose)
    assert cli._confirm_newer_project(tmp_path / "econ", {"last_app_version": "v6.0.2"}) is expected


def test_importing_the_app_selects_no_project(tmp_path):
    """Modules read no project when they are imported: the entry point chooses it, once."""
    import subprocess
    import sys

    code = ("import sys; import slidemage.cli, slidemage.compiler, slidemage.deck_scan, slidemage.app_settings, "
            "slidemage.ui.dialogs.open_project as o, slidemage.ui.workspace.window; "
            "from slidemage.ui.kit.theme import ThemeManager; ThemeManager(dark=True); "
            "from slidemage import project; sys.exit(int(hasattr(project, 'transitional_context') or hasattr(project, 'use')))")
    assert subprocess.run([sys.executable, "-c", code], capture_output=True, cwd=tmp_path).returncode == 0


# -- the start screen ------------------------------------------------------------------------

def start(monkeypatch, tmp_path, choose):
    """cli.main() with no project to be found, the picker answering by `choose(sheet)`."""
    import os

    started = []
    monkeypatch.setenv(project.ENV_VAR, "")
    monkeypatch.setattr(project, "discover", lambda: None)
    monkeypatch.setattr(cli, "_prepare_gui", lambda root: None)
    monkeypatch.setattr(OpenProjectSheet, "exec", choose)
    monkeypatch.setattr("slidemage.ui.app.main", lambda _context: started.append(os.environ[project.ENV_VAR]))
    return started


@pytest.mark.parametrize("open_project", [True, False])
def test_first_run_picks_a_project_or_quits(tmp_path, monkeypatch, qapp, open_project):
    folder = make_project(tmp_path / "mine")
    started = start(monkeypatch, tmp_path, lambda sheet: sheet.choose(folder) if open_project else 0)
    if open_project:
        cli.main([])
        assert started == [str(folder.resolve())]
        assert project.recent_projects() == [folder.resolve()]
    else:
        with pytest.raises(SystemExit) as stop:
            cli.main([])
        assert stop.value.code == 1 and started == []


@pytest.mark.parametrize("frozen", [False, True])
def test_relaunch_with_project_saves_and_spawns(monkeypatch, tmp_path, frozen):
    """2026-09-23: opening another project fixes silent reuse of a stale pointer.

    v3.33.1: a frozen restart reused the old _MEI directory and died on exit.
    """
    new_root = make_project(tmp_path / "other-project")
    monkeypatch.setattr(project.sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(project.sys, "executable", str(tmp_path / "SlideMage"))
    monkeypatch.setenv("_PYI_ARCHIVE_FILE", "/old/SlideMage")
    calls = []
    monkeypatch.setattr(project.subprocess, "Popen", lambda argv, env: calls.append((argv, env)))
    project.relaunch_with_project(new_root)
    assert project.load_last_project() == new_root
    assert len(calls) == 1
    argv, env = calls[0]
    assert str(new_root) in argv
    assert env[project.ENV_VAR] == str(new_root)
    if frozen:
        assert argv[1:] == ["--project", str(new_root)]
        assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


@pytest.mark.parametrize("frozen", [False, True])
def test_last_project_is_kept_for_source_and_frozen_runs(monkeypatch, tmp_path, frozen):
    """v5.25.0: a second PC had no APPDATA pointer for the cloud-synced exe."""
    exe_dir = tmp_path / "dist"
    exe_dir.mkdir()
    monkeypatch.setattr(project.sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(project.sys, "executable", str(exe_dir / "SlideMage.exe"))
    root = make_project(tmp_path / "Slidemaster")
    monkeypatch.setattr(project, "config_dir", lambda: tmp_path / "pc1")
    project.save_last_project(root)
    assert project.load_last_project() == root
    if frozen:
        assert (exe_dir / "last_project").read_text(encoding="utf-8") == str(root)
        monkeypatch.setattr(project, "config_dir", lambda: tmp_path / "pc2")
        assert project.load_last_project() == root
    else:
        assert not (tmp_path / "last_project").exists()
        assert not (exe_dir / "last_project").exists()


def test_last_project_hint_is_nearest_existing_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(project, "config_dir", lambda: tmp_path / "config")
    root = make_project(tmp_path / "cloud" / "Slidemaster")
    project.save_last_project(root)
    (root / project.MARKER).unlink()
    root.rmdir()
    assert project.load_last_project() is None
    assert project.last_project_hint() == tmp_path / "cloud"
