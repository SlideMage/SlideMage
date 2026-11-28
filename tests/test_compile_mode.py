# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""One-off color mode overrides, output names and PDF discovery."""
from __future__ import annotations

from dataclasses import replace

from slidemage import compiler, deck_scan
from slidemage.project import ProjectContext

DARK = "\\newcommand{\\SMModeOverride}{dark}"
GREY = "\\newcommand{\\SMModeOverride}{gray}"
DOC = ("\\documentclass{beamer}\n\\input{SlideMage_template_acme}\n"
       "% SlideMage view themes: after-course=acme:dark\n"
       "\\begin{document}\n\\slide{aaa-EN-One}\n\\end{document}\n")


def _deck(tmp_path, text=DOC):
    (tmp_path / "SlideMage_template_acme.tex").write_text("% SlideMage modes: light, dark=Dark slides, gray\n")
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
    gray = compiler.wrapper_text(ctx, replace(after, mode="gray"))
    assert GREY in gray and DARK not in gray
    assert deck.path.read_text() == DOC                                            # the deck is not touched


def test_a_file_name_for_all_outputs_gets_the_ending_of_each_version_and_the_presenter_pdf(tmp_path):
    ctx = ProjectContext.at(tmp_path)
    text = DOC.replace("\\begin{document}", "\\deckoutputfolder{D:/Out/Handout.pdf}\n\\begin{document}")
    named = _deck(tmp_path, text)
    stems = [compiler.resolve_output_location(ctx, job)[1] for job in (
        compiler.CompileJob(named, "instructor", None), compiler.CompileJob(named, "after-course", None),
        compiler.CompileJob(named, "instructor", None, presenter=True))]
    assert stems == ["Handout-instructor", "Handout-after-course", "Handout-instructor-presenter"]
    own = _deck(tmp_path, text.replace("\\deckoutputfolder{", "\\deckoutputfolder[after-course]{"))
    assert compiler.resolve_output_location(ctx, compiler.CompileJob(own, "after-course", None))[1] == "Handout"


def test_other_modes_leave_out_the_one_the_view_compiles_in(tmp_path):
    deck = _deck(tmp_path)
    ctx = ProjectContext.at(tmp_path)
    assert compiler.other_modes(ctx, deck, "instructor") == [("dark", "Dark slides"), ("gray", "Gray")]
    assert compiler.other_modes(ctx, deck, "after-course") == [("light", "Light"), ("gray", "Gray")]
    (tmp_path / "SlideMage_template_acme.tex").write_text("\\input{SlideMage_setup}\n")      # declares no modes
    assert compiler.other_modes(ctx, deck, "instructor") == []


def test_one_off_modes_have_distinct_outputs_and_appear_in_the_pdf_list(tmp_path):
    deck = _deck(tmp_path)
    ctx = ProjectContext.at(tmp_path)
    ctx.pdf_dir.mkdir(parents=True, exist_ok=True)
    job = compiler.CompileJob(deck, "instructor", None)
    dark = replace(job, mode="dark")
    assert compiler.resolve_output_location(ctx, dark) == (ctx.pdf_dir, "course-instructor-dark")
    listing_job = replace(job, version="instructor" if deck.supports_version else None)
    for output in (listing_job, replace(listing_job, mode="dark")):
        (ctx.pdf_dir / f"{output.jobname}.pdf").write_bytes(b"%PDF-1.4\n")
    labels = {pdf.label for pdf in compiler.deck_pdfs(ctx, deck)}
    assert labels == {"Instructor", "Instructor · dark colors"}

    named = _deck(tmp_path, DOC.replace("\\begin{document}", "\\deckoutputfolder{D:/Out/Handout.pdf}\n\\begin{document}"))
    job = compiler.CompileJob(named, "instructor", None)
    folder, stem = compiler.resolve_output_location(ctx, replace(job, mode="dark"))
    assert stem == "Handout-instructor-dark" and folder.name == "Out"
    assert compiler.resolve_output_location(ctx, job)[1] == "Handout-instructor"


def test_a_file_name_for_all_outputs_names_each_versions_transcript_and_ignores_its_extension(tmp_path):
    from slidemage import transcript
    ctx = ProjectContext.at(tmp_path)
    text = DOC.replace("\\begin{document}", "\\deckoutputfolder{D:/Out/Handout.pdf}\n\\begin{document}")
    deck = replace(_deck(tmp_path, text), supports_version=True)
    folder, stem = transcript.resolve_transcript_location(ctx, deck, deck.path, "after-course")
    assert folder.name == "Out" and stem == "Handout-after-course"
    own = replace(deck, output_folders={"transcript": "D:/Out/Notes.html"})
    assert transcript.resolve_transcript_location(ctx, own, deck.path, "after-course")[1] == "Notes"
