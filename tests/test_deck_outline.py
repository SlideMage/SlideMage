# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The slide list's data: sections with their slides, and each slide's status."""
from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from slidemage import alt_blocks, deck_outline, latex_lint, slide_language
from slidemage.deck_scan import Deck, parse_chapters
from slidemage.project import ProjectContext

GOOD = "\\begin{standardframe}{Title}Text\\end{standardframe}\n"
BROKEN = "\\begin{standardframe}{Title}{Text\\end{standardframe}\n"   # an unclosed brace


@pytest.fixture
def project(tmp_path):
    slides = tmp_path / "slides"
    slides.mkdir()
    deck_outline.forget_lint()
    return slides


def make_deck(tmp_path, body):
    text = "\\documentclass{beamer}\n\\begin{document}\n" + body + "\\end{document}\n"
    return Deck(
        name="course", path=tmp_path / "course.tex", archived=False, text=text,
        supports_version=True, uses_biblatex=False,
        preamble_end=text.index("\\begin{document}") + len("\\begin{document}"),
        chapters=parse_chapters(text), output_folders={},
    )


def slide(slides, id_slug, text=GOOD):
    (slides / f"{id_slug}-current.tex").write_text(text, encoding="utf-8")


def rows_of(outline):
    return [row for section in outline for row in section.rows]


def test_sections_hold_their_slides_and_the_front_matter_comes_first(ctx, tmp_path, project):
    first_section = "\\section{One}\n% \\section{Old stuff}\n\\slide{bbb-EN-First-Slide}\n"
    deck = make_deck(tmp_path, "\\slide{aaa-EN-Front}\n" + first_section
                     + "\\section{Empty}\n\\section{Two} \\slide{ccc-EN-Shared}\n")
    assert any(deck.text[c.start:c.end] == first_section for c in deck.chapters)
    outline = deck_outline.build_outline(ctx, deck, "instructor", "EN")
    assert [(s.title, [r.call.id for r in s.rows]) for s in outline] == [
        (deck_outline.UNSECTIONED, ["aaa"]), ("One", ["bbb"]), ("Empty", []), ("Two", ["ccc"])]
    # a marker that shares its line is locked, and so is the slide that shares it
    assert [s.editable for s in outline] == [False, True, True, False]
    assert not outline[3].rows[0].call.editable
    assert rows_of(outline)[1].title == "First Slide"                  # the slug, without its language
    assert [item.call.id if hasattr(item, "call") else item.title
            for item in deck_outline.ordered_items(outline)] == [
        "aaa", "One", "bbb", "Empty", "Two", "ccc"]


def test_cached_lint_and_title_follow_slide_edits(ctx, tmp_path, project, monkeypatch):
    slide(project, "aaa-EN-Good")
    slide(project, "bbb-EN-Broken", BROKEN)
    deck = make_deck(tmp_path, "\\slide{aaa-EN-Good}\n\\slide{bbb-EN-Broken}\n\\slide{ccc-EN-Missing}\n")
    linted = []
    real = latex_lint.lint_file
    monkeypatch.setattr(latex_lint, "lint_file", lambda _ctx, path: linted.append(path.name) or real(_ctx, path))

    def rows():
        return rows_of(deck_outline.build_outline(ctx, deck, "instructor", "EN"))

    first = rows()
    assert [r.lint_error for r in first] == [False, True, True]
    assert first[0].title == "Title"
    assert [r.lint_error for r in rows()] == [False, True, True]
    assert len(linted) == 2
    slide(project, "bbb-EN-Broken", GOOD)
    slide(project, "aaa-EN-Good", GOOD.replace("Title", "Edited"))
    for slug in ("aaa-EN-Good", "bbb-EN-Broken"):
        path = project / f"{slug}-current.tex"
        os.utime(path, ns=(1, path.stat().st_mtime_ns + 5_000_000_000))
    edited = rows()
    assert [r.lint_error for r in edited] == [False, False, True]
    assert edited[0].title == "Edited"
    assert linted[2:] == ["aaa-EN-Good-current.tex", "bbb-EN-Broken-current.tex"]


def test_hidden_slides_follow_the_view(ctx, tmp_path, project):
    deck = make_deck(tmp_path, (
        "\\slide{aaa-EN-A}\n\\omitslide{bbb-EN-B}\n\\conditionalslide[instructor]{ccc-EN-C}\n"
        "\\slidestep{ddd-EN-D}[instructor]{1}\n\\slidestep{ddd-EN-D}[during-course]{1}\n\\slide{eee-EN-E}\n"))
    during = rows_of(deck_outline.build_outline(ctx, deck, "during-course", "EN"))
    assert [r.hidden for r in during] == [False, True, True, True, False, False]
    instructor = rows_of(deck_outline.build_outline(ctx, deck, "instructor", "EN"))
    assert [r.hidden for r in instructor] == [False, False, False, False, True, False]
    assert [r.position for r in instructor] == [1, 2, 3, 4, 5, 6]


def test_a_slide_without_a_version_in_the_edited_language_is_missing_its_translation(ctx, tmp_path, project):
    slide(project, "aaa-EN-Alone")
    slide(project, "bbb-EN-Both", "%% DE translation: ccc-DE-Both\n" + GOOD)
    slide(project, "ccc-DE-Both", "%% Translation of: bbb-EN-Both\n" + GOOD)
    slide(project, "ddd-mult-Image")
    slide(project, "eee-Legacy")
    deck = make_deck(tmp_path, "".join(f"\\slide{{{s}}}\n" for s in (
        "aaa-EN-Alone", "bbb-EN-Both", "ccc-DE-Both", "ddd-mult-Image", "eee-Legacy")))
    for language, expected in (("EN", [False, False, False, False]),
                               ("DE", [True, False, False, False])):
        rows = rows_of(deck_outline.build_outline(ctx, deck, "instructor", language))
        assert [r.missing_translation for r in rows] == expected, language
    assert [r.badge for r in rows] == ["[EN]", "[DE + EN]", "[mult]", ""]
    assert [r.call.id for r in rows] == ["aaa", "ccc", "ddd", "eee"]


def test_a_call_is_found_again_by_what_it_is_even_twice_in_a_deck(ctx, tmp_path, project):
    body = "\\slide{aaa-EN-A}\n\\slidestep{ccc-EN-C}[instructor]{1}\n\\slidestep{ccc-EN-C}[instructor]{1}\n"
    first = rows_of(deck_outline.build_outline(ctx, make_deck(tmp_path, body), "instructor", "EN"))
    assert first[1].key != first[2].key
    moved = rows_of(deck_outline.build_outline(ctx, make_deck(tmp_path, "\\slide{new-EN-N}\n" + body), "instructor", "EN"))
    assert [r.key for r in moved[1:]] == [r.key for r in first]


def test_a_slides_title_is_its_frame_title_else_its_slug(ctx, tmp_path, project):
    slide(project, "aaa-EN-Quote-Demo", "\\begin{standardframe}{Risk \\& \\emph{Return}\\footnote{\\fullcite{k}}}x\\end{standardframe}\n")
    slide(project, "bbb-EN-Only-A-Slug", "just text\n")
    slide(project, "ccc-EN-Pinned-Old", "\\begin{standardframe}{Old title}x\\end{standardframe}\n")
    (project / "ccc-EN-Pinned-Old-v1-0-0.tex").write_text("no frame here\n", encoding="utf-8")
    deck = make_deck(tmp_path, "\\slide{aaa-EN-Quote-Demo}\n\\slide{bbb-EN-Only-A-Slug}\n"
                               "\\slideversion{ccc-EN-Pinned-Old}{1-0-0}\n\\slide{ddd-EN-Gone}\n")
    titles = [r.title for r in rows_of(deck_outline.build_outline(ctx, deck, "instructor", "EN"))]
    assert titles == ["Risk \\& Return", "Only A Slug", "Pinned Old", "Gone"]


REUSE_BODY = ("\\slide{aaa-EN-One}\n\\conditionalslide[instructor]{bbb-EN-Two}\n"
              "\\slidestep{ccc-EN-Three}[instructor]{1}\n\\slidestep{ccc-EN-Three}[during-course]{1}\n"
              "\\slide{ddd-DE-Vier}\n\\slide{aaa-EN-One}\n")


@pytest.fixture
def reuse_deck(tmp_path, project):
    slide(project, "aaa-EN-One", "%% DE translation: ddd-DE-Vier\n" + GOOD)
    slide(project, "ddd-DE-Vier", "%% Translation of: aaa-EN-One\n" + GOOD)
    for slug in ("bbb-EN-Two", "ccc-EN-Three"):
        slide(project, slug)
    return make_deck(tmp_path, REUSE_BODY)


def test_slide_row_finds_the_first_call_and_can_select_a_specific_occurrence(ctx, reuse_deck):
    outline = deck_outline.resolve_outline(ctx, reuse_deck, "during-course", "DE")
    rows = outline.rows
    assert outline.sections == deck_outline.build_outline(ctx, reuse_deck, "during-course", "DE")
    assert sorted(outline.instructor_frames.values()) == [1, 2, 3, 3, 4]
    assert rows[0].call.id == rows[-1].call.id == "ddd" and rows[0].key != rows[-1].key
    assert outline.row("aaa") is outline.row("ddd") is rows[0]
    assert outline.row("aaa", rows[-1].key) is rows[-1]
    assert outline.row("aaa", ("no", "such", "key")) is rows[0]
    assert outline.row("zzz") is None
    assert deck_outline.slide_row(ctx, reuse_deck, "aaa", "during-course", "DE") == rows[0]
    assert deck_outline.slide_row(ctx, reuse_deck, "zzz", "during-course", "DE") is None


def test_an_outline_reads_each_translation_header_once(ctx, tmp_path, project, monkeypatch):
    slide(project, "aaa-EN-One")
    slide(project, "ddd-DE-Eins", "%% Translation of: aaa-EN-One\n" + GOOD)
    slide(project, "bbb-EN-Two")
    (project / "aaa-EN-One-v1-0-0.tex").write_text(GOOD, encoding="utf-8")
    deck = make_deck(tmp_path, "\\slide{aaa-EN-One}\n\\slideversion{aaa-EN-One}{1-0-0}\n"
                               "\\slide{ddd-DE-Eins}\n\\slide{bbb-EN-Two}\n\\slide{bbb-EN-Two}\n")
    reads = []
    real = slide_language._header

    def header(path):
        reads.append(path.name.removesuffix("-current.tex"))
        return real(path)

    monkeypatch.setattr(slide_language, "_header", header)
    for build in range(2):
        outline = deck_outline.build_outline(ctx, deck, "instructor", "DE")
        assert rows_of(outline)[0].badge == "[DE + EN]"
        assert set(reads) == {"aaa-EN-One", "ddd-DE-Eins", "bbb-EN-Two"}
        assert all(reads.count(slug) == build + 1 for slug in set(reads))


def test_outline_reuse_requires_the_same_project_deck_view_and_language(ctx, tmp_path, reuse_deck, resolutions):
    outline = deck_outline.resolve_outline(ctx, reuse_deck, "instructor", "EN")
    assert outline.matches(ctx, replace(reuse_deck), "EN", "instructor")
    assert not outline.matches(ctx, replace(reuse_deck, text=reuse_deck.text + "\n"), "EN")
    assert not outline.matches(ctx, replace(reuse_deck, path=tmp_path / "other.tex"), "EN")
    assert not outline.matches(ProjectContext.at(tmp_path / "other"), reuse_deck, "EN")
    resolutions.reset()
    row = deck_outline.slide_row(ctx, reuse_deck, "ccc", "instructor", "EN", occurrence_key=outline.rows[3].key, outline=outline)
    assert row is outline.rows[3] and deck_outline.outline_rows(ctx, reuse_deck, "instructor", "EN", outline=outline) == outline.rows
    assert (resolutions.slots, resolutions.outlines, resolutions.scans) == (0, 0, 0)
    for view, language, hidden in (("during-course", "EN", True), ("instructor", "DE", False)):       # not this outline's
        fresh = deck_outline.slide_row(ctx, reuse_deck, "ccc", view, language, outline=outline)
        assert fresh is not None and (fresh.call.id, fresh.hidden) == ("ccc", hidden)
    assert resolutions.slots == 2 and resolutions.scans == 2


@pytest.mark.parametrize("raw, expected", [
    (r"Be kind\ldots\only<2->{ but clear}", "Be kind… but clear"),
    (r"A\uncover<2-3>{ B}\visible<4>{ C}", "A B C"),
    (r"\alt<2>{Shown}{Other} title", "Shown title"),
    (r"Step\onslide<2-> one\pause", "Step one"),
    (r"Plan\conditionalpause[2] done\deckonly{ A}\deckuncover<3->{ B}\deckvisible{ C}", "Plan done A B C"),
    (r"Risk\textbf<2->{ now}", "Risk now"),
    (r"Risk \& Return", r"Risk \& Return"),
    (r"a<b and c>d", "a<b and c>d"),
    (r"{\fontsize{13.7}{16.4}\selectfont Sustainable finance}", "Sustainable finance"),
])
def test_a_title_drops_overlay_markup_and_keeps_the_visible_text(raw, expected):
    assert alt_blocks.clean_frame_title(raw) == expected


def test_a_slides_title_with_an_overlay_reads_as_its_visible_text():
    source = r"\begin{standardframe}{Be kind\ldots\only<2->{ but clear}}x\end{standardframe}" + "\n"
    assert alt_blocks.slide_title(source, Path("sn8-EN-Be-Kind-but-Clear-current.tex"), ("EN", "DE")) == ("sn8", "Be kind… but clear")
