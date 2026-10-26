# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import pytest

from slidemage import deck_editor, deck_settings
from slidemage.deck_settings import DeckSettings

DECK = r"""% !TeX program = lualatex
\documentclass[aspectratio=169]{beamer}
\input{SlideMage_template_uni-graz}

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


def read(text: str) -> DeckSettings:
    return deck_settings.read_settings(text)


def test_read_settings_ignores_commented_lines_and_the_override_branch():
    s = read(DECK)
    assert s.template == "uni-graz"
    assert s.language == "en"
    assert s.footer_text == "PS Financial Management 2 | 2027s"
    assert s.output_folders == {
        None: "D:/Teaching/FM2/current", "presenter": "D:/Teaching/FM2/current/presenter.pdf"}
    assert s.course_url == ""
    assert not s.appendix_toc


def test_set_template_changes_only_the_name():
    new = deck_settings.set_template(DECK, "mci")
    assert "\\input{SlideMage_template_mci}" in new
    assert new.replace("mci", "uni-graz", 1) == DECK


def test_set_language_rewrites_the_literal_branch_only():
    new = deck_settings.set_language(DECK, "de")
    assert "\\decklanguage[de]           % options: en, de" in new
    assert "\\decklanguage[\\decklanguageoverride]" in new
    assert read(new).language == "de"


def test_set_language_adds_a_line_when_the_deck_has_none():
    text = DECK.replace("\\decklanguage[en]", "").replace("\\decklanguage[\\decklanguageoverride]", "")
    new = deck_settings.set_language(text, "de")
    assert read(new).language == "de"
    assert new.index("\\decklanguage[de]") < new.index("\\begin{document}")


def test_set_language_refuses_a_non_code():
    with pytest.raises(ValueError):
        deck_settings.set_language(DECK, "english")


def test_footer_text_is_replaced_in_place_even_with_braces_inside():
    new = deck_settings.set_footer_text(DECK, r"PS \textbf{FM2} | 2028s")
    assert read(new).footer_text == r"PS \textbf{FM2} | 2028s"
    assert new.count("\\FooterText") == 1


def test_footer_text_is_added_when_missing_and_not_for_an_empty_value():
    text = DECK.replace("\\newcommand{\\FooterText}{PS Financial Management 2 | 2027s}\n", "")
    assert deck_settings.set_footer_text(text, "") == text
    new = deck_settings.set_footer_text(text, "Talk")
    assert "\\newcommand{\\FooterText}{Talk}\n\\begin{document}" in new


def test_output_folder_changes_the_live_line_and_keeps_its_comment():
    new = deck_settings.set_output_folder(DECK, None, "E:\\New Folder")
    assert "\\deckoutputfolder{E:/New Folder} % all versions" in new
    assert "%\\deckoutputfolder[instructor]{D:/old/Instructor}" in new  # untouched


def test_output_folder_added_after_the_last_one_and_removed_again():
    added = deck_settings.set_output_folder(DECK, "after-course", "D:/Out")
    lines = added.splitlines()
    i = lines.index("\\deckoutputfolder[after-course]{D:/Out}")
    assert lines[i - 1].startswith("\\deckoutputfolder[presenter]")
    assert read(added).output_folders["after-course"] == "D:/Out"
    assert deck_settings.set_output_folder(added, "after-course", "") == DECK


def test_output_folder_added_after_the_template_input_when_there_is_none():
    text = DECK.replace(
        "\\deckoutputfolder{D:/Teaching/FM2/current} % all versions\n", "").replace(
        "\\deckoutputfolder[presenter]{D:/Teaching/FM2/current/presenter.pdf}\n", "")
    new = deck_settings.set_output_folder(text, None, "D:/Out")
    lines = new.splitlines()
    assert lines[lines.index("\\input{SlideMage_template_uni-graz}") + 1] == "\\deckoutputfolder{D:/Out}"


def test_output_folder_refuses_tex_special_characters():
    with pytest.raises(ValueError):
        deck_settings.set_output_folder(DECK, None, "D:/50%/x")


def test_appendix_toc_on_and_off():
    on = deck_settings.set_appendix_toc(DECK, True)
    assert read(on).appendix_toc
    assert deck_settings.set_appendix_toc(on, True) == on
    assert deck_settings.set_appendix_toc(on, False) == DECK


def test_apply_settings_writes_only_what_changed_and_keeps_crlf():
    text = DECK.replace("\n", "\r\n")
    old = read(text)
    new = read(text)
    new.template = "slidemage"
    new.course_url = "https://example.org/course"
    new.output_folders[None] = ""
    out = deck_settings.apply_settings(text, old, new, "t.tex")
    assert "\n" not in out.replace("\r\n", "")
    result = read(out)
    assert result.template == "slidemage"
    assert result.course_url == "https://example.org/course"
    assert None not in result.output_folders
    assert result.language == old.language and result.footer_text == old.footer_text
    # nothing changed -> text identical
    assert deck_settings.apply_settings(text, old, read(text)) == text


def test_save_settings_refuses_a_deck_changed_on_disk(tmp_path):
    path = tmp_path / "d.tex"
    path.write_text(DECK, encoding="utf-8", newline="")
    old = read(DECK)
    new = read(DECK)
    new.template = "mci"
    with pytest.raises(deck_editor.StaleFileError):
        deck_settings.save_settings(path, DECK + "% edited elsewhere\n", old, new)
    assert path.read_text(encoding="utf-8") == DECK
    saved = deck_settings.save_settings(path, DECK, old, new)
    assert path.read_text(encoding="utf-8", errors="replace") == saved
    assert read(saved).template == "mci"


def form(original=None, **fields) -> DeckSettings:
    original = original or DeckSettings(template="uni-graz")
    values = dict(template="uni-graz", language="en", footer_text="", course_url="", output_folders={},
                  appendix_toc=False, open_pdf="instructor") | fields
    return deck_settings.from_form(original, **values)


def test_from_form_checks_the_course_link_and_drops_empty_paths():
    assert form(course_url="  https://example.org/course  ").course_url == "https://example.org/course"
    assert form(course_url="   ").course_url == ""
    with pytest.raises(ValueError, match="http"):
        form(course_url="ftp://example.org/course")
    with pytest.raises(ValueError, match="spaces"):
        form(course_url="not a url")
    assert form(output_folders={None: " ", "presenter": "E:\\Talks "}).output_folders == {"presenter": "E:/Talks"}


def test_from_form_refuses_latex_specials_in_a_path_but_keeps_an_untouched_one_byte_for_byte():
    with pytest.raises(ValueError, match="may not contain"):
        form(output_folders={None: "D:/100%"})
    original = DeckSettings(output_folders={None: "D:\\Old\\Way", "presenter": "D:/50%"})
    new = form(original, output_folders={None: "D:\\Old\\Way", "presenter": "D:/50%"})
    assert new.output_folders == original.output_folders


def test_footer_elements_left_out_are_written_and_read_back():
    text = "\\input{SlideMage_template_uni-graz}\n\\newcommand{\\FooterText}{X}\n\\begin{document}\n\\end{document}\n"
    hidden = deck_settings.set_footer_hide(text, ("deck", "id"))
    assert "\\def\\SMFooterHide{id,deck}\n" in hidden
    assert deck_settings.read_settings(hidden).footer_hide == ("id", "deck")
    assert deck_settings.set_footer_hide(hidden, ()) == text


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_dark_mode_round_trip_places_switch_before_template_and_keeps_line_endings(newline):
    text = DECK.replace("\n", newline)
    old = read(text)
    new = read(text)
    new.dark_mode = True
    dark = deck_settings.apply_settings(text, old, new)
    assert read(dark).dark_mode
    assert dark.index(r"\newcommand{\SMDarkMode}{}") < dark.index(r"\input{SlideMage_template_")
    if newline == "\r\n":
        assert "\n" not in dark.replace("\r\n", "")
    assert deck_settings.apply_settings(dark, read(dark), old) == text


@pytest.mark.parametrize("declaration", [
    r"\newcommand{\SMDarkMode}{}", r"\newcommand*{\SMDarkMode}{}",
    r"\def\SMDarkMode{}", r"\providecommand\SMDarkMode{enabled}",
])
def test_dark_mode_reads_existing_switches_and_ignores_comments_and_body(declaration):
    marker = r"\input{SlideMage_template_uni-graz}"
    assert read(DECK.replace(marker, declaration + "\n" + marker)).dark_mode
    ignored = "% " + declaration + "\n" + DECK + "\n" + declaration
    assert not read(ignored).dark_mode
    assert deck_settings.set_dark_mode(ignored, False) == ignored


def test_enabling_dark_mode_moves_a_late_switch_before_the_template():
    text = DECK.replace(r"\begin{document}", "\\newcommand{\\SMDarkMode}{}\n\\begin{document}")
    assert not read(text).dark_mode
    dark = deck_settings.set_dark_mode(text, True)
    assert read(dark).dark_mode
    assert dark.count(r"\newcommand{\SMDarkMode}{}") == 1
    assert deck_settings.set_dark_mode(dark, True) == dark


def test_disabling_dark_mode_preserves_inline_comments_and_other_commands():
    line = "\\def\\SMDarkMode{}\\newcommand{\\KeepMe}{yes} % keep this\n"
    text = line + DECK
    light = deck_settings.set_dark_mode(text, False)
    assert light == "\\newcommand{\\KeepMe}{yes} % keep this\n" + DECK
    assert not read(light).dark_mode


def test_removing_a_setting_keeps_what_follows_it_on_its_line():
    text = "\\deckappendixtoc % the comment goes with it\n\\deckoutputfolder[presenter]{out/p.pdf} \\def\\SMFooterHide{date}\n"
    assert deck_settings.set_appendix_toc(text, False) == "\\deckoutputfolder[presenter]{out/p.pdf} \\def\\SMFooterHide{date}\n"
    assert deck_settings.set_output_folder(text, "presenter", "") == "\\deckappendixtoc % the comment goes with it\n \\def\\SMFooterHide{date}\n"


def test_dark_mode_form_does_not_depend_on_a_template_name():
    assert form(dark_mode=True).dark_mode
    assert form(template="custom-college", dark_mode=True).dark_mode


def test_dark_mode_support_is_discovered_from_template_headers(tmp_path):
    template = tmp_path / "SlideMage_template_custom-college.tex"
    template.write_text("% SlideMage dark mode: true\n")
    assert deck_settings.template_supports_dark_mode(tmp_path, "custom-college")
    template.write_text("% SlideMage dark mode: false\n")
    assert not deck_settings.template_supports_dark_mode(tmp_path, "custom-college")
    assert not deck_settings.template_supports_dark_mode(tmp_path, "missing")
