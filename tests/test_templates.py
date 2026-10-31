# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The generic SlideMage template is a known template like the institution
ones: detected from a deck's preamble, previews named after it, the
"Update previews" preamble built from it, and shipped with the framework
(latex/), so every project next to it can use it."""
from pathlib import Path

import pytest

from slidemage import app_settings, slide_preview, slide_snapshot, update_all_previews
from slidemage.project import ProjectContext

EXAMPLE = Path(__file__).resolve().parents[1] / "example"
LATEX = Path(__file__).resolve().parents[1] / "latex"


@pytest.fixture(autouse=True)
def _no_framework_override(monkeypatch):
    monkeypatch.delenv("SLIDEMAGE_LATEX", raising=False)


def test_slidemage_template_detected():
    preamble = "\\input{SlideMage_template_slidemage}\n"
    assert slide_snapshot.detect_template(preamble) == "slidemage"
    assert slide_snapshot.TEMPLATES["slidemage"] == "SlideMage"


def test_institution_templates_unchanged():
    for key in ("beta", "gamma", "acme"):
        assert slide_snapshot.detect_template(
            f"\\input{{SlideMage_template_{key}}}") == key
    assert slide_snapshot.detect_template("no template here") == "slidemage"
    assert slide_snapshot.detect_template("\\input{SlideMage_base}") == "slidemage"


def test_update_previews_preamble_uses_slidemage_template():
    preamble = update_all_previews._preamble_for("slidemage")
    assert "\\input{SlideMage_template_slidemage}" in preamble
    assert "\\input{SlideMage_template_beta}" not in preamble


def test_preview_filenames_recognized():
    assert update_all_previews._SNAPSHOT_FILENAME_RE.match("ZZZ-EN-SlideMage-1920-1080.png")


def test_framework_ships_the_template_and_its_logo():
    tex = (LATEX / "SlideMage_template_slidemage.tex").read_text(encoding="utf-8")
    assert "\\input{SlideMage_setup}" in tex and "\\input{SlideMage_base}" in tex
    # The SlideMage look is the setup catalog's default, logo included.
    setup = (LATEX / "SlideMage_setup.tex").read_text(encoding="utf-8")
    assert "\\newcommand{\\SMInstituteLogoPath}{slidemage-logo.pdf}" in setup
    assert (LATEX / "slidemage-logo.pdf").is_file()


def test_shipped_templates_change_catalog_settings_instead_of_creating_them():
    from slidemage import compat_setup
    for path in (LATEX / "SlideMage_template_slidemage.tex",):
        tex = path.read_text(encoding="utf-8")
        for pattern in (compat_setup._NEWCOMMAND, compat_setup._NEWLENGTH, compat_setup._PADDING):
            assert not compat_setup._live(pattern, tex), (path.name, pattern.pattern)
        assert tex.index("\\input{SlideMage_setup}") < tex.index("\\input{SlideMage_base}")
    # No longer a per-project copy (v5.7.0/v5.8.0 had it in example/).
    assert not (EXAMPLE / "SlideMage_template_slidemage.tex").exists()


# -- default render template (Settings -> General) ---------------------------


def _project(folder, *templates):
    folder.mkdir(parents=True, exist_ok=True)
    for key in templates:
        (folder / f"SlideMage_template_{key}.tex").write_text("%\n", encoding="utf-8")
    return folder


def _framework(folder, *templates):
    _project(folder, *templates)
    (folder / "SlideMage_base.tex").write_text("%\n", encoding="utf-8")
    return folder


def test_every_project_next_to_the_framework_offers_the_slidemage_template(tmp_path, monkeypatch):
    framework = _framework(tmp_path / "latex", "slidemage")
    project = _project(tmp_path / "project", "beta", "gamma", "acme")
    assert slide_snapshot.framework_dirs(project) == [framework]
    assert slide_snapshot.available_templates(project) == ["slidemage", "acme", "beta", "gamma"]
    assert slide_snapshot.preamble_file("slidemage", project) == framework / "SlideMage_template_slidemage.tex"
    assert slide_snapshot.render_template(ProjectContext.at(project)) == "slidemage"
    # A project's own copy wins over the framework's.
    _project(project, "slidemage")
    assert slide_snapshot.preamble_file("slidemage", project) == project / "SlideMage_template_slidemage.tex"


def test_framework_found_via_environment_or_slidemage_checkout(tmp_path, monkeypatch):
    checkout = _framework(tmp_path / "SlideMage" / "latex")
    project = _project(tmp_path / "project")
    assert slide_snapshot.framework_dirs(project) == [checkout]
    elsewhere = _framework(tmp_path / "elsewhere")
    monkeypatch.setenv("SLIDEMAGE_LATEX", str(elsewhere))
    assert slide_snapshot.framework_dirs(project) == [elsewhere, checkout]


def test_render_template_falls_back_to_what_the_project_has(tmp_path, monkeypatch):
    ctx = ProjectContext.at(tmp_path / "project")
    # A project with only institution layers and no framework next to it: the first of them.
    root = _project(tmp_path / "project", "beta", "acme")
    assert slide_snapshot.render_template(ProjectContext.at(root)) == "acme"
    # A saved choice whose file is gone falls back too.
    app_settings.set(ctx, slide_snapshot.RENDER_TEMPLATE_SETTING_KEY, "gamma")
    assert slide_snapshot.render_template(ProjectContext.at(root)) == "acme"
    only_acme = _project(tmp_path / "other", "acme")
    assert slide_snapshot.render_template(ProjectContext.at(only_acme)) == "acme"


def test_default_preamble_uses_the_render_template(ctx, monkeypatch):
    monkeypatch.setattr(slide_snapshot, "render_template", lambda ctx: "slidemage")
    preamble = slide_preview.default_preamble(ctx)
    assert "\\input{SlideMage_template_slidemage}" in preamble
    assert "\\input{SlideMage_template_beta}" not in preamble
    assert slide_snapshot.detect_template(preamble) == "slidemage"


@pytest.mark.parametrize("template", ["beta", "acme"])
def test_set_render_template_saves_a_known_template_only(tmp_path, monkeypatch, template):
    _framework(tmp_path / "latex", "slidemage")
    root = _project(tmp_path / "project", "beta", "acme", "slidemage")
    ctx = ProjectContext.at(root)
    assert slide_snapshot.available_templates(root) == ["slidemage", "acme", "beta"]
    assert slide_snapshot.render_template(ProjectContext.at(root)) == "slidemage"
    slide_snapshot.set_render_template(ctx, template)
    assert app_settings.get(ctx, slide_snapshot.RENDER_TEMPLATE_SETTING_KEY) == template
    assert slide_snapshot.render_template(ctx) == template
    with pytest.raises(ValueError, match="not a template"):
        slide_snapshot.set_render_template(ctx, "nope")
    assert slide_snapshot.render_template(ctx) == template


def test_templates_are_found_in_the_project_and_named_from_their_keys(tmp_path):
    root = _project(tmp_path / "project", "my-uni", "other")
    (root / "SlideMage_template_my-uni.tex").write_text("%% SlideMage template name: My University\n", encoding="utf-8")
    assert slide_snapshot.detect_template("\\input{SlideMage_template_my-uni}") == "my-uni"
    assert slide_snapshot.TEMPLATES["my-uni"] == "MyUni" and slide_snapshot.TEMPLATES["slidemage"] == "SlideMage"
    assert slide_snapshot.template_label("my-uni", root) == "My University"      # declared in the file
    assert slide_snapshot.template_label("other", root) == "Other"               # read from the key
    assert slide_snapshot.template_label("slidemage") == "SlideMage"
