# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""prose_spans.py: the regular text of a slide, the only text a spellchecker may read or change.

Proved here: a command, a URL, a key, a label, math, code or a comment is never inside a span (hand-written cases,
and every slide of the example project and the fixtures against an independent oracle); an edit never changes
anything outside the span it is in; every command the hover help documents was decided on."""
from __future__ import annotations

import random
import re
from pathlib import Path

import pytest
from conftest import EXAMPLE_PROJECT, SLIDE_TEXT

from slidemage import latex_help, latex_help_standard, latex_lint
from slidemage.ai import tasks as ai_tasks
from slidemage.alt_blocks import INCLUDEGRAPHICS_RE, iter_tex_commands
from slidemage.protected_regions import protected_spans
from slidemage.prose_spans import (
    ENVIRONMENTS, NO_PROSE, PROSE_COMMANDS, SKIPPED_BODIES, SPECIAL, SpanEdit, apply_span_edits, outside_prose,
    prose_spans, words,
)
from slidemage.tex_source import IFFALSE_RE, VERB_RE, VERBATIM_ENV_RE, blanked_verbatim, comment_start, masked_same_length

REPO = Path(__file__).resolve().parent.parent
CORPUS = sorted((REPO / "example" / "slides").glob("*.tex")) + sorted((REPO / "tests" / "fixtures").rglob("slides/*.tex"))


def texts(source: str, language: str = "en") -> list[str]:
    return [source[s.start:s.end] for s in prose_spans(source, language)]


# -- what is prose ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("source, expected", [
    (r"\href{https://x.org}{the site}", ["the site"]),
    (r"see \cite{smith2020}.", ["see"]),
    (r"see \citep[p.~3]{smith2020} too", ["see", "too"]),
    (r"$a+b$ is small", ["is small"]),
    (r"$$x$$ and \(y\) and \[z\] end", ["and", "and", "end"]),
    (r"\SMCode{teh} and \SMCmd{slide}", ["and"]),
    (r"\textcolor{red}{word}", ["word"]),
    (r"\begin{block}{Titel} body \end{block}", ["Titel", "body"]),
    (r"\cornerfigure[width=.3]{img.png}", []),
    ("% teh", []),
    ("text % a comment\nnext", ["text", "next"]),
    (r"50\% of it", ["of it"]),
    ("Visit www.uni-graz.at today", ["Visit", "today"]),
    ("Mail a.b@uni-graz.at now", ["Mail", "now"]),
    ("See https://x.org/a_b now", ["See", "now"]),
    ("File media/x.png here", ["File", "here"]),
    (r"\label{fig:x} \ref{fig:x} \eqref{eq} \url{http://a.b}", []),
    (r"\includegraphics[width=3cm]{media/teh-photo}", []),
    (r"\footnote{Note text} after", ["Note text", "after"]),
    (r"\item<2->[\textbf{x}] Item text", ["Item text"]),
    (r"line\\[-1pt] next", ["line", "next"]),
    (r"\begin{equation} teh \end{equation} after", ["after"]),
    (r"\begin{tikzpicture} \node {teh}; \end{tikzpicture} after", ["after"]),
    (r"\begin{lstlisting} teh \end{lstlisting} after", ["after"]),
    (r"a \verb|teh| b", ["a", "b"]),
    (r"\iffalse teh \fi b", ["b"]),
    (r"\def\foo#1{body text} after", ["after"]),
    (r"\providecommand{\x}[2]{#1 text} after", ["after"]),
    (r"\let\a\b rest of line" "\nnext", ["next"]),
    (r"\vbox to 0pt{\vss\hbox{overlay}} after", ["after"]),
    (r"\prevdepth=0pt after", ["after"]),
    (r"\begin{tabular}[t]{@{}c@{}} one & two \\ \end{tabular}", ["one", "two"]),
    (r"\unknownmacro{teh}[x]{y} after", ["after"]),
    (r"\SMLink{1vw}{\emph{Making a template}}", ["Making a template"]),
    (r"\begin{standardframe}{Title here} Body \end{standardframe}", ["Title here", "Body"]),
    (r'Gr\"o\ss e Sache', ["Sache"]),
    (r"Trenn\-ung hier", ["hier"]),
    (r"Fig.~3 shows", ["Fig.", "3 shows"]),
])
def test_prose_is_what_the_audience_reads(source, expected):
    assert texts(source) == expected


def test_the_protected_header_and_the_slide_version_are_never_prose():
    assert texts(SLIDE_TEXT.replace("\r\n", "\n")) == ["Hello", "First point", "Second point"]


def test_spans_carry_their_kind_and_language():
    source = r"\begin{block}{Title} Body \begin{itemize} \item One \end{itemize} \footnote{Note} \end{block}"
    assert [(source[s.start:s.end], s.kind) for s in prose_spans(source, "EN")] == [
        ("Title", "title"), ("Body", "body"), ("One", "item"), ("Note", "footnote")]
    assert {s.language for s in prose_spans(source, "EN")} == {"en"}


def test_multilingual_text_is_read_in_the_language_of_each_argument():
    two = r"\multilingualtext{Hello}{Hallo}"
    keyed = r"\multilingualtext*{EN={Hi there}, DE={Servus}, FR={Salut}}"
    assert [(two[s.start:s.end], s.language) for s in prose_spans(two, "en")] == [("Hello", "en"), ("Hallo", "de")]
    assert [(keyed[s.start:s.end], s.language) for s in prose_spans(keyed, "en")] == [
        ("Hi there", "en"), ("Servus", "de"), ("Salut", "fr")]


def test_words_leave_out_numbers_identifiers_and_short_abbreviations():
    source = "The 3rd item of the EU and NATO's v2 Gemeinde-Wahl don't"
    found = [w.text for w in words(source, prose_spans(source, "en"))]
    assert found == ["The", "item", "of", "the", "and", "NATO's", "Gemeinde", "Wahl", "don't"]


# -- every slide against an independent oracle --------------------------------------------------------------------

_ORACLE = [
    re.compile(r"(?<!\\)\$\$.*?\$\$", re.DOTALL), re.compile(r"(?<!\\)\$(?:[^$\\]|\\.)*\$"),
    re.compile(r"\\\(.*?\\\)", re.DOTALL), re.compile(r"(?<![\\])\\\[.*?\\\]", re.DOTALL),
    re.compile(r"\\[A-Za-z]*cite[A-Za-z]*\*?(?:\[[^\]]*\])*\{[^}]*\}"),
    re.compile(r"\\(?:label|ref|eqref|pageref|autoref|cref|Cref|url|input|include)\{[^}]*\}"),
    re.compile(r"\\href\{[^}]*\}"), re.compile(r"https?://[^\s{}]+"), INCLUDEGRAPHICS_RE,
    re.compile(r"\\SMC(?:ode|md)\{(?:[^{}]|\{[^{}]*\})*\}"),
]


def _oracle_regions(text: str) -> list[tuple[int, int]]:
    regions = [(m.start(), m.end()) for p in (VERBATIM_ENV_RE, IFFALSE_RE, VERB_RE) for m in p.finditer(text)]
    regions += [tuple(span) for span in protected_spans(text)]
    offset = 0
    for line in text.split("\n"):
        cut = comment_start(line)
        if cut >= 0:
            regions.append((offset + cut, offset + len(line)))
        offset += len(line) + 1
    clean = masked_same_length(blanked_verbatim(text))      # so a $ in a comment does not pair with a real one
    regions += [(m.start(), m.end()) for p in _ORACLE for m in p.finditer(clean)]
    regions += [(start, end) for _, start, end in iter_tex_commands(text)]     # every command name
    return regions


@pytest.mark.parametrize("path", CORPUS, ids=lambda p: p.name)
def test_no_span_holds_markup_on_any_slide(path):
    text = path.read_text(encoding="utf-8")
    spans = prose_spans(text)
    regions = _oracle_regions(text)
    for span in spans:
        piece = text[span.start:span.end]
        assert not SPECIAL & set(piece), piece
        clash = [text[a:b] for a, b in regions if a < span.end and span.start < b]
        assert not clash, (piece, clash[:3])


def test_the_corpus_is_not_trivial():
    """The oracle test means something only if the slides do have prose."""
    count = sum(len(prose_spans(p.read_text(encoding="utf-8"))) for p in CORPUS)
    assert len(CORPUS) > 100 and count > 1500


# -- edits never leak -----------------------------------------------------------------------------------------------

def test_an_edit_inside_a_span_changes_only_that_span():
    source = r"\textbf{Teh} market \cite{teh2020}"
    start = source.index("Teh")
    new, problems = apply_span_edits(source, [SpanEdit(start, start + 3, "Teh", "The")])
    assert (new, problems) == (r"\textbf{The} market \cite{teh2020}", [])


@pytest.mark.parametrize("before, after", [("teh2020", "the2020"), ("textbf", "textit"), ("Teh}", "The}")])
def test_an_edit_outside_the_prose_is_refused(before, after):
    source = r"\textbf{Teh} market \cite{teh2020}"
    start = source.index(before)
    new, problems = apply_span_edits(source, [SpanEdit(start, start + len(before), before, after)])
    assert new == source and problems


@pytest.mark.parametrize("after", ["a\\b", "a{b", "x$", "50%", "a~b", "two\nlines", "www.x.at"])
def test_a_replacement_with_markup_is_refused(after):
    source = "Some market text"
    new, problems = apply_span_edits(source, [SpanEdit(5, 11, "market", after)])
    assert new == source and problems


def test_an_insertion_may_not_extend_a_command_name():
    source = r"see \ldots.next"
    at = source.index(".next")
    assert apply_span_edits(source, [SpanEdit(at, at, "", "x")])[1]           # \ldotsx
    at = source.index("see") + 3
    assert apply_span_edits(source, [SpanEdit(at, at, "", "n")]) == (r"seen \ldots.next", [])


def test_a_stale_or_overlapping_edit_is_refused():
    source = "Some market text"
    assert apply_span_edits(source, [SpanEdit(5, 11, "marked", "markt")])[1]
    assert apply_span_edits(source, [SpanEdit(5, 11, "market", "m"), SpanEdit(8, 13, "ket t", "k")])[1]


def test_random_edits_never_change_text_outside_their_span():
    rng = random.Random(20261116)
    alphabet = "abcäöüß XYZ-,.'" + "\\{}$%&#^_~[]\n"
    accepted = 0
    for path in CORPUS[::3]:
        text = path.read_text(encoding="utf-8")
        spans = prose_spans(text)
        for _ in range(20):
            if spans and rng.random() < 0.6:                        # mostly inside a span, sometimes too long
                span = rng.choice(spans)
                start = rng.randint(span.start, span.end)
                stop = min(len(text), rng.randint(start, span.end + (3 if rng.random() < 0.2 else 0)))
            else:
                start = rng.randrange(len(text))
                stop = min(len(text), start + rng.randint(0, 12))
            after = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 6)))
            new, problems = apply_span_edits(text, [SpanEdit(start, stop, text[start:stop], after)])
            if problems:
                assert new == text
                continue
            accepted += 1
            assert new[:start] == text[:start] and new[start + len(after):] == text[stop:]
            assert any(s.start <= start and stop <= s.end for s in spans)
            assert not SPECIAL & set(after)
    assert accepted > 50


@pytest.mark.parametrize("path", CORPUS[::4], ids=lambda p: p.name)
def test_rewriting_every_span_adds_no_lint_error_and_keeps_the_spans(path):
    text = path.read_text(encoding="utf-8")
    spans = prose_spans(text)
    chars = list(text)
    for span in spans:
        for i in range(span.start, span.end):
            if chars[i].isalpha():
                chars[i] = "X" if chars[i].isupper() else "x"
    new = "".join(chars)

    def errors(source):
        return {(i.code, i.message) for i in latex_lint.lint_text(EXAMPLE_PROJECT, source)
                if i.severity == latex_lint.ERROR}

    assert errors(new) <= errors(text)
    assert [(s.start, s.end) for s in prose_spans(new)] == [(s.start, s.end) for s in spans]


# -- the AI proofread keeps to the prose (S7) -----------------------------------------------------------------------

def test_outside_prose_accepts_a_fix_in_the_text_and_names_one_in_markup():
    source = "\\begin{standardframe}{Teh title}\n\\item Teh point \\label{teh}\n\\end{standardframe}\n"
    assert outside_prose(source, source.replace("Teh title", "The title")) is None
    assert outside_prose(source, source.replace("Teh point", "The points")) is None
    assert "outside the regular text" in outside_prose(source, source.replace("{teh}", "{the}"))
    assert "special character" in outside_prose(source, source.replace("Teh point", "The~point"))


def test_proofreading_may_change_the_text_but_not_the_markup():
    lf = SLIDE_TEXT.replace("\r\n", "\n")
    edit = lambda before, after: {"edits": [{"before": before, "after": after}]}   # noqa: E731
    assert ai_tasks.check(EXAMPLE_PROJECT, ai_tasks.PROOFREAD, lf, edit("First point", "First points")) == (
        lf.replace("First point", "First points"), [])
    new, problems = ai_tasks.check(EXAMPLE_PROJECT, ai_tasks.PROOFREAD, lf, edit("standardframe}{Hello",
                                                                                   "standardframe}{Hallo"))
    assert new == lf.replace("{Hello}", "{Hallo}") and not problems      # the title is text
    new, problems = ai_tasks.check(EXAMPLE_PROJECT, ai_tasks.PROOFREAD, lf, edit("\\item First", "\\itemFirst"))
    assert new == lf and problems                                       # the command would become \itemFirst
    new, problems = ai_tasks.check(EXAMPLE_PROJECT, ai_tasks.PROOFREAD, lf, edit("{Hello}", "{Hello} there"))
    assert new == lf and problems                                       # text after the title's brace is not prose
    span = (lf.index("Second point"), lf.index("Second point") + len("Second point"))
    new, problems = ai_tasks.check(EXAMPLE_PROJECT, ai_tasks.PROOFREAD_SELECTION, lf, {"edits": [
        {"before": "Second point", "after": "Second \\textbf{point}"}]}, span=span)
    assert new == lf and problems


# -- every documented command was decided on ------------------------------------------------------------------------

def test_every_documented_command_and_environment_is_classified():
    commands = set(latex_help.COMMANDS) | set(latex_help_standard.COMMANDS)
    environments = set(latex_help.ENVIRONMENTS) | set(latex_help_standard.ENVIRONMENTS)
    assert not commands - set(PROSE_COMMANDS) - NO_PROSE
    assert not environments - set(ENVIRONMENTS) - SKIPPED_BODIES
    assert not set(PROSE_COMMANDS) & NO_PROSE
