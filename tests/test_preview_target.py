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
