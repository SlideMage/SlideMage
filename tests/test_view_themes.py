# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Themes per view: the settings line, the preamble each view sees, and the places that use it (no TeX)."""
from __future__ import annotations

from dataclasses import replace

from slidemage import compiler, deck_scan, preview_target, render_key, view_themes
from slidemage.project import ProjectContext

LINE = "% SlideMage view themes: instructor=uni-graz:dark, after-course=mci\n"
PREAMBLE = "\\documentclass{beamer}\n\\input{SlideMage_template_slidemage}\n" + LINE
DOC = PREAMBLE + "\\begin{document}\n\\slide{aaa-EN-One}\n\\end{document}\n"
DARK = "\\newcommand{\\SMDarkMode}{}"


def test_the_line_is_read_and_written():
    assert view_themes.parse(DOC) == {"instructor": ("uni-graz", "dark"), "after-course": ("mci", "")}
    entries = {"during-course": ("a-b", ""), "instructor": ("x", "dark"), "bogus": ("y", "")}
    written = view_themes.set_entries(DOC, entries)
    assert view_themes.parse(written) == {"during-course": ("a-b", ""), "instructor": ("x", "dark")}
    assert written.count("view themes") == 1 and written.index("view themes") < written.index("\\begin{document}")
    assert view_themes.set_entries(DOC, {}) == DOC.replace(LINE, "")


def test_malformed_entries_and_unknown_views_are_ignored():
    text = ("% SlideMage view themes: instructor=, weird=x, after-course=a b, during-course=ok:dark mode\n"
            "\\begin{document}\n")
    assert view_themes.parse(text) == {}


def test_a_view_sees_its_own_template_and_dark_switch():
    preamble = PREAMBLE
    instructor = view_themes.preamble_for_view(preamble, "instructor")
    assert "\\input{SlideMage_template_uni-graz}" in instructor and DARK in instructor
    assert view_themes.template_for(preamble, "after-course") == "mci"
    assert "SMDarkMode" not in view_themes.preamble_for_view(preamble, "after-course")
    assert view_themes.preamble_for_view(preamble, "during-course") == preamble      # no entry: the deck's own
    assert view_themes.template_for(preamble, "during-course") == "slidemage"
    assert view_themes.templates_used(preamble) == {"slidemage", "uni-graz", "mci"}
    assert view_themes.preamble_for_view(instructor, "instructor") == instructor     # idempotent


def test_an_entry_without_mode_turns_a_dark_default_off():
    text = (DARK + "\n\\input{SlideMage_template_g}\n% SlideMage view themes: after-course=g\n"
            "\\begin{document}\n")
    assert "SMDarkMode" not in view_themes.preamble_for_view(text, "after-course")
    assert "SMDarkMode" in view_themes.preamble_for_view(text, "instructor")


def test_a_deck_without_the_line_or_a_template_input_is_untouched():
    assert view_themes.preamble_for_view("\\begin{document}\n", "instructor") == "\\begin{document}\n"
    assert view_themes.preamble_for_view(None, "instructor") is None
    bare = "% SlideMage view themes: instructor=a\n\\begin{document}\n"
    assert view_themes.preamble_for_view(bare, "instructor") == bare


def _deck(tmp_path, text):
    (tmp_path / "decks").mkdir(exist_ok=True)
    (tmp_path / "slides").mkdir(exist_ok=True)
    path = tmp_path / "decks" / "course.tex"
    path.write_text(text)
    return next(d for d in deck_scan.scan_dir(path.parent, False) if d.path == path)


def test_the_wrapper_inlines_the_view_preamble_only_for_a_mapped_view(tmp_path):
    d = _deck(tmp_path, DOC)
    ctx = ProjectContext.at(tmp_path)
    job = compiler.CompileJob(d, "instructor", None)
    mapped = compiler.wrapper_text(ctx, job)
    assert "\\input{SlideMage_template_uni-graz}" in mapped and DARK in mapped
    unmapped = compiler.wrapper_text(ctx, replace(job, version="during-course"))
    assert "\\input{SlideMage_template_slidemage}" in unmapped and "SMDarkMode" not in unmapped
    after = compiler.wrapper_text(ctx, replace(job, version="after-course"))
    assert "SlideMage_template_mci" in after and "SMDarkMode" not in after


def test_units_of_views_with_different_themes_differ(tmp_path):
    d = _deck(tmp_path, DOC)
    ctx = ProjectContext.at(tmp_path)
    target = preview_target.PreviewTarget(ctx, "slide", "aaa-EN-One", None, None, None, 1, d.preamble_text, deck=d)
    units = {v: render_key.unit_for(target, v, "EN") for v in ("instructor", "during-course", "after-course")}
    assert [u.template for u in units.values()] == ["uni-graz", "slidemage", "mci"]
    assert len({u.preamble_text for u in units.values()}) == 3


def test_deck_settings_read_and_write_the_entries():
    from slidemage import deck_settings
    old = deck_settings.read_settings(DOC)
    assert old.view_themes == {"instructor": ("uni-graz", "dark"), "after-course": ("mci", "")}
    new = deck_settings.from_form(
        old, template=old.template, language=old.language, footer_text="", output_folders={},
        appendix_toc=False, open_pdf="instructor", view_themes={"during-course": ("mci", "")})
    text = deck_settings.apply_settings(DOC, old, new)
    assert deck_settings.read_settings(text).view_themes == {"during-course": ("mci", "")}
    assert deck_settings.apply_settings(DOC, old, old) == DOC
    # a form that does not pass entries (a deck without views) keeps them
    kept = deck_settings.from_form(old, template=old.template, language=old.language, footer_text="",
                                   output_folders={}, appendix_toc=False, open_pdf="instructor")
    assert kept.view_themes == old.view_themes
