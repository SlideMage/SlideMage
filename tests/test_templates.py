"""The generic SlideMage template is a known template like the institution
ones: detected from a deck's preamble, previews named after it, the
"Update previews" preamble built from it, and shipped with the framework
(latex/), so every project next to it can use it."""
from pathlib import Path

import pytest

from conftest import use_project
from slidemage import app_settings, slide_preview, slide_snapshot, update_all_previews
from slidemage.project import ProjectContext, transitional_context

EXAMPLE = Path(__file__).resolve().parents[1] / "example"
LATEX = Path(__file__).resolve().parents[1] / "latex"


@pytest.fixture(autouse=True)
def _no_framework_override(monkeypatch):
    monkeypatch.delenv("SLIDEMASTER_LATEX", raising=False)


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


def test_framework_ships_the_template_and_its_logo():
    tex = (LATEX / "Slidemaster_preamble_slidemage.tex").read_text(encoding="utf-8")
    assert "\\input{Slidemaster_preamble_base}" in tex
    assert "\\newcommand{\\SMInstituteLogoPath}{slidemage-logo.pdf}" in tex
    assert (LATEX / "slidemage-logo.pdf").is_file()
    # No longer a per-project copy (v5.7.0/v5.8.0 had it in example/).
    assert not (EXAMPLE / "Slidemaster_preamble_slidemage.tex").exists()


# -- default render template (Settings -> General) ---------------------------


def _project(folder, *templates):
    folder.mkdir(parents=True, exist_ok=True)
    for key in templates:
        (folder / f"Slidemaster_preamble_{key}.tex").write_text("%\n", encoding="utf-8")
    return folder


def _framework(folder, *templates):
    return _project(folder, "base", *templates)


def test_every_project_next_to_the_framework_offers_the_slidemage_template(tmp_path, monkeypatch):
    framework = _framework(tmp_path / "latex", "slidemage")
    project = _project(tmp_path / "project", "uni-graz", "uni-ibk", "mci")
    assert slide_snapshot.framework_dirs(project) == [framework]
    assert slide_snapshot.available_templates(project) == ["uni-graz", "uni-ibk", "mci", "slidemage"]
    assert slide_snapshot.preamble_file("slidemage", project) == framework / "Slidemaster_preamble_slidemage.tex"
    assert slide_snapshot.render_template(ProjectContext.at(project)) == "slidemage"
    # A project's own copy wins over the framework's.
    _project(project, "slidemage")
    assert slide_snapshot.preamble_file("slidemage", project) == project / "Slidemaster_preamble_slidemage.tex"


def test_framework_found_via_environment_or_slidemage_checkout(tmp_path, monkeypatch):
    checkout = _framework(tmp_path / "SlideMage" / "latex")
    project = _project(tmp_path / "project")
    assert slide_snapshot.framework_dirs(project) == [checkout]
    elsewhere = _framework(tmp_path / "elsewhere")
    monkeypatch.setenv("SLIDEMASTER_LATEX", str(elsewhere))
    assert slide_snapshot.framework_dirs(project) == [elsewhere, checkout]


def test_render_template_falls_back_to_what_the_project_has(tmp_path, monkeypatch):
    ctx = use_project(monkeypatch, tmp_path / "project")
    # A project with only institution layers and no framework next to it: Graz.
    root = _project(tmp_path / "project", "uni-graz", "mci")
    assert slide_snapshot.render_template(ProjectContext.at(root)) == "uni-graz"
    # A saved choice whose file is gone falls back too.
    app_settings.set(ctx, slide_snapshot.RENDER_TEMPLATE_SETTING_KEY, "uni-ibk")
    assert slide_snapshot.render_template(ProjectContext.at(root)) == "uni-graz"
    only_mci = _project(tmp_path / "other", "mci")
    assert slide_snapshot.render_template(ProjectContext.at(only_mci)) == "mci"


def test_default_preamble_uses_the_render_template(monkeypatch):
    monkeypatch.setattr(slide_snapshot, "render_template", lambda ctx: "slidemage")
    preamble = slide_preview.default_preamble(transitional_context())
    assert "\\input{Slidemaster_preamble_slidemage}" in preamble
    assert "\\input{Slidemaster_preamble_uni-graz}" not in preamble
    assert slide_snapshot.detect_template(preamble) == "slidemage"


@pytest.mark.parametrize("template", ["uni-graz", "mci"])
def test_set_render_template_saves_a_known_template_only(tmp_path, monkeypatch, template):
    _framework(tmp_path / "latex", "slidemage")
    root = _project(tmp_path / "project", "uni-graz", "mci", "slidemage")
    ctx = use_project(monkeypatch, root)
    assert slide_snapshot.available_templates(root) == ["uni-graz", "mci", "slidemage"]
    assert slide_snapshot.render_template(ProjectContext.at(root)) == "slidemage"
    slide_snapshot.set_render_template(ctx, template)
    assert app_settings.get(ctx, slide_snapshot.RENDER_TEMPLATE_SETTING_KEY) == template
    assert slide_snapshot.render_template(ctx) == template
    with pytest.raises(ValueError, match="not a template"):
        slide_snapshot.set_render_template(ctx, "nope")
    assert slide_snapshot.render_template(ctx) == template
