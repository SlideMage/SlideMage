# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the Preview renders: the call, the deck context, the view and language."""
from __future__ import annotations

import pymupdf
import pytest

from slidemage import deck_editor, preview_target, slide_preview, slide_snapshot
from slidemage.deck_scan import Deck, parse_chapters
from slidemage.project import ProjectContext
from conftest import EXAMPLE_PROJECT

PREAMBLE = "\\documentclass{beamer}\n\\input{Slidemaster_preamble_uni-ibk}\n\\begin{document}"


def make_deck(body):
    text = PREAMBLE + "\n" + body + "\\end{document}\n"
    return Deck(name="course", path=None, archived=False, text=text, supports_version=True,
                uses_biblatex=False, preamble_end=len(PREAMBLE), chapters=parse_chapters(text),
                output_folders={})


@pytest.fixture
def renders(monkeypatch):
    """slide_preview with its two renderers replaced by recorders."""
    calls = []
    monkeypatch.setattr(slide_preview, "render_slide_to_pdf",
                        lambda *args, **kwargs: calls.append(("call", args, kwargs)) or "a.pdf")
    monkeypatch.setattr(slide_preview, "render_slide_text_to_pdf",
                        lambda *args, **kwargs: calls.append(("text", args, kwargs)) or "b.pdf")
    return calls


def target_of(body, index=0):
    deck = make_deck(body)
    calls = deck_editor.parse_slide_calls(deck)
    return deck, preview_target.for_call(EXAMPLE_PROJECT, deck, calls[index], index + 1)


def test_a_call_renders_with_its_decks_preamble_frame_number_view_and_language(renders):
    _, target = target_of("\\slide{aaa-EN-One}\n\\slidestep{bbb-EN-Two}{1,2}\n", 1)
    assert target.macro == "slidestep" and target.frame_number == 2 and target.template == "uni-ibk"
    assert preview_target.render(target, "during-course", "DE", log=print) == "a.pdf"
    kind, args, kwargs = renders[0]
    assert args[1:3] == ("slidestep", "bbb-EN-Two")
    assert kwargs["deck_version"] == "during-course" and kwargs["deck_language"] == "de"
    assert kwargs["frame_number"] == 2 and kwargs["steps"] == "1,2"
    assert kwargs["capture_snapshot"]
    assert kwargs["preamble_text"].startswith("\\documentclass{beamer}")


def test_a_buffer_renders_in_the_same_context_and_a_presenter_render_is_instructor(renders):
    _, target = target_of("\\slide{aaa-EN-One}\n")
    preview_target.render_text(target, "BODY", "after-course", "EN", log=print,
                               mode="region", overlay=2)
    preview_target.render_text(target, "BODY", "after-course", "EN", log=print,
                               presenter=True)
    (_, args, kwargs), (_, _, presenter) = renders
    assert args[1:] == ("aaa-EN-One", "BODY")
    assert (kwargs["deck_version"], kwargs["preview_mode"], kwargs["overlay"]) == ("after-course", "region", 2)
    assert kwargs["frame_number"] == 1 and kwargs["deck_language"] == "en"
    assert presenter["deck_version"] == "instructor" and presenter["presenter"]


def test_a_slide_file_alone_has_no_deck_context_and_frozen_versions_do_not_use_snapshots(
    tmp_path, monkeypatch, renders,
):
    ctx = ProjectContext.at(tmp_path)
    slides = tmp_path / "slides"
    slides.mkdir()
    (tmp_path / ".previews" / "slide_previews").mkdir(parents=True)
    current = preview_target.for_path(ctx, slides / "abc-EN-Demo-current.tex")
    frozen = preview_target.for_path(ctx, slides / "abc-EN-Demo-v1-0-0.tex")
    assert (current.macro, current.version, current.preamble_text) == ("slide", None, None)
    assert (frozen.macro, frozen.version) == ("slideversion", "1-0-0")
    assert current.source_path == slides / "abc-EN-Demo-current.tex"
    assert frozen.source_path == slides / "abc-EN-Demo-v1-0-0.tex"
    assert preview_target.for_path(ctx, slides / "deck.tex") is None
    assert frozen.is_frozen_alone
    slide_snapshot.snapshot_path(ctx, "abc", frozen.template, slide_snapshot.FULL_SIZE).write_bytes(b"png")
    assert preview_target.cached_image(frozen) is None
    preview_target.render(frozen, "instructor", "EN", log=print)
    assert renders[0][2]["capture_snapshot"] is False
    # a deck that pins the version does show it, so the snapshot is its to refresh
    _, pinned = target_of("\\slideversion{abc-EN-Demo}{1-0-0}\n")
    assert not pinned.is_frozen_alone


def test_the_cached_image_is_fresh_only_when_newer_than_the_source(tmp_path, monkeypatch):
    import os

    ctx = ProjectContext.at(tmp_path)
    slides = tmp_path / "slides"
    slides.mkdir()
    (tmp_path / ".previews" / "slide_previews").mkdir(parents=True)
    target = preview_target.for_path(ctx, slides / "abc-EN-Demo-current.tex")
    assert preview_target.cached_image(target) is None
    source = slides / "abc-EN-Demo-current.tex"
    source.write_text("x", encoding="utf-8")
    png = slide_snapshot.snapshot_path(ctx, "abc", target.template, slide_snapshot.FULL_SIZE)
    png.write_bytes(b"png")
    os.utime(png, (1, source.stat().st_mtime + 10))
    assert preview_target.cached_image(target) == (png, True)
    os.utime(png, (1, source.stat().st_mtime - 10))
    assert preview_target.cached_image(target) == (png, False)


def test_page_png_is_the_last_page_at_the_requested_width(tmp_path):
    pdf = tmp_path / "p.pdf"
    doc = pymupdf.open()
    doc.new_page(width=320, height=180)
    doc.new_page(width=200, height=400)   # not 16:9: a cropped element keeps its shape
    doc.save(pdf)
    doc.close()
    data = slide_snapshot.page_png(pdf, 100)
    pixmap = pymupdf.Pixmap(data)
    assert (pixmap.width, pixmap.height) == (100, 200)
    assert slide_snapshot.page_png(tmp_path / "missing.pdf") is None


def test_view_resolution_preserves_hidden_counters_but_skips_absent_steps(tmp_path):
    ctx = ProjectContext.at(tmp_path)
    ctx.slides_dir.mkdir()
    body = ("\\conditionalslide[instructor]{aaa-EN-One}\n"
            "\\omitslide{bbb-EN-Two}\n"
            "\\slidestep{ccc-EN-Three}[instructor]{1,2}\n"
            "\\slide{ddd-EN-Four}\n")
    deck = make_deck(body)
    resolved = preview_target.resolve_views(ctx, deck, ctx.slides_dir / 'ddd-EN-Four-current.tex', 'all', 'EN')
    assert [v for v, _ in resolved] == ['instructor', 'during-course', 'after-course']
    assert [t.frame_number for _, t in resolved] == [4, 3, 3]
    hidden = preview_target.resolve_views(ctx, deck, ctx.slides_dir / 'aaa-EN-One-current.tex', 'all', 'EN')
    assert [t.hidden for _, t in hidden] == [False, True, True]
    with pytest.raises(ValueError, match='hidden'):
        preview_target.render(hidden[1][1], 'during-course', 'EN', log=print)


def test_duplicate_resolution_uses_occurrence_key_otherwise_first(tmp_path):
    from slidemage import deck_outline

    ctx = ProjectContext.at(tmp_path)
    ctx.slides_dir.mkdir()
    deck = make_deck('\\slidestep{aaa-EN-One}{1}\n\\slide{bbb-EN-Two}\n\\slidestep{aaa-EN-One}{3}\n')
    path = ctx.slides_dir / 'aaa-EN-One-current.tex'
    rows = deck_outline.resolve_slots(ctx, deck, 'instructor', 'EN')
    first = preview_target.resolve_views(ctx, deck, path, 'instructor', 'EN')[0][1]
    last = preview_target.resolve_views(ctx, deck, path, 'instructor', 'EN', occurrence_key=rows[2].key)[0][1]
    assert (first.steps, first.frame_number) == ('1', 1)
    assert (last.steps, last.frame_number) == ('3', 3)
    assert first.key != last.key


def test_invalid_view_fails_before_source_capture(tmp_path):
    from slidemage import preview_requests

    ctx = ProjectContext.at(tmp_path)
    with pytest.raises(ValueError, match='Invalid preview view'):
        preview_requests.resolve_requests(ctx, None, tmp_path / 'aaa-EN-One-current.tex', 'student', 'EN',
                                          read_source=lambda _: pytest.fail('read before validation'))


def test_all_views_capture_one_revision_and_new_same_version_source_is_distinct(tmp_path):
    from slidemage import preview_requests

    ctx = ProjectContext.at(tmp_path)
    ctx.slides_dir.mkdir()
    path = ctx.slides_dir / 'aaa-EN-One-current.tex'
    path.write_text('% version 1.0.0+\nOLD')
    captures = []

    def read(source):
        captures.append(source)
        return source.read_text()

    requests = preview_requests.resolve_requests(ctx, None, path, 'all', 'en', read_source=read)
    assert len(captures) == 1
    assert requests[0].revision is requests[1].revision is requests[2].revision
    assert requests[0].language == 'EN'
    path.write_text('% version 1.0.0+\nNEW')
    newer = preview_requests.resolve_requests(ctx, None, path, None, 'EN')[0]
    assert newer.revision.content_hash != requests[0].revision.content_hash


def test_pinned_resolution_and_translation_folding(tmp_path):
    from slidemage import preview_requests

    ctx = ProjectContext.at(tmp_path)
    ctx.slides_dir.mkdir()
    en = ctx.slides_dir / 'aaa-EN-One-current.tex'
    de = ctx.slides_dir / 'bbb-DE-Eins-current.tex'
    en.write_text('%% Language: EN\n%% DE translation: bbb-DE-Eins\nEN CURRENT')
    de.write_text('%% Language: DE\n%% Translation of: aaa-EN-One\nDE CURRENT')
    pinned = ctx.slides_dir / 'aaa-EN-One-v1-0-0.tex'
    pinned.write_text('EN PINNED')
    deck = make_deck('\\slideversion{aaa-EN-One}{1-0-0}\n\\slide{bbb-DE-Eins}\n\\slide{ccc-EN-Three}\n')
    english = preview_requests.resolve_requests(ctx, deck, en, 'instructor', 'EN')[0]
    assert english.target.version == '1-0-0'
    assert english.revision.text == 'EN PINNED'
    german = preview_requests.resolve_requests(ctx, deck, en, 'all', 'DE')
    assert all(r.target.id_slug == 'bbb-DE-Eins' and r.target.version is None for r in german)
    assert all(r.revision.text.endswith('DE CURRENT') for r in german)
    next_target = preview_target.resolve_views(ctx, deck, ctx.slides_dir / 'ccc-EN-Three-current.tex', 'instructor', 'DE')[0][1]
    assert next_target.frame_number == 2


def test_buffer_full_slide_preserves_call_steps_and_pinned_omit_state(monkeypatch):
    wrappers = []
    monkeypatch.setattr(slide_preview, 'compile_and_extract', lambda ctx, wrapper, *a, **kw: wrappers.append(wrapper))
    _, target = target_of('\\slidestep{aaa-EN-One}[instructor]{2,4}\n')
    preview_target.render_text(target, 'BODY', 'instructor', 'EN', log=print)
    assert r'\gdef\SMSlideSteps{2,4}' in wrappers[-1]
    _, pinned = target_of('\\omitslideversion{aaa-EN-One}{1-0-0}\n')
    preview_target.render_text(pinned, 'PINNED BODY', 'instructor', 'EN', log=print)
    assert r'\setSlideVersion{1-0-0}' in wrappers[-1]
    assert r'\global\SMOmittedSlidetrue' in wrappers[-1]


def test_presenter_of_hidden_student_target_uses_instructor_frame_number(monkeypatch, tmp_path):
    ctx = ProjectContext.at(tmp_path)
    ctx.slides_dir.mkdir()
    deck = make_deck('\\slidestep{bbb-EN-Two}[instructor]{1}\n\\omitslide{aaa-EN-One}\n')
    target = preview_target.resolve_views(ctx, deck, ctx.slides_dir / 'aaa-EN-One-current.tex', 'after-course', 'EN')[0][1]
    assert target.hidden and target.frame_number == 1
    wrappers = []
    monkeypatch.setattr(slide_preview, 'compile_and_extract', lambda ctx, wrapper, *a, **kw: wrappers.append(wrapper))
    preview_target.render_text(target, 'BODY', 'after-course', 'EN', presenter=True, log=print)
    assert r'\setcounter{framenumber}{1}' in wrappers[0]  # beamer increments before printing frame 2


def test_unrelated_frozen_version_stays_standalone(tmp_path):
    ctx = ProjectContext.at(tmp_path)
    deck = make_deck('\\slideversion{aaa-EN-One}{1-0-0}\n')
    target = preview_target.resolve_views(ctx, deck, ctx.slides_dir / 'aaa-EN-One-v2-0-0.tex', 'instructor', 'EN')[0][1]
    assert target.version == '2-0-0' and target.preamble_text is None


def test_slidefinal_buffer_disables_conditional_pauses(monkeypatch):
    wrappers = []
    monkeypatch.setattr(slide_preview, 'compile_and_extract', lambda ctx, wrapper, *a, **kw: wrappers.append(wrapper))
    _, target = target_of('\\slidefinal{aaa-EN-One}\n')
    preview_target.render_text(target, 'BODY', 'instructor', 'EN', log=print)
    assert r'\renewcommand{\conditionalpause}[1][instructor]{}' in wrappers[0]


def test_presenter_frame_number_is_part_of_target_identity():
    from dataclasses import replace

    _, target = target_of('\\slide{aaa-EN-One}\n')
    assert replace(target, presenter_frame_number=2).key != replace(target, presenter_frame_number=3).key


@pytest.mark.parametrize("view", ["instructor", "during-course"])
@pytest.mark.parametrize("language", ["EN", "DE"])
def test_for_call_with_the_resolved_outline_builds_the_target_the_resolver_does(tmp_path, view, language, resolutions):
    """Repeated calls, a call hidden in the other view and a translation: every row of the deck."""
    from slidemage import deck_outline

    ctx = ProjectContext.at(tmp_path)
    ctx.slides_dir.mkdir()
    (ctx.slides_dir / 'aaa-EN-One-current.tex').write_text('%% DE translation: ddd-DE-Vier\nbody')
    (ctx.slides_dir / 'ddd-DE-Vier-current.tex').write_text('%% Translation of: aaa-EN-One\nbody')
    deck = make_deck('\\slide{aaa-EN-One}\n\\conditionalslide[instructor]{bbb-EN-Two}\n\\slidestep{ccc-EN-Three}[instructor]{1}\n'
                     '\\slidestep{ccc-EN-Three}[during-course]{1}\n\\slide{ddd-DE-Vier}\n\\slide{aaa-EN-One}\n')
    outline = deck_outline.resolve_outline(ctx, deck, view, language)
    assert any(r.hidden for r in outline.rows)
    for row in outline.rows:
        args = (ctx, deck, row.call, row.position, language)
        kwargs = dict(frame_number=row.frame_number, occurrence_key=row.key, hidden=row.hidden)
        old = preview_target.for_call(*args, **kwargs)
        resolutions.reset()
        new = preview_target.for_call(*args, **kwargs, outline=outline)
        assert (resolutions.slots, resolutions.scans) == (0, 0)
        assert new == old and new.key == old.key and new.presenter_frame_number == old.presenter_frame_number
        assert new.presenter_frame_number == outline.instructor_frames[row.key]
    # an outline of another view or deck is no source for the numbers: the resolver answers
    resolutions.reset()
    other = 'DE' if language == 'EN' else 'EN'
    preview_target.for_call(ctx, deck, outline.rows[0].call, 1, other, occurrence_key=outline.rows[0].key, outline=outline)
    assert resolutions.slots == 1 and resolutions.scans == 2
