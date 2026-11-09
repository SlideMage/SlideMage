# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The generic SlideMage template is a known template like the institution
ones: detected from a deck's preamble, used for previews and shipped with the framework
(latex/), so every project next to it can use it."""
from pathlib import Path

import pytest

from slidemage import app_settings, project, slide_preview, slide_templates
from slidemage.project import ProjectContext

EXAMPLE = Path(__file__).resolve().parents[1] / "example"
LATEX = Path(__file__).resolve().parents[1] / "latex"


@pytest.fixture(autouse=True)
def _no_framework_override(monkeypatch):
    monkeypatch.delenv("SLIDEMAGE_LATEX", raising=False)


def test_slidemage_template_detected():
    preamble = "\\input{SlideMage_template_slidemage}\n"
    assert slide_templates.detect_template(preamble) == "slidemage"
    assert slide_templates.TEMPLATES["slidemage"] == "SlideMage"


def test_institution_templates_unchanged():
    for key in ("beta", "gamma", "acme"):
        assert slide_templates.detect_template(
            f"\\input{{SlideMage_template_{key}}}") == key
    assert slide_templates.detect_template("no template here") == "slidemage"
    assert slide_templates.detect_template("\\input{SlideMage_base}") == "slidemage"


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
    assert slide_templates.framework_dirs(project) == [framework]
    assert slide_templates.available_templates(project) == ["slidemage", "acme", "beta", "gamma"]
    assert slide_templates.preamble_file("slidemage", project) == framework / "SlideMage_template_slidemage.tex"
    assert slide_templates.render_template(ProjectContext.at(project)) == "slidemage"
    # A project's own copy wins over the framework's.
    _project(project, "slidemage")
    assert slide_templates.preamble_file("slidemage", project) == project / "SlideMage_template_slidemage.tex"


def test_framework_found_via_environment_or_slidemage_checkout(tmp_path, monkeypatch):
    checkout = _framework(tmp_path / "SlideMage" / "latex")
    project = _project(tmp_path / "project")
    assert slide_templates.framework_dirs(project) == [checkout]
    elsewhere = _framework(tmp_path / "elsewhere")
    monkeypatch.setenv("SLIDEMAGE_LATEX", str(elsewhere))
    assert slide_templates.framework_dirs(project) == [elsewhere, checkout]


def test_render_template_falls_back_to_what_the_project_has(tmp_path, monkeypatch):
    ctx = ProjectContext.at(tmp_path / "project")
    root = _project(tmp_path / "project", "beta", "acme")
    # v0.14.19: with no framework next to it, the project uses the one SlideMage bundles, so the out-of-the-box
    # template is there.
    assert slide_templates.render_template(ProjectContext.at(root)) == "slidemage"
    # Without a bundled framework either, only institution layers: the first of them.
    monkeypatch.setattr(project, "template_dir", lambda name: None)
    assert slide_templates.render_template(ProjectContext.at(root)) == "acme"
    # A saved choice whose file is gone falls back too.
    app_settings.set(ctx, slide_templates.RENDER_TEMPLATE_SETTING_KEY, "gamma")
    assert slide_templates.render_template(ProjectContext.at(root)) == "acme"
    only_acme = _project(tmp_path / "other", "acme")
    assert slide_templates.render_template(ProjectContext.at(only_acme)) == "acme"


def test_default_preamble_uses_the_render_template(ctx, monkeypatch):
    monkeypatch.setattr(slide_templates, "render_template", lambda ctx: "slidemage")
    preamble = slide_preview.default_preamble(ctx)
    assert "\\input{SlideMage_template_slidemage}" in preamble
    assert "\\input{SlideMage_template_beta}" not in preamble
    assert slide_templates.detect_template(preamble) == "slidemage"


@pytest.mark.parametrize("template", ["beta", "acme"])
def test_set_render_template_saves_a_known_template_only(tmp_path, monkeypatch, template):
    _framework(tmp_path / "latex", "slidemage")
    root = _project(tmp_path / "project", "beta", "acme", "slidemage")
    ctx = ProjectContext.at(root)
    assert slide_templates.available_templates(root) == ["slidemage", "acme", "beta"]
    assert slide_templates.render_template(ProjectContext.at(root)) == "slidemage"
    slide_templates.set_render_template(ctx, template)
    assert app_settings.get(ctx, slide_templates.RENDER_TEMPLATE_SETTING_KEY) == template
    assert slide_templates.render_template(ctx) == template
    with pytest.raises(ValueError, match="not a template"):
        slide_templates.set_render_template(ctx, "nope")
    assert slide_templates.render_template(ctx) == template


def test_templates_are_found_in_the_project_and_named_from_their_keys(tmp_path):
    root = _project(tmp_path / "project", "my-uni", "other")
    (root / "SlideMage_template_my-uni.tex").write_text("%% SlideMage template name: My University\n", encoding="utf-8")
    assert slide_templates.detect_template("\\input{SlideMage_template_my-uni}") == "my-uni"
    assert slide_templates.TEMPLATES["my-uni"] == "MyUni" and slide_templates.TEMPLATES["slidemage"] == "SlideMage"
    assert slide_templates.template_label("my-uni", root) == "My University"      # declared in the file
    assert slide_templates.template_label("other", root) == "Other"               # read from the key
    assert slide_templates.template_label("slidemage") == "SlideMage"
