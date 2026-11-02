# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The project's languages in SlideMage_base.tex with real TeX (skipped without latexmk): with the
\\SMProjectLanguages line SlideMage writes after the preamble, a slide whose slug names a project language sets
\\slideLanguage; without the line (a deck compiled outside SlideMage) only EN, DE and mult do, and the pages of an
English and German project say the same with and without it. \\SMPdfLang sets \\SMPDFLanguage, the tag of the PDF
language."""
from __future__ import annotations

import shutil

import pymupdf
import pytest

from conftest import EXAMPLE
from slidemage import languages, slide_preview
from slidemage.project import ProjectContext, _ignore_template_build_output

pytestmark = pytest.mark.skipif(shutil.which("latexmk") is None or shutil.which("lualatex") is None,
                                reason="needs a TeX installation")

BODY = ("\\begin{standardframe}{Language}\nSlide language: [\\slideLanguage] "
        "\\ifSMSlideLanguageSet is set\\else is not set\\fi. Main: [\\SMMainLanguage]. "
        "PDF language: [\\SMPDFLanguage].\n\\end{standardframe}\n")


@pytest.fixture
def ctx(tmp_path):
    """A copy of the example project: the languages of a project are in its own project.json."""
    root = tmp_path / "project"
    shutil.copytree(EXAMPLE, root, ignore=_ignore_template_build_output)
    ctx = ProjectContext.at(root)
    languages.set_project_languages(ctx, "en", ["de"])
    return ctx


def render(ctx, id_slug: str, language: str = "en"):
    """The text of the slide's page."""
    pdf = slide_preview.render_slide_text_to_pdf(ctx, id_slug, BODY, deck_version="instructor", deck_language=language,
                                                 capture_snapshot=False)
    with pymupdf.open(pdf) as doc:
        return " ".join(doc[0].get_text().split())


def test_a_project_language_in_a_slug_sets_the_slide_language_only_with_the_line(ctx):
    text = render(ctx, "zz7-FR-Test")
    assert "Slide language: [] is not set" in text                  # English and German: FR is not a language
    for slug, tag in (("zz7-EN-Test", "EN"), ("zz7-DE-Test", "DE"), ("zz7-mult-Test", "mult")):
        assert f"Slide language: [{tag}] is set" in render(ctx, slug)
    languages.set_project_languages(ctx, "en", ["de", "fr"])
    text = render(ctx, "zz7-FR-Test")
    assert "Slide language: [FR] is set" in text and "Main: [en]" in text
    assert "Slide language: [] is not set" in render(ctx, "zz7-IT-Test")      # Italian is not one of them
    assert "Slide language: [mult] is set" in render(ctx, "zz7-mult-Test")


def test_the_main_language_and_a_main_language_other_than_english(ctx):
    languages.set_project_languages(ctx, "fr", ["en", "de"])
    text = render(ctx, "zz7-FR-Test", "fr")
    assert "Slide language: [FR] is set" in text and "Main: [fr]" in text


def test_a_slug_that_looks_like_a_language_only_in_a_project_that_has_it(ctx):
    assert "Slide language: [] is not set" in render(ctx, "x7k-IT-Governance")
    languages.set_project_languages(ctx, "en", ["de", "it"])
    assert "Slide language: [IT] is set" in render(ctx, "x7k-IT-Governance")


def test_the_pdf_language_is_the_tables_tag_for_a_project_with_languages_of_its_own(ctx):
    assert "PDF language: [de-DE]" in render(ctx, "zz7-DE-Test", "de")
    languages.set_project_languages(ctx, "en", ["de", "fr"])
    assert "PDF language: [fr-FR]" in render(ctx, "zz7-FR-Test", "fr")
    assert "PDF language: [en-US]" in render(ctx, "zz7-EN-Test", "en")


def test_an_english_and_german_project_reads_the_same_with_and_without_the_languages_line(ctx, monkeypatch):
    body = ("\\begin{standardframe}{Language}\nSlide: [\\slideLanguage] \\ifSMSlideLanguageSet set\\else unset\\fi. "
            "\\multilingualtext{English text}{Deutscher Text}\n\\end{standardframe}\n")
    slides = [(slug, body, 1, None, None, False, False) for slug in ("zz7-EN-Test", "zz7-DE-Test", "zz7-mult-Test")]

    def pages(language):
        pdf = slide_preview.render_slide_texts_to_pdf(ctx, slides, "instructor", language, None)
        with pymupdf.open(pdf) as doc:
            return [" ".join(page.get_text().split()) for page in doc]

    # What the compile wrote before the line existed: the language only.
    without = lambda _ctx, language: f"\\decklanguage[{language}]\n" if language else ""
    for language in ("en", "de"):
        with_line = pages(language)
        monkeypatch.setattr(slide_preview, "language_lines", without)
        assert pages(language) == with_line and len(with_line) == 3 and "set" in with_line[0]
        monkeypatch.undo()
