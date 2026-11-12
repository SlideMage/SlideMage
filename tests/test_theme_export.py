# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage C4 of docs/plans/theme-editor.md: a theme exported as a .smtheme package. A personal theme (a template file in
the project) gets theme.toml, README, CHANGELOG and LICENSE written from the dialog's fields; an installed theme's
source folder is packed as it is. What is written installs with "Add from file…"."""
from __future__ import annotations

import shutil
import tomllib
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox, QWidget

from conftest import qapp as qapp
from slidemage import theme_export, theme_source_folder, themes
from slidemage.plugins import installer, session
from slidemage.ui.dialogs.settings_plugins import PluginsTab
from slidemage.ui.kit.theme import ThemeManager

REPO = Path(__file__).resolve().parents[1]
KEY = "my-look"
INFO = theme_export.ExportInfo(name="My Look", version="1.2.0", summary="A test look.", author="Tests",
                               homepage="https://example.org/my-look", license="LPPL-1.3c-or-later")


@pytest.fixture(autouse=True)
def isolated():
    installer._changed.clear()
    session.set_loaded([])
    yield
    installer._changed.clear()


@pytest.fixture
def project_dir(tmp_path):
    """A project with a personal theme made from the shipped one, with a logo of its own."""
    root = tmp_path / "project"
    root.mkdir()
    text = (REPO / "latex" / "SlideMage_template_slidemage.tex").read_bytes().decode("utf-8")
    (root / f"SlideMage_template_{KEY}.tex").write_bytes(text.replace(
        "% SlideMage modes:", "% SlideMage template name: My Look\n% SlideMage modes:", 1).encode("utf-8"))
    logo = root / "schemes" / "scheme_my_look" / "logo.pdf"
    logo.parent.mkdir(parents=True)
    logo.write_bytes(b"%PDF-1.4 test")
    (root / "slides").mkdir()
    return root


# -- the package

def test_a_personal_theme_exports_and_installs(project_dir, tmp_path):
    asset = theme_export.export(project_dir, KEY, INFO, tmp_path / "out")
    assert asset.name == "my-look-1.2.0.smtheme" and Path(str(asset) + ".sha256").is_file()
    with zipfile.ZipFile(asset) as zf:
        names = zf.namelist()
        manifest = tomllib.loads(zf.read("theme.toml").decode("utf-8"))
    assert names[0] == "theme.toml"
    assert set(names) == {"theme.toml", "CHANGELOG.md", "LICENSE", "README.md", f"SlideMage_template_{KEY}.tex",
                          "schemes/scheme_my_look/logo.pdf"}
    assert manifest["id"] == KEY and manifest["name"] == "My Look" and manifest["layout"] == "fira"
    assert manifest["requires_slidemage"].startswith(">=0.")
    themes.install_file(asset)
    installed = {theme.key: theme for theme in themes.installed()}
    assert installed[KEY].manifest.version == "1.2.0" and not installed[KEY].problem
    # nothing was written into the project
    assert sorted(p.name for p in project_dir.iterdir()) == ["SlideMage_template_my-look.tex", "schemes", "slides"]


def test_the_same_theme_gives_the_same_bytes(project_dir, tmp_path):
    first = theme_export.export(project_dir, KEY, INFO, tmp_path / "a").read_bytes()
    second = theme_export.export(project_dir, KEY, INFO, tmp_path / "b").read_bytes()
    assert first == second


def test_an_own_layout_profile_goes_along(project_dir, tmp_path):
    path = project_dir / f"SlideMage_template_{KEY}.tex"
    path.write_bytes(path.read_bytes().replace(b"\\input{SlideMage_base}",
                                               b"\\renewcommand{\\SMLayoutProfile}{mine}\n\\input{SlideMage_base}", 1))
    (project_dir / "SlideMage_layout_mine.tex").write_text("% a profile\n", encoding="utf-8")
    asset = theme_export.export(project_dir, KEY, INFO, tmp_path / "out")
    with zipfile.ZipFile(asset) as zf:
        assert "SlideMage_layout_mine.tex" in zf.namelist()
        assert 'layout = "mine"' in zf.read("theme.toml").decode("utf-8")


def test_defaults_come_from_the_template(project_dir):
    start = theme_export.defaults(project_dir, KEY)
    assert start.name == "My Look" and start.version == "1.0.0" and start.license == "LPPL-1.3c-or-later"
    assert start.author == "" and start.homepage == ""


def test_check_info_says_what_is_missing():
    assert theme_export.check_info(KEY, INFO) == ""
    assert theme_export.check_info(KEY, theme_export.ExportInfo(**{**INFO.__dict__, "author": ""})) ==         "A package needs an author."
    assert "version" in theme_export.check_info(KEY, theme_export.ExportInfo(**{**INFO.__dict__, "version": "1.2"}))
    assert "homepage" in theme_export.check_info(KEY, theme_export.ExportInfo(**{**INFO.__dict__, "homepage": "x"}))
    assert "SlideMage ships" in theme_export.check_info("slidemage", INFO)


def test_a_quote_in_a_field_stays_valid_toml(project_dir, tmp_path):
    quoted = theme_export.ExportInfo(**{**INFO.__dict__, "summary": 'The "quoted" look \\ of us.'})
    asset = theme_export.export(project_dir, KEY, quoted, tmp_path / "out")
    with zipfile.ZipFile(asset) as zf:
        assert tomllib.loads(zf.read("theme.toml").decode("utf-8"))["summary"] == 'The "quoted" look \\ of us.'


def test_a_missing_template_is_said(tmp_path):
    with pytest.raises(themes.ThemeError, match="was not found"):
        theme_export.export(tmp_path, KEY, INFO, tmp_path / "out")


# -- Settings

class FakeApp(QWidget):
    def __init__(self, root):
        super().__init__()
        self.project = SimpleNamespace(root=root)
        self.theme = ThemeManager()


def test_export_from_the_personal_themes_row(qapp, project_dir, tmp_path, monkeypatch):
    tab = PluginsTab(FakeApp(project_dir))
    out = tmp_path / "out"
    out.mkdir()
    said: list = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: said.append(a[2]))

    def answer(dialog):
        fields = tab._export_fields
        assert fields["name"].text() == "My Look" and fields["version"].text() == "1.0.0"
        fields["folder"].setText(str(out))
        fields["author"].setText("Tests")
        fields["homepage"].setText("https://example.org/my-look")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", lambda self: answer(self))
    tab.personal_rows[KEY].export_button.click()
    assert tab.last_export == out / "my-look-1.0.0.smtheme" and tab.last_export.is_file()
    assert said and "my-look-1.0.0.smtheme" in said[0]


def test_the_dialog_holds_export_back_until_the_fields_are_valid(qapp, project_dir, tmp_path, monkeypatch):
    tab = PluginsTab(FakeApp(project_dir))
    seen: dict = {}

    def answer(dialog):
        from PySide6.QtWidgets import QDialogButtonBox
        button = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok)
        fields = tab._export_fields
        seen["empty author"] = button.isEnabled()
        fields["author"].setText("Tests")
        fields["homepage"].setText("https://example.org")
        seen["filled"] = button.isEnabled()
        fields["folder"].setText(str(tmp_path / "nowhere"))
        seen["no folder"] = button.isEnabled()
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", lambda self: answer(self))
    tab.personal_rows[KEY].export_button.click()
    assert seen == {"empty author": False, "filled": True, "no folder": False}
    assert getattr(tab, "last_export", None) is None


def test_an_installed_themes_source_folder_is_packed_as_it_is(qapp, project_dir, tmp_path, monkeypatch):
    source = tmp_path / "repos" / "slidemage-theme-sample"
    shutil.copytree(REPO / "tests" / "fixtures" / "theme_package" / "sample-theme", source)
    themes.install_file(theme_export.pack(source, tmp_path / "dist"))
    theme_source_folder.set_folder("sample-theme", source)
    toml = source / "theme.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace('"1.0.0"', '"1.0.1"'), encoding="utf-8")
    out = tmp_path / "release"
    out.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(out))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    tab = PluginsTab(FakeApp(project_dir))
    tab.theme_rows["sample-theme"].export_source_button.click()
    assert tab.last_export == out / "sample-theme-1.0.1.smtheme" and tab.last_export.is_file()


def test_the_tool_and_the_app_pack_alike(project_dir, tmp_path):
    import sys
    sys.path.insert(0, str(REPO / "tools"))
    import make_theme_package
    folder = theme_export.stage(project_dir, KEY, INFO, tmp_path / "staged")
    assert make_theme_package.pack(folder, tmp_path / "a").read_bytes() == \
        theme_export.export(project_dir, KEY, INFO, tmp_path / "b").read_bytes()
