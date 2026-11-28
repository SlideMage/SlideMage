# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Student transcript content and instructor-note privacy."""
import re

import pytest

from slidemage import alt_draft, alt_images, transcript


def render(ctx, tmp_path, source, version="during-course"):
    path = tmp_path / "abc-EN-Question-current.tex"
    path.write_text(source, encoding="utf-8")
    entry = transcript.render_slide(ctx, transcript.DeckSlide(1, "abc", path, True), version, {})
    assert entry is not None
    return path, entry


@pytest.mark.parametrize("version", transcript.STUDENT_VERSIONS)
def test_student_transcripts_keep_deckreveal_content(ctx, tmp_path, version):
    _, entry = render(ctx, tmp_path, r"\begin{standardframe}{Question}"
                      r"Visible question. \deckreveal{Intended answer.}"
                      r"\deckonly[instructor]{Instructor-only detail.}\end{standardframe}", version)
    assert "Intended answer." in entry.body and "Instructor-only detail." not in entry.body


@pytest.mark.parametrize("options", ["", " ", "<2>", "<2>[item]"])
def test_instructor_notes_stay_out_of_transcript_and_draft_context(ctx, tmp_path, monkeypatch, options):
    monkeypatch.setattr(alt_images, "load_store", lambda _ctx: {})
    path, entry = render(ctx, tmp_path,
                         r"\begin{standardframe}{Clean title \note{PRIVATE TITLE}}Visible body. "
                         rf"\note{options}{{PRIVATE BODY \includegraphics{{private.png}}}}\end{{standardframe}}")
    assert entry.title == "Clean title" and entry.body == "Visible body."
    assert entry.images == []
    assert "PRIVATE" not in alt_draft.build_context(ctx, path, "public.png").body


def test_transcript_omits_color_but_keeps_the_colored_text(ctx, tmp_path):
    _, entry = render(ctx, tmp_path,
        r"\begin{standardframe}{Colors}"
        r"\begin{itemize}"
        r"\item ``\textbf{\textcolor{c_primary_highlight}{data dredging}} involves''"
        r"\item \textcolor[HTML]{C00000}{Promotes non-replicable results}"
        r"\item {\color{red} Switched} and \colorbox{yellow}{boxed} and \fcolorbox{red}{white}{framed}"
        r"\end{itemize}"
        r"\begin{tabular}{ll}\rowcolor{gray} A & \cellcolor[HTML]{EEEEEE} B \\ C & D \\ \end{tabular}"
        r"\end{standardframe}")
    body = entry.body
    assert "**data dredging** involves" in body
    assert "- Promotes non-replicable results" in body
    assert "Switched and boxed and framed" in body
    assert "| A | B |" in body
    for color in ("c_primary_highlight", "C00000", "HTML", "red", "yellow", "white", "gray", "EEEEEE"):
        assert not re.search(rf"(?<![a-z]){color}(?![a-z])", body), color
