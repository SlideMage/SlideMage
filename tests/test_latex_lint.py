# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
import pytest

from slidemage import deck_scan, latex_lint
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
    ("\\begin{gothamtable}{lcc}\na & b & c\\\\\n\\end{gothamtable}\n", True),
    ("\\begin{gothamtable}{lc}\n\\end{gothamtable}\n", True),
    ("\\begin{gothamtable}[gap=12pt]{lcc}\n\\end{gothamtable}\n", False),
    ("\\begin{gothamtable}{@{}l<{\\hspace{12pt}}c@{}}\n\\end{gothamtable}\n", False),
    ("% \\begin{gothamtable}{lcc}\n", False),
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
