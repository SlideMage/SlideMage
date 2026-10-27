# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Export LaTeX (latex_export.py): a deck as a folder that compiles on its own. Works on a copy of the example
project holding two small decks: one with the Uni Graz template, one with the SlideMage template."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pymupdf
import pytest
from PIL import Image

from conftest import EXAMPLE
from slidemage import compiler, deck_scan, latex_export, unused_content
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
    for name, template in (("graz", "uni-graz"), ("plain", "slidemage")):
        (root / "decks" / f"{name}.tex").write_text(
            HEAD.format(template=template, calls="\\slide{zz1-EN-One}\n\\slide{zz2-EN-Two}"), encoding="utf-8")
    return ProjectContext.at(root)


@pytest.fixture
def project(tmp_path):
    return make_project(tmp_path)


def deck_of(ctx: ProjectContext, name: str):
    return next(d for d in deck_scan.scan_decks(ctx) if d.name == name)


def export(project, name="graz", dest=None):
    dest = dest or project.root.parent / "out"
    dest.mkdir(exist_ok=True)
    return latex_export.export_deck(project, deck_of(project, name), dest)


def test_the_folder_holds_the_deck_its_slides_and_only_the_media_they_use(project):
    result = export(project)
    assert result.folder == project.root.parent / "out" / "graz-latex" and result.missing == []
    assert (result.folder / "graz.tex").is_file()
    assert sorted(p.name for p in (result.folder / "slides").iterdir()) == ["zz1-EN-One-current.tex", "zz2-EN-Two-current.tex"]
    # a bare "media/bare" brings the files sharing that stem; a commented-out reference and an unused slide's image stay home
    assert sorted(p.name for p in (result.folder / "media").iterdir()) == ["alt-text.json", "bare.png", "bare.svg", "pic-one.png"]
    assert sorted(result.files) == sorted(
        p.relative_to(result.folder).as_posix() for p in result.folder.rglob("*") if p.is_file())


def test_the_preambles_theme_logo_bib_and_code_files_come_along(project):
    names = set(export(project).files)
    assert {"SlideMage_template_uni-graz.tex", "SlideMage_base.tex", "SlideMage_alt.lua",
            "SlideMage_measure.lua", "SlideMage_setup.tex", "beamerthemeSlideMage.sty", "SlideMage.bib",
            "SlideMage_layout_fira.tex",
            "schemes/scheme_uni_graz/Logo_Uni-Graz_4c-cropped.pdf", "snippets/zz2-1.tex", ".latexmkrc"} <= names
    assert not any(n.startswith(("decks/", "latex/")) for n in names)
    # the deck never names the theme: only SlideMage_setup.tex does, and that is where the export finds it
    deck_text = (project.root / "decks" / "graz.tex").read_text(encoding="utf-8")
    setup = (Path(__file__).resolve().parents[1] / "latex" / "SlideMage_setup.tex").read_text(encoding="utf-8")
    assert "usetheme" not in deck_text and "\\usetheme{SlideMage}" in setup
    assert not any("gotham" in n.lower() for n in names)


def test_setups_default_profile_is_the_one_the_export_assumes():
    latex = Path(__file__).resolve().parents[1] / "latex"
    setup = (latex / "SlideMage_setup.tex").read_text(encoding="utf-8")
    assert "\\providecommand{\\SMLayoutProfile}{%s}" % latex_export.DEFAULT_PROFILE in setup
    assert (latex / f"{latex_export.PROFILE_PREFIX}{latex_export.DEFAULT_PROFILE}.tex").is_file()


def own_profile_project(project, profile_line, template="mine"):
    """The project gets a template that names a layout profile (one in its root, unless the name is a ghost) and a deck."""
    root = project.root
    (root / f"SlideMage_template_{template}.tex").write_text(
        profile_line + "\n\\input{SlideMage_setup}\n\\input{SlideMage_base}\n", encoding="utf-8")
    (root / "SlideMage_layout_mine.tex").write_text("\\newcommand{\\SMFontAscender}{0.9}\n", encoding="utf-8")
    (root / "decks" / "own.tex").write_text(
        HEAD.format(template=template, calls="\\slide{zz1-EN-One}"), encoding="utf-8")
    return ProjectContext.at(root)


def test_the_profile_a_template_names_comes_along_instead_of_the_default(project):
    project = own_profile_project(project, "\\newcommand{\\SMLayoutProfile}{mine}")
    result = export(project, "own")
    assert "SlideMage_layout_mine.tex" in result.files and "SlideMage_layout_fira.tex" not in result.files
    assert result.missing == []


def test_a_template_without_a_profile_line_gets_the_default_profile(project):
    assert "SlideMage_layout_fira.tex" in set(export(project, "plain").files)


def test_a_profile_the_template_names_but_nobody_has_is_reported(project):
    project = own_profile_project(project, "\\def\\SMLayoutProfile{ghost}")
    result = export(project, "own")
    assert "SlideMage_layout_ghost.tex" in result.missing and "SlideMage_layout_fira.tex" not in result.files


def test_a_file_shown_as_code_is_copied_but_not_read_for_references(project):
    result = export(project)
    assert "snippets/zz2-1.tex" in result.files and "nowhere-at-all" not in result.missing


def test_the_decks_path_lines_point_at_the_folder_itself(project):
    folder = export(project).folder
    text = (folder / "graz.tex").read_text(encoding="utf-8")
    assert "\\def\\input@path{{./}}" in text and "\\graphicspath{{./}}" in text and "../" not in text
    assert text.replace("./", "../") == (project.root / "decks" / "graz.tex").read_text(encoding="utf-8")


def test_a_missing_image_and_a_missing_slide_are_reported_and_the_rest_is_exported(project):
    (project.root / "media" / "pic-one.png").unlink()
    (project.root / "slides" / "zz2-EN-Two-current.tex").unlink()
    result = export(project)
    assert result.missing == ["media/pic-one.png", "slides/zz2-EN-Two-current.tex"]
    assert (result.folder / "slides" / "zz1-EN-One-current.tex").is_file() and (result.folder / "graz.tex").is_file()


def test_an_existing_folder_is_replaced(project):
    first = export(project)
    (first.folder / "stale.txt").write_text("old", encoding="utf-8")
    second = export(project)
    assert second.folder == first.folder and not (second.folder / "stale.txt").exists()
    assert (second.folder / "graz.tex").is_file()
    assert [p.name for p in second.folder.parent.iterdir()] == ["graz-latex"]


def test_a_failure_leaves_no_half_written_folder_and_the_old_one_alone(project, monkeypatch):
    first = export(project)
    (first.folder / "keep.txt").write_text("old", encoding="utf-8")

    def broken(source, dest):
        raise OSError("disk full")

    monkeypatch.setattr(latex_export.shutil, "copy2", broken)
    with pytest.raises(OSError):
        export(project)
    assert [p.name for p in first.folder.parent.iterdir()] == ["graz-latex"]
    assert (first.folder / "keep.txt").read_text(encoding="utf-8") == "old"
    fresh = project.root.parent / "fresh"
    fresh.mkdir()
    with pytest.raises(OSError):
        export(project, dest=fresh)
    assert list(fresh.iterdir()) == []


def test_a_rename_windows_denies_for_a_moment_is_tried_again_and_one_it_keeps_denying_keeps_the_old_folder(
        project, monkeypatch):
    first = export(project)
    (first.folder / "keep.txt").write_text("old", encoding="utf-8")
    real, denied = os.replace, []
    monkeypatch.setattr(latex_export.time, "sleep", lambda _s: None)

    def busy(source, target):                           # a scanner holds the new folder for two tries
        if Path(source).name.startswith(".graz-latex-") and len(denied) < 2:
            denied.append(source)
            raise PermissionError("in use")
        real(source, target)

    monkeypatch.setattr(latex_export.os, "replace", busy)
    export(project)
    assert len(denied) == 2 and not (first.folder / "keep.txt").exists()
    assert [p.name for p in first.folder.parent.iterdir()] == ["graz-latex"]
    (first.folder / "keep.txt").write_text("old", encoding="utf-8")

    def never(source, target):                          # up to v8.51.0 the old folder was deleted before this
        if Path(source).name.startswith(".graz-latex-") and not Path(source).name.startswith(".graz-latex-old-"):
            raise PermissionError("in use")
        real(source, target)

    monkeypatch.setattr(latex_export.os, "replace", never)
    with pytest.raises(PermissionError):
        export(project)
    assert (first.folder / "keep.txt").read_text(encoding="utf-8") == "old"
    assert [p.name for p in first.folder.parent.iterdir()] == ["graz-latex"]


def test_the_slide_and_media_scans_are_the_ones_that_archive_unused_content(project):
    result = export(project)
    exported = {Path(f).name for f in result.files if f.startswith(("slides/", "media/"))}
    kept = unused_content.find_used_slide_filenames(project) | unused_content.find_used_media_filenames(project)
    assert exported == kept | {"alt-text.json"}


@pytest.mark.skipif(shutil.which("latexmk") is None or shutil.which("lualatex") is None, reason="needs a TeX installation")
def test_the_exported_folder_compiles_on_its_own(project, tmp_path_factory):
    """The folder is copied away from the project and the framework: nothing but the TeX distribution is around it."""
    folder = export(project, "plain").folder
    alone = tmp_path_factory.mktemp("alone") / folder.name
    shutil.copytree(folder, alone)
    started = time.monotonic()
    subprocess.run(["latexmk", "plain.tex"], cwd=alone, capture_output=True, timeout=600,
                   env={k: v for k, v in os.environ.items() if k != "SLIDEMAGE_LATEX"})
    print(f"latexmk: {time.monotonic() - started:.1f} s")
    log = (alone / "plain.log").read_text(encoding="utf-8", errors="replace")
    assert not compiler.FATAL_ERROR_RE.search(log)
    with pymupdf.open(alone / "plain.pdf") as pdf:
        assert len(pdf) == 2
        assert "One" in pdf[0].get_text() and "Two" in pdf[1].get_text()
