"""Transcript policy explicitly confirmed while addressing the code review."""
import re
from pathlib import Path

import pytest

from slidemage import transcript


@pytest.mark.parametrize("version", transcript.STUDENT_VERSIONS)
def test_student_transcripts_keep_deckreveal_content(tmp_path: Path, version: str):
    path = tmp_path / "abc-EN-Question-current.tex"
    path.write_text(
        r"\begin{standardframe}{Question}"
        r"Visible question. \deckreveal{Intended answer.}"
        r"\deckonly[instructor]{Instructor-only detail.}"
        r"\end{standardframe}",
        encoding="utf-8",
    )
    entry = transcript.render_slide(
        transcript.DeckSlide(1, "abc", path, True), version, {}
    )
    assert entry is not None
    assert "Intended answer." in entry.body
    assert "Instructor-only detail." not in entry.body


@pytest.mark.parametrize(("title", "note", "expected_title"), [
    ("Question", note, "Question") for note in (
        r"\note{PRIVATE NOTE \includegraphics{private.png}}",
        r"\note {PRIVATE NOTE \includegraphics{private.png}}",
        r"\note<2>{PRIVATE NOTE \includegraphics{private.png}}",
        r"\note<2>[item]{PRIVATE NOTE \includegraphics{private.png}}",
    )
] + [(
    r"Clean title \note{PRIVATE TITLE}",
    r"\note<2>[item]{PRIVATE BODY \includegraphics{private.png}}", "Clean title",
)])
def test_instructor_notes_stay_out_of_transcript_and_draft_context(
    tmp_path: Path, monkeypatch, title: str, note: str, expected_title: str
):
    from slidemage import alt_draft, alt_images

    monkeypatch.setattr(alt_images, "load_store", lambda: {})
    path = tmp_path / "abc-EN-Question-current.tex"
    path.write_text(
        rf"\begin{{standardframe}}{{{title}}}Visible body. "
        + note
        + r"\end{standardframe}",
        encoding="utf-8",
    )
    entry = transcript.render_slide(
        transcript.DeckSlide(1, "abc", path, True), "during-course", {}
    )
    assert entry is not None
    assert entry.title == expected_title
    assert "Visible body." in entry.body
    assert "PRIVATE" not in entry.title + entry.body
    assert entry.images == []
    context = alt_draft.build_context(path, "public.png")
    assert "PRIVATE" not in context.body


def test_transcript_omits_colour_but_keeps_the_coloured_text(tmp_path: Path):
    # Before v4.1.0 the colour name was left glued to the text:
    # "c_primary_highlightdata dredging", "C00000Promotes non-replicable results".
    path = tmp_path / "abc-EN-Colours-current.tex"
    path.write_text(
        r"\begin{standardframe}{Colours}"
        r"\begin{itemize}"
        r"\item ``\textbf{\textcolor{c_primary_highlight}{data dredging}} involves''"
        r"\item \textcolor[HTML]{C00000}{Promotes non-replicable results}"
        r"\item {\color{red} Switched} and \colorbox{yellow}{boxed} and \fcolorbox{red}{white}{framed}"
        r"\end{itemize}"
        r"\begin{tabular}{ll}\rowcolor{gray} A & \cellcolor[HTML]{EEEEEE} B \\ C & D \\ \end{tabular}"
        r"\end{standardframe}",
        encoding="utf-8",
    )
    entry = transcript.render_slide(
        transcript.DeckSlide(1, "abc", path, True), "during-course", {}
    )
    body = entry.body
    assert "**data dredging** involves" in body
    assert "- Promotes non-replicable results" in body
    assert "Switched and boxed and framed" in body
    assert "| A | B |" in body
    for colour in ("c_primary_highlight", "C00000", "HTML", "red", "yellow", "white", "gray", "EEEEEE"):
        assert not re.search(rf"(?<![a-z]){colour}(?![a-z])", body), colour
