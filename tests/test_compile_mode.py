# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""A one-off colour mode for a build (v0.16.4, Compile -> "Current view in another colour mode"): the wrapper writes
the mode, the PDF gets its own name, the deck's PDF list finds it, and the deck is not touched (no TeX)."""
from __future__ import annotations

from dataclasses import replace

from slidemage import compiler, deck_scan
from slidemage.project import ProjectContext

DARK = "\\newcommand{\\SMModeOverride}{dark}"
GREY = "\\newcommand{\\SMModeOverride}{grey}"
DOC = ("\\documentclass{beamer}\n\\input{SlideMage_template_acme}\n"
       "% SlideMage view themes: after-course=acme:dark\n"
       "\\begin{document}\n\\slide{aaa-EN-One}\n\\end{document}\n")


def _deck(tmp_path, text=DOC):
    (tmp_path / "SlideMage_template_acme.tex").write_text("% SlideMage modes: light, dark=Dark slides, grey\n")
    (tmp_path / "decks").mkdir(exist_ok=True)
    (tmp_path / "slides").mkdir(exist_ok=True)
    path = tmp_path / "decks" / "course.tex"
    path.write_text(text)
    return next(d for d in deck_scan.scan_dir(path.parent, False) if d.path == path)


def test_the_wrapper_writes_the_one_off_mode_and_the_base_mode_removes_it(tmp_path):
    deck = _deck(tmp_path)
    ctx = ProjectContext.at(tmp_path)
    job = compiler.CompileJob(deck, "instructor", None)
    assert "SMModeOverride" not in compiler.wrapper_text(ctx, job)                 # the deck's own: light
    dark = compiler.wrapper_text(ctx, replace(job, mode="dark"))
    assert DARK in dark and dark.index(DARK) < dark.index("\\input{SlideMage_template_acme}")
    after = replace(job, version="after-course")
    assert DARK in compiler.wrapper_text(ctx, after)                              # the view's own mode
    light = compiler.wrapper_text(ctx, replace(after, mode="light"))               # the base: no override
    assert "SMModeOverride" not in light and "SlideMage_template_acme" in light
    grey = compiler.wrapper_text(ctx, replace(after, mode="grey"))
    assert GREY in grey and DARK not in grey
    assert deck.path.read_text() == DOC                                            # the deck is not touched


def test_a_one_off_mode_gets_its_own_pdf_name_and_label(tmp_path):
    deck = _deck(tmp_path)
    ctx = ProjectContext.at(tmp_path)
    job = compiler.CompileJob(deck, "instructor", None, mode="dark")
    assert job.jobname == "course-instructor-dark"
    assert compiler.job_label(job) == "Instructor · dark colours"
    assert compiler.resolve_output_location(ctx, job) == (ctx.pdf_dir, "course-instructor-dark")
    named = _deck(tmp_path, DOC.replace("\\begin{document}", "\\deckoutputfolder{D:/Out/Handout.pdf}\n\\begin{document}"))
    folder, stem = compiler.resolve_output_location(ctx, compiler.CompileJob(named, "instructor", None, mode="dark"))
    assert stem == "Handout-dark" and folder.name == "Out"                         # a fixed file name keeps apart too
    assert compiler.resolve_output_location(ctx, compiler.CompileJob(named, "instructor", None))[1] == "Handout"


def test_other_modes_leave_out_the_one_the_view_compiles_in(tmp_path):
    deck = _deck(tmp_path)
    ctx = ProjectContext.at(tmp_path)
    assert compiler.other_modes(ctx, deck, "instructor") == [("dark", "Dark slides"), ("grey", "Grey")]
    assert compiler.other_modes(ctx, deck, "after-course") == [("light", "Light"), ("grey", "Grey")]
    (tmp_path / "SlideMage_template_acme.tex").write_text("\\input{SlideMage_setup}\n")      # declares no modes
    assert compiler.other_modes(ctx, deck, "instructor") == []


def test_the_decks_pdf_list_finds_a_one_off_mode_pdf(tmp_path):
    deck = _deck(tmp_path)
    ctx = ProjectContext.at(tmp_path)
    ctx.pdf_dir.mkdir(parents=True, exist_ok=True)
    version = "instructor" if deck.supports_version else None
    for mode in (None, "dark"):
        name = compiler.CompileJob(deck, version, None, mode=mode).jobname
        (ctx.pdf_dir / f"{name}.pdf").write_bytes(b"%PDF-1.4\n")
    labels = {pdf.label for pdf in compiler.deck_pdfs(ctx, deck)}
    assert labels == {"Instructor", "Instructor · dark colours"}
