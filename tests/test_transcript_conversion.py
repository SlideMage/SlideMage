# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Visible transcript artifacts from the SlideMage manual and IA2 decks."""
from pathlib import Path

from slidemage import transcript
from slidemage.project import ProjectContext


def _render(ctx, tmp_path: Path, source: str):
    path = tmp_path / "abc-EN-Test-current.tex"
    path.write_text(source, encoding="utf-8")
    entry = transcript.render_slide(ctx, transcript.DeckSlide(1, "abc", path, True), "during-course", {})
    assert entry is not None
    return entry


def _frame(body: str) -> str:
    return "\\begin{standardframe}{T}\n" + body + "\n\\end{standardframe}\n"


def test_inline_code_is_verbatim(ctx, tmp_path):
    entry = _render(ctx, tmp_path, _frame(
        r"\SMCmd{input}\SMCode{\{SlideMage\_base\}}, \SMCmd{slideversion}\SMCode{\{abc-EN-X\}\{1-0-0\}}, "
        r"\SMCode{--project}, \SMCode{SMTable[gap=12pt]}, "
        r"\SMCode{\textbackslash setfootnotesymbols\{\textdagger,\S\}}, "
        r"\SMCmd{multilingualtext}\SMCode{\{Hello\}\{Hallo\}}"))
    for span in (r"`\input{SlideMage_base}`", r"`\slideversion{abc-EN-X}{1-0-0}`", "`--project`",
                 "`SMTable[gap=12pt]`", r"`\setfootnotesymbols{†,§}`", r"`\multilingualtext{Hello}{Hallo}`"):
        assert span in entry.body


def test_maths_symbols_fractions_and_underbraces(ctx, tmp_path):
    entry = _render(ctx, tmp_path, _frame(
        r"Menu $\rightarrow$ Item; $S=\dfrac{E[R]-r_f}{\sigma}$; "
        r"$r_f + \SMUnderbrace{\beta\,x}{risk premium}$; \EUR\,100"))
    assert "Menu → Item" in entry.body
    assert "$S=(E[R]-r_f)/σ$" in entry.body
    assert "β x [risk premium]" in entry.body
    assert "€ 100" in entry.body


def test_layout_commands_leave_nothing_behind(ctx, tmp_path):
    entry = _render(ctx, tmp_path, _frame(
        "\\shrinklists{1}\n\\fontsize{6.4}{7.6}\\selectfont\n"
        "\\begin{enumerate}\\setcounter{enumi}{5}\n"
        "\\SMTocLabelFlushLeft{\\dimexpr3.6pt+\\SMTocLabelExtraGap\\relax}\n"
        "\\ifnum\\value{enumi}=5 \\item[] \\fi\n\\item Real text\n\\end{enumerate}"))
    assert entry.body == "1. Real text"


def test_tikzillustration_is_described_not_transcribed(ctx, tmp_path):
    entry = _render(ctx, tmp_path, _frame(
        "Before.\n\\begin{tikzillustration}[x=1cm, part/.style={draw}]{abc-tikz}\n"
        "\\node[part] at (0,0) {Label};\n\\end{tikzillustration}\nAfter."))
    assert all(leak not in entry.body for leak in ("Label", "tikzillustration", "abc-tikz"))
    assert [image.reference for image in entry.images] == ["tikz:abc-tikz"]


def test_figure_helpers_drop_paths_keep_content(ctx, tmp_path):
    entry = _render(ctx, tmp_path, _frame(
        "\\sectionfigure{media/a.pdf}\n"
        "\\cornerfigure[corner=e]{\\begin{minipage}{3cm}Kept text\\end{minipage}}\n"
        "\\fitfigure[top=here]{media/b.png}\n"
        "\\begin{besidefigure}[height=4cm, border]{media/c.png}Beside text\\end{besidefigure}"))
    assert "media/" not in entry.body and "corner=e" not in entry.body
    assert "Kept text" in entry.body and "Beside text" in entry.body


def test_local_macros_are_expanded(ctx, tmp_path):
    entry = _render(ctx, tmp_path,
                    "\\providecommand{\\pair}[2]{#1 \\hfill #2}\n"
                    + _frame("\\pair{\\SMCode{key}}{its meaning}"))
    assert entry.body == "`key` its meaning"


def test_nested_tables_hyperlinks_and_escaped_ampersands(ctx, tmp_path):
    entry = _render(ctx, tmp_path, _frame(
        "\\begin{tabular}{cc}\n"
        "\\hyperlink{xyz}{\\begin{tabular}{c}A\\\\[-2pt] cap A\\end{tabular}} &"
        " B \\& C \\\\[1pt]\n"
        "D & E\n\\end{tabular}"))
    assert "| A cap A | B & C |" in entry.body
    assert "| D | E |" in entry.body
    assert "xyz" not in entry.body and "[" not in entry.body


def test_progress_strip_warning_sign_and_overlay_specs(ctx, tmp_path):
    entry = _render(ctx, tmp_path, _frame(
        "\\progressstrip{One,Two,Three}{2}\n"
        "\\only<4>{Step four} \\textcolor<4>{red}{word}\n"
        "\\SMWarningSign{385pt}{200pt}{Watch out!}{2.5}{-8}"))
    assert "One → **Two** → Three" in entry.body
    assert "Step four word" in entry.body
    assert "⚠ Watch out!" in entry.body
    assert "<4>" not in entry.body and "2.5" not in entry.body


def test_the_leaks_found_in_the_ia2_transcripts_are_gone(ctx, tmp_path):
    entry = _render(ctx, tmp_path, _frame(
        "\\begin{itemize}\n\\item Total risk \\textbackslash\\ Symmetric risk\n"
        "\\begin{SMAlphaItemize}\n\\item Outer\n\\begin{itemize}\n\\item Deep one\n\\item Deep two\n"
        "\\end{itemize}\n\\end{SMAlphaItemize}\n\\end{itemize}\n"
        "\\begin{flalign*}\n\\beta_i &= \\frac{\\dfrac{a}{b}}{\\dfrac{c}{d}} &\n\\end{flalign*}\n"
        "$R = \\max[x] - \\min[x]$, $\\sqrt[2]{\\sigma^2}$, $r_{i,t}$\n"
        "\\tikz[remember picture, baseline]{\\node[SMImageBorder, inner sep=0pt] (m) "
        "{\\includegraphics[height=3cm]{media/x.png}};}\n"
        "\\begin{tikzpicture}[overlay]\\node at (0,0) {\\begin{tikzpicture}\\node {Inner label};"
        "\\end{tikzpicture}\\hspace{0.03\\linewidth}};\\end{tikzpicture}"))
    body = entry.body
    assert "Total risk \\ Symmetric risk" in body
    assert "Deep one" in body and "Deep two" in body and "\x00" not in body
    assert "β_i = (a/b)/(c/d)" in body and "&" not in body
    assert "max[x] - min[x]" in body and "√(σ^2)" in body and "r_(i,t)" in body
    assert "Inner label" in body
    for leak in ("tikzpicture", "remember picture", "inner sep", "0.03", "[2]"):
        assert leak not in body, leak


def test_a_text_box_keeps_its_text_and_drops_its_keys_as_do_parbox_and_rotatebox(ctx, tmp_path):
    entry = _render(ctx, tmp_path, _frame(
        "\\SMTextBox<2->[anchor=center, xshift=-74.9pt, border={rgb,255:red,146;green,208;blue,80}, "
        "font={\\fontsize{8.6}{10.4}\\selectfont}]{No new \\textit{insights}.}\n"
        "\\cornerfigure[corner=nw]{\\fontsize{9}{11}\\selectfont\\parbox[t]{87.9bp}{\\raggedright Quiz}}\n"
        "\\cornerfigure{\\rotatebox{90}{\\Large Feedback}}"))
    assert "No new *insights*." in entry.body
    assert "Quiz" in entry.body and "Feedback" in entry.body
    for leak in ("anchor", "xshift", "rgb", "<2->", "[t]", "87.9", "90"):
        assert leak not in entry.body, leak


def test_sideimageframe_standout_frame_and_quote_source(ctx, tmp_path):
    side = _render(ctx, tmp_path, "\\begin{sideimageframe}{Side title}{media/p.pdf}\n"
                             "Body text\n\\end{sideimageframe}\n")
    assert (side.title, side.body) == ("Side title", "Body text")
    standout = _render(ctx, tmp_path, "\\SMAgendaTitle{Standout}\n\\begin{frame}[standout]\n"
                                 "One statement\n\\end{frame}\n")
    assert (standout.title, standout.body) == ("Standout", "One statement")
    quote = _render(ctx, tmp_path, "\\quotesource{Source: A,\n  B.}\n"
                              "\\SMAgendaTitle{Q}\n\\quoteframe{Words.}{Author}\n")
    assert quote.source == "Source: A, B."


def test_table_of_contents_lists_the_deck_chapters(tmp_path, monkeypatch):
    slides = tmp_path / "slides"
    slides.mkdir()
    ctx = ProjectContext.at(tmp_path)
    (slides / "aaa-EN-Contents-current.tex").write_text(_frame(
        "\\begin{enumerate}\\tableofcontents[sections={2-3},hideallsubsections]"
        "\\end{enumerate}"), encoding="utf-8")
    for slide_id in ("aab", "aac", "aad"):
        (slides / f"{slide_id}-EN-X-current.tex").write_text(_frame(f"Text {slide_id}"), encoding="utf-8")
    deck = tmp_path / "deck.tex"
    deck.write_text(
        "\\begin{document}\n\\slide{aaa-EN-Contents}\n"
        "\\section{First}\n\\slide{aab-EN-X}\n"
        "\\section{Second}\n\\slide{aac-EN-X}\n"
        "\\section{Third \\SMCode{x}}\n\\slide{aad-EN-X}\n\\end{document}\n",
        encoding="utf-8")
    monkeypatch.setattr(transcript.alt_images, "load_store", lambda _ctx: {})
    monkeypatch.setattr(transcript.alt_images, "load_slide_notes", lambda _ctx: {})
    result = transcript.generate(ctx, deck, "during-course")
    assert result.slides[0].body == "2. Second (slide 3)\n3. Third `x` (slide 4)"


def test_the_journal_citation_styles_add_the_journal_after_the_year():
    from slidemage import bibliography
    entries = {"k22": bibliography.BibEntry("k22", "article", {
        "author": "Kaiser, Tim", "year": "2022", "title": "T", "journaltitle": "Journal of Financial Economics"})}
    assert bibliography.format_citation("k22", entries, "paren_journal") == "(Kaiser, 2022, Journal of Financial Economics)"
    assert bibliography.format_citation("k22", entries, "text_journal") == "Kaiser (2022, Journal of Financial Economics)"
