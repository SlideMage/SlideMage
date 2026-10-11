from pathlib import Path

import pytest

from slidemage import alt_blocks, deck_language, deck_scan, slide_language, transcript


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
    assert "PRIVATE" not in clean
    assert r"\noteworthy{public macro}" in clean
    assert r"\\note{escaped literal}" in clean
    assert r"\string\note{stringified literal}" in clean
    assert r"\verb|\note{verbatim literal}|" in clean


def test_render_slide_uses_note_sanitized_title_body_and_images(tmp_path: Path):
    path = tmp_path / "abc-EN-Question-current.tex"
    path.write_text(
        r"\begin{standardframe}{Clean title \note{PRIVATE TITLE}}"
        r"Visible body. \note<2>[item]{PRIVATE BODY "
        r"\includegraphics{private.png}}"
        r"\end{standardframe}",
        encoding="utf-8",
    )

    entry = transcript.render_slide(
        transcript.DeckSlide(1, "abc", path, True), "during-course", {}
    )

    assert entry is not None
    assert entry.title == "Clean title"
    assert "Visible body." in entry.body
    assert "PRIVATE" not in entry.title + entry.body
    assert entry.images == []


def test_resolve_deck_visibility_distinguishes_missing_and_empty_lists(tmp_path: Path):
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
        slides = transcript.resolve_deck(deck, version)
        assert [(s.slide_id, s.number) for s in slides if s.included] == [
            ("aaa", 1), ("ccc", 3), ("eee", 4)]
    assert [s.slide_id for s in transcript.resolve_deck(deck, "instructor") if s.included] == [
        "aaa", "ccc", "eee", "fff", "ggg"]
    assert [(s.slide_id, s.number, s.included) for s in slides] == [
        ("aaa", 1, True), ("bbb", 2, False), ("ccc", 3, True),
        ("eee", 4, True), ("fff", 5, False), ("ggg", 6, False)]
    assert slides[-1].path.name == "ggg-EN-Instructor-v1-0-0.tex"
    assert transcript.deck_version_of(r"\deckversion[]") == "instructor"


def test_resolve_deck_expands_relative_and_project_includes_in_order(
    tmp_path: Path, monkeypatch
):
    project = tmp_path / "project"
    decks = project / "decks"
    (decks / "nested").mkdir(parents=True)
    (project / "slides").mkdir()
    (decks / "deck.tex").write_text(
        r"\documentclass{article}"
        r"\newcommand{\helper}{\slide{PREAMBLE}}"
        r"\input{missing-preamble-list}"
        r"\begin{document}"
        r"\slide{AAA-EN-First}"
        r"\input{nested/list-one}"
        r"\include{shared-list}"
        r"\input{nested/list-one}"
        r"\note{\input{missing-note-list}}"
        r"\end{document}",
        encoding="utf-8",
    )
    (decks / "nested" / "list-one.tex").write_text(
        r"\slide{BBB-EN-Second}"
        r"\input{list-two}"
        r"\slide{CCC-EN-Fourth}",
        encoding="utf-8",
    )
    (decks / "list-two.tex").write_text(
        r"\slide{DDD-EN-Third}", encoding="utf-8"
    )
    (decks / "nested" / "list-two.tex").write_text(
        r"\slide{WRONG-NESTED-LOOKUP}", encoding="utf-8"
    )
    (project / "shared-list.tex").write_text(
        r"\slide{ROOT-EN-Fifth}", encoding="utf-8"
    )
    monkeypatch.setattr(transcript, "PROJECT_ROOT", project)
    monkeypatch.setattr(transcript, "SLIDES_DIR", project / "slides")

    slides = transcript.resolve_deck(decks / "deck.tex", "during-course")

    assert [(slide.slide_id, slide.number) for slide in slides] == [
        ("AAA", 1),
        ("BBB", 2),
        ("DDD", 3),
        ("CCC", 4),
        ("ROOT", 5),
        ("BBB", 6),
        ("DDD", 7),
        ("CCC", 8),
    ]
    assert slides[0].path == project / "slides" / "AAA-EN-First-current.tex"


def test_resolve_deck_supports_body_only_fragments(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    fragment = project / "fragment.tex"
    child = project / "child.tex"
    fragment.write_text(r"\slide{BODY-EN-One}\input{child}", encoding="utf-8")
    child.write_text(r"\slide{BODY-EN-Two}", encoding="utf-8")
    monkeypatch.setattr(transcript, "PROJECT_ROOT", project)
    monkeypatch.setattr(transcript, "SLIDES_DIR", project / "slides")

    slides = transcript.resolve_deck(fragment, "during-course")

    assert [(slide.slide_id, slide.number) for slide in slides] == [
        ("BODY", 1),
        ("BODY", 2),
    ]


@pytest.mark.parametrize(
    ("deck_text", "error_type", "message"),
    [
        (
            r"\begin{document}\input{missing-list}\end{document}",
            FileNotFoundError,
            "missing-list",
        ),
        (
            r"\begin{document}\input{cycle-a}\end{document}",
            ValueError,
            "cycle",
        ),
    ],
)
def test_resolve_deck_reports_missing_and_cyclic_includes(
    tmp_path: Path,
    monkeypatch,
    deck_text: str,
    error_type: type[Exception],
    message: str,
):
    project = tmp_path / "project"
    decks = project / "decks"
    decks.mkdir(parents=True)
    deck = decks / "deck.tex"
    deck.write_text(deck_text, encoding="utf-8")
    (decks / "cycle-a.tex").write_text(r"\input{cycle-b}", encoding="utf-8")
    (decks / "cycle-b.tex").write_text(r"\input{cycle-a}", encoding="utf-8")
    monkeypatch.setattr(transcript, "PROJECT_ROOT", project)
    monkeypatch.setattr(transcript, "SLIDES_DIR", project / "slides")

    scanned = deck_scan.read_deck(deck)
    # Compilation retains its existing permissive default.
    assert deck_language.compile_deck(scanned, "EN")[0].text == scanned.text

    with pytest.raises(error_type, match=message):
        transcript.resolve_deck(deck, "during-course")


def test_shipped_manual_resolves_every_slide_in_both_student_versions(monkeypatch):
    # The SlideMage manual (the shipped demo deck since the ZZ* demo slides
    # and test.tex/test-student.tex were retired): every current call, the \slidestep
    # demo 1mu at both of its places, none left out of a student version.
    # Explicit language partners count only in their original logical slot.
    repo_root = Path(__file__).resolve().parents[1]
    project_root = repo_root / "example"
    monkeypatch.setattr(transcript, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(transcript, "SLIDES_DIR", project_root / "slides")

    deck = next(d for d in deck_scan.scan_decks() if d.name == 'slidemage-manual')
    calls = [slot.call for slot in deck_language.deck_slots(
        deck, transcript.deck_language_of(deck.text).upper())]

    for version in transcript.STUDENT_VERSIONS:
        slides = transcript.resolve_deck(
            project_root / "decks" / "slidemage-manual.tex", version
        )
        included = [slide for slide in slides if slide.included]
        expected = sum(c.included_in(version) for c in calls)
        assert len(included) == len(slides) == expected
        assert [slide.slide_id for slide in included].count("1mu") == 2


@pytest.fixture
def translated_project(tmp_path: Path, monkeypatch):
    (tmp_path / "decks").mkdir()
    slides = tmp_path / "slides"
    slides.mkdir()
    (slides / "aaa-EN-One-current.tex").write_text(
        "%% DE translation: ddd-DE-Eins\n", encoding="utf-8")
    (slides / "ddd-DE-Eins-current.tex").write_text(
        "%% Translation of: aaa-EN-One\n", encoding="utf-8")
    monkeypatch.setattr(transcript, "SLIDES_DIR", slides)
    monkeypatch.setattr(slide_language, "SLIDES_DIR", slides)
    return tmp_path


@pytest.mark.parametrize("call", [r"\slide{aaa-EN-One}", r"\slideversion{aaa-EN-One}{1-0-0}"])
@pytest.mark.parametrize("command", ["input", "include"])
def test_resolve_german_deck_uses_linked_partner(translated_project: Path, call, command):
    decks = translated_project / "decks"
    (decks / "list.tex").write_text(call, encoding="utf-8")
    deck = decks / "deck.tex"
    deck.write_text(
        r"\documentclass{beamer}\decklanguage[de]\begin{document}"
        + rf"\{command}{{list}}" + r"\end{document}", encoding="utf-8")

    slides = transcript.resolve_deck(deck, "after-course")

    assert [(s.number, s.slide_id, s.path, s.included, s.chapter) for s in slides] == [
        (1, "ddd", translated_project / "slides/ddd-DE-Eins-current.tex", True, 0)]


@pytest.mark.parametrize(("language", "slide_id", "filename"), [
    ("en", "aaa", "aaa-EN-One-current.tex"),
    ("de", "ddd", "ddd-DE-Eins-current.tex"),
])
def test_resolve_deck_folds_explicit_partner_in_original_slot(
    translated_project: Path, language, slide_id, filename
):
    deck = translated_project / "decks/deck.tex"
    deck.write_text(
        r"\documentclass{beamer}" + rf"\decklanguage[{language}]"
        r"\begin{document}\section{First}\slide{aaa-EN-One}"
        r"\section{Last}\slide{ddd-DE-Eins}\slide{bbb-EN-Two}\end{document}",
        encoding="utf-8")

    slides = transcript.resolve_deck(deck, "after-course")

    assert [(s.number, s.slide_id, s.chapter) for s in slides] == [
        (1, slide_id, 1), (2, "bbb", 2)]
    assert slides[0].path == translated_project / "slides" / filename


@pytest.mark.parametrize("inactive", [
    "\\iffalse\n\\slide{bbb-EN-Hidden}\n\\fi\n",
    "\\begin{verbatim}\n\\slide{bbb-EN-Hidden}\n\\end{verbatim}\n",
    "% \\slide{bbb-EN-Hidden}\n",
    r"\note{outer {\slide{bbb-EN-Hidden}}}",
])
def test_resolve_deck_ignores_inactive_and_note_calls(tmp_path: Path, inactive):
    deck = tmp_path / "deck.tex"
    deck.write_text(
        r"\documentclass{beamer}\begin{document}\slide{aaa-EN-First}"
        + inactive + r"\slide{ccc-EN-Last}\end{document}", encoding="utf-8")

    scanned = deck_scan.read_deck(deck)
    assert [c.id for c in deck_language.active_calls(scanned)] == ["aaa", "ccc"]
    slides = transcript.resolve_deck(deck, "after-course")

    assert [(s.number, s.slide_id) for s in slides] == [(1, "aaa"), (2, "ccc")]


def test_resolve_deck_ignores_note_calls_and_includes_in_fragments(translated_project: Path):
    decks = translated_project / "decks"
    fragment = decks / "list.tex"
    fragment.write_text(
        "\\note<2>[item]{outer {\\slide{aaa-EN-One}}\n"
        "\\input{missing-note-list}}\n\\slide{ddd-DE-Eins}\n", encoding="utf-8")
    deck = decks / "deck.tex"
    deck.write_text(
        r"\documentclass{beamer}\decklanguage[de]\begin{document}"
        r"\input{list}\end{document}", encoding="utf-8")

    slides = transcript.resolve_deck(deck, "after-course")

    assert [(s.number, s.slide_id) for s in slides] == [(1, "ddd")]
    scanned = deck_scan.read_deck(deck)
    resolved, _dependencies = deck_language.expand_fragments(scanned, strict_includes=True)
    call, = deck_language.active_calls(resolved)
    assert resolved.text[call.call_start:call.call_end] == r"\slide{ddd-DE-Eins}"
    assert call.call_start > resolved.text.index(r"\input{missing-note-list}")


def test_read_deck_accepts_fragments_without_changing_discovery(tmp_path: Path):
    fragment = tmp_path / "fragment.tex"
    text = "\\section{Body}\r\n\\slide{aaa-EN-One}\r\n"
    fragment.write_bytes(text.encode())
    wrapper = tmp_path / "_wrapper.tex"
    wrapper.write_text(r"\documentclass{beamer}\begin{document}\end{document}")
    deck = tmp_path / "deck.tex"
    deck.write_bytes(wrapper.read_bytes())

    read = deck_scan.read_deck(fragment, archived=True)

    assert read.path == fragment and read.archived and read.text == text
    assert read.preamble_end is None and read.chapters[0].title == "Body"
    assert [d.path for d in deck_scan.scan_dir(tmp_path, False)] == [deck]
    assert deck_scan.read_deck(wrapper).name == "_wrapper"
