# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The generated appendix (agenda + thumbnail grids): which compiles carry it, and which slides it lists."""
from __future__ import annotations

from pathlib import Path

import pytest

from slidemage import appendix_toc, compiler
from slidemage.compiler import CompileJob
from slidemage.deck_scan import Deck, parse_chapters
from conftest import EXAMPLE_PROJECT

DECK = (
    "\\documentclass{beamer}\n\\begin{document}\n"
    "\\slide{aaa-EN-Intro-slide}\n"
    "\\section{Basics}\n"
    "\\slide{bbb-EN-Everyone}\n"
    "\\omitslide{fff-EN-Omitted}\n"
    "\\conditionalslide[instructor]{ccc-EN-Instructor-only}\n"
    "\\slidestep{ddd-EN-Steps}[during-course,after-course]{1}\n"
    "\\section{Appendix}\n"
    "\\slide{eee-EN-Extra}\n"
    "\\end{document}\n"
)


def make_deck(text=DECK) -> Deck:
    return Deck(
        name="demo", path=Path("demo.tex"), archived=False, text=text, supports_version=True,
        uses_biblatex=False, preamble_end=text.index("\\begin{document}") + len("\\begin{document}"),
        chapters=parse_chapters(text), output_folders={}, tags=[])


def test_the_appendix_lists_only_slides_for_its_view():
    deck = make_deck(DECK.replace("\\omitslide", "% \\slide{xxx-EN-Commented}\n\\omitslide"))
    expected = {
        "instructor": {"aaa", "bbb", "ccc", "eee", "fff"},
        "during-course": {"aaa", "bbb", "ddd", "eee"},
        "after-course": {"aaa", "bbb", "ddd", "eee"},
    }
    for view, ids in expected.items():
        tex = appendix_toc.generate_appendix_tex(EXAMPLE_PROJECT, deck, "t", view)
        assert {slug for slug in ("aaa", "bbb", "ccc", "ddd", "eee", "fff", "xxx")
                if f"\\hyperlink{{{slug}}}" in tex} == ids, view


@pytest.mark.parametrize("version, presenter, chapter, enabled, applies", [
    (None, False, False, True, True),
    ("instructor", False, False, True, True),
    ("during-course", False, False, True, True),
    ("after-course", False, False, True, True),
    ("instructor", True, False, True, True),
    ("after-course", False, True, True, False),
    ("after-course", False, False, False, False),
], ids=["unversioned", "instructor", "during", "after", "presenter", "chapter", "disabled"])
def test_wrapper_carries_appendix_after_body_for_whole_deck(version, presenter, chapter, enabled, applies):
    deck = make_deck()
    job = CompileJob(deck, version, deck.chapters[0] if chapter else None,
                     presenter=presenter, appendix_toc=enabled)
    assert job.jobname == CompileJob(deck, version, job.chapter, presenter=presenter).jobname
    text = compiler.wrapper_text(EXAMPLE_PROJECT, job)
    assert ("\\appendix" in text) == applies
    assert ("\\def\\SMAppendixTocOverride{1}" in text) == applies
    if applies:
        assert text.index("\\slide{eee-EN-Extra}") < text.index("\\appendix") < text.rindex("\\end{document}")
    if applies and version in ("during-course", "after-course"):
        assert f"\\def\\deckversionoverride{{{version}}}" in text
        assert "\\hyperlink{ddd}" in text and "\\hyperlink{ccc}" not in text


def test_the_appendix_uses_the_stored_instructor_reference_or_a_box(ctx):
    from io import BytesIO
    from PIL import Image
    from slidemage import dep_hash, preview_target, render_key, render_store
    from slidemage.fileio import text_sha256

    ctx.slides_dir.mkdir()
    source = ctx.slides_dir / "aaa-EN-Intro-slide-current.tex"
    source.write_text("saved slide")
    deck = make_deck()
    store = render_store.RenderStore(ctx)
    try:
        resolver = render_key.Resolver(ctx, dep_hash.HashCache(store.db, store.lock), store)
        target = preview_target.for_path(ctx, source)
        unit = render_key.unit_for(target, "instructor", "EN", "another-deck")
        pdf = ctx.root / "reference.pdf"
        pdf.write_bytes(b"%PDF reference")
        first, last = BytesIO(), BytesIO()
        Image.new("RGB", (1920, 1080), "red").save(first, format="PNG")
        Image.new("RGB", (1920, 1080), "blue").save(last, format="PNG")
        store.put("reference", pdf, [first.getvalue(), last.getvalue()],
                  dict(unit=unit.label, template=unit.template, inventory=[],
                       manifest=[["project", "slides/aaa-EN-Intro-slide-current.tex", text_sha256(source.read_text())]]))
        tex = appendix_toc.generate_appendix_tex(ctx, deck, unit.template, resolver=resolver)
        png, = (ctx.build_dir / "appendix-thumbs" / unit.template).glob("*.png")
        assert png.as_posix() in tex
        with Image.open(png) as image:
            assert image.getpixel((150, 85)) == (0, 0, 255)
        store.clear()
        assert png.is_file()  # the running compile owns its copy
        tex = appendix_toc.generate_appendix_tex(ctx, deck, unit.template, resolver=resolver)
        assert r"\includegraphics" not in tex
        assert r"\hyperlink{aaa}{\fbox" in tex
    finally:
        store.close()
