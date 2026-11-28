# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import pytest

from slidemage import deck_editor, deck_settings
from slidemage.deck_settings import DeckSettings, read_settings as read

DECK = r"""% !TeX program = lualatex
\documentclass[aspectratio=169]{beamer}
\input{SlideMage_template_acme}

\deckoutputfolder{D:/Teaching/FM2/current} % all versions
%\deckoutputfolder[instructor]{D:/old/Instructor}
\deckoutputfolder[presenter]{D:/Teaching/FM2/current/presenter.pdf}

\newcommand{\FooterText}{PS Financial Management 2 | 2027s}
\ifdefined\decklanguageoverride
	\decklanguage[\decklanguageoverride]
\else
	\decklanguage[en]           % options: en, de
\fi
\decktags{course}
\begin{document}
	\slide{abc-EN-X}
\end{document}
"""


def test_setting_a_language_inserts_a_valid_code_and_refuses_other_values():
    text = DECK.replace("\\decklanguage[en]", "").replace("\\decklanguage[\\decklanguageoverride]", "")
    new = deck_settings.set_language(text, "de")
    assert read(new).language == "de"
    assert new.index("\\decklanguage[de]") < new.index("\\begin{document}")

    with pytest.raises(ValueError):
        deck_settings.set_language(DECK, "english")


def test_footer_text_is_added_when_missing_and_replaces_nested_braces_in_place():
    text = DECK.replace("\\newcommand{\\FooterText}{PS Financial Management 2 | 2027s}\n", "")
    assert deck_settings.set_footer_text(text, "") == text
    new = deck_settings.set_footer_text(text, "Talk")
    assert "\\newcommand{\\FooterText}{Talk}\n\\begin{document}" in new

    new = deck_settings.set_footer_text(DECK, r"PS \textbf{FM2} | 2028s")
    assert read(new).footer_text == r"PS \textbf{FM2} | 2028s"
    assert new.count("\\FooterText") == 1


def test_setting_an_output_folder_preserves_comments_and_refuses_tex_specials():
    new = deck_settings.set_output_folder(DECK, None, "E:\\New Folder")
    assert "\\deckoutputfolder{E:/New Folder} % all versions" in new
    assert "%\\deckoutputfolder[instructor]{D:/old/Instructor}" in new  # untouched

    with pytest.raises(ValueError):
        deck_settings.set_output_folder(DECK, None, "D:/50%/x")


def test_output_folder_insertions_follow_the_last_folder_or_the_template():
    added = deck_settings.set_output_folder(DECK, "after-course", "D:/Out")
    lines = added.splitlines()
    i = lines.index("\\deckoutputfolder[after-course]{D:/Out}")
    assert lines[i - 1].startswith("\\deckoutputfolder[presenter]")
    assert read(added).output_folders["after-course"] == "D:/Out"
    assert deck_settings.set_output_folder(added, "after-course", "") == DECK

    text = "\n".join(line for line in DECK.split("\n") if not line.startswith(r"\deckoutputfolder"))
    new = deck_settings.set_output_folder(text, None, "D:/Out")
    lines = new.splitlines()
    assert lines[lines.index("\\input{SlideMage_template_acme}") + 1] == "\\deckoutputfolder{D:/Out}"


def test_apply_settings_writes_only_what_changed_and_keeps_crlf():
    text = DECK.replace("\n", "\r\n")
    old = read(text)
    assert old.template == "acme"
    assert old.language == "en"
    assert old.footer_text == "PS Financial Management 2 | 2027s"
    assert old.output_folders == {
        None: "D:/Teaching/FM2/current", "presenter": "D:/Teaching/FM2/current/presenter.pdf"}
    assert not old.appendix_toc
    new = read(text)
    new.template = "slidemage"
    new.output_folders[None] = ""
    out = deck_settings.apply_settings(text, old, new, "t.tex")
    assert "\n" not in out.replace("\r\n", "")
    result = read(out)
    assert result.template == "slidemage"
    assert None not in result.output_folders
    assert result.language == old.language and result.footer_text == old.footer_text
    assert deck_settings.apply_settings(text, old, read(text)) == text


def test_save_settings_preserves_course_url_and_refuses_stale_edits(tmp_path):
    text = DECK.replace("\\begin{document}", "%% SlideMage course URL: https://example.org/course/1\n\\begin{document}")
    path = tmp_path / "d.tex"
    path.write_text(text, encoding="utf-8", newline="")
    old = read(text)
    new = read(text)
    new.template, new.language, new.footer_text, new.appendix_toc = "other", "de", "Other", True
    new.open_pdf = "presenter"
    with pytest.raises(deck_editor.StaleFileError):
        deck_settings.save_settings(path, text + "% edited elsewhere\n", old, new)
    assert path.read_text(encoding="utf-8") == text
    saved = deck_settings.save_settings(path, text, old, new)
    assert saved.count("%% SlideMage course URL: https://example.org/course/1\n") == 1
    assert path.read_text(encoding="utf-8") == saved
    parsed = read(saved)
    assert parsed.template == "other" and parsed.language == "de" and parsed.appendix_toc
    assert r"\decklanguage[\decklanguageoverride]" in saved
    assert r"\decklanguage[de]           % options: en, de" in saved


def form(original=None, **fields) -> DeckSettings:
    original = original or DeckSettings(template="acme")
    values = dict(template="acme", language="en", footer_text="", output_folders={},
                  appendix_toc=False, open_pdf="instructor") | fields
    return deck_settings.from_form(original, **values)


def test_from_form_drops_empty_paths():
    assert form(output_folders={None: " ", "presenter": "E:\\Talks "}).output_folders == {"presenter": "E:/Talks"}


def test_from_form_accepts_a_hash_in_a_path_and_it_survives_a_round_trip():
    path = "U:/#CurrentWork/IHS3 - Intervention/Presentations"
    settings = form(output_folders={None: path})
    assert settings.output_folders == {None: path}
    written = deck_settings.set_output_folder("\\documentclass{x}\n", None, path)
    assert deck_settings.read_settings(written).output_folders == {None: path}


def test_from_form_refuses_latex_specials_in_a_path_but_keeps_an_untouched_one_byte_for_byte():
    with pytest.raises(ValueError, match="may not contain"):
        form(output_folders={None: "D:/100%"})
    with pytest.raises(ValueError, match="may not contain"):
        form(output_folders={None: "D:/{x}"})
    original = DeckSettings(output_folders={None: "D:\\Old\\Way", "presenter": "D:/50%"})
    new = form(original, output_folders={None: "D:\\Old\\Way", "presenter": "D:/50%"})
    assert new.output_folders == original.output_folders


FOOTER_DECK = r"""\input{SlideMage_template_acme}
\newcommand{\FooterText}{X}
\begin{document}
\end{document}
"""


def test_footer_elements_left_out_are_written_and_read_back():
    text = FOOTER_DECK
    hidden = deck_settings.set_footer_hide(text, ("deck", "id"))
    assert "\\def\\SMFooterHide{id,deck}\n" in hidden
    assert deck_settings.read_settings(hidden).footer_hide == ("id", "deck")
    assert deck_settings.set_footer_hide(hidden, ()) == text


def test_the_footer_words_of_the_deck_versions_are_written_read_back_and_removed():
    text = FOOTER_DECK
    old = deck_settings.read_settings(text)
    assert old.deck_labels == {}
    new = form(old, footer_text="X", deck_labels={"instructor": " speaker  deck ", "during-course": "",
                                               "after-course": "student final deck"})
    assert new.deck_labels == {"instructor": "speaker deck"}       # blanks squeezed; empty and default: no line
    written = deck_settings.apply_settings(text, old, new)
    assert "\\newcommand{\\FooterText}{X}\n\\def\\SMDeckLabelInstructor{speaker deck}\n" in written
    assert deck_settings.read_settings(written).deck_labels == {"instructor": "speaker deck"}
    assert deck_settings.set_deck_label(written, "instructor", "") == text
    with pytest.raises(ValueError, match="may not contain"):
        form(old, footer_text="X", deck_labels={"instructor": "50%"})


def test_dark_mode_round_trip_places_the_mode_line_before_template_and_keeps_crlf():
    text = DECK.replace("\n", "\r\n")
    old = read(text)
    new = read(text)
    new.mode = "dark"
    dark = deck_settings.apply_settings(text, old, new)
    assert read(dark).mode == "dark"
    assert dark.index(r"\newcommand{\SMModeOverride}{dark}") < dark.index(r"\input{SlideMage_template_")
    assert "SMDarkMode" not in dark
    assert "\n" not in dark.replace("\r\n", "")
    assert deck_settings.apply_settings(dark, read(dark), old) == text


@pytest.mark.parametrize("declaration", [
    r"\newcommand*{\SMModeOverride}{dark}", r"\def\SMModeOverride{dark}", r"\providecommand\SMModeOverride{dark}",
])
def test_the_mode_line_is_read_and_comments_and_the_body_are_ignored(declaration):
    marker = r"\input{SlideMage_template_acme}"
    assert read(DECK.replace(marker, declaration + "\n" + marker)).mode == "dark"
    ignored = "% " + declaration + "\n" + DECK + "\n" + declaration
    assert read(ignored).mode == ""
    assert deck_settings.set_mode(ignored, "") == ignored


def test_setting_a_mode_moves_a_late_mode_line_before_the_template():
    text = DECK.replace(r"\begin{document}", r"\newcommand{\SMModeOverride}{dark}" + "\n" + r"\begin{document}")
    assert read(text).mode == ""
    dark = deck_settings.set_mode(text, "dark")
    assert read(dark).mode == "dark"
    assert dark.count(r"\newcommand{\SMModeOverride}{dark}") == 1
    assert deck_settings.set_mode(dark, "dark") == dark


def test_the_base_mode_preserves_inline_comments_and_other_commands():
    line = r"\def\SMModeOverride{dark}\newcommand{\KeepMe}{yes} % keep this" + "\n"
    text = line + DECK
    light = deck_settings.set_mode(text, "")
    assert light == r"\newcommand{\KeepMe}{yes} % keep this" + "\n" + DECK
    assert read(light).mode == ""


def test_removing_a_setting_keeps_what_follows_it_on_its_line():
    text = "\\deckappendixtoc % the comment goes with it\n\\deckoutputfolder[presenter]{out/p.pdf} \\def\\SMFooterHide{date}\n"
    assert deck_settings.set_appendix_toc(text, False) == "\\deckoutputfolder[presenter]{out/p.pdf} \\def\\SMFooterHide{date}\n"
    assert deck_settings.set_output_folder(text, "presenter", "") == "\\deckappendixtoc % the comment goes with it\n \\def\\SMFooterHide{date}\n"


def test_dark_mode_support_is_discovered_from_template_headers(tmp_path):
    template = tmp_path / "SlideMage_template_custom-college.tex"
    template.write_text("% SlideMage modes: light, dark\n")
    assert deck_settings.template_supports_dark_mode(tmp_path, "custom-college")
    template.write_text("% SlideMage dark mode: true\n")          # the header of before v0.16.0 means nothing
    assert not deck_settings.template_supports_dark_mode(tmp_path, "custom-college")
    assert not deck_settings.template_supports_dark_mode(tmp_path, "missing")


def test_an_output_path_splits_into_folder_and_file_name_and_joins_back():
    assert deck_settings.split_output("D:/Out/Handout.pdf") == ("D:/Out", "Handout")
    assert deck_settings.split_output("D:/Out") == ("D:/Out", "")
    assert deck_settings.split_output("D:/Out.v2/Handout.md") == ("D:/Out.v2", "Handout")
    assert deck_settings.split_output("/Handout.pdf") == ("/", "Handout")
    assert deck_settings.split_output("Teacher.pdf") == (".", "Teacher")                 # relative to the project root
    assert deck_settings.join_output("instructor", ".", "Teacher", "D:/Out") == "./Teacher.pdf"
    join = deck_settings.join_output
    assert join(None, "D:/Out", "Handout") == "D:/Out/Handout.pdf"
    assert join(None, "D:/Out/", "Handout.PDF") == "D:/Out/Handout.pdf"          # an extension typed works too
    assert join("transcript", "D:/Out", "Notes.html") == "D:/Out/Notes.md"
    assert join("instructor", "", "Teacher", "D:/Out") == "D:/Out/Teacher.pdf"   # no folder: the one for all outputs
    assert join(None, "", "Handout") == "pdf/Handout.pdf" and join("transcript", "", "N") == "transcripts/N.md"
    assert join(None, "D:/Out", "") == "D:/Out" and join("instructor", "", "") == ""
    assert join(None, "D:/Out", "v1.2 notes") == "D:/Out/v1.2 notes.pdf"         # only the output extensions are dropped
