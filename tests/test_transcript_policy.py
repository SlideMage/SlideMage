"""Transcript policy explicitly confirmed while addressing the code review."""
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


@pytest.mark.parametrize("note", [
    r"\note{PRIVATE NOTE \includegraphics{private.png}}",
    r"\note {PRIVATE NOTE \includegraphics{private.png}}",
    r"\note<2>{PRIVATE NOTE \includegraphics{private.png}}",
    r"\note<2>[item]{PRIVATE NOTE \includegraphics{private.png}}",
])
def test_instructor_notes_stay_out_of_transcript_and_draft_context(
    tmp_path: Path, monkeypatch, note: str
):
    from slidemage import alt_draft, alt_images

    monkeypatch.setattr(alt_images, "load_store", lambda: {})
    path = tmp_path / "abc-EN-Question-current.tex"
    path.write_text(
        r"\begin{standardframe}{Question}Visible question. "
        + note
        + r"\end{standardframe}",
        encoding="utf-8",
    )
    entry = transcript.render_slide(
        transcript.DeckSlide(1, "abc", path, True), "during-course", {}
    )
    assert entry is not None
    assert "PRIVATE NOTE" not in entry.body
    assert entry.images == []
    context = alt_draft.build_context(path, "public.png")
    assert "PRIVATE NOTE" not in context.body
