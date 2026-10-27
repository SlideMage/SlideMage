# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Admin slides backend: the slide sources, which slides a choice makes, and their insertion."""
from __future__ import annotations

from dataclasses import replace

import pytest

from slidemage import admin_slides, course_schedule, deck_editor, slide_ids
from slidemage.course_schedule import CourseDetail, CourseGroup, CourseSession, Lecturer
from slidemage.deck_scan import Deck

DETAIL = CourseDetail(
    number="355.001", title="Bachelorkurs (Management Science)",
    semester="Wintersemester 2026/27",
    lecturers=(
        Lecturer("Erika", "Musterfrau", "Vortragende*r"),
        Lecturer("Jürgen", "Fleiß", "Vortragende*r"),
    ),
)
GROUP = CourseGroup("Standardgruppe", (
    CourseSession("05.10.2026", "09:00", "10:00", "SR 15.25", "Abhaltung", "Vorbesprechung"),
    CourseSession("12.10.2026", "09:00", "10:00", "HS 01", "Prüfung", "Bitte Ausweis mitbringen"),
))


def make_deck(tmp_path, language="de"):
    path = tmp_path / "course.tex"
    text = (
        "\\documentclass{beamer}\n\\decklanguage[" + language + "]\n"
        "\\begin{document}\n\\end{document}\n"
    )
    path.write_text(text, encoding="utf-8", newline="")
    return Deck(
        name="course", path=path, archived=False, text=text,
        supports_version=False, uses_biblatex=False, preamble_end=0,
        chapters=[], output_folders={}, tags=[], course_url="https://example.invalid/course",
    )


@pytest.fixture
def new_slides(tmp_path, monkeypatch):
    ids = iter(["abc", "def"])
    monkeypatch.setattr(slide_ids, "mint_slide_id", lambda _ctx: next(ids))


def test_schedule_positions_follow_regular_slide_calls(tmp_path):
    deck = make_deck(tmp_path)
    text = (
        "\\begin{document}\n\\section{Intro}\n"
        "\\slide{aaa-EN-First}\n\\slide{bbb-EN-Second}\n"
        "\\end{document}\n"
    )
    deck.path.write_text(text, encoding="utf-8", newline="")
    deck = replace(deck, text=text)
    positions = deck_editor.slide_insert_positions(deck)
    assert [position.label for position in positions] == [
        "At the beginning", "After 1. aaa-EN-First", "After 2. bbb-EN-Second",
    ]
    assert positions[-1].insert_at == text.index("\\end{document}")


def test_plan_makes_a_slide_for_each_part_asked_for():
    specs = admin_slides.plan_slides("de", detail=DETAIL, lecturers=DETAIL.lecturers[1:], group=GROUP)
    assert [suffix for suffix, _ in specs] == ["Title-Slide", "Course-Sessions"]
    title, sessions = (source for _, source in specs)
    assert "Jürgen Fleiß" in title and "Erika Musterfrau" not in title
    assert r"\textbf{Datum} & \textbf{Zeit}" in sessions and "Abhaltung — Vorbesprechung" in sessions
    assert [suffix for suffix, _ in admin_slides.plan_slides("de", detail=DETAIL, lecturers=DETAIL.lecturers)] == [
        "Title-Slide"]
    assert admin_slides.plan_slides("de") == []


def test_english_deck_gets_a_translated_sessions_table():
    source = admin_slides.plan_slides("en", group=GROUP)[0][1]
    assert r"\begin{standardframe}{Course sessions}" in source
    assert r"\textbf{Date} & \textbf{Time} & \textbf{Location} & \textbf{Session}" in source
    assert r"\textbf{Standard group}" in source
    assert "SR 15.25 & Class — Preliminary meeting" in source
    # A remark with unknown words stays German rather than half-translated.
    assert "HS 01 & Exam — Bitte Ausweis mitbringen" in source
    assert "Zeit" not in source and "Abhaltungstermine" not in source


@pytest.mark.parametrize(("deck_language", "taught", "warned"), [
    ("en", ("de",), True),
    ("de", ("de",), False),
    ("en", ("de", "en"), False),
    ("de", (), False),
])
def test_language_mismatch_is_a_warning_only_when_the_course_is_taught_in_another_language(
        deck_language, taught, warned):
    text = admin_slides.language_warning(deck_language, replace(DETAIL, languages=taught))
    assert bool(text) is warned


def test_the_two_parts_of_a_fetch_fail_independently(monkeypatch):
    def broken_schedule(url):
        raise RuntimeError("network unreachable")

    monkeypatch.setattr(course_schedule, "fetch_schedule", broken_schedule)
    monkeypatch.setattr(course_schedule, "fetch_course_detail", lambda url, language: DETAIL)
    assert admin_slides.fetch("https://example.invalid", "de") == ("network unreachable", DETAIL)


@pytest.mark.parametrize("language", ["de", "en"])
def test_insertion_creates_editable_slides_and_deck_calls_in_order(ctx, tmp_path, new_slides, language):
    deck = make_deck(tmp_path, language=language)
    position = deck_editor.slide_insert_positions(deck)[0]
    specs = [
        ("Title-Slide", admin_slides.build_title_slide_source(r"\titleframe{Financial Markets}{Stefan Palan\\Summer term 2026}")),
        ("Course-Sessions", admin_slides.build_sessions_slide_source(r"\begin{tabular}{ll}Datum & Zeit \\ \end{tabular}", language)),
    ]

    slide_paths = admin_slides.insert_admin_slides(ctx, deck, position, specs, language)

    tag = language.upper()
    assert [path.name for path in slide_paths] == [
        f"abc-{tag}-Title-Slide-current.tex", f"def-{tag}-Course-Sessions-current.tex",
    ]
    deck_text = deck.path.read_text(encoding="utf-8")
    assert deck_text.index(r"\slide{abc-" + tag + "-Title-Slide}") < deck_text.index(r"\slide{def-" + tag + "-Course-Sessions}")
    assert '"abc"' in (tmp_path / "slide_ids.csv").read_text(encoding="utf-8")
    assert '"def"' in (tmp_path / "slide_ids.csv").read_text(encoding="utf-8")


def test_failure_on_a_later_slide_leaves_deck_untouched(ctx, tmp_path, monkeypatch, new_slides):
    deck = make_deck(tmp_path)
    # Same ID twice: the second slide file already exists, so its open("x") fails.
    monkeypatch.setattr(slide_ids, "mint_slide_id", lambda _ctx: "abc")
    position = deck_editor.slide_insert_positions(deck)[0]
    specs = [("Title-Slide", admin_slides.build_title_slide_source("A")),
             ("Title-Slide", admin_slides.build_title_slide_source("B"))]

    with pytest.raises(FileExistsError):
        admin_slides.insert_admin_slides(ctx, deck, position, specs)

    assert deck.path.read_text(encoding="utf-8") == deck.text
    assert not list((tmp_path / "slides").glob("*.tex"))


def test_insert_slide_calls_at_end_of_file_without_newline(tmp_path):
    path = tmp_path / "deck.tex"
    text = "\\begin{document}\n\\slide{aaa-EN-First}"
    path.write_text(text, encoding="utf-8", newline="")

    deck_editor.insert_slide_calls(path, text, len(text), "", ["bbb-DE-A", "ccc-DE-B"])

    assert path.read_text(encoding="utf-8") == (
        "\\begin{document}\n\\slide{aaa-EN-First}\n\\slide{bbb-DE-A}\n\\slide{ccc-DE-B}\n"
    )


def test_stale_deck_keeps_external_change_and_removes_new_slide(ctx, tmp_path, new_slides):
    deck = make_deck(tmp_path)
    position = deck_editor.slide_insert_positions(deck)[0]
    deck.path.write_text(deck.text + "% external edit\n", encoding="utf-8", newline="")

    with pytest.raises(deck_editor.StaleFileError):
        admin_slides.insert_admin_slides(ctx, 
            deck, position, [("Course-Sessions", admin_slides.build_sessions_slide_source("Table"))])

    assert "% external edit" in deck.path.read_text(encoding="utf-8")
    assert not list((tmp_path / "slides").glob("*.tex"))
