# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Editing installed themes in their source folders."""
from __future__ import annotations

import os
import shutil
import sys
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from conftest import EXAMPLE_PROJECT, build_window, qapp as qapp
from slidemage import theme_sample, theme_source_folder, themes
from slidemage.theme_form_model import ThemeModel, layout_profiles
from slidemage.ui.dialogs.settings_plugins import PluginsTab
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.workspace.source_editor import LatexPlainTextEdit
from slidemage.ui.workspace.theme_workspace import ThemeWorkspace
from test_theme_sources import ASSET, FIXTURE, REPO
from test_themes_gui import FakeApp, isolated as isolated

KEY = "sample-theme"
TEMPLATE = f"SlideMage_template_{KEY}.tex"
SETUP = REPO / "latex" / "SlideMage_setup.tex"


@pytest.fixture
def repo_folder(tmp_path):
    folder = tmp_path / "repos" / "slidemage-theme-sample"
    shutil.copytree(FIXTURE, folder)
    return folder


@pytest.fixture
def installed_sample():
    themes.install_file(ASSET)


def test_folders_that_cannot_be_the_source_folder(repo_folder, installed_sample, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert "is not a folder" in theme_source_folder.check(KEY, tmp_path / "nowhere")
    assert f"no SlideMage_template_{KEY}.tex" in theme_source_folder.check(KEY, empty)
    assert "installed theme itself" in theme_source_folder.check(KEY, themes.themes_dir() / KEY)
    shutil.copyfile(repo_folder / TEMPLATE, repo_folder / "SlideMage_template_other-key.tex")
    assert "not 'other-key'" in theme_source_folder.check("other-key", repo_folder)
    with pytest.raises(themes.ThemeError):
        theme_source_folder.set_folder(KEY, empty)
    assert theme_source_folder.folder(KEY) is None


def test_place_says_where_a_theme_file_is(repo_folder, installed_sample, project_dir):
    copy = theme_source_folder.place(project_dir / TEMPLATE, project_dir)
    assert copy.kind == "project" and "instead of the installed theme 1.0.0" in copy.line
    installed = theme_source_folder.place(themes.themes_dir() / KEY / TEMPLATE, project_dir)
    assert installed.kind == "installed" and installed.warning and "next update" in installed.line
    assert theme_source_folder.place(repo_folder / TEMPLATE, project_dir).kind == "other"
    theme_source_folder.set_folder(KEY, repo_folder)
    source = theme_source_folder.place(repo_folder / TEMPLATE, project_dir)
    assert source.kind == "source" and not source.warning and str(repo_folder) in source.line
    assert "version 1.0.0 here, 1.0.0 installed" in source.line and "raise the version in theme.toml" in source.line
    toml = repo_folder / "theme.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace('"1.0.0"', '"1.0.1"'), encoding="utf-8")
    raised = theme_source_folder.place(repo_folder / TEMPLATE, project_dir).line
    assert "version 1.0.1 here, 1.0.0 installed" in raised and "raise the version" not in raised


def test_a_logo_is_imported_into_the_source_folders_schemes(repo_folder, project_dir, tmp_path):
    text = (repo_folder / TEMPLATE).read_text(encoding="utf-8")
    model = ThemeModel(text, project_dir, KEY, SETUP.read_text(encoding="utf-8"), repo_folder)
    logo = tmp_path / "new-logo.pdf"
    logo.write_bytes(b"%PDF-1.4 test")
    relative = "schemes/scheme_sample_theme/new-logo.pdf"
    assert model.import_logo(logo) == relative and (repo_folder / relative).is_file()
    assert not (project_dir / "schemes").exists()


def test_the_source_folders_layout_profile_is_offered(repo_folder, project_dir):
    (repo_folder / "SlideMage_layout_own.tex").write_text("% a profile\n", encoding="utf-8")
    assert "own" not in layout_profiles(project_dir)
    assert "own" in layout_profiles(project_dir, repo_folder)


def test_the_sample_finds_the_source_folder_before_the_project(repo_folder, project_dir, tmp_path):
    work = tmp_path / "work"
    separator = ";" if sys.platform == "win32" else ":"
    folders = theme_sample.texinputs(work, project_dir, {"TEXINPUTS": "rest"}, repo_folder).split(separator)
    assert folders[:3] == [str(work), str(repo_folder), str(project_dir)] and folders[-1] == "rest"
    assert theme_sample.texinputs(work, project_dir, {}, None).split(separator)[1] == str(project_dir)
    deck = theme_sample.deck_text(KEY, "", project_dir, repo_folder)
    assert f"\\graphicspath{{{{{repo_folder.as_posix()}/}}{{{project_dir.as_posix()}/}}}}" in deck
    assert f"\\graphicspath{{{{{project_dir.as_posix()}/}}}}" in theme_sample.deck_text(KEY, "", project_dir)


def test_a_personal_theme_has_no_place_line(qapp, project_dir):
    path = project_dir / "SlideMage_template_my-look.tex"
    path.write_text("\\input{SlideMage_setup}\n\\input{SlideMage_base}\n", encoding="utf-8")
    editor = LatexPlainTextEdit(ThemeManager())
    editor.set_text(path.read_text(encoding="utf-8"))
    side = ThemeWorkspace(editor, path, SimpleNamespace(root=project_dir), SETUP)
    assert side.place_label.isHidden() and side.sample.home is None and side.sample._home_args() == {}


def test_settings_edits_and_forgets_a_source_folder_and_reports_invalid_folders(
    qapp, repo_folder, installed_sample, project_dir, tmp_path, monkeypatch,
):
    app = FakeApp(project_dir)
    opened, warnings = [], []
    monkeypatch.setattr(app, "open_theme_editor", opened.append, raising=False)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a[2]))
    tab = PluginsTab(app)
    row = tab.theme_rows[KEY]
    assert row.edit_source_button is None and row.source_folder_label is None
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path))
    row.source_folder_button.click()
    assert f"no {TEMPLATE}" in warnings.pop() and theme_source_folder.folder(KEY) is None

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(repo_folder))
    tab.theme_rows[KEY].source_folder_button.click()
    row = tab.theme_rows[KEY]
    assert row.source_folder_button is None and str(repo_folder) in row.source_folder_label.text()
    path = repo_folder / TEMPLATE
    assert theme_source_folder.template(KEY) == path
    row.edit_source_button.click()
    assert opened == [path]
    path.unlink()
    row.edit_source_button.click()
    assert warnings and opened == [path]
    tab.theme_rows[KEY].forget_folder_button.click()
    assert theme_source_folder.folder(KEY) is None and tab.theme_rows[KEY].edit_source_button is None


def test_the_window_saves_the_theme_source_without_rendering_decks(qapp, repo_folder, installed_sample, monkeypatch):
    window = build_window(monkeypatch)
    theme_source_folder.set_folder(KEY, repo_folder)
    path = repo_folder / TEMPLATE
    renders: list = []
    monkeypatch.setattr(window, "theme_installed", renders.append)
    window.open_theme_editor(path)
    tab = window.centre.source.file_for(path)
    assert tab is not None and tab.theme_side.place.kind == "source"
    assert not tab.theme_side.place_label.isHidden() and str(repo_folder) in tab.theme_side.place_label.text()
    assert tab.theme_form.model.home == repo_folder and tab.theme_sample._home_args() == {"home": repo_folder}
    tab.theme_form.apply(lambda: tab.theme_form.model.set_value("SMLogoHeight", "4ex"))
    assert window.centre.source.save()
    assert r"\SMLogoHeight}{4ex}" in path.read_text(encoding="utf-8").replace(" ", "")
    assert window._themes_written == set() and renders == []
    assert not (window.project.root / path.name).exists()


@pytest.mark.skipif(not os.environ.get("SLIDEMAGE_TEX_TESTS") or not shutil.which("lualatex"),
                    reason="compiles with lualatex: SLIDEMAGE_TEX_TESTS=1")
def test_the_sample_renders_with_the_source_folders_logo(repo_folder):
    """Not installed, not in the project: the theme's logo is found in its source folder only."""
    text = (repo_folder / TEMPLATE).read_text(encoding="utf-8")
    result = theme_sample.render(EXAMPLE_PROJECT, text, KEY, "", home=repo_folder)
    assert result.pdf is not None, result.log
    assert result.pdf.parent.parent.name == f"{KEY}@source"
    log = (result.pdf.parent / f"{theme_sample.DECK}.log").read_text(encoding="utf-8", errors="replace")
    assert (repo_folder / "schemes").as_posix() in log.replace("\n", "").replace("\r", "")
