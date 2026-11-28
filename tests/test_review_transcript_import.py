# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path

import pytest

from slidemage import alt_blocks, deck_language, deck_scan, transcript
from slidemage.project import ProjectContext


def test_note_parser_removes_complete_commands_without_matching_literals():
    source = (
        r"Visible text "
        r"\note {outer {nested \textbf{secret}}} "
        r"\note<2>[item] {PRIVATE OVERLAY} "
        r"\note [item]<3> {PRIVATE REVERSED} "
        r"\noteworthy{public macro} "
        r"\\note{escaped literal} "
        r"\string\note{stringified literal} "
        r"\verb|\note{verbatim literal}|"
    )

    clean, notes = alt_blocks.extract_note_calls(source)

    assert notes == [
        r"outer {nested \textbf{secret}}",
        "PRIVATE OVERLAY",
        "PRIVATE REVERSED",
    ]
    assert clean.split() == (
        r"Visible text \noteworthy{public macro} \\note{escaped literal} "
        r"\string\note{stringified literal} \verb|\note{verbatim literal}|"
    ).split()


def test_resolve_deck_visibility_distinguishes_missing_and_empty_lists(ctx, tmp_path: Path):
    deck = tmp_path / "deck.tex"
    deck.write_text(
        r"\slide{aaa-EN-Always}"
        r"\conditionalslide[]{bbb-EN-Empty}"
        r"\conditionalslide{ccc-EN-Default}"
        r"\slidestep{ddd-EN-Empty}[]{1}"
        r"\slidestep{eee-EN-Default}{1}"
        r"\omitslide{fff-EN-Instructor}"
        r"\omitslideversion{ggg-EN-Instructor}{1-0-0}", encoding="utf-8")
    for version in transcript.STUDENT_VERSIONS:
        slides = transcript.resolve_deck(ctx, deck, version)
        assert [(s.slide_id, s.number) for s in slides if s.included] == [
            ("aaa", 1), ("ccc", 3), ("eee", 4)]
    assert [s.slide_id for s in transcript.resolve_deck(ctx, deck, "instructor") if s.included] == [
        "aaa", "ccc", "eee", "fff", "ggg"]
    assert [(s.slide_id, s.number, s.included) for s in slides] == [
        ("aaa", 1, True), ("bbb", 2, False), ("ccc", 3, True),
        ("eee", 4, True), ("fff", 5, False), ("ggg", 6, False)]
    assert slides[-1].path.name == "ggg-EN-Instructor-v1-0-0.tex"


def test_resolve_deck_expands_includes_in_order_and_ignores_notes(ctx, tmp_path):
    decks = tmp_path / "decks"
    (decks / "nested").mkdir(parents=True)
    deck = decks / "deck.tex"
    deck.write_text(
        r"\documentclass{article}\newcommand{\helper}{\slide{PREAMBLE}}"
        r"\input{missing-preamble-list}\begin{document}\slide{AAA-EN-First}"
        r"\input{nested/list-one}\include{shared-list}\input{nested/list-one}\end{document}",
        encoding="utf-8",
    )
    (decks / "nested/list-one.tex").write_text(
        r"\slide{BBB-EN-Second}\input{list-two}"
        r"\note<2>[item]{outer {\slide{HIDDEN-EN-Note}}\input{missing-note-list}}"
        r"\slide{CCC-EN-Fourth}", encoding="utf-8")
    (decks / "list-two.tex").write_text(r"\slide{DDD-EN-Third}", encoding="utf-8")
    (decks / "nested/list-two.tex").write_text(r"\slide{WRONG-EN-Lookup}", encoding="utf-8")
    (tmp_path / "shared-list.tex").write_text(r"\slide{ROOT-EN-Fifth}", encoding="utf-8")

    slides = transcript.resolve_deck(ctx, deck, "during-course")
    expected = "AAA BBB DDD CCC ROOT BBB DDD CCC".split()
    assert [(slide.number, slide.slide_id) for slide in slides] == list(enumerate(expected, 1))
    assert slides[0].path == ctx.slides_dir / "AAA-EN-First-current.tex"
    expanded, _ = deck_language.expand_fragments(deck_scan.read_deck(deck), strict_includes=True)
    assert [expanded.text[c.call_start:c.call_end] for c in deck_language.active_calls(expanded) if c.id == "CCC"] == [
        r"\slide{CCC-EN-Fourth}", r"\slide{CCC-EN-Fourth}"]


@pytest.mark.parametrize(("include", "error", "message"), [
    ("missing-list", FileNotFoundError, "missing-list"),
    ("cycle-a", ValueError, "cycle"),
])
def test_resolve_deck_reports_missing_and_cyclic_includes(ctx, tmp_path, include, error, message):
    decks = tmp_path / "decks"
    decks.mkdir()
    deck = decks / "deck.tex"
    deck.write_text(r"\begin{document}" + rf"\input{{{include}}}" + r"\end{document}", encoding="utf-8")
    (decks / "cycle-a.tex").write_text(r"\input{cycle-b}", encoding="utf-8")
    (decks / "cycle-b.tex").write_text(r"\input{cycle-a}", encoding="utf-8")

    scanned = deck_scan.read_deck(deck)
    # Compilation retains its permissive default.
    assert deck_language.compile_deck(ctx, scanned, "EN")[0].text == scanned.text
    with pytest.raises(error, match=message):
        transcript.resolve_deck(ctx, deck, "during-course")


def test_shipped_manual_resolves_every_slide_in_both_student_versions():
    ctx = ProjectContext.at(Path(__file__).resolve().parents[1] / "example")
    deck = next(d for d in deck_scan.scan_decks(ctx) if d.name == "slidemage-manual")
    language = transcript.deck_language_of(deck.text).upper()
    calls = [slot.call for slot in deck_language.deck_slots(ctx, deck, language)]

    for version in transcript.STUDENT_VERSIONS:
        slides = transcript.resolve_deck(ctx, deck.path, version)
        assert len(slides) == sum(c.included_in(version) for c in calls)
        assert all(slide.included for slide in slides)
        assert [slide.slide_id for slide in slides].count("1mu") == 2


@pytest.fixture
def translated_project(tmp_path: Path):
    (tmp_path / "decks").mkdir()
    slides = tmp_path / "slides"
    slides.mkdir()
    (slides / "aaa-EN-One-current.tex").write_text(
        "%% DE translation: ddd-DE-Eins\n", encoding="utf-8")
    (slides / "ddd-DE-Eins-current.tex").write_text(
        "%% Translation of: aaa-EN-One\n", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(("call", "command"), [
    (r"\slide{aaa-EN-One}", "input"),
    (r"\slideversion{aaa-EN-One}{1-0-0}", "include"),
])
def test_resolve_german_deck_uses_linked_partner(ctx, translated_project: Path, call, command):
    decks = translated_project / "decks"
    (decks / "list.tex").write_text(call, encoding="utf-8")
    deck = decks / "deck.tex"
    deck.write_text(
        r"\documentclass{beamer}\decklanguage[de]\begin{document}"
        + rf"\{command}{{list}}" + r"\end{document}", encoding="utf-8")

    slides = transcript.resolve_deck(ctx, deck, "after-course")

    assert [(s.number, s.slide_id, s.path, s.included, s.chapter) for s in slides] == [
        (1, "ddd", translated_project / "slides/ddd-DE-Eins-current.tex", True, 0)]


@pytest.mark.parametrize(("language", "slide_id", "filename"), [
    ("en", "aaa", "aaa-EN-One-current.tex"),
    ("de", "ddd", "ddd-DE-Eins-current.tex"),
])
def test_resolve_deck_folds_explicit_partner_in_original_slot(ctx, translated_project, language, slide_id, filename):
    deck = translated_project / "decks/deck.tex"
    deck.write_text(
        r"\documentclass{beamer}" + rf"\decklanguage[{language}]"
        r"\begin{document}\section{First}\slide{aaa-EN-One}"
        r"\section{Last}\slide{ddd-DE-Eins}\slide{bbb-EN-Two}\end{document}",
        encoding="utf-8")

    slides = transcript.resolve_deck(ctx, deck, "after-course")

    assert [(s.number, s.slide_id, s.chapter) for s in slides] == [
        (1, slide_id, 1), (2, "bbb", 2)]
    assert slides[0].path == translated_project / "slides" / filename


def test_resolve_deck_ignores_inactive_and_note_calls(ctx, tmp_path):
    deck = tmp_path / "deck.tex"
    deck.write_text(
        r"\documentclass{beamer}\begin{document}\slide{aaa-EN-First}" "\n"
        "\\iffalse\n\\slide{bbb-EN-Conditional}\n\\fi\n"
        "\\begin{verbatim}\n\\slide{ddd-EN-Verbatim}\n\\end{verbatim}\n"
        "% \\slide{eee-EN-Comment}\n"
        r"\note{outer {\slide{fff-EN-Note}}}\slide{ccc-EN-Last}\end{document}", encoding="utf-8")

    assert [c.id for c in deck_language.active_calls(deck_scan.read_deck(deck))] == ["aaa", "ccc"]
    slides = transcript.resolve_deck(ctx, deck, "after-course")
    assert [(s.number, s.slide_id) for s in slides] == [(1, "aaa"), (2, "ccc")]


def test_read_deck_accepts_crlf_body_fragments_without_changing_discovery(ctx, tmp_path):
    fragment = tmp_path / "fragment.tex"
    text = "\\section{Body}\r\n\\slide{aaa-EN-One}\r\n\\input{child}\r\n"
    fragment.write_bytes(text.encode())
    (tmp_path / "child.tex").write_text(r"\slide{aaa-EN-Two}", encoding="utf-8")
    deck = tmp_path / "deck.tex"
    deck.write_text(r"\documentclass{beamer}\begin{document}\end{document}", encoding="utf-8")
    wrapper = tmp_path / "_wrapper.tex"
    wrapper.write_bytes(deck.read_bytes())

    read = deck_scan.read_deck(fragment, archived=True)
    assert read.path == fragment and read.archived and read.text == text
    assert read.preamble_end is None and read.chapters[0].title == "Body"
    assert [d.path for d in deck_scan.scan_dir(tmp_path, False)] == [deck]
    assert deck_scan.read_deck(wrapper).name == "_wrapper"
    slides = transcript.resolve_deck(ctx, fragment, "during-course")
    assert [(slide.slide_id, slide.number) for slide in slides] == [("aaa", 1), ("aaa", 2)]
