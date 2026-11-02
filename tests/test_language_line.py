# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The language lines of a compile and a preview wrapper (deck_language.language_lines).

Every project states its languages, so every wrapper carries `\\SMProjectLanguages`: the GOLDEN texts below are
what develop (v0.13.23, `language_line` and `_deck_language_line`) wrote, and a project's wrappers are those plus that
line (and `\\SMPdfLang` when the PDF language tag needs it). The line changes the preview's build folder and the render
key."""
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


def with_line(golden: dict[str, str], line: str) -> dict[str, str]:
    """What the wrappers of GOLDEN become in a project with `line` (\\SMProjectLanguages...): the line and nothing else,
    except that a compile without a language of its own now keeps its preamble to carry it, and a language whose PDF
    tag is not TeX's own (fr) has its tag line."""
    out = {}
    for key, text in golden.items():
        kind, language = key.split()
        if language == "None" and kind == "compile":
            text = HEAD + "\\documentclass{beamer}\n\\begin{document}\n" + line + "\n\n\\section{One}\n\\slide{1aa-EN-A}\n\\end{document}\n\n"
        elif language == "None" and kind == "partial":
            text = HEAD + "\\documentclass{beamer}\n\\begin{document}\n" + line + "\n\\section{One}\n\\end{document}\n"
        elif language == "None":
            text = text.replace("\\deckversion[instructor]\n", "\\deckversion[instructor]\n" + line)
        else:
            tag = "\\SMPdfLang{fr-FR}\n" if language == "fr" else ""
            text = text.replace(f"\\decklanguage[{language}]\n", f"{line}\\decklanguage[{language}]\n{tag}")
        out[key] = text
    return out


@pytest.mark.parametrize("secondary, line", [
    (["de"], "\\SMProjectLanguages[en]{EN,DE}\n"),
    (["de", "fr"], "\\SMProjectLanguages[en]{EN,DE,FR}\n"),
    ([], "\\SMProjectLanguages[en]{EN}\n")])
def test_every_wrapper_is_what_develop_wrote_plus_the_languages_line(ctx, secondary, line):
    languages.set_project_languages(ctx, "en", secondary)
    assert wrappers(ctx) == with_line(GOLDEN, line)


@pytest.mark.infer_languages
def test_the_lines_of_a_project_without_a_key_follow_what_it_uses():
    ctx = ProjectContext.at(Path("/nonexistent/project"))
    assert deck_language.language_lines(ctx, "DE") == "\\SMProjectLanguages[en]{EN}\n\\decklanguage[de]\n"
    assert deck_language.language_lines(ctx, None) == "\\SMProjectLanguages[en]{EN}\n"


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


def test_the_preview_build_folder_follows_the_project_languages(ctx):
    languages.set_project_languages(ctx, "en", ["de"])
    plain = wrappers(ctx)
    languages.set_project_languages(ctx, "en", ["de", "fr"])
    french = wrappers(ctx)
    languages.set_project_languages(ctx, "de", ["en", "fr"])
    german_main = wrappers(ctx)
    def variant(text):          # the wrappers here have a stand-in preamble: give view_variant its \begin{document}
        return preview_build.view_variant("\\begin{document}\n" + text)

    assert variant(plain["calls de"]) == "\\deckversion[instructor]|\\SMProjectLanguages[en]{EN,DE}|\\decklanguage[de]"
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


def test_the_render_key_changes_with_the_projects_languages_and_main_language(ctx, resolver):
    unit = unit_for(ctx)
    keys = []
    for main, secondary in (("en", []), ("en", ["de"]), ("en", ["de", "fr"]), ("de", ["en", "fr"]), ("en", ["de", "fr", "it"])):
        languages.set_project_languages(ctx, main, secondary)
        keys.append(resolver.fast_key(unit))
    assert len(set(keys)) == 5
    languages.set_project_languages(ctx, "en", ["de", "fr"])
    assert resolver.fast_key(unit) == keys[2]                          # and back


def test_the_render_key_of_a_project_without_the_key_is_that_of_the_languages_it_uses(ctx, resolver):
    unit = unit_for(ctx)                                               # an English slide only
    inferred = resolver.fast_key(unit)
    assert not (ctx.root / ".slidemage" / "project.json").exists()
    languages.migrate(ctx)
    assert resolver.fast_key(unit) == inferred
