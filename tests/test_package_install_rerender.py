# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Installing a package re-renders only what uses it (issue #251, docs/plans/package-install-rerender.md).

Installing the APA citation package made SlideMage render every preview of a project again, though no deck used it:
the package folder is on TEXINPUTS (so in every render key), the new SlideMage_citation_apa.tex matched a probe name
(so it counted for every render), and a new slide file made the precompiled preamble format stale.

The renders here are stored by the background renderer's fake TeX; the xfail marks name the plan step that fixes each.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from slidemage import background_renders, citations, compiler, preview_format, render_evidence, slide_templates, themes
from slidemage.render_key import Freshness

from test_background_renders import FakeTeX, deck_named, make, project, raster, render_unit, store  # noqa: F401
from test_citations import _compile, needs_tex
from test_preview_build import _ensure, _fake_engine


@pytest.fixture
def world(request):
    """The example project in a temp folder, with its render store and rasteriser (test_background_renders' fixtures)."""
    return SimpleNamespace(**{name: request.getfixturevalue(name) for name in ("project", "store", "raster")})


def install_citation(key="apa") -> Path:
    path = citations.citations_dir() / key / citations.format_file(key)
    path.parent.mkdir(parents=True)
    path.write_text("% a citation format\n", encoding="utf-8")
    return path.parent


def install_theme(key="newtheme", layout=None) -> Path:
    folder = themes.themes_dir() / key
    folder.mkdir(parents=True)
    (folder / themes.template_file(key)).write_text("% a template\n", encoding="utf-8")
    if layout:
        (folder / f"{themes.LAYOUT_PREFIX}{layout}.tex").write_text("% a layout profile\n", encoding="utf-8")
    return folder


INSTALL = {"citation": install_citation, "theme": install_theme}


def unit_of(world, tex=None):
    """The renderer and the first unit of the manual (a deck that uses no package)."""
    r = make(world.project, world.store, world.raster, tex=tex)
    return r, background_renders.deck_units(world.project, deck_named(r, "slidemage-manual"), "instructor", "EN")[0]


def render_one(world, inputs=()):
    """A stored, fresh render of that unit, which read `inputs` besides its slide."""
    r, unit = unit_of(world, FakeTeX(world.project, inputs=inputs))
    assert render_unit(r, unit) and r.resolver.lookup(unit).state is Freshness.FRESH
    return r, unit


def test_a_citation_package_no_deck_uses_leaves_the_render_fresh(world):
    r, unit = render_one(world)
    install_citation()
    assert r.resolver.lookup(unit).state is Freshness.FRESH


def test_a_theme_package_no_deck_uses_leaves_the_render_fresh(world):
    r, unit = render_one(world)
    install_theme()
    assert r.resolver.lookup(unit).state is Freshness.FRESH


@pytest.mark.parametrize("kind", ["citation", "theme"])
def test_removing_a_package_no_deck_uses_leaves_the_render_fresh(kind, world):
    folder = INSTALL[kind]()
    r, unit = render_one(world)
    shutil.rmtree(folder)
    assert r.resolver.lookup(unit).state is Freshness.FRESH


def test_updating_a_theme_package_a_render_read_makes_it_stale(world):
    """The folder keeps its name, so only the file's content tells."""
    template = install_theme() / themes.template_file("newtheme")
    r, unit = render_one(world, inputs=[template])
    template.write_text("% a changed template\n", encoding="utf-8")
    assert r.resolver.lookup(unit).state is Freshness.STALE


def test_only_search_roots_with_probe_names_count_for_the_conservative_digest(tmp_path):
    env = {"TEXINPUTS": ""}
    before = render_evidence.search_inventory(tmp_path, env)["conservative"]
    empty = tmp_path / "empty"
    empty.mkdir()
    env["TEXINPUTS"] = os.pathsep.join([str(empty), str(tmp_path / "missing")])
    assert render_evidence.search_inventory(tmp_path, env)["conservative"] == before
    named = tmp_path / "named"
    named.mkdir()
    (named / "SlideMage_project_macros.tex").write_text("% project macros\n", encoding="utf-8")
    env["TEXINPUTS"] = str(named)
    with_names = render_evidence.search_inventory(tmp_path, env)["conservative"]
    assert with_names != before
    shutil.rmtree(named)
    assert render_evidence.search_inventory(tmp_path, env)["conservative"] == before


def fail_with(r, unit, log, monkeypatch):
    """Render the unit through the real failure path with the log TeX wrote; its key before the install."""
    r.render_override = None
    monkeypatch.setenv("SLIDEMAGE_PREVIEW_FORMAT", "0")

    def run(command, *, jobname, outdir, **kwargs):
        (outdir / (jobname + ".fls")).write_text(f"PWD {r.ctx.decks_dir}\nINPUT {unit.source_path}\n")
        return compiler.Build(1, outdir / (jobname + ".pdf"), outdir / (jobname + ".log"), log, False)

    monkeypatch.setattr(compiler, "run_latexmk", run)
    key = r.resolver.lookup(unit).key
    with pytest.raises(RuntimeError, match="Render failed"):
        render_unit(r, unit)
    assert r.resolver.lookup(unit, key).state is Freshness.FAILED
    return key


@needs_tex
def test_a_render_that_failed_for_want_of_a_citation_format_runs_again_once_it_is_installed(world, tmp_path, monkeypatch):
    """Judged under the unchanged key: the install itself must end the failure, not the key it happens to change."""
    deck = (r"\documentclass{beamer}" "\n" r"\input{SlideMage_template_grayscale}" "\n"
            r"\renewcommand{\SMCitationFormat}{apa}" "\n" r"\SMUseBibliography" "\n"
            r"\newcommand{\FooterText}{x}" "\n" r"\begin{document}\end{document}" "\n")
    r, unit = unit_of(world)
    key = fail_with(r, unit, _compile(tmp_path, deck, []), monkeypatch)
    install_citation()
    assert r.resolver.lookup(unit, key).state is not Freshness.FAILED


@needs_tex
def test_a_render_that_failed_for_want_of_a_layout_profile_runs_again_once_it_is_installed(world, tmp_path, monkeypatch):
    deck = (r"\documentclass{beamer}" "\n" r"\newcommand{\SMLayoutProfile}{myfont}" "\n"
            r"\input{SlideMage_template_slidemage}" "\n" r"\begin{document}\end{document}" "\n")
    r, unit = unit_of(world)
    key = fail_with(r, unit, _compile(tmp_path, deck, []), monkeypatch)
    install_theme(layout="myfont")
    assert r.resolver.lookup(unit, key).state is not Freshness.FAILED


def package_file(root):
    return install_theme() / themes.template_file("newtheme")


def framework_file(root):
    return slide_templates.framework_dirs(root)[0] / themes.template_file("slidemage")


@pytest.mark.parametrize("where", [
    pytest.param(framework_file, id="framework"),
    pytest.param(package_file, id="package")])
def test_a_copy_of_a_file_a_render_read_in_the_project_makes_it_stale(where, world):
    """A file of the same name earlier on the search path shadows the one the render read."""
    original = where(world.project.root)
    r, unit = render_one(world, inputs=[original])
    shutil.copy(original, world.project.root / original.name)
    assert r.resolver.lookup(unit).state is Freshness.STALE


def test_a_new_slide_file_leaves_the_precompiled_format_current(tmp_path, monkeypatch):
    runs = _fake_engine(monkeypatch)
    directory = _ensure(tmp_path)
    assert preview_format._fresh(directory / "format.json", tmp_path, {})
    (tmp_path / "slides").mkdir()
    (tmp_path / "slides" / "new-EN-Slide-current.tex").write_text("\\begin{frame}\\end{frame}", encoding="utf-8")
    assert preview_format._fresh(directory / "format.json", tmp_path, {})
    assert len(runs) == 1


@pytest.mark.parametrize("name", [
    pytest.param("decks/package.cls", id="a file with the stem of an input"),
    pytest.param("refs.bib", id="a probe name"),
    pytest.param("package.sty", id="an input's content")])
def test_what_the_preamble_read_makes_the_precompiled_format_stale(name, tmp_path, monkeypatch):
    _fake_engine(monkeypatch)
    directory = _ensure(tmp_path)
    (tmp_path / name).parent.mkdir(exist_ok=True)
    (tmp_path / name).write_text("changed, and longer", encoding="utf-8")
    assert not preview_format._fresh(directory / "format.json", tmp_path, {})
