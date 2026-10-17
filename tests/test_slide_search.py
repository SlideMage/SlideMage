"""The project-wide text search behind the palette's "Text in project files"."""
from __future__ import annotations

from slidemage import slide_search


def make_project(root):
    (root / "slides").mkdir()
    (root / "decks" / "archive").mkdir(parents=True)
    (root / "slides" / "1ab-EN-Intro-current.tex").write_text(
        "\\begin{standardframe}{Intro}\nSome text\nabout CITATION keys\n\\end{standardframe}\n", encoding="utf-8")
    (root / "slides" / "1cd-EN-Other-current.tex").write_text("\\begin{standardframe}{Other}\nnothing\n\\end{standardframe}\n",
                                                          encoding="utf-8")
    (root / "slides" / "1ab-EN-Intro-v1-0-0.tex").write_text("a frozen citation\n", encoding="utf-8")   # not searched
    (root / "decks" / "course.tex").write_text("% a citation in the deck\n", encoding="utf-8")
    (root / "decks" / "archive" / "old.tex").write_text("citation again\n", encoding="utf-8")
    (root / "decks" / "_slidemage_preview-1.tex").write_text("citation in a throwaway\n", encoding="utf-8")
    (root / "Slidemaster.bib").write_text("@book{key,\n  title = {A Citation}\n}\n", encoding="utf-8")


def test_the_files_searched_are_slides_decks_and_the_bibliography(tmp_path):
    make_project(tmp_path)
    assert [p.relative_to(tmp_path).as_posix() for p in slide_search.project_files(tmp_path)] == [
        "slides/1ab-EN-Intro-current.tex", "slides/1cd-EN-Other-current.tex",
        "decks/course.tex", "decks/archive/old.tex", "Slidemaster.bib"]


def test_a_hit_names_the_file_the_line_and_the_text_around_the_match(tmp_path):
    make_project(tmp_path)
    hits = slide_search.search_project("citation", tmp_path)       # any case
    assert [h.title for h in hits] == ["1ab · Intro", "decks/course.tex", "decks/archive/old.tex", "Slidemaster.bib"]
    slide = hits[0]
    assert (slide.path.name, slide.line) == ("1ab-EN-Intro-current.tex", 3)
    assert "Some text about CITATION keys \\end{standardframe}" in slide.snippet        # newlines collapsed
    assert [h.line for h in hits] == [3, 1, 1, 2]


def test_a_blank_query_matches_nothing_and_a_cancelled_search_stops(tmp_path):
    make_project(tmp_path)
    assert slide_search.search_project("  ", tmp_path) == []
    assert slide_search.search_project("citation", tmp_path, cancelled=lambda: True) == []
    seen = []
    slide_search.search_project("citation", tmp_path, cancelled=lambda: seen.append(1) or len(seen) > 2)
    assert len(seen) == 3
