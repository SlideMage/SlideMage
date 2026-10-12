"""The slide list's data: sections with their slides, and each slide's status."""
from __future__ import annotations

import os

import pytest

from slidemage.project import transitional_context
from slidemage import deck_outline, slide_language, slide_snapshot
from slidemage.deck_scan import Deck, parse_chapters
from conftest import use_project

GOOD = "\\begin{standardframe}{Title}Text\\end{standardframe}\n"
BROKEN = "\\begin{standardframe}{Title}{Text\\end{standardframe}\n"   # an unclosed brace


@pytest.fixture
def project(tmp_path, monkeypatch):
    """An empty slides/ folder and preview cache the outline looks at."""
    slides = tmp_path / "slides"
    slides.mkdir()
    use_project(monkeypatch, tmp_path)
    (tmp_path / ".previews" / "slide_previews").mkdir(parents=True)
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


def test_sections_hold_their_slides_and_the_front_matter_comes_first(tmp_path, project):
    deck = make_deck(tmp_path, "\\slide{aaa-EN-Front}\n\\section{One}\n\\slide{bbb-EN-First-Slide}\n"
                               "\\section{Empty}\n\\section{Two} \\slide{ccc-EN-Shared}\n")
    outline = deck_outline.build_outline(deck, "instructor", "EN")
    assert [(s.title, [r.call.id for r in s.rows]) for s in outline] == [
        (deck_outline.UNSECTIONED, ["aaa"]), ("One", ["bbb"]), ("Empty", []), ("Two", ["ccc"])]
    # a marker that shares its line is locked, and so is the slide that shares it
    assert [s.editable for s in outline] == [False, True, True, False]
    assert not outline[3].rows[0].call.editable
    assert rows_of(outline)[1].title == "First Slide"                  # the slug, without its language
    assert [item.call.id if hasattr(item, "call") else item.title
            for item in deck_outline.ordered_items(outline)] == [
        "aaa", "One", "bbb", "Empty", "Two", "ccc"]


def test_a_deck_without_front_matter_has_no_unsectioned_section(tmp_path, project):
    deck = make_deck(tmp_path, "\\section{One}\n\\slide{bbb-EN-First}\n")
    assert [s.title for s in deck_outline.build_outline(deck, "instructor", "EN")] == ["One"]


def test_lint_errors_are_found_and_remembered_until_the_file_changes(tmp_path, project, monkeypatch):
    from slidemage import latex_lint

    slide(project, "aaa-EN-Good")
    slide(project, "bbb-EN-Broken", BROKEN)
    deck = make_deck(tmp_path, "\\slide{aaa-EN-Good}\n\\slide{bbb-EN-Broken}\n\\slide{ccc-EN-Missing}\n")
    linted = []
    real = latex_lint.lint_file
    monkeypatch.setattr(latex_lint, "lint_file", lambda path: linted.append(path.name) or real(path))

    def errors():
        return [r.lint_error for r in rows_of(deck_outline.build_outline(deck, "instructor", "EN"))]

    assert errors() == [False, True, True]       # a missing file is an error too
    assert len(linted) == 2                      # (nothing to read for the missing one)
    assert errors() == [False, True, True]
    assert len(linted) == 2                      # from the cache
    slide(project, "bbb-EN-Broken", GOOD)
    os.utime(project / "bbb-EN-Broken-current.tex", (1, 4_000_000_000))
    assert errors() == [False, False, True]
    assert linted[2:] == ["bbb-EN-Broken-current.tex"]


def test_a_preview_older_than_its_source_is_stale_and_none_is_just_missing(tmp_path, project):
    for name in ("aaa-EN-Fresh", "bbb-EN-Stale", "ccc-EN-NoPreview"):
        slide(project, name)
    deck = make_deck(tmp_path, "\\slide{aaa-EN-Fresh}\n\\slide{bbb-EN-Stale}\n\\slide{ccc-EN-NoPreview}\n")
    template = slide_snapshot.detect_template(deck.preamble_text)
    for slide_id, mtime in (("aaa", 4_000_000_000), ("bbb", 1)):
        png = slide_snapshot.snapshot_path(transitional_context(), slide_id, template, slide_snapshot.THUMB_SIZE, f"{slide_id}-EN-X")
        png.write_bytes(b"png")
        os.utime(png, (mtime, mtime))
    fresh, stale, none = rows_of(deck_outline.build_outline(deck, "instructor", "EN"))
    assert (fresh.stale_preview, stale.stale_preview, none.stale_preview) == (False, True, False)
    assert fresh.thumbnail is not None and none.thumbnail is None


def test_hidden_slides_follow_the_view(tmp_path, project):
    deck = make_deck(tmp_path, (
        "\\slide{aaa-EN-A}\n\\omitslide{bbb-EN-B}\n\\conditionalslide[instructor]{ccc-EN-C}\n"
        "\\slidestep{ddd-EN-D}[instructor]{1}\n\\slidestep{ddd-EN-D}[during-course]{1}\n\\slide{eee-EN-E}\n"))
    during = rows_of(deck_outline.build_outline(deck, "during-course", "EN"))
    assert [r.hidden for r in during] == [False, True, True, True, False, False]
    instructor = rows_of(deck_outline.build_outline(deck, "instructor", "EN"))
    assert [r.hidden for r in instructor] == [False, False, False, False, True, False]
    assert [r.position for r in instructor] == [1, 2, 3, 4, 5, 6]


def test_a_slide_without_a_version_in_the_edited_language_is_missing_its_translation(tmp_path, project):
    slide(project, "aaa-EN-Alone")
    slide(project, "bbb-EN-Both", "%% DE translation: ccc-DE-Both\n" + GOOD)
    slide(project, "ccc-DE-Both", "%% Translation of: bbb-EN-Both\n" + GOOD)
    slide(project, "ddd-mult-Image")
    slide(project, "eee-Legacy")
    deck = make_deck(tmp_path, "".join(f"\\slide{{{s}}}\n" for s in (
        "aaa-EN-Alone", "bbb-EN-Both", "ccc-DE-Both", "ddd-mult-Image", "eee-Legacy")))
    for language, expected in (("EN", [False, False, False, False]),
                               ("DE", [True, False, False, False])):
        rows = rows_of(deck_outline.build_outline(deck, "instructor", language))
        assert [r.missing_translation for r in rows] == expected, language
    assert [r.badge for r in rows] == ["[EN]", "[DE + EN]", "[mult]", ""]
    assert [r.call.id for r in rows] == ["aaa", "ccc", "ddd", "eee"]


def test_a_call_is_found_again_by_what_it_is_even_twice_in_a_deck(tmp_path, project):
    body = "\\slide{aaa-EN-A}\n\\slidestep{ccc-EN-C}[instructor]{1}\n\\slidestep{ccc-EN-C}[instructor]{1}\n"
    first = rows_of(deck_outline.build_outline(make_deck(tmp_path, body), "instructor", "EN"))
    assert first[1].key != first[2].key
    moved = rows_of(deck_outline.build_outline(make_deck(tmp_path, "\\slide{new-EN-N}\n" + body), "instructor", "EN"))
    assert [r.key for r in moved[1:]] == [r.key for r in first]


def test_a_slides_title_is_its_frame_title_else_its_slug(tmp_path, project):
    slide(project, "aaa-EN-Quote-Demo", "\\begin{standardframe}{Risk \\& \\emph{Return}\\footnote{\\fullcite{k}}}x\\end{standardframe}\n")
    slide(project, "bbb-EN-Only-A-Slug", "just text\n")
    slide(project, "ccc-EN-Pinned-Old", "\\begin{standardframe}{Old title}x\\end{standardframe}\n")
    (project / "ccc-EN-Pinned-Old-v1-0-0.tex").write_text("no frame here\n", encoding="utf-8")
    deck = make_deck(tmp_path, "\\slide{aaa-EN-Quote-Demo}\n\\slide{bbb-EN-Only-A-Slug}\n"
                               "\\slideversion{ccc-EN-Pinned-Old}{1-0-0}\n\\slide{ddd-EN-Gone}\n")
    titles = [r.title for r in rows_of(deck_outline.build_outline(deck, "instructor", "EN"))]
    assert titles == ["Risk \\& Return", "Only A Slug", "Pinned Old", "Gone"]


def test_a_title_follows_the_file_when_it_changes(tmp_path, project):
    slide(project, "aaa-EN-Slug", "\\begin{standardframe}{First}x\\end{standardframe}\n")
    deck = make_deck(tmp_path, "\\slide{aaa-EN-Slug}\n")
    assert rows_of(deck_outline.build_outline(deck, "instructor", "EN"))[0].title == "First"
    path = project / "aaa-EN-Slug-current.tex"
    path.write_text("\\begin{standardframe}{Second}x\\end{standardframe}\n", encoding="utf-8")
    os.utime(path, ns=(1, path.stat().st_mtime_ns + 5_000_000_000))
    assert rows_of(deck_outline.build_outline(deck, "instructor", "EN"))[0].title == "Second"


def test_slide_row_is_the_outlines_row_of_the_first_call(tmp_path, project):
    slide(project, "aaa-EN-One")
    slide(project, "bbb-EN-Two")
    deck = make_deck(tmp_path, "\\slide{aaa-EN-One}\n\\slide{bbb-EN-Two}\n\\slide{bbb-EN-Two}\n")
    rows = rows_of(deck_outline.build_outline(deck, "instructor", "EN"))
    row = deck_outline.slide_row(deck, "bbb", "instructor", "EN")
    assert (row.call.id, row.position, row.key) == ("bbb", 2, rows[1].key)
    assert row.title == "Title" and not row.hidden
    assert deck_outline.slide_row(deck, "zzz", "instructor", "EN") is None


@pytest.mark.parametrize("language", ["EN", "DE"])
def test_an_outline_reads_each_translation_header_once(tmp_path, project, monkeypatch, language):
    slide(project, "aaa-EN-One")
    slide(project, "ddd-DE-Eins", "%% Translation of: aaa-EN-One\n" + GOOD)
    slide(project, "bbb-EN-Two")
    (project / "aaa-EN-One-v1-0-0.tex").write_text(GOOD, encoding="utf-8")
    deck = make_deck(tmp_path, "\\slide{aaa-EN-One}\n\\slideversion{aaa-EN-One}{1-0-0}\n"
                               "\\slide{ddd-DE-Eins}\n\\slide{bbb-EN-Two}\n\\slide{bbb-EN-Two}\n")
    reads = []
    real = slide_language._header

    def header(id_slug, path=None):
        reads.append(id_slug)
        return real(id_slug, path)

    monkeypatch.setattr(slide_language, "_header", header)
    for build in range(2):
        outline = deck_outline.build_outline(deck, "instructor", language)
        assert rows_of(outline)[0].badge == ("[EN + DE]" if language == "EN" else "[DE + EN]")
        assert set(reads) == {"aaa-EN-One", "ddd-DE-Eins", "bbb-EN-Two"}
        assert all(reads.count(slug) == build + 1 for slug in set(reads))


def test_commented_out_section_is_not_a_chapter():
    from slidemage.deck_scan import parse_chapters

    text = (
        "\\documentclass{beamer}\n\\begin{document}\n"
        "\\section{Intro}\n\\slide{aaa-EN-A}\n"
        "% \\section{Old stuff}\n\\slide{bbb-EN-B}\n\\end{document}\n"
    )
    chapters = parse_chapters(text)
    assert [c.title for c in chapters] == ["Intro"]
    # The real chapter's own span still covers the commented line as
    # ordinary content -- offsets must stay into the *original* text.
    expected = text[text.index("\\section{Intro}"):text.index("\\end{document}")]
    assert text[chapters[0].start:chapters[0].end] == expected
