# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Route B of docs/plans/theme-editor.md, section 3.6: an installed theme's source folder (its repository), set per
key, edited there with the theme form. The form's logo import and the sample slides work from that folder, and the
theme tab says where an edit is written."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from conftest import qapp as qapp
from slidemage import theme_sample, theme_source_folder, themes
from slidemage.plugins import installer, session
from slidemage.theme_form_model import ThemeModel, layout_profiles
from slidemage.ui.dialogs.settings_plugins import PluginsTab
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.workspace.source_editor import LatexPlainTextEdit
from slidemage.ui.workspace.theme_workspace import ThemeWorkspace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import make_theme_package  # noqa: E402

KEY = "sample-theme"
SETUP = REPO / "latex" / "SlideMage_setup.tex"


@pytest.fixture(autouse=True)
def isolated():
    installer._changed.clear()
    session.set_loaded([])
    yield
    installer._changed.clear()


@pytest.fixture
def repo_folder(tmp_path):
    """The theme's source as its author keeps it: the package's files in a folder of their own."""
    folder = tmp_path / "repos" / "slidemage-theme-sample"
    shutil.copytree(REPO / "tests" / "fixtures" / "theme_package" / KEY, folder)
    return folder


@pytest.fixture
def installed_sample(tmp_path, repo_folder):
    themes.install_file(make_theme_package.pack(repo_folder, tmp_path / "dist"))


@pytest.fixture
def project_dir(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    return root


# -- the setting

def test_a_folder_with_the_template_can_be_the_source_folder(repo_folder, installed_sample, tmp_path):
    assert theme_source_folder.check(KEY, repo_folder) == ""
    assert theme_source_folder.folder(KEY) is None and theme_source_folder.template(KEY) is None
    theme_source_folder.set_folder(KEY, repo_folder)
    assert theme_source_folder.folder(KEY) == repo_folder
    assert theme_source_folder.template(KEY) == repo_folder / f"SlideMage_template_{KEY}.tex"
    assert theme_source_folder.version(repo_folder) == "1.0.0"
    theme_source_folder.set_folder(KEY, None)
    assert theme_source_folder.folder(KEY) is None


def test_folders_that_cannot_be_the_source_folder(repo_folder, installed_sample, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert "is not a folder" in theme_source_folder.check(KEY, tmp_path / "nowhere")
    assert f"no SlideMage_template_{KEY}.tex" in theme_source_folder.check(KEY, empty)
    # route C is not offered: the installed copy is replaced by the next update
    assert "installed theme itself" in theme_source_folder.check(KEY, themes.themes_dir() / KEY)
    assert "not 'other-key'" in theme_source_folder.check("other-key", _with_template(repo_folder, "other-key"))
    with pytest.raises(themes.ThemeError):
        theme_source_folder.set_folder(KEY, empty)
    assert theme_source_folder.folder(KEY) is None


def _with_template(folder: Path, key: str) -> Path:
    shutil.copyfile(folder / f"SlideMage_template_{KEY}.tex", folder / f"SlideMage_template_{key}.tex")
    return folder


# -- where an edit is written

def test_place_says_where_a_theme_file_is(repo_folder, installed_sample, project_dir):
    name = f"SlideMage_template_{KEY}.tex"
    personal = theme_source_folder.place(project_dir / "SlideMage_template_my-look.tex", project_dir)
    assert (personal.kind, personal.line) == ("project", "")
    copy = theme_source_folder.place(project_dir / name, project_dir)
    assert copy.kind == "project" and "instead of the installed theme 1.0.0" in copy.line
    installed = theme_source_folder.place(themes.themes_dir() / KEY / name, project_dir)
    assert installed.kind == "installed" and installed.warning and "next update" in installed.line
    assert theme_source_folder.place(repo_folder / name, project_dir).kind == "other"
    theme_source_folder.set_folder(KEY, repo_folder)
    source = theme_source_folder.place(repo_folder / name, project_dir)
    assert source.kind == "source" and not source.warning and str(repo_folder) in source.line
    assert "version 1.0.0 here, 1.0.0 installed" in source.line and "raise the version in theme.toml" in source.line
    toml = repo_folder / "theme.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace('"1.0.0"', '"1.0.1"'), encoding="utf-8")
    raised = theme_source_folder.place(repo_folder / name, project_dir).line
    assert "version 1.0.1 here, 1.0.0 installed" in raised and "raise the version" not in raised


def test_home_is_the_theme_files_folder(repo_folder, project_dir):
    assert theme_source_folder.home(project_dir / "SlideMage_template_my-look.tex", project_dir) == project_dir
    assert theme_source_folder.home(repo_folder / f"SlideMage_template_{KEY}.tex", project_dir) == repo_folder


# -- the form and the sample work from the source folder

def test_a_logo_is_imported_into_the_source_folders_schemes(repo_folder, project_dir, tmp_path):
    text = (repo_folder / f"SlideMage_template_{KEY}.tex").read_text(encoding="utf-8")
    model = ThemeModel(text, project_dir, KEY, SETUP.read_text(encoding="utf-8"), repo_folder)
    logo = tmp_path / "pictures" / "new-logo.pdf"
    logo.parent.mkdir()
    logo.write_bytes(b"%PDF-1.4 test")
    assert model.import_logo(logo) == "schemes/scheme_sample_theme/new-logo.pdf"
    assert (repo_folder / "schemes" / "scheme_sample_theme" / "new-logo.pdf").is_file()
    assert not (project_dir / "schemes").exists()


def test_the_source_folders_layout_profile_is_offered(repo_folder, project_dir):
    (repo_folder / "SlideMage_layout_own.tex").write_text("% a profile\n", encoding="utf-8")
    assert "own" not in layout_profiles(project_dir)
    assert "own" in layout_profiles(project_dir, repo_folder)


def test_the_sample_finds_the_source_folder_before_the_project(repo_folder, project_dir, tmp_path):
    work = tmp_path / "work"
    folders = theme_sample.texinputs(work, project_dir, {"TEXINPUTS": "rest"}, repo_folder).split(";" if sys.platform == "win32" else ":")
    assert folders[:3] == [str(work), str(repo_folder), str(project_dir)] and folders[-1] == "rest"
    assert theme_sample.texinputs(work, project_dir, {}, None).split(";" if sys.platform == "win32" else ":")[1] == str(project_dir)
    deck = theme_sample.deck_text(KEY, "", project_dir, repo_folder)
    assert f"\\graphicspath{{{{{repo_folder.as_posix()}/}}{{{project_dir.as_posix()}/}}}}" in deck
    assert f"\\graphicspath{{{{{project_dir.as_posix()}/}}}}" in theme_sample.deck_text(KEY, "", project_dir)


def test_the_theme_tab_says_where_it_writes_and_renders_from_there(qapp, repo_folder, installed_sample, project_dir):
    theme_source_folder.set_folder(KEY, repo_folder)
    path = repo_folder / f"SlideMage_template_{KEY}.tex"
    editor = LatexPlainTextEdit(ThemeManager())
    editor.set_text(path.read_text(encoding="utf-8"))
    side = ThemeWorkspace(editor, path, SimpleNamespace(root=project_dir), SETUP)
    assert side.place.kind == "source" and not side.place_label.isHidden()
    assert str(repo_folder) in side.place_label.text()
    assert side.sample.home == repo_folder and side.form.model.home == repo_folder
    assert side.sample._home_args() == {"home": repo_folder}


def test_a_personal_theme_has_no_place_line(qapp, project_dir):
    path = project_dir / "SlideMage_template_my-look.tex"
    path.write_text("\\input{SlideMage_setup}\n\\input{SlideMage_base}\n", encoding="utf-8")
    editor = LatexPlainTextEdit(ThemeManager())
    editor.set_text(path.read_text(encoding="utf-8"))
    side = ThemeWorkspace(editor, path, SimpleNamespace(root=project_dir), SETUP)
    assert side.place_label.isHidden() and side.sample.home is None and side.sample._home_args() == {}


# -- Settings: the installed theme's row

class FakeApp(QWidget):
    def __init__(self, root):
        super().__init__()
        self.project = SimpleNamespace(root=root)
        self.theme = ThemeManager()
        self.opened: list = []

    def open_theme_editor(self, path):
        self.opened.append(path)


def test_the_row_takes_a_source_folder_and_edits_the_source(qapp, repo_folder, installed_sample, project_dir,
                                                            monkeypatch):
    app = FakeApp(project_dir)
    tab = PluginsTab(app)
    row = tab.theme_rows[KEY]
    assert row.edit_source_button is None and row.source_folder_label is None
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(repo_folder))
    row.source_folder_button.click()
    row = tab.theme_rows[KEY]
    assert row.source_folder_button is None
    assert row.source_folder_label.text() == f"Source folder: {repo_folder} (version 1.0.0)"
    row.edit_source_button.click()
    assert app.opened == [repo_folder / f"SlideMage_template_{KEY}.tex"]
    row.forget_folder_button.click()
    assert theme_source_folder.folder(KEY) is None and tab.theme_rows[KEY].edit_source_button is None


def test_a_refused_folder_is_said_and_not_kept(qapp, installed_sample, project_dir, tmp_path, monkeypatch):
    tab = PluginsTab(FakeApp(project_dir))
    said: list = []
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: said.append(a[2]))
    tab.theme_rows[KEY].source_folder_button.click()
    assert said and f"no SlideMage_template_{KEY}.tex" in said[0]
    assert theme_source_folder.folder(KEY) is None


def test_a_source_folder_that_lost_its_template_is_said(qapp, repo_folder, installed_sample, project_dir, monkeypatch):
    theme_source_folder.set_folder(KEY, repo_folder)
    app = FakeApp(project_dir)
    tab = PluginsTab(app)
    (repo_folder / f"SlideMage_template_{KEY}.tex").unlink()
    said: list = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: said.append(a[2]))
    tab.theme_rows[KEY].edit_source_button.click()
    assert said and app.opened == []


# -- the real window

def test_the_window_edits_the_source_in_its_folder_and_leaves_the_decks(qapp, repo_folder, installed_sample,
                                                                        monkeypatch):
    from conftest import build_window
    window = build_window(monkeypatch)
    theme_source_folder.set_folder(KEY, repo_folder)
    path = repo_folder / f"SlideMage_template_{KEY}.tex"
    renders: list = []
    monkeypatch.setattr(window, "theme_installed", renders.append)
    window.open_theme_editor(path)
    tab = window.centre.source.file_for(path)
    assert tab is not None and tab.theme_side.place.kind == "source"
    assert tab.theme_form.model.home == repo_folder and tab.theme_sample.home == repo_folder
    tab.theme_form.apply(lambda: tab.theme_form.model.set_value("SMLogoHeight", "4ex"))
    assert window.centre.source.save()
    assert r"\SMLogoHeight}{4ex}" in path.read_text(encoding="utf-8").replace(" ", "")
    # the decks use the installed theme: a save in the source folder renders nothing again
    assert window._themes_written == set() and renders == []
    assert not (window.project.root / path.name).exists()


@pytest.mark.skipif(not os.environ.get("SLIDEMAGE_TEX_TESTS") or not shutil.which("lualatex"),
                    reason="compiles with lualatex: SLIDEMAGE_TEX_TESTS=1")
def test_the_sample_renders_with_the_source_folders_logo(repo_folder):
    """Not installed, not in the project: the theme's logo is found in its source folder only."""
    from conftest import EXAMPLE_PROJECT as project
    text = (repo_folder / f"SlideMage_template_{KEY}.tex").read_text(encoding="utf-8")
    result = theme_sample.render(project, text, KEY, "", home=repo_folder)
    assert result.pdf is not None, result.log
    assert result.pdf.parent.parent.name == f"{KEY}@source"
    log = (result.pdf.parent / f"{theme_sample.DECK}.log").read_text(encoding="utf-8", errors="replace")
    assert (repo_folder / "schemes").as_posix() in log.replace("\n", "").replace("\r", "")
