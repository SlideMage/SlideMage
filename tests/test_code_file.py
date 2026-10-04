"""\\SMCodeFile: pre-render check and transcript."""
from pathlib import Path

from slidemage import latex_lint, transcript


def test_lint_reports_a_missing_code_file(tmp_path, monkeypatch):
    monkeypatch.setattr(latex_lint, "PROJECT_ROOT", tmp_path)
    (tmp_path / "snippets").mkdir()
    (tmp_path / "snippets" / "abc-1.tex").write_text("\\item x\n", encoding="utf-8")
    codes = [i.code for i in latex_lint.lint_text("\\SMCodeFile{snippets/abc-1.tex}\n")]
    assert "code-file" not in codes
    issues = latex_lint.lint_text("x\n\\SMCodeFile[firstline=2]{snippets/no_such.tex}\n")
    missing = [i for i in issues if i.code == "code-file"]
    assert len(missing) == 1 and missing[0].line == 2 and missing[0].severity == latex_lint.ERROR
    assert "underscore" not in [i.code for i in issues]  # a path argument


def test_transcript_shows_the_code_file_as_a_code_block(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(transcript, "PROJECT_ROOT", tmp_path)
    (tmp_path / "snippets").mkdir()
    (tmp_path / "snippets" / "abc-1.tex").write_text(
        "% first\n\\begin{itemize}\n\t\\item A & B\n\\end{itemize}\n% last\n", encoding="utf-8")
    path = tmp_path / "abc-EN-Code-current.tex"
    path.write_text(
        "\\begin{standardframe}{Code}\n\\begin{itemize}\\item Live text\\end{itemize}\n"
        "\\SMCodeFile[firstline=2, lastline=4]{snippets/abc-1.tex}\n\\end{standardframe}\n",
        encoding="utf-8")
    entry = transcript.render_slide(transcript.DeckSlide(1, "abc", path, True), "during-course", {})
    assert entry is not None
    assert "- Live text" in entry.body
    assert "```latex\n\\begin{itemize}\n  \\item A & B\n\\end{itemize}\n```" in entry.body
    assert "% first" not in entry.body and "% last" not in entry.body

    html = transcript.markdown_to_html_body(entry.body)
    assert '<pre><code class="language-latex">\\begin{itemize}\n  \\item A &amp; B\n\\end{itemize}</code></pre>' in html
