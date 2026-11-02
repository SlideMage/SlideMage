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


LABELS = "Label: [\\SMImageSourceLabel]. Prefix: [\\SMAltImagePrefix]."


def render_labels(ctx, language: str):
    """The page text and the TeX log of a slide in `language` that shows the two automatic texts."""
    body = f"\\begin{{standardframe}}{{Texts}}\n{LABELS}\n\\end{{standardframe}}\n"
    pdf = slide_preview.render_slide_text_to_pdf(ctx, "zz7-EN-Test", body, deck_version="instructor",
                                                 deck_language=language, capture_snapshot=False)
    logs = ctx.build_dir.glob("preview-cache/*/*.log")
    log = max(logs, key=lambda path: path.stat().st_mtime).read_text(encoding="utf-8", errors="replace")
    with pymupdf.open(pdf) as doc:
        return " ".join(doc[0].get_text().split()), " ".join(log.split()), doc.xref_get_key(doc.pdf_catalog(), "Lang")[1]


def test_the_automatic_texts_and_the_pdf_language_follow_the_decks_language(ctx):
    languages.set_project_languages(ctx, "en", ["fr", "es", "it"])
    for code, label, prefix, tag in (("fr", "Source(s) de l’image", "Image : ", "fr-FR"),
                                     ("es", "Fuente(s) de la imagen", "Imagen: ", "es-ES"),
                                     ("it", "Fonte/i dell’immagine", "Immagine: ", "it-IT")):
        text, log, lang = render_labels(ctx, code)
        assert f"Label: [{label}]. Prefix: [{prefix}]." in text
        assert lang == tag
        assert "No \"" not in log


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


def test_a_keyed_multilingual_text_falls_back_to_the_main_language(ctx):
    languages.set_project_languages(ctx, "fr", ["en", "de"])
    body = ("\\begin{standardframe}{Mult}\n\\multilingualtext*{EN={Hello}, DE={Hallo}, FR={Bonjour}} and "
            "\\multilingualtext*{EN={only}, FR={seul}}\n\\end{standardframe}\n")
    for language, expected in (("fr", "Bonjour and seul"), ("de", "Hallo and seul")):
        pdf = slide_preview.render_slide_text_to_pdf(ctx, "zz7-mult-Test", body, deck_version="instructor",
                                                     deck_language=language, capture_snapshot=False)
        with pymupdf.open(pdf) as doc:
            assert expected in " ".join(doc[0].get_text().split())


HYPHENATION = ("\\begin{standardframe}{Hyphenation}\nLanguage: [\\the\\language] mins [\\the\\lefthyphenmin/"
               "\\the\\righthyphenmin]\n\n\\parbox{1.2cm}{xqzxqzxqzxqzxqz}\n\\end{standardframe}\n")


def render_hyphenation(ctx, language: str, slide: str | None = None):
    """The page text and the TeX log (its lines joined as TeX wrapped them) of a slide with one long word in a narrow
    box, in a deck in `language`; the slide's own language is `slide`, by default the deck's."""
    pdf = slide_preview.render_slide_text_to_pdf(ctx, f"zz7-{slide or language.upper()}-Test", HYPHENATION,
                                                 deck_version="instructor", deck_language=language,
                                                 capture_snapshot=False)
    logs = ctx.build_dir.glob("preview-cache/*/*.log")
    log = max(logs, key=lambda path: path.stat().st_mtime).read_text(encoding="utf-8", errors="replace")
    with pymupdf.open(pdf) as doc:
        return " ".join(doc[0].get_text().split()), "".join(log.splitlines())


def fake_french(ctx):
    (ctx.root / "hyphenation").mkdir(exist_ok=True)
    (ctx.root / "hyphenation" / "hyph-fr.pat.txt").write_text("z1x\n", encoding="utf-8")


def test_a_deck_hyphenates_in_its_language(ctx):
    # The project's own hyphenation/ folder is searched first, so these made-up French patterns win over the shipped
    # ones: break after every z.
    fake_french(ctx)
    languages.set_project_languages(ctx, "en", ["fr"])
    text, _log = render_hyphenation(ctx, "fr")
    assert "mins [2/3]" in text and "Language: [0]" not in text
    assert "xqz- xqz-" in text
    text, _log = render_hyphenation(ctx, "en")                   # back to English: the format's own language 0
    assert "Language: [0] mins [2/3]" in text and "xqz- xqz-" not in text
    text, _log = render_hyphenation(ctx, "fr")                   # again, through the preview format
    assert "xqz- xqz-" in text


def test_a_slide_hyphenates_in_its_own_language_and_a_multilingual_one_in_the_decks(ctx):
    fake_french(ctx)
    languages.set_project_languages(ctx, "en", ["fr"])
    text, _log = render_hyphenation(ctx, "fr", "EN")             # not translated yet: English, also in a French deck
    assert "Language: [0] mins [2/3]" in text and "xqz- xqz-" not in text
    text, _log = render_hyphenation(ctx, "fr", "mult")
    assert "xqz- xqz-" in text
    text, _log = render_hyphenation(ctx, "en", "FR")             # a French slide in an English deck
    assert "xqz- xqz-" in text


def test_the_shipped_patterns_hyphenate_without_the_distributions(ctx):
    body = ("\\begin{standardframe}{Shipped}\n\\parbox{1pt}{\\hspace{0pt}Donaudampfschifffahrt}\n"
            "\\directlua{texio.write_nl('PATTERNS ' .. (kpse.find_file('hyphenation/hyph-de-1996.pat.txt') or ''))}\n"
            "\\end{standardframe}\n")
    pdf = slide_preview.render_slide_text_to_pdf(ctx, "zz7-DE-Test", body, deck_version="instructor",
                                                 deck_language="de", capture_snapshot=False)
    logs = ctx.build_dir.glob("preview-cache/*/*.log")
    log = "".join(max(logs, key=lambda path: path.stat().st_mtime).read_text(encoding="utf-8").splitlines())
    with pymupdf.open(pdf) as doc:                                    # every break taken: German's, not English's
        assert "Do- nau- dampf- schiff- fahrt" in " ".join(doc[0].get_text().split())
    assert "latex/hyphenation/hyph-de-1996.pat.txt" in log


def test_a_language_without_patterns_hyphenates_as_english_with_a_warning(ctx):
    languages.set_project_languages(ctx, "en", ["ro", "ja"])
    text, log = render_hyphenation(ctx, "ro")
    if "Language: [0]" in text:                                  # (Romanian is not shipped: a TeX without it)
        assert "mins [2/3]" in text and "hyph-ro.pat.txt) are not installed" in log
    text, log = render_hyphenation(ctx, "ja")                    # no patterns in hyph-utf8: not hyphenated
    assert "Language: [0]" not in text and "not installed" not in log and "xqzxqzxqzxqzxqz" in text
