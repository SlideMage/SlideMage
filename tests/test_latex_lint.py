import pytest

from slidemage import deck_editor, deck_scan, latex_lint
from conftest import make_project


def test_student_lint_skips_omitslide(tmp_path, monkeypatch):
    (tmp_path / "deck.tex").write_text(
        "\\documentclass{beamer}\n\\begin{document}\n"
        "\\omitslide{abc-EN-Missing}\n\\end{document}\n", encoding="utf-8")
    deck, = deck_scan._scan_dir(tmp_path, False)
    monkeypatch.setattr(deck_editor, "SLIDES_DIR", tmp_path / "slides")
    for version in ("during-course", "after-course"):
        assert not latex_lint.check_deck_job(deck, version).errors
    assert [i.code for i in latex_lint.check_deck_job(deck, "instructor").errors] == ["slide-file"]


def codes(text):
    return [i.code for i in latex_lint.lint_text(text)]


def test_table_edges_flags_plain_spec():
    assert "table-edges" in codes("\\begin{gothamtable}{lcc}\na & b & c\\\\\n\\end{gothamtable}\n")


def test_table_edges_accepts_gap_option_and_flush_spec():
    assert "table-edges" not in codes("\\begin{gothamtable}[gap=12pt]{lcc}\n\\end{gothamtable}\n")
    assert "table-edges" not in codes("\\begin{gothamtable}{@{}l<{\\hspace{12pt}}c@{}}\n\\end{gothamtable}\n")


def test_table_edges_ignores_comments():
    assert "table-edges" not in codes("% \\begin{gothamtable}{lcc}\n")


def test_heading_text_above_a_list():
    bad = "\\begin{standardframe}{T}\n\t\\textbf{Mispricing example}\n\t\\begin{itemize}\n\t\\item a\n\t\\end{itemize}\n\\end{standardframe}\n"
    good = "\\begin{standardframe}{T}\n\t\\begin{itemize}\n\t\\item \\textbf{Mispricing example}\n\t\\end{itemize}\n\\end{standardframe}\n"
    assert "heading-text" in codes(bad)
    assert "heading-text" not in codes(good)


def test_table_edges_is_a_warning():
    issue = next(i for i in latex_lint.lint_text("\\begin{gothamtable}{lc}\n\\end{gothamtable}\n")
                 if i.code == "table-edges")
    assert issue.severity == latex_lint.WARNING
    assert issue.line == 1


def test_cited_keys_are_listed_once_in_order_without_comments_or_macro_keys():
    text = ("\\footnote{\\fullcite{smith2020,doe2021}} \\textcite[p.~3]{doe2021}\n"
            "% \\fullcite{commented2000}\n\\parencite{\\mykey} \\parencite{#1} \\textcite{lee1999}\n")
    assert latex_lint.cited_keys(text) == ["smith2020", "doe2021", "lee1999"]
    assert latex_lint.cited_keys("no citations here") == []


@pytest.mark.parametrize("name", ["fragment", "fragment.tex"])
def test_lint_checks_included_fragment_slides(tmp_path, monkeypatch, name):
    root = make_project(monkeypatch, tmp_path)
    monkeypatch.setattr(latex_lint, "DECKS_DIR", root / "decks")
    (root / "decks/fragment.tex").write_text("\\slide{abc-EN-Hello}\n")
    (root / "decks/test.tex").write_text(
        "\\documentclass{beamer}\n\\begin{document}\n"
        + f"\\include{{{name}}}\n\\end{{document}}\n")
    slide = root / "slides/abc-EN-Hello-current.tex"
    slide.write_text("{")
    deck, = deck_scan._scan_dir(root / "decks", False)
    result = latex_lint.check_deck_job(deck)
    assert result.files_checked == 3
    assert result.errors and all(i.path == slide for i in result.errors)
