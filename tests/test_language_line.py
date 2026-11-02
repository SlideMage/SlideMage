# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The language lines of a compile and a preview wrapper (deck_language.language_lines).

A project without its own languages gets exactly the wrappers it always got: the GOLDEN texts below are what
develop (v0.13.23, `language_line` and `_deck_language_line`) wrote. A project with its own languages gets
`\\SMProjectLanguages` (and `\\SMPdfLang`) as well, which changes the preview's build folder and render key."""
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
OVERLAY = ("\\makeatletter\n\\pretocmd{\\beamer@doseveralframes}{\\gdef\\beamer@whichframes{2}}{}"
           "{\\PackageError{SlideMage}{Cannot select preview overlay}{}}\n"
           "\\pretocmd{\\beamer@autobreakframe}{\\PackageError{SlideMage}{Overlay preview does not support "
           "allowframebreaks}{Use all overlays}}{}{\\PackageError{SlideMage}{Cannot validate preview overlay}{}}\n"
           "\\makeatother\n")
ALL_STEPS = ("\\makeatletter\n\\pretocmd{\\beamer@doseveralframes}{\\gdef\\beamer@whichframes{1-}}{}"
             "{\\PackageError{SlideMage}{Cannot select all preview overlays}{}}\n\\makeatother\n")
HEAD = "\\def\\deckversionoverride{instructor}\n"

GOLDEN = {
    "compile None": HEAD + "\\input{t-D.tex}\n",
    "partial None": HEAD + "\\documentclass{beamer}\n\\begin{document}\n\\section{One}\n\\end{document}\n",
    "compile de": (HEAD + "\\def\\decklanguageoverride{de}\n\\documentclass{beamer}\n\\begin{document}\n\\decklanguage[de]\n\n\n"
                   "\\section{One}\n\\slide{1aa-EN-A}\n\\end{document}\n\n"),
    "partial de": (HEAD + "\\def\\decklanguageoverride{de}\n\\documentclass{beamer}\n\\begin{document}\n\\decklanguage[de]\n\n"
                   "\\section{One}\n\\end{document}\n"),
    "compile fr": (HEAD + "\\def\\decklanguageoverride{fr}\n\\documentclass{beamer}\n\\begin{document}\n\\decklanguage[fr]\n\n\n"
                   "\\section{One}\n\\slide{1aa-EN-A}\n\\end{document}\n\n"),
    "partial fr": (HEAD + "\\def\\decklanguageoverride{fr}\n\\documentclass{beamer}\n\\begin{document}\n\\decklanguage[fr]\n\n"
                   "\\section{One}\n\\end{document}\n"),
    "calls None": "PRE\n\\deckversion[instructor]\n" + OVERLAY + "\\setcounter{framenumber}{2}\n\t\\slide{1aa-EN-A}\n\\end{document}\n",
    "calls de": ("PRE\n\\deckversion[instructor]\n\\decklanguage[de]\n" + OVERLAY
                 + "\\setcounter{framenumber}{2}\n\t\\slide{1aa-EN-A}\n\\end{document}\n"),
    "text None": "PRE\n" + ALL_STEPS + "\\deckversion[instructor]\nBODY\n\\end{document}\n",
    "text de": "PRE\n" + ALL_STEPS + "\\deckversion[instructor]\n\\decklanguage[de]\nBODY\n\\end{document}\n",
}


@pytest.fixture
def ctx(tmp_path):
    root = tmp_path / "Proj"
    (root / "decks").mkdir(parents=True)
    (root / "slides").mkdir()
    (root / "decks" / "t-D.tex").write_text(DECK, encoding="utf-8", newline="")
    (root / "slides" / "1aa-EN-A-current.tex").write_text("x\n", encoding="utf-8")
    return ProjectContext.at(root)


def wrappers(ctx) -> dict[str, str]:
    """Every kind of wrapper, keyed like GOLDEN."""
    deck = deck_scan.scan_dir(ctx.decks_dir, False)[0]
    out = {}
    for language in (None, "de", "fr"):
        job = compiler.CompileJob(deck, "instructor", None, language=language)
        out[f"compile {language}"] = compiler.wrapper_text(ctx, job)
        plan = partial_compile.PartialPlan(ctx, job, [], [], [], Path("full.pdf"), Path("full.aux"), {})
        out[f"partial {language}"] = partial_compile.wrapper_text(plan)
    for language in (None, "de"):
        out[f"calls {language}"] = slide_preview._wrapper_text(
            ctx, "PRE\n", "instructor", language, [(3, "\\slide{1aa-EN-A}")], overlay=2)
        out[f"text {language}"] = slide_preview._text_wrapper(ctx, "PRE\n", "instructor", language, "BODY\n", all_steps=True)
    return out


def test_a_default_projects_wrappers_are_what_develop_wrote(ctx):
    assert languages.is_default(ctx)
    assert wrappers(ctx) == GOLDEN


def test_a_project_that_wrote_out_english_and_german_is_still_the_default(ctx):
    languages.set_project_languages(ctx, "en", ["de"])
    assert wrappers(ctx) == GOLDEN


def test_the_lines_of_a_default_project():
    ctx = ProjectContext.at(Path("/nonexistent/project"))
    assert deck_language.language_lines(ctx, "DE") == "\\decklanguage[de]\n"
    assert deck_language.language_lines(ctx, "fr") == "\\decklanguage[fr]\n"        # no PDF tag line: as before
    assert deck_language.language_lines(ctx, None) == ""


def test_the_lines_of_a_project_with_its_own_languages(ctx):
    languages.set_project_languages(ctx, "en", ["de", "fr"])
    assert deck_language.language_lines(ctx, None) == "\\SMProjectLanguages[en]{EN,DE,FR}\n"
    assert deck_language.language_lines(ctx, "en") == "\\SMProjectLanguages[en]{EN,DE,FR}\n\\decklanguage[en]\n"
    assert deck_language.language_lines(ctx, "FR") == (
        "\\SMProjectLanguages[en]{EN,DE,FR}\n\\decklanguage[fr]\n\\SMPdfLang{fr-FR}\n")
    languages.set_project_languages(ctx, "de", ["en", "no"])
    assert deck_language.language_lines(ctx, "no") == (
        "\\SMProjectLanguages[de]{DE,EN,NO}\n\\decklanguage[no]\n\\SMPdfLang{nb-NO}\n")
    assert deck_language.language_lines(ctx, "de") == "\\SMProjectLanguages[de]{DE,EN,NO}\n\\decklanguage[de]\n"


def test_a_project_with_its_own_languages_tells_every_wrapper_about_them(ctx):
    languages.set_project_languages(ctx, "en", ["de", "fr"])
    found = wrappers(ctx)
    project_line = "\\SMProjectLanguages[en]{EN,DE,FR}\n"
    # The whole-deck compile keeps its preamble and names the languages even without a language of its own.
    assert found["compile None"] == (
        HEAD + "\\documentclass{beamer}\n\\begin{document}\n" + project_line + "\n\n\\section{One}\n\\slide{1aa-EN-A}\n\\end{document}\n\n")
    assert found["partial None"] == (
        HEAD + "\\documentclass{beamer}\n\\begin{document}\n" + project_line + "\n\\section{One}\n\\end{document}\n")
    assert "\\decklanguage[fr]\n\\SMPdfLang{fr-FR}\n" in found["compile fr"] and project_line in found["compile fr"]
    assert "\\decklanguage[fr]\n\\SMPdfLang{fr-FR}\n" in found["partial fr"]
    assert found["compile de"].replace(project_line, "") == GOLDEN["compile de"]      # nothing else changed
    assert found["calls None"] == GOLDEN["calls None"].replace("\\deckversion[instructor]\n",
                                                                "\\deckversion[instructor]\n" + project_line)
    assert found["calls de"] == GOLDEN["calls de"].replace("\\decklanguage[de]\n", project_line + "\\decklanguage[de]\n")
    assert found["text de"] == GOLDEN["text de"].replace("\\decklanguage[de]\n", project_line + "\\decklanguage[de]\n")


def test_the_preview_build_folder_follows_the_project_languages(ctx):
    plain = wrappers(ctx)
    languages.set_project_languages(ctx, "en", ["de", "fr"])
    french = wrappers(ctx)
    languages.set_project_languages(ctx, "de", ["en", "fr"])
    german_main = wrappers(ctx)
    def variant(text):          # the wrappers here have a stand-in preamble: give view_variant its \begin{document}
        return preview_build.view_variant("\\begin{document}\n" + text)

    assert variant(plain["calls de"]) == "\\deckversion[instructor]|\\decklanguage[de]"
    assert variant(french["calls de"]) == "\\deckversion[instructor]|\\SMProjectLanguages[en]{EN,DE,FR}|\\decklanguage[de]"
    assert variant(french["calls de"]) != variant(german_main["calls de"]) != variant(plain["calls de"])
    assert variant(french["text de"]) != variant(plain["text de"])
    assert variant(german_main["text de"]) != variant(french["text de"])
    languages.set_project_languages(ctx, "de", ["en", "no"])
    assert variant(deck_language.language_lines(ctx, "no") + "\\setSlideID{x}") == (
        "\\SMProjectLanguages[de]{DE,EN,NO}|\\decklanguage[no]|\\SMPdfLang{nb-NO}")


# -- the render key ------------------------------------------------------------------------

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


# The key of unit_for(ctx) in a project without its own languages, as develop computed it: not to change.
DEFAULT_KEY = "11f0a4827849545224ba58774b7a18151857ec17959abdc042f0be8f5d8f9d6e"


def test_the_render_key_of_a_default_project_is_what_it_was(ctx, resolver):
    assert resolver.fast_key(unit_for(ctx)) == DEFAULT_KEY


def test_the_render_key_changes_with_the_projects_languages_and_main_language(ctx, resolver):
    unit = unit_for(ctx)
    default = resolver.fast_key(unit)
    languages.set_project_languages(ctx, "en", ["de"])
    assert resolver.fast_key(unit) == default
    languages.set_project_languages(ctx, "en", ["de", "fr"])
    with_french = resolver.fast_key(unit)
    languages.set_project_languages(ctx, "de", ["en", "fr"])
    german_main = resolver.fast_key(unit)
    languages.set_project_languages(ctx, "en", ["de", "fr", "it"])
    assert len({default, with_french, german_main, resolver.fast_key(unit)}) == 4
    languages.set_project_languages(ctx, "en", ["de", "fr"])
    assert resolver.fast_key(unit) == with_french                    # and back
