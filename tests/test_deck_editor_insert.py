# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from slidemage import deck_editor
from slidemage.deck_scan import deck_from_text


def test_insert_positions_follow_regular_slide_calls(tmp_path):
    text = (
        "\\begin{document}\n\\section{Intro}\n"
        "\\slide{aaa-EN-First}\n\\slide{bbb-EN-Second}\n"
        "\\end{document}\n"
    )
    positions = deck_editor.slide_insert_positions(deck_from_text(tmp_path / "course.tex", text))
    assert [position.label for position in positions] == [
        "At the beginning", "After 1. aaa-EN-First", "After 2. bbb-EN-Second",
    ]
    assert positions[-1].insert_at == text.index("\\end{document}")

    for calls in (r"\input{shared}", r"\slideblock{topic}" + "\n" + r"\slide{aaa-EN-First}",
                  r"\slide{aaa-EN-First}" + "\n" + r"\slideblock{topic}"):
        source = "\\begin{document}\n\\section{Topic}\n" + calls + "\n\\end{document}\n"
        deck = deck_from_text(tmp_path / "course.tex", source)
        anchors = deck_editor.slide_insert_positions(deck)
        assert anchors[0].insert_at == source.index(calls)
        end = source.index("\\end{document}")
        assert deck_editor.append_position(deck)[0] == deck_editor.section_append_point(deck, deck.chapters[0]) == end


def test_insert_slide_calls_at_end_of_file_without_newline(tmp_path):
    path = tmp_path / "deck.tex"
    text = "\\begin{document}\n\\slide{aaa-EN-First}"
    path.write_text(text, encoding="utf-8", newline="")

    deck_editor.insert_slide_calls(path, text, len(text), "", ["bbb-DE-A", "ccc-DE-B"])

    assert path.read_text(encoding="utf-8") == (
        "\\begin{document}\n\\slide{aaa-EN-First}\n\\slide{bbb-DE-A}\n\\slide{ccc-DE-B}\n"
    )
