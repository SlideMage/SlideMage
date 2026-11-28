# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Export a deck and its dependencies into a standalone LaTeX folder."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pymupdf
import pytest
from PIL import Image

from conftest import EXAMPLE
from slidemage import compiler, deck_scan, fileio, latex_export
from slidemage.project import ProjectContext, _ignore_template_build_output

HEAD = """\\documentclass[aspectratio=169]{{beamer}}
\\makeatletter
\\def\\input@path{{{{../}}}}
\\makeatother
\\graphicspath{{{{../}}}}
\\input{{SlideMage_template_{template}}}
\\SMUseBibliography
\\newcommand{{\\FooterText}}{{Export test}}
\\begin{{document}}
{calls}
\\end{{document}}
"""
SLIDES = {
    "zz1-EN-One": "\\begin{standardframe}{One}\n\\includegraphics[width=3cm]{media/pic-one.png}\n\\end{standardframe}\n",
    "zz2-EN-Two": ("\\begin{standardframe}{Two}\n\\includegraphics[width=3cm]{media/bare}\n"
                   "% \\includegraphics{media/commented-out.png}\n\\SMCodeFile{snippets/zz2-1.tex}\n\\end{standardframe}\n"),
    "zz9-EN-Unused": "\\begin{standardframe}{Unused}\n\\includegraphics{media/pic-unused.png}\n\\end{standardframe}\n",
}


def make_project(tmp_path: Path) -> ProjectContext:
    root = tmp_path / "example"
    shutil.copytree(EXAMPLE, root, ignore=_ignore_template_build_output)
    for folder in ("decks", "slides", "snippets", "media"):
        for path in (root / folder).iterdir():
            if path.is_file():
                path.unlink()
    for slug, body in SLIDES.items():
        (root / "slides" / f"{slug}-current.tex").write_text(body, encoding="utf-8")
    for name in ("pic-one.png", "pic-unused.png", "bare.png", "commented-out.png"):
        Image.new("RGB", (40, 30), "teal").save(root / "media" / name)
    (root / "media" / "bare.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    (root / "media" / "alt-text.json").write_text("{}", encoding="utf-8")
    (root / "snippets" / "zz2-1.tex").write_text("\\input{nowhere-at-all}\n", encoding="utf-8")
    acme = Path(__file__).resolve().parent / "fixtures" / "template_acme"
    shutil.copytree(acme, root, dirs_exist_ok=True)       # SlideMage_template_acme.tex and schemes/acme/logo.pdf
    for name, template in (("acme", "acme"), ("plain", "slidemage")):
        (root / "decks" / f"{name}.tex").write_text(
            HEAD.format(template=template, calls="\\slide{zz1-EN-One}\n\\slide{zz2-EN-Two}"), encoding="utf-8")
    return ProjectContext.at(root)


@pytest.fixture
def project(tmp_path):
    return make_project(tmp_path)


def deck_of(ctx: ProjectContext, name: str):
    return next(d for d in deck_scan.scan_decks(ctx) if d.name == name)


def export(project, name="acme", dest=None, **kwargs):
    dest = dest or project.root.parent / "out"
    dest.mkdir(exist_ok=True)
    return latex_export.export_deck(project, deck_of(project, name), dest, **kwargs)


def test_export_copies_only_the_decks_dependencies_and_reports_progress(project):
    steps = []
    result = export(project, on_progress=steps.append)
    assert result.folder == project.root.parent / "out" / "acme-latex" and result.missing == []
    names = set(result.files)
    assert {
        "acme.tex", "SlideMage_template_acme.tex", "SlideMage_base.tex", "SlideMage_alt.lua",
        "SlideMage_measure.lua", "SlideMage_setup.tex", "beamerthemeSlideMage.sty", "SlideMage.bib",
        "SlideMage_layout_fira.tex", "schemes/acme/logo.pdf", "snippets/zz2-1.tex", ".latexmkrc",
    } <= names
    assert not any(n.startswith(("decks/", "latex/")) or "gotham" in n.lower() for n in names)
    assert {n for n in names if n.startswith("slides/")} == {
        "slides/zz1-EN-One-current.tex", "slides/zz2-EN-Two-current.tex",
    }
    assert {n for n in names if n.startswith("media/")} == {
        "media/alt-text.json", "media/bare.png", "media/bare.svg", "media/pic-one.png",
    }
    assert names == {p.relative_to(result.folder).as_posix() for p in result.folder.rglob("*") if p.is_file()}
    text = (result.folder / "acme.tex").read_text(encoding="utf-8")
    original = (project.root / "decks" / "acme.tex").read_text(encoding="utf-8")
    assert r"\def\input@path{{./}}" in text and r"\graphicspath{{./}}" in text
    assert text.replace("./", "../") == original
    assert len(steps) == len(names) - 1 and steps[-1].fraction == 1  # .latexmkrc is generated


def test_setups_default_profile_is_the_one_the_export_assumes():
    latex = Path(__file__).resolve().parents[1] / "latex"
    setup = (latex / "SlideMage_setup.tex").read_text(encoding="utf-8")
    assert "\\providecommand{\\SMLayoutProfile}{%s}" % latex_export.DEFAULT_PROFILE in setup
    assert (latex / f"{latex_export.PROFILE_PREFIX}{latex_export.DEFAULT_PROFILE}.tex").is_file()


def add_profile_deck(project, profile_line):
    root = project.root
    (root / "SlideMage_template_mine.tex").write_text(
        profile_line + "\n\\input{SlideMage_setup}\n\\input{SlideMage_base}\n", encoding="utf-8")
    (root / "SlideMage_layout_mine.tex").write_text("\\newcommand{\\SMFontAscender}{0.9}\n", encoding="utf-8")
    (root / "decks" / "own.tex").write_text(
        HEAD.format(template="mine", calls="\\slide{zz1-EN-One}"), encoding="utf-8")


def test_the_profile_a_template_names_comes_along_instead_of_the_default(project):
    add_profile_deck(project, "\\newcommand{\\SMLayoutProfile}{mine}")
    result = export(project, "own")
    assert "SlideMage_layout_mine.tex" in result.files and "SlideMage_layout_fira.tex" not in result.files
    assert result.missing == []


def test_a_deck_on_the_shipped_grayscale_template_gets_it_its_profile_and_the_logo(project):
    root = project.root
    (root / "decks" / "grey.tex").write_text(HEAD.format(template="grayscale", calls="\\slide{zz1-EN-One}"),
                                             encoding="utf-8")
    result = export(project, "grey")
    files = set(result.files)
    assert {"SlideMage_template_grayscale.tex", "SlideMage_layout_lmroman.tex", "slidemage-logo.pdf"} <= files
    assert "SlideMage_layout_fira.tex" not in files and result.missing == []


def test_a_template_without_a_profile_line_gets_the_default_profile(project):
    assert "SlideMage_layout_fira.tex" in set(export(project, "plain").files)


def test_a_profile_the_template_names_but_nobody_has_is_reported(project):
    add_profile_deck(project, "\\def\\SMLayoutProfile{ghost}")
    result = export(project, "own")
    assert "SlideMage_layout_ghost.tex" in result.missing and "SlideMage_layout_fira.tex" not in result.files


def test_a_missing_image_and_a_missing_slide_are_reported_and_the_rest_is_exported(project):
    (project.root / "media" / "pic-one.png").unlink()
    (project.root / "slides" / "zz2-EN-Two-current.tex").unlink()
    result = export(project)
    assert result.missing == ["media/pic-one.png", "slides/zz2-EN-Two-current.tex"]
    assert (result.folder / "slides" / "zz1-EN-One-current.tex").is_file() and (result.folder / "acme.tex").is_file()


def test_copy_and_publish_failures_leave_the_previous_export_intact(project, monkeypatch):
    first = export(project)
    keep = first.folder / "keep.txt"
    keep.write_text("old", encoding="utf-8")

    def broken(source, dest):
        raise OSError("disk full")

    with monkeypatch.context() as fault:
        fault.setattr(latex_export.shutil, "copy2", broken)
        with pytest.raises(OSError, match="disk full"):
            export(project)
        fresh = project.root.parent / "fresh"
        with pytest.raises(OSError, match="disk full"):
            export(project, dest=fresh)
    assert not list(fresh.iterdir()) and keep.read_text(encoding="utf-8") == "old"

    real, denied = os.replace, []
    monkeypatch.setattr(fileio.time, "sleep", lambda _s: None)

    def is_staging(source):
        name = Path(source).name
        return name.startswith(".acme-latex-") and not name.startswith(".acme-latex-old-")

    def busy(source, target):
        if is_staging(source) and len(denied) < 2:
            denied.append(source)
            raise PermissionError("in use")
        real(source, target)

    monkeypatch.setattr(os, "replace", busy)
    export(project)
    assert len(denied) == 2 and not keep.exists()
    assert [p.name for p in first.folder.parent.iterdir()] == ["acme-latex"]
    keep.write_text("old", encoding="utf-8")

    def never(source, target):
        if is_staging(source):
            raise PermissionError("in use")
        real(source, target)

    monkeypatch.setattr(os, "replace", never)
    with pytest.raises(PermissionError):
        export(project)
    assert keep.read_text(encoding="utf-8") == "old"
    assert [p.name for p in first.folder.parent.iterdir()] == ["acme-latex"]


@pytest.mark.skipif(shutil.which("latexmk") is None or shutil.which("lualatex") is None, reason="needs a TeX installation")
def test_the_exported_folder_compiles_on_its_own(project, tmp_path_factory):
    folder = export(project, "plain").folder
    alone = tmp_path_factory.mktemp("alone") / folder.name
    shutil.copytree(folder, alone)
    subprocess.run(["latexmk", "plain.tex"], cwd=alone, capture_output=True, timeout=600,
                   env={k: v for k, v in os.environ.items() if k != "SLIDEMAGE_LATEX"})
    log = (alone / "plain.log").read_text(encoding="utf-8", errors="replace")
    assert not compiler.FATAL_ERROR_RE.search(log)
    with pymupdf.open(alone / "plain.pdf") as pdf:
        assert len(pdf) == 2
        assert "One" in pdf[0].get_text() and "Two" in pdf[1].get_text()


def test_an_archived_deck_exports_its_slideblock_and_dependencies(project):
    project.blocks_dir.mkdir(exist_ok=True)
    block = project.blocks_dir / "topic.tex"
    block.write_text("\\slide{zz1-EN-One}\n\\slide{zz2-EN-Two}\n", encoding="utf-8")
    path = project.decks_dir / "archive" / "linked.tex"
    path.parent.mkdir(exist_ok=True)
    path.write_text(HEAD.format(template="slidemage", calls=r"\slideblock{topic}"), encoding="utf-8")

    result = export(project, "linked")

    assert result.missing == []
    assert {"linked.tex", "blocks/topic.tex", "slides/zz1-EN-One-current.tex", "slides/zz2-EN-Two-current.tex",
            "media/pic-one.png", "media/bare.png", "snippets/zz2-1.tex"} <= set(result.files)
    for name in ("blocks/topic.tex", "slides/zz1-EN-One-current.tex", "slides/zz2-EN-Two-current.tex"):
        assert (result.folder / name).read_bytes() == (project.root / name).read_bytes()
    assert r"\slideblock{topic}" in (result.folder / "linked.tex").read_text(encoding="utf-8")
