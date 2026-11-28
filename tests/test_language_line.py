# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Project languages in TeX wrappers, preview variants and render keys."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from slidemage import compiler, deck_language, deck_scan, dep_hash, languages, partial_compile, preview_build
from slidemage import render_key, render_store, slide_preview
from slidemage.project import ProjectContext
from slidemage.render_key import Unit

DECK = ("\\documentclass{beamer}\n\\begin{document}\n\\section{One}\n\\slide{1aa-EN-A}\n\\end{document}\n")
ALL_STEPS = ("\\makeatletter\n\\pretocmd{\\beamer@doseveralframes}{\\gdef\\beamer@whichframes{1-}}{}"
             "{\\PackageError{SlideMage}{Cannot select all preview overlays}{}}\n\\makeatother\n")
HEAD = "\\def\\deckversionoverride{instructor}\n"

@pytest.fixture
def ctx(tmp_path):
    root = tmp_path / "Proj"
    (root / "decks").mkdir(parents=True)
    (root / "slides").mkdir()
    (root / "decks" / "t-D.tex").write_text(DECK, encoding="utf-8", newline="")
    (root / "slides" / "1aa-EN-A-current.tex").write_text("x\n", encoding="utf-8")
    return ProjectContext.at(root)


def test_compile_and_preview_wrappers_write_the_language_lines(ctx):
    languages.set_project_languages(ctx, "en", ["de", "fr"])
    deck = deck_scan.scan_dir(ctx.decks_dir, False)[0]
    project_line = "\\SMProjectLanguages[en]{EN,DE,FR}\n"
    for language, extra in ((None, ""), ("fr", "\\decklanguage[fr]\n\\SMPdfLang{fr-FR}\n")):
        job = compiler.CompileJob(deck, "instructor", None, language=language)
        plan = partial_compile.PartialPlan(ctx, job, [], [], [], Path("full.pdf"), Path("full.aux"), {})
        head = HEAD + ("\\def\\decklanguageoverride{fr}\n" if language else "")
        preamble = head + "\\documentclass{beamer}\n\\begin{document}\n" + project_line + extra
        assert compiler.wrapper_text(ctx, job) == preamble + "\n\n\\section{One}\n\\slide{1aa-EN-A}\n\\end{document}\n\n"
        assert partial_compile.wrapper_text(plan) == preamble + "\n\\section{One}\n\\end{document}\n"

    lines = project_line + "\\decklanguage[de]\n"
    assert calls_wrapper(ctx) == "PRE\n\\deckversion[instructor]\n" + lines + (
        "\\setcounter{framenumber}{2}\n\t\\slide{1aa-EN-A}\n\\end{document}\n")
    assert text_wrapper(ctx) == "PRE\n" + ALL_STEPS + "\\deckversion[instructor]\n" + lines + "BODY\n\\end{document}\n"


def calls_wrapper(ctx):
    return slide_preview._wrapper_text(ctx, "PRE\n", "instructor", "de", [(3, r"\slide{1aa-EN-A}")])


def text_wrapper(ctx):
    return slide_preview._text_wrapper(ctx, "PRE\n", "instructor", "de", "BODY\n", all_steps=True)


@pytest.mark.infer_languages
def test_the_lines_of_a_project_without_a_key_follow_what_it_uses():
    ctx = ProjectContext.at(Path("/nonexistent/project"))
    assert deck_language.language_lines(ctx, "DE") == "\\SMProjectLanguages[en]{EN}\n\\decklanguage[de]\n"
    assert deck_language.language_lines(ctx, None) == "\\SMProjectLanguages[en]{EN}\n"


def test_the_decks_own_language_gets_its_pdf_tag_without_an_override(ctx):
    languages.set_project_languages(ctx, "en", ["de", "fr"])
    assert deck_language.language_lines(ctx, None, deck="fr") == "\\SMProjectLanguages[en]{EN,DE,FR}\n\\SMPdfLang{fr-FR}\n"
    assert deck_language.language_lines(ctx, None, deck="de") == "\\SMProjectLanguages[en]{EN,DE,FR}\n"
    assert deck_language.language_lines(ctx, "en", deck="fr") == "\\SMProjectLanguages[en]{EN,DE,FR}\n\\decklanguage[en]\n"


def test_preview_build_folder_follows_project_languages_and_main_language(ctx):
    def variant(text):
        return preview_build.view_variant("\\begin{document}\n" + text)

    variants = []
    for main, secondary in (("en", ["de"]), ("en", ["de", "fr"]), ("de", ["en", "fr"])):
        languages.set_project_languages(ctx, main, secondary)
        calls, text = variant(calls_wrapper(ctx)), variant(text_wrapper(ctx))
        assert calls == text
        variants.append(calls)
    assert variants[0] == "\\deckversion[instructor]|\\SMProjectLanguages[en]{EN,DE}|\\decklanguage[de]"
    assert len(set(variants)) == 3
    languages.set_project_languages(ctx, "de", ["en", "no"])
    assert variant(deck_language.language_lines(ctx, "no") + r"\setSlideID{x}") == (
        "\\SMProjectLanguages[de]{DE,EN,NO}|\\decklanguage[no]|\\SMPdfLang{nb-NO}")


@pytest.fixture
def resolver(ctx, tmp_path):
    store = render_store.RenderStore(ctx, tmp_path / "local")
    yield render_key.Resolver(ctx, dep_hash.HashCache(store.db, store.lock), store, engine_fp=lambda: "LuaHBTeX 1.22|Linux")
    store.close()


def unit_for(ctx, language="DE"):
    path = ctx.slides_dir / "aaa-EN-One-current.tex"
    path.write_text("slide\n", encoding="utf-8")
    os.utime(path, (time.time() - 3600,) * 2)
    return Unit("deck1", "slide", "aaa-EN-One", None, (), "instructor", language, 3,
                "\\documentclass{beamer}\n\\begin{document}", "acme", path)


def test_render_key_uses_inferred_languages_and_tracks_language_changes(ctx, resolver):
    unit = unit_for(ctx)                                               # an English slide only
    inferred = resolver.fast_key(unit)
    assert not (ctx.root / ".slidemage" / "project.json").exists()
    languages.migrate(ctx)
    assert resolver.fast_key(unit) == inferred

    keys = []
    for main, secondary in (("en", []), ("en", ["de"]), ("en", ["de", "fr"]), ("de", ["en", "fr"]), ("en", ["de", "fr", "it"])):
        languages.set_project_languages(ctx, main, secondary)
        keys.append(resolver.fast_key(unit))
    assert len(set(keys)) == 5
    languages.set_project_languages(ctx, "en", ["de", "fr"])
    assert resolver.fast_key(unit) == keys[2]                          # and back
