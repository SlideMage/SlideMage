# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Render slides with real TeX to check language selection, text and hyphenation."""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import pymupdf
import pytest

from conftest import EXAMPLE
from slidemage import languages, slide_preview
from slidemage.project import ProjectContext, _ignore_template_build_output

pytestmark = [pytest.mark.skipif(shutil.which("latexmk") is None or shutil.which("lualatex") is None,
                                 reason="needs a TeX installation"),
              pytest.mark.usefixtures("same_tex_configuration")]

BODY = ("\\begin{standardframe}{Language}\nSlide language: [\\slideLanguage] "
        "\\ifSMSlideLanguageSet is set\\else is not set\\fi. Main: [\\SMMainLanguage]. "
        "PDF language: [\\SMPDFLanguage].\n\\end{standardframe}\n")


@pytest.fixture(scope="module")
def project_copy(tmp_path_factory):
    # On Windows, Git's Perl rewrites TEMP paths to /tmp, which TeX cannot resolve in TEXINPUTS.
    if sys.platform == "win32":
        with tempfile.TemporaryDirectory(prefix="slidemage-test-", dir=Path.home()) as parent:
            yield copy_project(Path(parent))
    else:
        yield copy_project(tmp_path_factory.mktemp("languages"))


def copy_project(parent):
    root = parent / "project"
    shutil.copytree(EXAMPLE, root, ignore=_ignore_template_build_output)
    return ProjectContext.at(root)


@pytest.fixture
def ctx(project_copy):
    (project_copy.root / "SlideMage_project_macros.tex").unlink(missing_ok=True)
    shutil.rmtree(project_copy.root / "hyphenation", ignore_errors=True)
    languages.set_project_languages(project_copy, "en", ["de"])
    return project_copy


def render_all(ctx, id_slugs, language="en", body=BODY):
    slides = [(slug, body, 1, None, None, False, False) for slug in id_slugs]
    pdf = slide_preview.render_slide_texts_to_pdf(ctx, slides, "instructor", language, None)
    with pymupdf.open(pdf) as doc:
        pages = [" ".join(page.get_text().split()) for page in doc]
    assert len(pages) == len(id_slugs)
    return dict(zip(id_slugs, pages))


def test_only_project_languages_and_mult_are_recognized_in_slide_slugs(ctx):
    slugs = ["zz7-FR-Test", "zz7-EN-Test", "zz7-DE-Test", "zz7-mult-Test"]
    pages = render_all(ctx, slugs)
    assert "Slide language: [] is not set" in pages[slugs[0]]
    assert "PDF language: [en-US]" in pages[slugs[0]]
    for slug, tag in zip(slugs[1:], ("EN", "DE", "mult")):
        assert f"Slide language: [{tag}] is set" in pages[slug]
    languages.set_project_languages(ctx, "fr", ["en", "de"])
    text = render_all(ctx, slugs[:1], "fr")[slugs[0]]
    assert "Slide language: [FR] is set" in text and "Main: [fr]" in text


def test_english_and_german_render_the_same_without_the_project_languages_line(ctx, monkeypatch):
    body = ("\\begin{standardframe}{Language}\nSlide: [\\slideLanguage] \\ifSMSlideLanguageSet set\\else unset\\fi. "
            "\\multilingualtext{EN={English text}, DE={Deutscher Text}}\n\\end{standardframe}\n")
    slugs = ("zz7-EN-Test", "zz7-DE-Test", "zz7-mult-Test")
    for language in ("en", "de"):
        with_line = render_all(ctx, slugs, language, body)
        with monkeypatch.context() as patch:
            patch.setattr(slide_preview, "language_lines", lambda _ctx, lang: f"\\decklanguage[{lang}]\n")
            assert render_all(ctx, slugs, language, body) == with_line
        assert "set" in with_line[slugs[0]]


LABELS = "Label: [\\SMImageSourceLabel]. Prefix: [\\SMAltImagePrefix]."


def render(ctx, slug, body, language):
    pdf = slide_preview.render_slide_text_to_pdf(ctx, slug, body, deck_version="instructor", deck_language=language)
    with pymupdf.open(pdf) as doc:
        text = " ".join(doc[0].get_text().split())
        return text, doc.xref_get_key(doc.pdf_catalog(), "Lang")[1]


def latest_log(ctx):
    logs = ctx.build_dir.glob("preview-cache/*/*.log")
    return max(logs, key=lambda path: path.stat().st_mtime).read_text(encoding="utf-8", errors="replace")


def render_labels(ctx, language):
    body = f"\\begin{{standardframe}}{{Texts}}\n{LABELS}\n\\end{{standardframe}}\n"
    text, tag = render(ctx, "zz7-EN-Test", body, language)
    return text, " ".join(latest_log(ctx).split()), tag


def test_the_automatic_texts_and_the_pdf_language_follow_the_decks_language(ctx):
    languages.set_project_languages(ctx, "en", ["fr"])
    text, log, tag = render_labels(ctx, "fr")
    assert "Label: [Source(s) de l’image]. Prefix: [Image : ]." in text
    assert tag == "fr-FR" and 'No "' not in log


def test_a_missing_string_falls_back_to_the_main_language_with_a_warning(ctx):
    languages.set_project_languages(ctx, "de", ["en", "pt"])
    text, log, lang = render_labels(ctx, "pt")
    assert "Label: [Bildquelle(n)]. Prefix: [Bild: ]." in text          # Portuguese has none: the main language's
    assert 'No "ImageSource" text for the language "pt"' in log and 'No "ImagePrefix" text for the language "pt"' in log
    assert lang == "pt-PT"


def test_a_project_adds_strings_of_its_own(ctx):
    macros = ctx.root / "SlideMage_project_macros.tex"
    macros.write_text("\\SMSetLanguageStrings{pt}{ImageSource={Fonte(s) da imagem}, ImagePrefix={Imagem: }}\n", encoding="utf-8")
    languages.set_project_languages(ctx, "en", ["de", "pt"])
    text, log, _lang = render_labels(ctx, "pt")
    assert "Label: [Fonte(s) da imagem]. Prefix: [Imagem: ]." in text and "No \"" not in log


def test_the_old_two_argument_multilingual_text_stops_with_an_error(ctx):
    body = "\\begin{standardframe}{Mult}\n\\multilingualtext{Hello}{Hallo}\n\\end{standardframe}\n"
    with pytest.raises(RuntimeError, match="two-argument form"):
        render(ctx, "zz7-mult-Test", body, "en")


def test_a_keyed_multilingual_text_falls_back_to_the_main_language(ctx):
    languages.set_project_languages(ctx, "fr", ["en", "de"])
    body = ("\\begin{standardframe}{Mult}\n\\multilingualtext*{EN={Hello}, DE={Hallo}, FR={Bonjour}} and "
            "\\multilingualtext*{EN={only}, FR={seul}}\n\\end{standardframe}\n")
    for language, expected in (("fr", "Bonjour and seul"), ("de", "Hallo and seul")):
        assert expected in render(ctx, "zz7-mult-Test", body, language)[0]


HYPHENATION = ("\\begin{standardframe}{Hyphenation}\nLanguage: [\\the\\language] mins [\\the\\lefthyphenmin/"
               "\\the\\righthyphenmin]\n\n\\parbox{1.2cm}{xqzxqzxqzxqzxqz}\n\\end{standardframe}\n")


def render_hyphenation(ctx, language, slide=None):
    text, _tag = render(ctx, f"zz7-{slide or language.upper()}-Test", HYPHENATION, language)
    return text, "".join(latest_log(ctx).splitlines())


def test_preview_hyphenates_in_the_slide_language_or_in_the_deck_language_for_mult(ctx):
    patterns = ctx.root / "hyphenation"
    patterns.mkdir()
    (patterns / "hyph-fr.pat.txt").write_text("z1x\n", encoding="utf-8")
    languages.set_project_languages(ctx, "en", ["fr"])
    text, _ = render_hyphenation(ctx, "fr")
    assert "mins [2/3]" in text and "Language: [0]" not in text and "xqz- xqz-" in text
    english, mult = "zz7-EN-Test", "zz7-mult-Test"
    pages = render_all(ctx, [english, mult], "fr", HYPHENATION)
    assert "Language: [0] mins [2/3]" in pages[english] and "xqz- xqz-" not in pages[english]
    assert "xqz- xqz-" in pages[mult]
    assert "xqz- xqz-" in render_hyphenation(ctx, "en", "FR")[0]
    assert "xqz- xqz-" in render_hyphenation(ctx, "fr")[0]


def test_the_shipped_patterns_hyphenate_without_the_distributions(ctx):
    body = ("\\begin{standardframe}{Shipped}\n\\parbox{1pt}{\\hspace{0pt}Donaudampfschifffahrt}\n"
            "\\directlua{texio.write_nl('PATTERNS ' .. (kpse.find_file('hyphenation/hyph-de-1996.pat.txt') or ''))}\n"
            "\\end{standardframe}\n")
    assert "Do- nau- dampf- schiff- fahrt" in render(ctx, "zz7-DE-Test", body, "de")[0]
    assert "latex/hyphenation/hyph-de-1996.pat.txt" in "".join(latest_log(ctx).splitlines())


def test_a_language_without_patterns_hyphenates_as_english_with_a_warning(ctx):
    languages.set_project_languages(ctx, "en", ["ro", "ja"])
    text, log = render_hyphenation(ctx, "ro")
    if "Language: [0]" in text:                                  # (Romanian is not shipped: a TeX without it)
        assert "mins [2/3]" in text and "hyph-ro.pat.txt) are not installed" in log
    text, log = render_hyphenation(ctx, "ja")                    # no patterns in hyph-utf8: not hyphenated
    assert "Language: [0]" not in text and "not installed" not in log and "xqzxqzxqzxqzxqz" in text
