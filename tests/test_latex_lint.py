# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
import pytest

from slidemage import deck_scan, latex_lint
from slidemage.latex_lint import LintIssue, _lex
from conftest import make_project
from slidemage.project import ProjectContext


def test_student_lint_skips_omitslide(ctx, tmp_path, monkeypatch):
    (tmp_path / "deck.tex").write_text(
        "\\documentclass{beamer}\n\\begin{document}\n"
        "\\omitslide{abc-EN-Missing}\n\\end{document}\n", encoding="utf-8")
    deck, = deck_scan.scan_dir(tmp_path, False)
    for version in ("during-course", "after-course"):
        assert not latex_lint.check_deck_job(ctx, deck, version).errors
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
    ("\\begin{SMTable}{lc}\n\\end{SMTable}\n", True),
    ("\\begin{SMTable}[gap=12pt]{lcc}\n\\end{SMTable}\n", False),
    ("\\begin{SMTable}{@{}l<{\\hspace{12pt}}c@{}}\n\\end{SMTable}\n", False),
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
            "% \\fullcite{commented2000}\n\\parencite{\\mykey} \\parencite{#1} \\textcite{lee1999}\n")
    assert latex_lint.cited_keys(text) == ["smith2020", "doe2021", "lee1999"]
    assert latex_lint.cited_keys("no citations here") == []


@pytest.mark.parametrize("name", ["fragment", "fragment.tex"])
def test_lint_checks_included_fragment_slides(tmp_path, monkeypatch, name):
    root = make_project(monkeypatch, tmp_path)
    ctx = ProjectContext.at(root)
    (root / "decks/fragment.tex").write_text("\\slide{abc-EN-Hello}\n")
    (root / "decks/test.tex").write_text(
        "\\documentclass{beamer}\n\\begin{document}\n"
        + f"\\include{{{name}}}\n\\end{{document}}\n")
    slide = root / "slides/abc-EN-Hello-current.tex"
    slide.write_text("{")
    deck, = deck_scan.scan_dir(root / "decks", False)
    result = latex_lint.check_deck_job(ctx, deck)
    assert result.files_checked == 3
    assert result.errors and all(i.path == slide for i in result.errors)


# Keep messages here too: changing a diagnostic is observable even if its code and line stay the same.
_MESSAGES = {
    "ampersand": "unescaped & in running text -- write \\& (or put it inside a table/align)",
    "caret": (
        "'^' in running text outside math -- put the exponent in $...$ or write \\textasciicircum (LaTeX: "
        "\"Missing $ inserted\")"
    ),
    "hash": "unescaped # -- write \\# (a macro parameter outside a definition is an error)",
    "underscore": "'_' in running text outside math -- write \\_ (LaTeX: \"Missing $ inserted\")",
    "percent": (
        "'%' directly after a digit starts a comment -- everything after it on this line is ignored; "
        "write \\% for a percent sign"
    ),
}


def _issue(code, line, message=None):
    return LintIssue(code, _MESSAGES[code] if message is None else message, line)


@pytest.mark.parametrize("text,expected", [
    pytest.param("", [], id="empty"),
    pytest.param("$unclosed", [_issue("math-dollar", 1, "$ opened here is never closed")], id="inline-math-eof"),
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
        [
            _issue("percent", 2),
            _issue("ampersand", 11),
            _issue("ampersand", 12),
            _issue("caret", 12),
            _issue("hash", 12),
            _issue("underscore", 12),
        ],
        id="masking",
    ),
    pytest.param(
        "\ufffd\x01\n"
        "\x02\ufffd\n"
        "\t\r\n"
        "\x00\n",
        [
            _issue("encoding", 1,
                   "invalid UTF-8 (U+FFFD replacement character) -- the file's encoding is damaged here"),
            _issue("encoding", 2,
                   "control character U+0002 in the source (LuaTeX: \"Text line contains an invalid character\")"),
            _issue("encoding", 4,
                   "control character U+0000 in the source (LuaTeX: \"Text line contains an invalid character\")"),
        ],
        id="encoding",
    ),
    pytest.param(
        "\\end{none}\n"
        "\\begin{a}\n"
        "\\begin{b}\n"
        "\\end{a}\n"
        "\\begin{c}\\end{d}\n"
        "\\begin{e}\n",
        [
            _issue("environments", 1, "\\end{none} without a matching \\begin{none}"),
            _issue("environments", 3, "\\begin{b} is not closed before \\end{a} on line 4"),
            _issue("environments", 5, "\\end{d} does not match the open \\begin{c} (line 5)"),
            _issue("environments", 5, "\\begin{c} is never closed"),
            _issue("environments", 6, "\\begin{e} is never closed"),
        ],
        id="environments",
    ),
    # Environment matches consume embedded newlines without advancing the scanner's line counter.
    pytest.param(
        "\\begin \n"
        "{ a }\n"
        "{\n"
        "\\end{a}\n",
        [
            _issue("braces", 2, "opening { is never closed"),
        ],
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
        [
            _issue("braces", 1, "closing } without a matching {"),
            _issue("braces", 1, "opening { is never closed"),
            _issue("hash", 2),
            _issue("hash", 3),
            _issue("hash", 4),
            _issue("hash", 7),
        ],
        id="groups-and-definitions",
    ),
    pytest.param(
        "\\only*<2->{a_b} \\only<2-{oops}\n"
        "\\item[{x]y}] good \\item[{bad}\n"
        "\\foo[[x] a_b^] [a_b] \\foo<bad\n"
        "\\foo<2>\n"
        "[a_b] < a_b\n",
        [
            _issue("overlay", 1, "overlay specification '<' is never closed with '>'"),
            _issue("underscore", 1),
            _issue("optional-arg", 2, "\\item[ label has no closing ] on this line"),
            _issue("caret", 3),
            _issue("underscore", 3),
            _issue("underscore", 3),
            _issue("underscore", 5),
            _issue("underscore", 5),
        ],
        id="optional-and-overlay",
    ),
    pytest.param(
        "\\{\\}\\$\\&\\%\\#\\_\\\\ \\,\n"
        "\\\n"
        "{a_b}\n"
        "\\",
        [
            _issue("underscore", 3),
        ],
        id="control-symbols",
    ),
    pytest.param(
        "$a_b^&$ $$a_b^&$$ $open\n"
        "% comment\n"
        "\n"
        "$last $$last\n",
        [
            _issue("math-dollar", 1, "$ opened here is not closed before the next blank line"),
            _issue("math-dollar", 4, "$ opened here is not closed before the next blank line"),
            _issue("math-dollar", 4, "$$ opened here is never closed"),
        ],
        id="dollars",
    ),
    pytest.param(
        "\\] \\) \\[a\\[b\\] \\(a\\(b\\)\n"
        "\\[ \\(\n"
        "\\left(\\left[\\right]\n",
        [
            _issue("math-delims", 1, "\\] without a matching \\["),
            _issue("math-delims", 1, "\\) without a matching \\("),
            _issue("math-delims", 1, "\\[ opened again before the previous one was closed"),
            _issue("math-delims", 2, "\\( opened here is never closed by \\)"),
            _issue("math-delims", 2, "\\[ opened here is never closed by \\]"),
            _issue("math-delims", 3, "2 \\left but 1 \\right in this file"),
        ],
        id="math-delimiters",
    ),
    pytest.param(
        "\\begin{equation}a_b^ & #\\end{equation}\n",
        [
            _issue("hash", 1),
        ],
        id="math-environment",
    ),
    pytest.param(
        "\\begin{tabular}a_b^ & #\\end{tabular}\n"
        "\\begin{tikzpicture}a_b^ & #\\end{tikzpicture}\n"
        "\\node{a_b^ & #} \\draw{a_b^ & #} \\tikzset{a_b^ & #}\n",
        [
            _issue("caret", 1),
            _issue("hash", 1),
            _issue("underscore", 1),
        ],
        id="alignment-and-tikz",
    ),
    pytest.param(
        "\\url{a_b^&#} \\textbf{a_b^&#} \\Customcolor{a_b^&#}\n"
        "\\href{a_b^&#}{a_b^&#} a_b _a a_ 10^6\n",
        [
            _issue("ampersand", 1),
            _issue("ampersand", 1),
            _issue("caret", 1),
            _issue("hash", 1),
            _issue("hash", 1),
            _issue("underscore", 1),
            _issue("ampersand", 2),
            _issue("caret", 2),
            _issue("caret", 2),
            _issue("hash", 2),
            _issue("underscore", 2),
            _issue("underscore", 2),
        ],
        id="owners",
    ),
    # A lexical check does not execute \catcode assignments.
    pytest.param(
        "\\makeatletter a_b^&# \\makeatother a_b^&#\n"
        "\\ExplSyntaxOn a_b^&# \\ExplSyntaxOff a_b^&#\n"
        "\\catcode`\\%=12 5% growth {\n"
        "\\catcode`\\_=12 a_b\n",
        [
            _issue("ampersand", 1),
            _issue("caret", 1),
            _issue("hash", 1),
            _issue("underscore", 1),
            _issue("ampersand", 2),
            _issue("caret", 2),
            _issue("hash", 2),
            _issue("underscore", 2),
            _issue("percent", 3),
            _issue("underscore", 4),
        ],
        id="code-regions-and-catcodes",
    ),
    pytest.param(
        "\\newcommand{\\x}[1]{\\def\\y{#1} #1} #\n"
        "\\def\\x#1{#1\n"
        "\n"
        "#1} #\n"
        "\\newcommand\\x\\\n"
        "{#1}{#1} #\n",
        [
            _issue("hash", 1),
            _issue("hash", 4),
            _issue("hash", 6),
        ],
        id="definition-depths",
    ),
])
def test_lex_golden(text, expected):
    # Includes ordering and duplicates, plus the default source/path on each cached issue.
    assert _lex(text) == tuple(expected)
