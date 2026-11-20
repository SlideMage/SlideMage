# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Personal themes: the template files in the project folder. Settings → Extensions lists them (marked as personal, with
Edit and Reveal in Explorer, no install controls), Edit opens the file in a centre tab, saving it renders what uses it
again, and an installed theme can be copied into the project to be edited there."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QLabel, QMessageBox, QWidget

from conftest import build_window, qapp as qapp
from slidemage import open_path, slide_templates, themes
from slidemage.plugins import installer, session
from slidemage.ui.dialogs.settings_plugins import PersonalThemeRow, PluginsTab
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.workspace.window import WorkspaceWindow

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import make_theme_package  # noqa: E402


@pytest.fixture(autouse=True)
def isolated():
    installer._changed.clear()
    session.set_loaded([])
    yield
    installer._changed.clear()


@pytest.fixture
def installed_sample(tmp_path):
    folder = tmp_path / "src" / "sample-theme"
    shutil.copytree(REPO / "tests" / "fixtures" / "theme_package" / "sample-theme", folder)
    themes.install_file(make_theme_package.pack(folder, tmp_path / "dist"))


def template(root: Path, key: str, header: str = "") -> Path:
    path = root / f"SlideMage_template_{key}.tex"
    path.write_text(header + "\\input{SlideMage_setup}\n\\input{SlideMage_base}\n", encoding="utf-8")
    return path


@pytest.fixture
def project_dir(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    return root


# -- the list

def test_the_projects_templates_are_its_personal_themes(project_dir):
    template(project_dir, "uni-graz", "% SlideMage template name: Uni Graz\n")
    template(project_dir, "my-look")
    (project_dir / "notes.tex").write_text("x")
    found = slide_templates.personal_themes(project_dir)
    assert [(t.key, t.name, t.replaces) for t in found] == [
        ("my-look", "My Look", ""), ("uni-graz", "Uni Graz", "")]
    assert found[0].path == project_dir / "SlideMage_template_my-look.tex"
    assert {t.key for t in found} <= set(slide_templates.available_templates(project_dir))   # what the deck settings offer


def test_a_personal_theme_says_what_it_wins_over(project_dir, installed_sample):
    template(project_dir, "sample-theme")
    template(project_dir, "grayscale")
    replaced = {t.key: t.replaces for t in slide_templates.personal_themes(project_dir)}
    assert replaced == {"grayscale": "the shipped template", "sample-theme": "an installed theme"}


def test_no_personal_theme_without_a_template_file(project_dir):
    assert slide_templates.personal_themes(project_dir) == []


# -- Settings → Extensions

class FakeApp(QWidget):
    def __init__(self, root):
        super().__init__()
        self.project = SimpleNamespace(root=root)
        self.theme = ThemeManager()
        self.opened: list = []
        self.copied: list = []

    def open_theme_editor(self, path):
        self.opened.append(path)

    def copy_theme_to_project(self, key):
        self.copied.append(key)


def test_extensions_lists_personal_themes_marked_with_file_and_reveal(qapp, project_dir, monkeypatch):
    path = template(project_dir, "my-look", "% SlideMage template name: My Look\n")
    tab = PluginsTab(FakeApp(project_dir))
    assert list(tab.personal_rows) == ["my-look"]
    row = tab.personal_rows["my-look"]
    assert isinstance(row, PersonalThemeRow) and row.location_label.text() == str(path)
    texts = [label.text() for label in row.findChildren(QLabel)]
    assert "Personal (project folder)" in texts and "My Look" in texts
    assert row.reveal_button.text() == "Reveal in Explorer"
    assert tab.theme_rows == {}                                  # not an installed package: no remove or update controls
    revealed = []
    monkeypatch.setattr(open_path, "reveal_in_file_manager", revealed.append)
    row.reveal_button.click()
    assert revealed == [path]


def test_edit_closes_the_sheet_then_opens_the_theme(qapp, project_dir):
    path = template(project_dir, "my-look")
    app = FakeApp(project_dir)
    later = []
    tab = PluginsTab(app, later.append)
    tab.personal_rows["my-look"].edit_button.click()
    assert app.opened == [] and len(later) == 1          # after the modal sheet is gone
    later[0]()
    assert app.opened == [path]


def test_no_personal_theme_is_a_caption(qapp, project_dir):
    tab = PluginsTab(FakeApp(project_dir))
    assert tab.personal_rows == {}


def test_an_installed_theme_can_be_copied_to_the_project(qapp, project_dir, installed_sample):
    app = FakeApp(project_dir)
    tab = PluginsTab(app)
    tab.theme_rows["sample-theme"].copy_button.click()
    assert app.copied == ["sample-theme"]


# -- copying an installed theme

def test_copy_to_project_takes_template_and_scheme_and_keeps_what_is_there(project_dir, installed_sample):
    path = themes.copy_to_project("sample-theme", project_dir)
    assert path == project_dir / "SlideMage_template_sample-theme.tex" and path.is_file()
    assert (project_dir / "schemes" / "scheme_sample_theme" / "sample-logo.pdf").is_file()
    path.write_text("% mine\n")
    themes.copy_to_project("sample-theme", project_dir)
    assert path.read_text() == "% mine\n"                # a second copy overwrites nothing
    assert [t.key for t in slide_templates.personal_themes(project_dir)] == ["sample-theme"]


def test_copy_to_project_of_a_theme_that_is_not_installed(project_dir):
    with pytest.raises(themes.ThemeError, match="not installed"):
        themes.copy_to_project("nope", project_dir)
    assert list(project_dir.iterdir()) == []


# -- the window

def test_edit_opens_a_source_tab(tmp_path):
    opened = []
    path = tmp_path / "SlideMage_template_x.tex"
    fake = SimpleNamespace(open_slide_editor=lambda p, **kw: opened.append((p, kw)))
    WorkspaceWindow.open_theme_editor(fake, path)
    assert opened == [(path, {"tab": True})]


def test_copying_opens_the_copy_and_a_missing_theme_only_warns(tmp_path, monkeypatch):
    warned, steps = [], []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[2])))
    fake = SimpleNamespace(project=SimpleNamespace(root=tmp_path), log=steps.append,
                           open_theme_editor=lambda p: steps.append(("open", p)),
                           reload_decks=lambda: steps.append("reload"))
    WorkspaceWindow.copy_theme_to_project(fake, "nope")
    assert len(warned) == 1 and "not installed" in warned[0] and steps == []


def test_copying_an_installed_theme_opens_the_copy(tmp_path, installed_sample, monkeypatch):
    steps = []
    fake = SimpleNamespace(project=SimpleNamespace(root=tmp_path), log=lambda line: steps.append("log"),
                           open_theme_editor=lambda p: steps.append(("open", p)),
                           reload_decks=lambda: steps.append("reload"))
    WorkspaceWindow.copy_theme_to_project(fake, "sample-theme")
    assert steps == ["log", ("open", tmp_path / "SlideMage_template_sample-theme.tex"), "reload"]


def test_saving_a_theme_renders_what_uses_it_after_a_pause(qapp, monkeypatch):
    window = build_window(monkeypatch)
    renders = []
    monkeypatch.setattr(window, "theme_installed", renders.append)
    root = window.project.root
    window.centre.source.written.emit(root / "SlideMage_template_my-look.tex")
    window.centre.source.written.emit(root / "SlideMage_template_my-look.tex")
    window.centre.source.written.emit(root / "slides" / "SlideMage_template_other.tex")     # not in the project folder
    window.centre.source.written.emit(root / "SlideMage_project_macros.tex")                  # not a template
    assert window._themes_written == {"my-look"} and window._theme_recompile.isActive() and renders == []
    window._theme_recompile.stop()
    window._recompile_written_themes()
    assert renders == ["my-look"] and window._themes_written == set()
