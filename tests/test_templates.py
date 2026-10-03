"""The generic SlideMage template is a known template like the institution
ones: detected from a deck's preamble, previews named after it, the
"Update previews" preamble built from it, and shipped in example/."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from slidemage import alt_draft, app_settings, slide_preview, slide_snapshot, update_all_previews

EXAMPLE = Path(__file__).resolve().parents[1] / "example"


def test_slidemage_template_detected():
    preamble = "\\usetheme{gotham}\n\\input{Slidemaster_preamble_slidemage}\n"
    assert slide_snapshot.detect_template(preamble) == "slidemage"
    assert slide_snapshot.TEMPLATES["slidemage"] == "SlideMage"


def test_institution_templates_unchanged():
    for key in ("uni-graz", "uni-ibk", "mci"):
        assert slide_snapshot.detect_template(
            f"\\input{{Slidemaster_preamble_{key}}}") == key
    assert slide_snapshot.detect_template("no template here") == "uni-graz"


def test_update_previews_preamble_uses_slidemage_template():
    preamble = update_all_previews._preamble_for("slidemage")
    assert "\\input{Slidemaster_preamble_slidemage}" in preamble
    assert "\\input{Slidemaster_preamble_uni-graz}" not in preamble


def test_preview_filenames_recognized():
    assert update_all_previews._SNAPSHOT_FILENAME_RE.match("ZZZ-EN-SlideMage-1920-1080.png")


def test_example_ships_the_template_and_its_logo():
    tex = (EXAMPLE / "Slidemaster_preamble_slidemage.tex").read_text(encoding="utf-8")
    assert "\\input{Slidemaster_preamble_base}" in tex
    logo = "schemes/scheme_slidemage/Logo_SlideMage-cropped.pdf"
    assert logo in tex
    assert (EXAMPLE / logo).is_file()


# -- default render template (Settings -> General) ---------------------------


def _project(tmp_path, *templates):
    for key in templates:
        (tmp_path / f"Slidemaster_preamble_{key}.tex").write_text("%\n", encoding="utf-8")
    return tmp_path


def test_render_template_out_of_the_box_is_slidemage(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "STORE_PATH", tmp_path / "app_settings.json")
    root = _project(tmp_path, "uni-graz", "slidemage")
    assert slide_snapshot.available_templates(root) == ["uni-graz", "slidemage"]
    assert slide_snapshot.render_template(root) == "slidemage"


def test_render_template_follows_the_setting(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "STORE_PATH", tmp_path / "app_settings.json")
    root = _project(tmp_path, "uni-graz", "slidemage")
    app_settings.set(slide_snapshot.RENDER_TEMPLATE_SETTING_KEY, "uni-graz")
    assert slide_snapshot.render_template(root) == "uni-graz"


def test_render_template_falls_back_to_what_the_project_has(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "STORE_PATH", tmp_path / "app_settings.json")
    # A project with only institution layers (like SlideMaster_SP): Graz.
    root = _project(tmp_path, "uni-graz", "mci")
    assert slide_snapshot.render_template(root) == "uni-graz"
    # A saved choice whose file is gone falls back too.
    app_settings.set(slide_snapshot.RENDER_TEMPLATE_SETTING_KEY, "uni-ibk")
    assert slide_snapshot.render_template(root) == "uni-graz"
    (tmp_path / "other").mkdir()
    only_mci = _project(tmp_path / "other", "mci")
    assert slide_snapshot.render_template(only_mci) == "mci"


def test_default_preamble_uses_the_render_template(monkeypatch):
    monkeypatch.setattr(slide_snapshot, "render_template", lambda root=None: "slidemage")
    preamble = slide_preview.default_preamble()
    assert "\\input{Slidemaster_preamble_slidemage}" in preamble
    assert "\\input{Slidemaster_preamble_uni-graz}" not in preamble
    assert slide_snapshot.detect_template(preamble) == "slidemage"


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_settings_offers_the_project_templates_and_saves_the_choice(tmp_path, monkeypatch, qapp):
    from PySide6.QtWidgets import QWidget

    from slidemage.qt_settings_dialog import SettingsDialog

    monkeypatch.setattr(app_settings, "STORE_PATH", tmp_path / "app_settings.json")
    monkeypatch.setattr(slide_snapshot, "PROJECT_ROOT", _project(tmp_path, "uni-graz", "slidemage"))
    monkeypatch.setattr(alt_draft, "list_all_models", lambda: [])
    monkeypatch.setattr(alt_draft, "list_vision_models", lambda: [])
    monkeypatch.setattr(alt_draft, "list_installed_models_detailed", lambda: [])
    monkeypatch.setattr(SettingsDialog, "_build_ai_prompts_tab", lambda self: QWidget())

    class App(QWidget):
        def __init__(self):
            super().__init__()
            self.theme = SimpleNamespace(dark=False)
            self.set_dark_mode = lambda _value: None
            self.set_tab_width_chars = lambda _value: None
            self.log = lambda _message: None

    settings = SettingsDialog(App())
    combo = settings.render_template_combo
    assert [combo.itemData(i) for i in range(combo.count())] == ["uni-graz", "slidemage"]
    assert combo.currentData() == "slidemage"  # out of the box
    combo.setCurrentIndex(combo.findData("uni-graz"))
    assert app_settings.get(slide_snapshot.RENDER_TEMPLATE_SETTING_KEY) == "uni-graz"
    assert slide_snapshot.render_template() == "uni-graz"
