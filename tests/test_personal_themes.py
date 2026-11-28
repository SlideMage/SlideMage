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
from PySide6.QtWidgets import QMessageBox, QWidget

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


# -- the list

def test_project_templates_are_discovered_and_report_what_they_override(project_dir, installed_sample):
    path = template(project_dir, "uni-graz", "% SlideMage template name: Uni Graz\n")
    (project_dir / "notes.tex").write_text("x")
    template(project_dir, "sample-theme")
    template(project_dir, "grayscale")
    found = {t.key: t for t in slide_templates.personal_themes(project_dir)}
    assert {key: theme.replaces for key, theme in found.items()} == {
        "grayscale": "the shipped template", "sample-theme": "an installed theme", "uni-graz": "",
    }
    assert (found["uni-graz"].name, found["uni-graz"].path) == ("Uni Graz", path)
    assert found.keys() <= set(slide_templates.available_templates(project_dir))


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


def test_extensions_lists_personal_themes_and_defers_editing(qapp, project_dir, monkeypatch, installed_sample):
    path = template(project_dir, "my-look", "% SlideMage template name: My Look\n")
    app, later = FakeApp(project_dir), []
    tab = PluginsTab(app, later.append)
    assert list(tab.personal_rows) == ["my-look"]
    row = tab.personal_rows["my-look"]
    assert isinstance(row, PersonalThemeRow) and row.location_label.text() == str(path)
    assert list(tab.theme_rows) == ["sample-theme"]
    tab.theme_rows["sample-theme"].copy_button.click()
    assert not app.copied and len(later) == 1
    later.pop()()
    assert app.copied == ["sample-theme"]
    revealed = []
    monkeypatch.setattr(open_path, "reveal_in_file_manager", revealed.append)
    row.reveal_button.click()
    assert revealed == [path]
    row.edit_button.click()
    assert app.opened == [] and len(later) == 1          # after the modal sheet is gone
    later.pop()()
    assert app.opened == [path]

    standalone = PluginsTab(app)
    standalone.theme_rows["sample-theme"].copy_button.click()
    assert app.copied == ["sample-theme", "sample-theme"] and later == []


# -- copying an installed theme

def test_copy_to_project_takes_template_and_scheme_and_keeps_what_is_there(project_dir, installed_sample):
    path = themes.copy_to_project("sample-theme", project_dir)
    assert path == project_dir / "SlideMage_template_sample-theme.tex" and path.is_file()
    assert (project_dir / "schemes" / "scheme_sample_theme" / "sample-logo.pdf").is_file()
    path.write_text("% mine\n")
    themes.copy_to_project("sample-theme", project_dir)
    assert path.read_text() == "% mine\n"                # a second copy overwrites nothing
    assert [t.key for t in slide_templates.personal_themes(project_dir)] == ["sample-theme"]


# -- the window

def test_edit_opens_a_source_tab(tmp_path):
    opened = []
    path = tmp_path / "SlideMage_template_x.tex"
    fake = SimpleNamespace(open_slide_editor=lambda p, **kw: opened.append((p, kw)))
    WorkspaceWindow.open_theme_editor(fake, path)
    assert opened == [(path, {"tab": True})]


def test_copying_opens_the_copy_and_a_missing_theme_only_warns(project_dir, monkeypatch, installed_sample):
    warned, steps = [], []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[2])))
    fake = SimpleNamespace(project=SimpleNamespace(root=project_dir), log=lambda line: steps.append("log"),
                           open_theme_editor=lambda p: steps.append(("open", p)),
                           reload_decks=lambda: steps.append("reload"))
    WorkspaceWindow.copy_theme_to_project(fake, "nope")
    assert len(warned) == 1 and "not installed" in warned[0] and steps == []
    assert list(project_dir.iterdir()) == []
    WorkspaceWindow.copy_theme_to_project(fake, "sample-theme")
    assert steps == ["log", ("open", project_dir / "SlideMage_template_sample-theme.tex"), "reload"]


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
