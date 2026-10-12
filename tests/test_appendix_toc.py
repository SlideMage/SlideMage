"""The generated appendix (agenda + thumbnail grids): which compiles carry it, and which slides it lists."""
from __future__ import annotations

from pathlib import Path

import pytest

from slidemage.project import transitional_context
from slidemage import appendix_toc, compiler, deck_editor
from slidemage.compiler import CompileJob
from slidemage.deck_scan import Deck, parse_chapters

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
    doc_begin = text.find("\\begin{document}")
    return Deck(
        name="demo", path=Path("demo.tex"), archived=False, text=text, supports_version=True,
        uses_biblatex=False, preamble_end=doc_begin + len("\\begin{document}"),
        chapters=parse_chapters(text), output_folders={}, tags=[])


def listed_ids(tex: str) -> list[str]:
    return [i for i in ("aaa", "bbb", "ccc", "ddd", "eee") if f"\\hyperlink{{{i}}}" in tex]


def test_the_appendix_lists_the_slides_of_its_own_version():
    deck = make_deck()
    assert listed_ids(appendix_toc.generate_appendix_tex(transitional_context(), deck, "t", "instructor")) == [
        "aaa", "bbb", "ccc", "eee"]
    assert "\\hyperlink{fff}" in appendix_toc.generate_appendix_tex(transitional_context(), deck, "t", "instructor")
    for version in ("during-course", "after-course"):
        assert "\\hyperlink{fff}" not in appendix_toc.generate_appendix_tex(transitional_context(), deck, "t", version)
        assert listed_ids(appendix_toc.generate_appendix_tex(transitional_context(), deck, "t", version)) == [
            "aaa", "bbb", "ddd", "eee"], version

    text = (
        "\\documentclass{beamer}\n\\begin{document}\n"
        "\\slide{abc-EN-Old}\n% \\slide{xyz-EN-Old}\n\\end{document}\n"
    )
    deck = make_deck(text)
    calls = deck_editor.parse_slide_calls(deck)
    commented = {c.id_slug: deck_editor.is_commented_out(deck.text, c) for c in calls}
    assert commented == {"abc-EN-Old": False, "xyz-EN-Old": True}
    assert "\\hyperlink{abc}" in appendix_toc.generate_appendix_tex(transitional_context(), deck, "t", "instructor")
    assert "\\hyperlink{xyz}" not in appendix_toc.generate_appendix_tex(transitional_context(), deck, "t", "instructor")


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
    # Regression: every whole-deck version gets the appendix and keeps its PDF name.
    assert "appendix" not in job.jobname
    assert job.jobname == CompileJob(deck, version, job.chapter, presenter=presenter).jobname
    text = compiler.wrapper_text(transitional_context(), job)
    assert ("\\appendix" in text) == applies
    assert ("\\def\\SMAppendixTocOverride{1}" in text) == applies
    if applies:
        body_end = text.index("\\slide{eee-EN-Extra}")
        assert body_end < text.index("\\appendix") < text.rindex("\\end{document}")
    if applies and version in ("during-course", "after-course"):
        assert f"\\def\\deckversionoverride{{{version}}}" in text
        assert "\\hyperlink{ddd}" in text and "\\hyperlink{ccc}" not in text
