# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""View theme settings and their effect on compilation and render keys."""
from __future__ import annotations

from dataclasses import replace

from slidemage import compiler, deck_scan, deck_settings, preview_target, render_key, view_themes
from slidemage.project import ProjectContext

LINE = "% SlideMage view themes: instructor=uni-graz:dark, after-course=mci\n"
PREAMBLE = "\\documentclass{beamer}\n\\input{SlideMage_template_slidemage}\n" + LINE
DOC = PREAMBLE + "\\begin{document}\n\\slide{aaa-EN-One}\n\\end{document}\n"
DARK = "\\newcommand{\\SMModeOverride}{dark}"


def test_the_line_is_read_and_written():
    assert view_themes.parse(DOC) == {"instructor": ("uni-graz", "dark"), "after-course": ("mci", "")}
    entries = {"during-course": ("a-b", ""), "instructor": ("x", "dark"), "bogus": ("y", "")}
    written = view_themes.set_entries(DOC, entries)
    assert view_themes.parse(written) == {"during-course": ("a-b", ""), "instructor": ("x", "dark")}
    assert written.count("view themes") == 1 and written.index("view themes") < written.index("\\begin{document}")
    assert view_themes.set_entries(DOC, {}) == DOC.replace(LINE, "")
    text = ("% SlideMage view themes: instructor=, weird=x, after-course=a b, during-course=ok:dark mode\n"
            "\\begin{document}\n")
    assert view_themes.parse(text) == {}


def test_an_entry_without_mode_turns_a_dark_default_off():
    text = (DARK + "\n\\input{SlideMage_template_g}\n% SlideMage view themes: after-course=g\n"
            "\\begin{document}\n")
    assert "SMModeOverride" not in view_themes.preamble_for_view(text, "after-course")
    assert "SMModeOverride" in view_themes.preamble_for_view(text, "instructor")


def test_compile_wrappers_and_render_units_use_the_view_theme(tmp_path):
    decks = tmp_path / "decks"
    decks.mkdir()
    (tmp_path / "slides").mkdir()
    (decks / "course.tex").write_text(DOC, encoding="utf-8")
    deck, = deck_scan.scan_dir(decks, False)
    ctx = ProjectContext.at(tmp_path)
    job = compiler.CompileJob(deck, "instructor", None)
    target = preview_target.PreviewTarget(ctx, "slide", "aaa-EN-One", None, None, None, 1, deck.preamble_text, deck=deck)
    units = []
    for view, theme, dark in (("instructor", "uni-graz", True), ("during-course", "slidemage", False),
                              ("after-course", "mci", False)):
        wrapper = compiler.wrapper_text(ctx, replace(job, version=view))
        assert f"\\input{{SlideMage_template_{theme}}}" in wrapper
        assert (DARK in wrapper) == dark
        unit = render_key.unit_for(target, view, "EN")
        assert unit.template == theme
        units.append(unit)
    assert len({unit.preamble_text for unit in units}) == 3
    assert view_themes.templates_used(deck.preamble_text) == {unit.template for unit in units}


def test_deck_settings_read_and_write_the_entries():
    old = deck_settings.read_settings(DOC)
    assert old.view_themes == {"instructor": ("uni-graz", "dark"), "after-course": ("mci", "")}
    new = deck_settings.from_form(
        old, template=old.template, language=old.language, footer_text="", output_folders={},
        appendix_toc=False, open_pdf="instructor", view_themes={"during-course": ("mci", "")})
    text = deck_settings.apply_settings(DOC, old, new)
    assert deck_settings.read_settings(text).view_themes == {"during-course": ("mci", "")}
    assert deck_settings.apply_settings(DOC, old, old) == DOC
    kept = deck_settings.from_form(old, template=old.template, language=old.language, footer_text="",
                                   output_folders={}, appendix_toc=False, open_pdf="instructor")
    assert kept.view_themes == old.view_themes
