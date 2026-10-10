"""The project picker, the "Made with a newer SlideMage" sheet, and the recent-projects list and
status they show (project.py)."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QPushButton

from slidemage import cli, project
from slidemage.ui.dialogs.open_project import NewerProjectSheet, OpenProjectSheet


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


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


def test_unreadable_recent_list_reads_as_empty(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "recent_projects.json").write_text("{not json", encoding="utf-8")
    assert project.recent_projects() == []


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


def test_clicking_a_project_chooses_it(tmp_path, qapp):
    folder = make_project(tmp_path / "plain")
    project.save_last_project(folder)
    sheet = OpenProjectSheet(None)
    sheet.rows[0].clicked.emit()
    assert sheet.chosen == folder.resolve() and sheet.result() == 1


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


def test_new_project_creates_the_folder_and_chooses_it(tmp_path, monkeypatch, qapp):
    made = []
    monkeypatch.setattr(project, "init_project", lambda path, copy_example=True: made.append((path, copy_example)))
    sheet = OpenProjectSheet(None)
    button(sheet, "New project…").click()
    sheet.folder_edit.setText(str(tmp_path / "talks"))
    sheet.with_manual.setChecked(False)
    sheet.create_button.click()
    assert made == [(tmp_path / "talks", False)] and sheet.chosen == (tmp_path / "talks").resolve()


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
    assert project.is_project(tmp_path / "empty") and (tmp_path / "empty" / "decks").is_dir()


def test_picker_in_the_window_says_it_restarts(qapp):
    restart = "Opening another project restarts SlideMage."

    def notes(sheet):
        return [label.text() for label in sheet.findChildren(QLabel)]

    assert restart in notes(OpenProjectSheet(None, current=Path("/x")))
    assert restart not in notes(OpenProjectSheet(None))


# -- Made with a newer SlideMage ---------------------------------------------------------------

def test_newer_project_before_opening_offers_cancel_and_open_anyway(qapp):
    sheet = NewerProjectSheet(None, "econ-seminar", "v6.0.2", "v5.35.0", opening=True)
    assert [b.text() for b in sheet.findChildren(QPushButton)] == ["Cancel", "Open anyway"]
    assert sheet.choice == NewerProjectSheet.CANCEL
    button(sheet, "Open anyway").click()
    assert sheet.choice == NewerProjectSheet.OPEN


def test_newer_project_notice_after_opening_can_check_for_updates(qapp):
    called = []
    sheet = NewerProjectSheet(None, "econ", "v6.0.2", "v5.35.0", opening=False, on_update=lambda: called.append(1))
    assert [b.text() for b in sheet.findChildren(QPushButton)] == ["Don't ask again", "Not now", "Check for updates"]
    assert sheet.choice == NewerProjectSheet.NOT_NOW
    button(sheet, "Check for updates").click()
    assert called == [1] and sheet.choice == NewerProjectSheet.UPDATE
    assert [b.text() for b in NewerProjectSheet(None, "econ", "v6", "v5", opening=False).findChildren(QPushButton)] == [
        "Don't ask again", "Not now"]


def test_the_start_up_guard_for_a_newer_format_follows_the_sheet(tmp_path, monkeypatch, qapp):
    monkeypatch.setattr(cli, "_prepare_gui", lambda root: None)
    for press, expected in (("Open anyway", True), (None, False)):
        monkeypatch.setattr(NewerProjectSheet, "exec", lambda sheet, press=press: press and button(sheet, press).click())
        assert cli._confirm_newer_project(tmp_path / "econ", {"last_app_version": "v6.0.2"}) is expected


def test_the_picker_before_a_project_exists_does_not_import_the_project_folder(tmp_path):
    """deck_scan fixes the project folder when it is first imported: the picker must not cause that."""
    import subprocess
    import sys

    code = ("import sys; import slidemage.cli, slidemage.ui.dialogs.open_project as o; "
            "from slidemage.ui.kit.theme import ThemeManager; ThemeManager(dark=True); "
            "sys.exit(int('slidemage.deck_scan' in sys.modules or 'slidemage.app_settings' in sys.modules))")
    assert subprocess.run([sys.executable, "-c", code], capture_output=True).returncode == 0


# -- the start screen ------------------------------------------------------------------------

def start(monkeypatch, tmp_path, choose):
    """cli.main() with no project to be found, the picker answering by `choose(sheet)`."""
    import os

    started = []
    monkeypatch.setenv(project.ENV_VAR, "")
    monkeypatch.setattr(project, "discover", lambda: None)
    monkeypatch.setattr(cli, "_prepare_gui", lambda root: None)
    monkeypatch.setattr(OpenProjectSheet, "exec", choose)
    monkeypatch.setattr("slidemage.qt_gui.main", lambda: started.append(os.environ[project.ENV_VAR]))
    return started


def test_without_a_project_the_start_screen_picks_one_and_the_app_goes_on(tmp_path, monkeypatch, qapp):
    folder = make_project(tmp_path / "mine")
    started = start(monkeypatch, tmp_path, lambda sheet: sheet.choose(folder))
    cli.main([])
    assert started == [str(folder.resolve())]
    assert project.recent_projects() == [folder.resolve()]          # and it is the first of the recent projects


def test_closing_the_start_screen_quits(tmp_path, monkeypatch, qapp):
    started = start(monkeypatch, tmp_path, lambda sheet: 0)
    with pytest.raises(SystemExit) as stop:
        cli.main([])
    assert stop.value.code == 1 and started == []
