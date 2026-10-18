"""Deck context with real TeX (skipped without latexmk): a contents slide listing every section of a tiny deck, as
a page compile in the deck's last whole-deck compile (approach A) and with the skeleton around it (approach B)."""
from __future__ import annotations

import shutil
import time

import pymupdf
import pytest

from conftest import EXAMPLE
from slidemage import compile_records, compiler, deck_context, deck_editor, deck_scan, preview_target
from slidemage.project import ProjectContext, _ignore_template_build_output

pytestmark = pytest.mark.skipif(shutil.which("latexmk") is None or shutil.which("lualatex") is None,
                                reason="needs a TeX installation")

SLIDES = {
    "zz1-EN-Intro": "\\begin{standardframe}{Introduction}\nHello\n\\end{standardframe}\n",
    "zz2-EN-Contents": "\\begin{standardframe}{Contents}\n\\tableofcontents[hideallsubsections]\n\\end{standardframe}\n",
    "zz3-EN-Agenda": "\\begin{standardframe}{Chapter}\n\\SMChapterAgenda\n\\end{standardframe}\n",
    "zz4-EN-Fourth": "\\begin{standardframe}{Fourth slide}\nFour\n\\end{standardframe}\n",
    "zz5-EN-Fifth": "\\begin{standardframe}{Fifth slide}\nFive\n\\end{standardframe}\n",
}
BODY = ("\\begin{document}\n\\slide{zz1-EN-Intro}\n\\section{Alpha}\n\\slide{zz2-EN-Contents}\n\\slide{zz3-EN-Agenda}\n"
        "\\slide{zz4-EN-Fourth}\n\\section{Beta}\n\\slide{zz5-EN-Fifth}\n\\end{document}\n")


@pytest.fixture(scope="module")
def tiny(tmp_path_factory):
    """A copy of the example project with a five-slide, two-section deck, compiled once as a whole."""
    root = tmp_path_factory.mktemp("ctx") / "example"
    shutil.copytree(EXAMPLE, root, ignore=_ignore_template_build_output)
    for old in (root / "decks").glob("*.tex"):
        old.unlink()
    ctx = ProjectContext.at(root)
    for slug, body in SLIDES.items():
        (root / "slides" / f"{slug}-current.tex").write_text(body, encoding="utf-8")
    manual = (EXAMPLE / "decks" / "slidemage-manual.tex").read_text(encoding="utf-8").splitlines()
    head = "\n".join(manual[11:manual.index("\\begin{document}") if "\\begin{document}" in manual else 33])
    head = head.replace("\\decktags{manual}", "").replace("\\deckappendixtoc", "")
    deck_file = root / "decks" / "zzdeck.tex"
    deck_file.write_text(head + "\n" + BODY, encoding="utf-8")
    deck = deck_scan.scan_dir(root / "decks", False)[0]
    job = compiler.CompileJob(deck, "instructor", None)
    assert compiler.run_job(ctx, job, lambda line: None)
    deadline = time.monotonic() + 120
    while compile_records.read_record(ctx.build_dir, job.jobname) is None and time.monotonic() < deadline:
        time.sleep(1)                                    # the record is written when the PDF has been published
    assert compile_records.read_record(ctx.build_dir, job.jobname) is not None
    return ctx, deck_file


def pages_text(pdf):
    with pymupdf.open(pdf) as doc:
        return [page.get_text().replace("\n", " ") for page in doc]


def call_of(deck, slide_id):
    return next(c for c in deck_editor.parse_slide_calls(deck) if c.id == slide_id)


def test_in_the_deck_a_contents_slide_lists_every_section_and_has_its_real_frame_number(tiny):
    ctx, deck_file = tiny
    deck = deck_scan.scan_dir(deck_file.parent, False)[0]
    pdf = deck_context.render_in_deck(ctx, deck, "instructor", "zz2", "zz2-EN-Contents", print)
    assert pdf is not None and deck_context.mode_of(pdf) == deck_context.DECK
    (text,) = pages_text(pdf)
    assert "Alpha" in text and "Beta" in text and "(slide id: zz2" in text and text.rstrip().endswith("2")


def test_in_the_deck_a_chapter_agenda_lists_the_titles_of_its_slides(tiny):
    ctx, deck_file = tiny
    deck = deck_scan.scan_dir(deck_file.parent, False)[0]
    pdf = deck_context.render_in_deck(ctx, deck, "instructor", "zz3", "zz3-EN-Agenda", print)
    assert pdf is not None
    (text,) = pages_text(pdf)
    assert "Contents" in text and "Fourth slide" in text and "Fifth slide" not in text   # slides of section Alpha


def test_a_deck_that_changed_before_the_slide_gives_no_deck_render(tiny):
    ctx, deck_file = tiny
    original = deck_file.read_text(encoding="utf-8")
    try:
        deck_file.write_text(original.replace("\\slide{zz1-EN-Intro}", "\\slide{zz1-EN-Intro}\n\\slide{zz4-EN-Fourth}"),
                             encoding="utf-8")
        deck = deck_scan.scan_dir(deck_file.parent, False)[0]
        assert deck_context.render_in_deck(ctx, deck, "instructor", "zz2", "zz2-EN-Contents", print) is None
    finally:
        deck_file.write_text(original, encoding="utf-8")


def test_with_the_skeleton_a_contents_slide_lists_every_section_and_an_agenda_its_titles(tiny):
    ctx, deck_file = tiny
    deck = deck_scan.scan_dir(deck_file.parent, False)[0]
    for slide_id, position, expected, absent in (("zz2", 2, ("Alpha", "Beta"), ()),
                                                  ("zz3", 3, ("Contents", "Fourth slide"), ("Fifth slide",))):
        target = preview_target.for_call(ctx, deck, call_of(deck, slide_id), position)
        assert target.needs_context
        skeleton = deck_context.skeleton(ctx, deck, position, target.id_slug, "instructor", "EN")
        pdf = preview_target_render_with(ctx, target, skeleton)
        (text,) = pages_text(pdf)                         # the flush frame's page is gone
        assert all(word in text for word in expected) and not any(word in text for word in absent)
        assert deck_context.mode_of(pdf) == deck_context.SKELETON


def preview_target_render_with(ctx, target, skeleton):
    from slidemage import slide_preview

    return slide_preview.render_slide_to_pdf(
        ctx, target.macro, target.id_slug, deck_version="instructor", footer_timestamp=False,
        preamble_text=target.preamble_text, frame_number=target.frame_number, capture_snapshot=False,
        context_before=skeleton.before, context_after=skeleton.after)


def test_without_any_context_the_same_slide_has_an_empty_contents_list(tiny):
    ctx, deck_file = tiny
    deck = deck_scan.scan_dir(deck_file.parent, False)[0]
    target = preview_target.for_call(ctx, deck, call_of(deck, "zz2"), 2)
    from slidemage import slide_preview

    pdf = slide_preview.render_slide_to_pdf(
        ctx, target.macro, target.id_slug, deck_version="instructor", footer_timestamp=False,
        preamble_text=target.preamble_text, frame_number=2, capture_snapshot=False)
    (text,) = pages_text(pdf)
    assert "Alpha" not in text and "Beta" not in text
