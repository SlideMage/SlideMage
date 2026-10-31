# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Transcript parsing of the optional arguments added 2026-09-30:
\\begin{SMTable}[gap=...]{spec} and \\begin{SMFloating*Block}[top=...]{width}{title}."""
from slidemage import transcript


def test_gap_table_spec_is_not_a_cell():
    out = transcript._convert_body(
        "\\begin{SMTable}[gap=12pt]{lcc}\n\\toprule\nA & B & C \\\\\n1 & 2 & 3 \\\\\n"
        "\\end{SMTable}", 0)
    assert "gap" not in out and "lcc" not in out
    assert "| A | B | C |" in out
    assert "| 1 | 2 | 3 |" in out


def test_version_if_keeps_one_branch_per_version():
    text = ("\\ifSMInstructorVersion\n\\item<3-> Answer\n\\else\n\\item Answer\n\\fi\n"
            "\\ifSMDuringCourseVersion\\else Solution \\ifx\\a\\b inner\\else other\\fi\\fi")
    during = transcript.resolve_deck_conditionals(text, "during-course")
    after = transcript.resolve_deck_conditionals(text, "after-course")
    assert during.count("Answer") == 1 and "<3->" not in during
    assert "Solution" not in during
    assert after.count("Answer") == 1 and "Solution" in after
    assert "\\ifx\\a\\b inner\\else other\\fi" in after   # nested \if left intact


def test_deckitem_and_starred_reveals():
    out = transcript.resolve_deck_conditionals(
        "\\deckitem<2-> First \\deckitem<3->[x] Second "
        "\\deckreveal*[3]{Kept} \\deckrevealfinal*{Also} \\deckreveal{Too}", "during-course")
    assert out.count("\\item") == 2 and "deckitem" not in out and "<2->" not in out
    assert "Kept" in out and "Also" in out and "Too" in out
    assert "[3]" not in out and "*" not in out


def test_control_space_is_a_space():
    assert transcript._convert_body("a\\ b", 0) == "a b"


def test_floating_block_title_is_the_title_not_the_width():
    for env in ("SMFloatingInfoBlock", "SMFloatingExampleBlock", "SMFloatingBlock"):
        for option in ("", "[top=0pt, bottom=1mm]"):
            out = transcript._convert_body(
                f"\\begin{{{env}}}{option}{{6cm}}{{Cash flows}}\nBody text\n\\end{{{env}}}", 0)
            assert "> **Cash flows**" in out, (env, option, out)
            assert "6cm" not in out and "top=" not in out
            assert "Body text" in out


def test_tikz_mark_names_are_dropped_and_tikzword_text_kept():
    out = transcript._convert_body(
        "grow'', \\SMTikzword{acUse}{use} the tree and a \\SMTikzmark{x}mark", 0)
    assert "use the tree" in out
    assert "acUse" not in out and "xmark" not in out and "a mark" in out


def test_beamer_templates_dropped_and_item_labels_kept():
    template = transcript._convert_body(
        r"\setbeamertemplate{itemize subitem}{\SMBulletEllipsis}" "\n"
        r"\begin{itemize}" "\n" r"\item Good\ldots" "\n" r"\begin{itemize}" "\n"
        r"\item one" "\n" r"\end{itemize}" "\n" r"\end{itemize}", 0)
    assert "itemize subitem" not in template and "Good…" in template
    label = transcript._convert_body(
        r"\begin{itemize}" "\n" r"\item[\SMBulletEllipsis] one" "\n"
        r"\item[(a)] two" "\n" r"\end{itemize}", 0)
    assert "- … one" in label and "- (a) two" in label and "[]" not in label

