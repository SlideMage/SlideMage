# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from html.parser import HTMLParser

import pytest

from slidemage import latex_edit as le
from slidemage import transcript


def apply(text: str, start: int, end: int, edit: le.Edit) -> tuple[str, int]:
    return text[:start] + edit.text + text[end:], start + edit.caret



@pytest.mark.parametrize("text,expected", [
    ("  \\begin{standardframe}{T}\n\\begin{itemize}\n   \\item a\n\n\\end{itemize}\n\\end{standardframe}",
     "\\begin{standardframe}{T}\n\t\\begin{itemize}\n\t\t\\item a\n\n\t\\end{itemize}\n\\end{standardframe}"),
    ("\\end{x}\n  text", "\\end{x}\ntext"),  # an unmatched end must not amplify a source error
])
def test_reindent_respects_environment_depth(text, expected):
    assert le.reindent_latex(text) == expected


def test_a_deck_is_reindented_by_environment_conditional_and_brace():
    expected = """\\documentclass{beamer}
\\input{SlideMage_template_slidemage}
\\newcommand{\\FooterText}{Course}
\\newcommand{\\SMExtra}{%
\t\\textbf{x}%
}
\\ifdefined\\deckversionoverride
\t\\deckversion[\\deckversionoverride]
\\else
\t\\deckversion[instructor]   % options: instructor, during-course
\\fi
\\ifstrequal{a}{b}{\\relax}{}
\\ifSMInstructorVersion\\relax\\else\\relax\\fi
\\decktags{course}
\\begin{document}
\t\\slide{aaa-EN-Title}
\t% ---- Part A ----
\t\\section{Intro}
\t\\slide{bbb-EN-One}
\t\\subsection{Details}
\t\\SMReview[check]{\\slide{ccc-EN-Two}}
\t\\section{Next}
\t\\conditionalslide[instructor]{ddd-EN-Three}
\\end{document}
"""
    unindented = "\n".join(line.lstrip("\t") for line in expected.split("\n"))
    assert le.reindent_deck(unindented) == expected
    assert le.reindent_deck(expected) == expected


def test_a_deck_keeps_its_own_way_of_indenting_under_sections():
    deeper = ("\\begin{document}\n\t\\section{A}\n\t\\slide{a-1}\n\t\\subsection{B}\n\t\t\\slide{b-1}\n\t\t\\slide{b-2}\n"
              "\t\\subsection{C}\n\t\t\\slide{c-1}\n\\slide{c-2}\n\t\\section{D}\n\t\\slide{d-1}\n\\end{document}")
    assert le.section_offsets(deeper) == {"section": 0, "subsection": 1, "subsubsection": 0}
    assert le.reindent_deck(deeper) == deeper.replace("\n\\slide{c-2}", "\n\t\t\\slide{c-2}")
    flat = deeper.replace("\t\t", "\t")
    assert le.section_offsets(flat)["subsection"] == 0
    assert le.reindent_deck(flat) == flat.replace("\n\\slide{c-2}", "\n\t\\slide{c-2}")


def test_a_bib_gets_one_tab_per_field_and_keeps_its_values():
    text = ("% header\n  % indented note\n\n  @article{a2000,\n"
            "author    = {A, B},\n      title = {A {Nested}\n                 continued title},\n"
            "  year  = 2000,\n    }\n"
            "@book(b2001,\n note = \"quoted\n   on two {lines}\",\n publisher = {P}\n )\n"
            "@misc{c, note = {x}}\n")
    assert le.reindent_bib(text) == (
        "% header\n% indented note\n\n@article{a2000,\n"
        "\tauthor    = {A, B},\n\ttitle = {A {Nested}\n                 continued title},\n"
        "\tyear  = 2000,\n}\n"
        "@book(b2001,\n\tnote = \"quoted\n   on two {lines}\",\n\tpublisher = {P}\n)\n"
        "@misc{c, note = {x}}\n")
    done = le.reindent_bib(text)
    assert le.reindent_bib(done) == done


@pytest.mark.parametrize("word,url", [
    ("", "https://example.org"),
    ("Word", "javascript:alert(1)"),
    ("Word", "https://example.org/a b"),
    ("Word", "https://example.org:bad"),
])
def test_hyperlink_formatter_rejects_invalid_input(word, url):
    with pytest.raises(ValueError):
        le.format_hyperlink(word, url)


def test_hyperlink_url_survives_transcript_html(ctx):
    url = "https://example.org/a_b?x=1&y=2#part%20x"
    source = le.format_hyperlink(" R&D ", url)
    assert source == r"\href{https://example.org/a\_b?x=1\&y=2\#part\%20x}{R\&D}"
    html = transcript._inline_html(transcript._inline_markdown(source, {}))

    class Links(HTMLParser):
        def __init__(self):
            super().__init__()
            self.targets = []

        def handle_starttag(self, tag, attrs):
            if tag == "a":
                self.targets.append(dict(attrs)["href"])

    parsed = Links()
    parsed.feed(html)
    assert parsed.targets == [url]
    assert "R&amp;D" in html


def test_wrap_macro_wraps_the_selection_or_leaves_the_cursor_between_the_braces():
    assert apply("a word b", 2, 6, le.wrap_macro("word", "textit")) == ("a \\textit{word} b", 15)
    assert apply("ab", 1, 1, le.wrap_macro("", "textbf")) == ("a\\textbf{}b", 9)


def test_wrapping_environments_preserves_indent_and_turns_selected_text_into_items():
    edit = le.wrap_environment("", "\t", "itemize")
    assert edit.text == "\\begin{itemize}\n\t\t\\item \n\t\\end{itemize}"
    assert edit.text[:edit.caret].endswith("\\item ")
    plain = le.wrap_environment("", "", "center")
    assert plain.text == "\\begin{center}\n\t\n\\end{center}"
    assert plain.caret == len("\\begin{center}\n\t")

    edit = le.wrap_environment("one\n\n two ", "", "enumerate")
    assert edit.text == "\\begin{enumerate}\n\t\\item one\n\t\\item two\n\\end{enumerate}"
    assert edit.caret == len(edit.text)
    assert le.wrap_environment("\n\n", "", "itemize").text == "\\begin{itemize}\n\t\\item \n\\end{itemize}"


def test_ellipsis_list_has_its_own_item_label_and_a_reminder_comment():
    ellipsis = next(i for i in le.INSERT_LIST_COMMANDS if i.kind == "wrap_env_ellipsis")
    edit = le.insert_edit(ellipsis, "", "  ")
    assert edit.text.startswith("%Use \\ldots for in-text ellipses\n  \\begin{itemize}")
    assert "\\item[\\SMBulletEllipsis] " in edit.text


def test_multilingual_puts_the_selection_in_the_first_language_and_the_cursor_in_the_second():
    assert le.insert_multilingual("", ("EN", "DE")) == le.Edit("\\multilingualtext{EN={}, DE={}}",
                                                               len("\\multilingualtext{EN={"))
    text = "\\multilingualtext{EN={Hi}, DE={}}"
    assert le.insert_multilingual("Hi", ("EN", "DE")) == le.Edit(text, text.index("DE={") + 4)
    one = le.insert_multilingual("Hi", ("EN",))                     # a one-language project: nothing to go on to
    assert one == le.Edit("\\multilingualtext{EN={Hi}}", len("\\multilingualtext{EN={Hi"))


def test_the_languages_entry_has_one_key_per_project_language_and_no_star():
    entry = next(i for i in le.INSERT_COMMANDS if i.kind == "wrap_multilingual")
    keyed = le.multilingual_for(entry, ("FR", "EN", "DE"))
    assert keyed.hint == "\\multilingualtext{FR={...}, EN={...}, DE={...}}" and "FR" in keyed.tip
    empty = le.insert_edit(keyed, "", "")
    assert empty == le.Edit("\\multilingualtext{FR={}, EN={}, DE={}}", len("\\multilingualtext{FR={"))
    text = "\\multilingualtext{FR={Salut}, EN={}, DE={}}"
    assert le.insert_edit(keyed, "Salut", "") == le.Edit(text, text.index("EN={") + 4)


def test_block_lands_in_the_title_braces_and_floating_blocks_take_a_width_first():
    edit = le.wrap_block("body", "\t", "infoblock")
    assert edit.text == "\\begin{infoblock}{}\nbody\n\t\\end{infoblock}"
    assert edit.text[:edit.caret].endswith("\\begin{infoblock}{")
    floating = le.wrap_block("", "", "SMFloatingBlock", floating=True)
    assert floating.text.startswith("\\begin{SMFloatingBlock}{5cm}{}\n\t\n")
    assert floating.text[:floating.caret].endswith("{5cm}{")


def test_every_insert_entry_has_an_edit_except_those_that_ask_first():
    for insert in le.INSERT_COMMANDS + le.INSERT_LIST_COMMANDS + le.INSERT_BLOCK_COMMANDS:
        edit = le.insert_edit(insert, "sel", "\t")
        assert (edit is None) == (insert.kind in le.ASKS), insert
    assert {i.kind for i in le.INSERT_COMMANDS} >= set(le.ASKS)
    literal = le.insert_edit(le.Insert("\\tallitem", "literal"), "sel", "")
    assert literal == le.Edit("\\tallitem", len("\\tallitem"))



@pytest.mark.parametrize("line,at_end,expected", [
    ("\ttext", True, le.Edit("\n\t", 2)),
    ("\\begin{standardframe}{Title}", True, le.Edit("\n", 1)),
    ("\\begin{itemize} x", False, le.Edit("\n", 1)),
])
def test_enter_continues_the_indent_without_opening_an_environment(line, at_end, expected):
    assert le.smart_return(line, at_end) == expected


def test_enter_after_begin_adds_an_end_only_when_one_is_missing():
    # Enter at the end of a \begin line whose \end is already there put a second \end under it (v8.66.0).
    line = "\\begin{sectionframe}{Preregistration}"
    text = f"\\setSlideVersion{{1-0-0}}\n{line}\n\\end{{sectionframe}}\n"
    assert le.smart_return(line, True, text) == le.Edit("\n\t", 2)
    nested = "\\begin{itemize}\n\t\\item a\n\t\\begin{itemize}\n\\end{itemize}\n"
    assert le.smart_return("\t\\begin{itemize}", True, nested).text.endswith("\\end{itemize}")   # one is open
    assert le.smart_return("\\begin{center}", True, "\\begin{center}\n% \\end{center}\n").text.endswith("\\end{center}")
    assert le.smart_return("\\begin{itemize}", True, "\\begin{itemize}\n\\end{itemize}") == le.Edit("\n\t\\item ", 8)

    edit = le.smart_return("\t\\begin{itemize}", True)
    assert edit.text == "\n\t\t\\item \n\t\\end{itemize}"
    assert edit.text[:edit.caret] == "\n\t\t\\item "
    assert le.smart_return("\\begin{center}", True).text == "\n\t\n\\end{center}"


def test_enter_after_an_item_starts_the_next_one_with_the_same_label():
    assert le.smart_return("\t\\item[\\SMBulletEllipsis] text", True) == le.Edit(
        "\n\t\\item[\\SMBulletEllipsis] ", len("\n\t\\item[\\SMBulletEllipsis] "))
    assert le.smart_return("\\item \\begin{itemize}", True).text.endswith("\\end{itemize}")


def test_comment_toggle_comments_every_line_and_then_uncomments_them():
    assert le.comment_ops(["a", "", "\tb"]) == [(0, 0, "%")] * 3
    assert le.comment_ops(["%a", "", "\t% b"]) == [(0, 1, ""), (0, 0, ""), (1, 1, "")]
    assert le.comment_ops(["%a", "b"]) == [(0, 0, "%")] * 2   # mixed: comment wins


def test_outdent_takes_one_tab_or_up_to_a_tab_width_of_spaces():
    assert le.outdent_width("\t\tx", 4) == 1
    assert le.outdent_width("      x", 4) == 4
    assert le.outdent_width("  x", 4) == 2
    assert le.outdent_width("  \tx", 4) == 3         # a tab after fewer spaces ends the level
    assert le.outdent_width("x", 4) == 0


def test_brace_pair_finds_the_partner_on_either_side_and_skips_escaped_braces():
    text = "\\a{b{c}\\}d}"
    assert le.brace_pair(text, 2) == (2, 10)
    assert le.brace_pair(text, 11) == (10, 2)
    assert le.brace_pair(text, 0) is None
    assert le.brace_pair("{unclosed", 0) is None


def test_header_comment_lines_counts_the_leading_comment_block():
    assert le.header_comment_lines("% a\n  % b\n\\slide\n% c") == 2
    assert le.header_comment_lines("\\slide") == 0


def test_bib_entry_start_is_the_first_key_with_that_letter():
    text = "@book{alpha,\n url = {x@y},\n}\n\n@article{beta, a=1}\n@misc{Bravo,\n}\n"
    assert le.bib_entry_start(text, "B") == text.index("@article")
    assert le.bib_entry_start(text, "q") is None


def test_minimal_replacement_reports_utf16_offsets():
    old = "😀\n\\setSlideVersion{1.0.0}\nBODY"
    new = old.replace("1.0.0", "12.0.1")
    start, end, replacement = le.minimal_replacement(old, new)
    units = le.utf16_units(old)
    assert units[:start] + replacement + units[end:] == le.utf16_units(new)
    assert start == units.index("1.0.0") + 1   # the common "1" stays; the emoji counts twice
    assert le.minimal_replacement("same", "same")[2] == ""
