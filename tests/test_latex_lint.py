from slidemage import latex_lint


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
