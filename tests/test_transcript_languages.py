# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Localized transcripts and fallback for multilingual slide text."""
from pathlib import Path

from slidemage import languages, transcript

KEYED = (r"\begin{standardframe}{\multilingualtext*{EN={Hello}, DE={Hallo}, FR={Bonjour}}}"
         r"Say \multilingualtext*{EN={cheese}, FR={fromage}}. Without the star: \multilingualtext{EN={one}, DE={eins}}."
         r"\end{standardframe}")


def render(ctx, tmp_path: Path, language: str):
    path = tmp_path / "abc-mult-Hello-current.tex"
    path.write_text(KEYED, encoding="utf-8")
    entry = transcript.render_slide(ctx, transcript.DeckSlide(1, "abc", path, True), "during-course", {},
                                    language=transcript.strings_language(language, languages.project_languages(ctx).main),
                                    deck_language=language)
    assert entry is not None
    return entry


def test_a_keyed_multilingual_slide_shows_the_decks_language(ctx, tmp_path):
    languages.set_project_languages(ctx, "en", ["de", "fr"])
    entry = render(ctx, tmp_path, "de")
    assert entry.title == "Hallo" and "Say cheese." in entry.body and "Without the star: eins." in entry.body


def test_a_language_the_keys_lack_gets_the_main_languages_value(ctx, tmp_path):
    languages.set_project_languages(ctx, "fr", ["en", "es"])
    entry = render(ctx, tmp_path, "es")
    assert entry.title == "Bonjour" and "Say fromage." in entry.body       # not Hello: the main language is French


def test_the_texts_exist_for_fr_es_it_and_fall_back():
    for code in ("fr", "es", "it"):
        assert transcript.STRINGS[code].keys() == transcript.STRINGS["en"].keys()
        assert transcript._VERSION_LABELS_BY_LANGUAGE[code].keys() == transcript.VERSION_LABELS.keys()
    assert transcript.strings_language("pt", "de") == "de"
    assert transcript.strings_language("pt", "nl") == "en"


def test_a_french_deck_gets_a_french_transcript(ctx):
    languages.set_project_languages(ctx, "en", ["fr"])
    deck = ctx.decks_dir / "t-Deck.tex"
    deck.parent.mkdir(exist_ok=True)
    deck.write_text("\\documentclass{beamer}\n\\decklanguage[fr]\n\\begin{document}\n\\end{document}\n", encoding="utf-8")
    result = transcript.generate(ctx, deck, "during-course")
    assert result.language == "fr"
    assert "transcription accessible" in result.markdown and "version pendant le cours" in result.markdown
