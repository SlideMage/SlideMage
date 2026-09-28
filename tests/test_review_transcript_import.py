from pathlib import Path

import pytest

from slidemage import alt_blocks, transcript


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

    with pytest.raises(error_type, match=message):
        transcript.resolve_deck(deck, "during-course")


def test_shipped_demo_decks_resolve_seventeen_during_course_slides(monkeypatch):
    # 13 until v4.0.0 wired the ZZJ/ZZK/ZZL/ZZO demo slides into
    # test-slides.tex -- four plain \slide{} calls, in every version.
    repo_root = Path(__file__).resolve().parents[1]
    project_root = repo_root / "example"
    monkeypatch.setattr(transcript, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(transcript, "SLIDES_DIR", project_root / "slides")

    for name in ("test.tex", "test-student.tex"):
        slides = transcript.resolve_deck(
            project_root / "decks" / name, "during-course"
        )
        assert len([slide for slide in slides if slide.included]) == 17
