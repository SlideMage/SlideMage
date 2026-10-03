"""The generated appendix (agenda + thumbnail grids): which compiles carry it, and which slides it lists."""
from __future__ import annotations

from pathlib import Path

from slidemage import appendix_toc, compiler
from slidemage.compiler import CompileJob
from slidemage.deck_scan import Deck, _parse_chapters

DECK = (
    "\\documentclass{beamer}\n\\begin{document}\n"
    "\\slide{aaa-EN-Intro-slide}\n"
    "\\section{Basics}\n"
    "\\slide{bbb-EN-Everyone}\n"
    "\\conditionalslide[instructor]{ccc-EN-Instructor-only}\n"
    "\\slidestep{ddd-EN-Steps}[during-course,after-course]{1}\n"
    "\\section{Appendix}\n"
    "\\slide{eee-EN-Extra}\n"
    "\\end{document}\n"
)


def make_deck() -> Deck:
    doc_begin = DECK.find("\\begin{document}")
    return Deck(
        name="demo", path=Path("demo.tex"), archived=False, text=DECK, supports_version=True,
        uses_biblatex=False, preamble_end=doc_begin + len("\\begin{document}"),
        chapters=_parse_chapters(DECK), output_folders={}, tags=[])


def listed_ids(tex: str) -> list[str]:
    return [i for i in ("aaa", "bbb", "ccc", "ddd", "eee") if f"\\hyperlink{{{i}}}" in tex]


def test_every_whole_deck_job_gets_the_appendix_but_not_a_chapter_job():
    deck = make_deck()
    for version in (None, "instructor", "during-course", "after-course"):
        job = CompileJob(deck, version, None, appendix_toc=True)
        assert job._appendix_applies and job.jobname.endswith("-appendix"), version
    presenter = CompileJob(deck, "instructor", None, presenter=True, appendix_toc=True)
    assert presenter._appendix_applies
    chapter = CompileJob(deck, "after-course", deck.chapters[0], appendix_toc=True)
    assert not chapter._appendix_applies and "appendix" not in chapter.jobname
    assert not CompileJob(deck, "after-course", None, appendix_toc=False)._appendix_applies


def test_the_appendix_lists_the_slides_of_its_own_version():
    deck = make_deck()
    assert listed_ids(appendix_toc.generate_appendix_tex(deck, "t", "instructor")) == [
        "aaa", "bbb", "ccc", "eee"]
    for version in ("during-course", "after-course"):
        assert listed_ids(appendix_toc.generate_appendix_tex(deck, "t", version)) == [
            "aaa", "bbb", "ddd", "eee"], version


def test_student_wrapper_carries_the_appendix_after_the_body():
    deck = make_deck()
    job = CompileJob(deck, "during-course", None, appendix_toc=True)
    text = compiler._wrapper_text(job)
    assert "\\def\\deckversionoverride{during-course}" in text
    assert "\\def\\SMAppendixTocOverride{1}" in text
    body_end = text.index("\\slide{eee-EN-Extra}")
    assert body_end < text.index("\\appendix") < text.rindex("\\end{document}")
    assert "\\hyperlink{ddd}" in text and "\\hyperlink{ccc}" not in text
