# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
import pytest

from slidemage import deck_scan, latex_lint
from slidemage.latex_lint import LintIssue, _lex
from conftest import make_project
from slidemage.project import ProjectContext


def test_student_lint_skips_omitslide(ctx, tmp_path):
    (tmp_path / "deck.tex").write_text(
        "\\documentclass{beamer}\n\\begin{document}\n"
        "\\omitslide{abc-EN-Missing}\n\\end{document}\n", encoding="utf-8")
    deck, = deck_scan.scan_dir(tmp_path, False)
    assert not latex_lint.check_deck_job(ctx, deck, "during-course").errors
    assert [i.code for i in latex_lint.check_deck_job(ctx, deck, "instructor").errors] == ["slide-file"]


def codes(ctx, text):
    return [i.code for i in latex_lint.lint_text(ctx, text)]


def test_heading_text_above_a_list(ctx):
    bad = "\\begin{standardframe}{T}\n\t\\textbf{Mispricing example}\n\t\\begin{itemize}\n\t\\item a\n\t\\end{itemize}\n\\end{standardframe}\n"
    good = "\\begin{standardframe}{T}\n\t\\begin{itemize}\n\t\\item \\textbf{Mispricing example}\n\t\\end{itemize}\n\\end{standardframe}\n"
    assert "heading-text" in codes(ctx, bad)
    assert "heading-text" not in codes(ctx, good)


@pytest.mark.parametrize("text,expected", [
    ("\\begin{SMTable}{lcc}\na & b & c\\\\\n\\end{SMTable}\n", True),
    ("\\begin{SMTable}[gap=12pt]{lcc}\n\\end{SMTable}\n", False),
    ("\\begin{SMTable}{@{}l<{\\hspace{12pt}}c@{}}\n\\end{SMTable}\n", False),
    ("\\begin{SMTable}{@{\\hspace{2bp}}lc@{}}\n\\end{SMTable}\n", False),
    ("% \\begin{SMTable}{lcc}\n", False),
])
def test_table_edges_warns_only_for_live_tables_without_gap_or_flush_edges(ctx, text, expected):
    issues = [i for i in latex_lint.lint_text(ctx, text) if i.code == "table-edges"]
    assert bool(issues) is expected
    if expected:
        assert issues[0].severity == latex_lint.WARNING
        assert issues[0].line == 1


def test_cited_keys_are_listed_once_in_order_without_comments_or_macro_keys():
    text = ("\\footnote{\\fullcite{smith2020,doe2021}} \\textcite[p.~3]{doe2021}\n"
            "% \\fullcite{commented2000}\n\\parencite{\\mykey} \\parencite{#1} \\textcite{lee1999}\n"
            "\\parenciteplusjournal{a2020} \\textciteplusjournal[p.~2]{b2021} \\fullcitenodoi{c2022}\n")
    assert latex_lint.cited_keys(text) == ["smith2020", "doe2021", "lee1999", "a2020", "b2021", "c2022"]
    assert latex_lint.cited_keys("no citations here") == []


def test_lint_checks_included_fragment_slides(tmp_path, monkeypatch):
    root = make_project(monkeypatch, tmp_path)
    ctx = ProjectContext.at(root)
    (root / "decks/fragment.tex").write_text("\\slide{abc-EN-Hello}\n")
    (root / "decks/test.tex").write_text(
        "\\documentclass{beamer}\n\\begin{document}\n"
        "\\include{fragment.tex}\n\\end{document}\n")
    slide = root / "slides/abc-EN-Hello-current.tex"
    slide.write_text("{")
    deck, = deck_scan.scan_dir(root / "decks", False)
    result = latex_lint.check_deck_job(ctx, deck)
    assert result.files_checked == 3
    assert result.errors and all(i.path == slide for i in result.errors)


@pytest.mark.parametrize("text,expected", [
    pytest.param("", [], id="empty"),
    pytest.param("$unclosed", [("math-dollar", 1)], id="inline-math-eof"),
    # The shared masker stops at the first \fi, including in nested \iffalse blocks.
    pytest.param(
        "% { } $ \\end{x}\n"
        "5% growth { #\n"
        "\\% \\\\% comment {\n"
        "\\begin{verbatim}\n"
        "{ $ # & _ ^\n"
        "\\end{verbatim}\n"
        "\\begin{Verbatim} } $ \\end{Verbatim}\n"
        "\\begin{lstlisting} } $ \\end{lstlisting}\n"
        "\\begin{minted}{python} } $ \\end{minted}\n"
        "\\verb|{ $ #| \\verb*+} &+\n"
        "\\iffalse { $ \\iffalse } # \\fi & \\fi\n"
        "a_b ^ & #\n",
        [("percent", 2), ("ampersand", 11), ("ampersand", 12), ("caret", 12),
         ("hash", 12), ("underscore", 12)],
        id="masking",
    ),
    pytest.param(
        "\ufffd\x01\n"
        "\x02\ufffd\n"
        "\t\r\n"
        "\x00\n",
        [("encoding", 1), ("encoding", 2), ("encoding", 4)],
        id="encoding",
    ),
    pytest.param(
        "\\end{none}\n"
        "\\begin{a}\n"
        "\\begin{b}\n"
        "\\end{a}\n"
        "\\begin{c}\\end{d}\n"
        "\\begin{e}\n",
        [("environments", 1), ("environments", 3), ("environments", 5), ("environments", 5),
         ("environments", 6)],
        id="environments",
    ),
    # Environment matches consume embedded newlines without advancing the scanner's line counter.
    pytest.param(
        "\\begin \n"
        "{ a }\n"
        "{\n"
        "\\end{a}\n",
        [("braces", 2)],
        id="multiline-environment",
    ),
    pytest.param(
        "} {\n"
        "\\newcommand{\\foo}[2]{#1 {#2}} #\n"
        "\\def\\bar#1{#1 & a_b^} #\n"
        "\\newenvironment{x}{#1}{#2} #\n"
        "\\newcommand\\empty\n"
        "\n"
        "#\n"
        "\\newcommand{\\open}\n"
        "\n"
        "#\n",
        [("braces", 1), ("braces", 1), ("hash", 2), ("hash", 3),
         ("hash", 4), ("hash", 7)],
        id="groups-and-definitions",
    ),
    pytest.param(
        "\\only*<2->{a_b} \\only<2-{oops}\n"
        "\\item[{x]y}] good \\item[{bad}\n"
        "\\foo[[x] a_b^] [a_b] \\foo<bad\n"
        "\\foo<2>\n"
        "[a_b] < a_b\n",
        [("overlay", 1), ("underscore", 1), ("optional-arg", 2), ("caret", 3),
         ("underscore", 3), ("underscore", 5)],
        id="optional-and-overlay",
    ),
    pytest.param(
        "\\{\\}\\$\\&\\%\\#\\_\\\\ \\,\n"
        "\\\n"
        "{a_b}\n"
        "\\",
        [("underscore", 3)],
        id="control-symbols",
    ),
    pytest.param(
        "$a_b^&$ $$a_b^&$$ $open\n"
        "% comment\n"
        "\n"
        "$last $$last\n",
        [("math-dollar", 1), ("math-dollar", 4), ("math-dollar", 4)],
        id="dollars",
    ),
    pytest.param(
        "\\] \\) \\[a\\[b\\] \\(a\\(b\\)\n"
        "\\[ \\(\n"
        "\\left(\\left[\\right]\n",
        [("math-delims", 1), ("math-delims", 1), ("math-delims", 1), ("math-delims", 2),
         ("math-delims", 2), ("math-delims", 3)],
        id="math-delimiters",
    ),
    pytest.param(
        "\\begin{equation}a_b^ & #\\end{equation}\n",
        [("hash", 1)],
        id="math-environment",
    ),
    pytest.param(
        "\\begin{tabular}a_b^ & #\\end{tabular}\n"
        "\\begin{tikzpicture}a_b^ & #\\end{tikzpicture}\n"
        "\\node{a_b^ & #} \\draw{a_b^ & #} \\tikzset{a_b^ & #}\n",
        [("caret", 1), ("hash", 1), ("underscore", 1)],
        id="alignment-and-tikz",
    ),
    pytest.param(
        "\\url{a_b^&#} \\textbf{a_b^&#} \\Customcolor{a_b^&#}\n"
        "\\href{a_b^&#}{a_b^&#} a_b _a a_ 10^6\n",
        [("ampersand", 1), ("caret", 1), ("hash", 1), ("underscore", 1),
         ("ampersand", 2), ("caret", 2), ("hash", 2), ("underscore", 2)],
        id="owners",
    ),
    pytest.param(
        "\\colorlet{SMCodeKeywordColor}{c_secondary_blue}\n"
        "\\definecolor{c_graz_dark}{HTML}{2B2B2B} \\SMSetColor{c_custom_red}{dark}{HTML}{FF6B6B}\n"
        "\\SMSetRole{text_on_accent}{dark}{c_true_black} \\SMDeclareMode{light_x}{}\n"
        "\\textcolor{c_custom_red}{a_b}\n",
        [("underscore", 4)],
        id="name-only-arguments",
    ),
    # A lexical check does not execute \catcode assignments.
    pytest.param(
        "\\makeatletter a_b^&# \\makeatother a_b^&#\n"
        "\\ExplSyntaxOn a_b^&# \\ExplSyntaxOff a_b^&#\n"
        "\\catcode`\\%=12 5% growth {\n"
        "\\catcode`\\_=12 a_b\n",
        [("ampersand", 1), ("caret", 1), ("hash", 1), ("underscore", 1),
         ("ampersand", 2), ("caret", 2), ("hash", 2), ("underscore", 2), ("percent", 3), ("underscore", 4)],
        id="code-regions-and-catcodes",
    ),
    pytest.param(
        "\\newcommand{\\x}[1]{\\def\\y{#1} #1} #\n"
        "\\def\\x#1{#1\n"
        "\n"
        "#1} #\n"
        "\\newcommand\\x\\\n"
        "{#1}{#1} #\n",
        [("hash", 1), ("hash", 4), ("hash", 6)],
        id="definition-depths",
    ),
])
def test_lex_golden(text, expected):
    issues = _lex(text)
    assert [(issue.code, issue.line) for issue in issues] == expected
    assert all(issue == LintIssue(issue.code, issue.message, issue.line) for issue in issues)
    if expected and expected[0][0] == "encoding":
        assert "invalid UTF-8" in issues[0].message
        assert "U+0002" in issues[1].message and "U+0000" in issues[2].message



def test_a_color_under_a_color_name_macros_name_is_warned_about(ctx):
    text = ("\\colorlet{SMTitleBoxColor}{c_secondary_blue}\n% \\colorlet{SMBulletColor}{red}\n"
            "\\definecolor{SMBulletColor}{HTML}{112233}\n\\colorlet{SMCodeKeywordColor}{c_secondary_blue}\n"
            "\\renewcommand{\\SMTitleBoxColor}{c_secondary_blue}\n")
    issues = [i for i in latex_lint.lint_text(ctx, text) if i.code == "macro-color"]
    assert [(i.line, i.severity) for i in issues] == [(1, "warning"), (3, "warning")]
    assert "\\renewcommand{\\SMTitleBoxColor}" in issues[0].message


@pytest.mark.parametrize("extra", [r"\section{Topic}", r"\slideblock{nested}", "plain text"])
def test_lint_reports_forbidden_block_content(ctx, extra):
    ctx.blocks_dir.mkdir(parents=True)
    ctx.decks_dir.mkdir(parents=True)
    ctx.slides_dir.mkdir(parents=True)
    block = ctx.blocks_dir / "topic_block.tex"
    block.write_text("%% Topics: Example\n% \\section{Comment}\n\n" + extra
                     + "\n\\slide{abc-EN-Hello} % kept\n", encoding="utf-8")
    (ctx.slides_dir / "abc-EN-Hello-current.tex").write_text("Hello\n", encoding="utf-8")
    (ctx.decks_dir / "test.tex").write_text(
        "\\documentclass{beamer}\n\\begin{document}\n"
        "\\slideblock{topic_block}\n\\end{document}\n", encoding="utf-8")
    deck, = deck_scan.scan_dir(ctx.decks_dir, False)
    result = latex_lint.check_deck_job(ctx, deck)
    assert [(i.code, i.line, i.path) for i in result.errors] == [("block-content", 4, block)]
    assert extra in result.errors[0].message
    assert not result.warnings


def test_a_hash_in_a_deck_output_folder_is_not_an_error(ctx):
    assert "hash" not in codes(ctx, "\\deckoutputfolder{U:/#Work/Talks}\n")
