# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The project-wide text search behind the palette's "Text in project files"."""
from __future__ import annotations

import pytest

from slidemage import slide_search


@pytest.fixture
def root(tmp_path):
    root = tmp_path
    (root / "slides").mkdir()
    (root / "decks" / "archive").mkdir(parents=True)
    (root / "slides" / "1ab-EN-Intro-current.tex").write_text(
        "\\begin{standardframe}{Intro}\nSome text\nabout CITATION keys\n\\end{standardframe}\n", encoding="utf-8")
    (root / "slides" / "1ab-EN-Intro-v1-0-0.tex").write_text("a frozen citation\n", encoding="utf-8")
    (root / "decks" / "course.tex").write_text("% a citation in the deck\n", encoding="utf-8")
    (root / "decks" / "archive" / "old.tex").write_text("citation again\n", encoding="utf-8")
    (root / "decks" / "_slidemage_preview-1.tex").write_text("citation in a throwaway\n", encoding="utf-8")
    (root / "SlideMage.bib").write_text("@book{key,\n  title = {A Citation}\n}\n", encoding="utf-8")
    return root


def test_a_hit_names_the_file_the_line_and_the_text_around_the_match(root):
    hits = slide_search.search_project("citation", root)       # any case
    assert [h.title for h in hits] == ["1ab · Intro", "decks/course.tex", "decks/archive/old.tex", "SlideMage.bib"]
    slide = hits[0]
    assert slide.path == root / "slides/1ab-EN-Intro-current.tex"
    assert "Some text about CITATION keys \\end{standardframe}" in slide.snippet        # newlines collapsed
    assert [h.line for h in hits] == [3, 1, 1, 2]


def test_a_blank_query_matches_nothing_and_a_cancelled_search_stops(root):
    assert slide_search.search_project("  ", root) == []
    assert slide_search.search_project("citation", root, cancelled=lambda: True) == []
    seen = []
    slide_search.search_project("citation", root, cancelled=lambda: seen.append(1) or len(seen) > 2)
    assert len(seen) == 3
