"""Reveal steps with real TeX (skipped without latexmk): an all-steps render has page k = step k, whatever the
call, the final-state flag or the slide's own frame says, and the version macros change the count per version."""
from __future__ import annotations

import shutil

import pymupdf
import pytest

from conftest import EXAMPLE_PROJECT
from slidemage import slide_preview

pytestmark = pytest.mark.skipif(shutil.which("latexmk") is None or shutil.which("lualatex") is None,
                                reason="needs a TeX installation")

SLIDE_ID = "zz9-EN-Steps-Test"
FRAME = "\\begin{standardframe}{Steps}\nA\\pause B\\pause C\n\\end{standardframe}\n"


@pytest.fixture
def slide_file():
    path = EXAMPLE_PROJECT.slides_dir / f"{SLIDE_ID}-current.tex"
    created = []

    def write(text):
        path.write_text(text, encoding="utf-8")
        created.append(path)
        return path

    yield write
    for item in created:
        item.unlink(missing_ok=True)


def pages_of(pdf):
    with pymupdf.open(pdf) as doc:
        return [page.get_text().replace("\n", " ") for page in doc]


def text_render(body, view="instructor", all_steps=True):
    return slide_preview.render_slide_text_to_pdf(
        EXAMPLE_PROJECT, SLIDE_ID, body, deck_version=view, footer_timestamp=False, capture_snapshot=False,
        all_steps=all_steps)


def call_render(macro="slide", view="instructor", steps=None, all_steps=True):
    return slide_preview.render_slide_to_pdf(
        EXAMPLE_PROJECT, macro, SLIDE_ID, deck_version=view, footer_timestamp=False, steps=steps,
        capture_snapshot=False, all_steps=all_steps)


def test_two_pauses_are_three_steps_and_page_k_is_step_k():
    pages = pages_of(text_render(FRAME))
    assert len(pages) == 3
    assert [("A" in p, "B" in p, "C" in p) for p in pages] == [(True, False, False), (True, True, False), (True, True, True)]


def test_a_raw_frame_spec_is_overridden_so_page_k_is_still_step_k():
    raw = "\\begin{frame}<2-3>{Raw}\nA\\pause B\\pause C\\pause D\n\\end{frame}\n"
    assert len(pages_of(text_render(raw, all_steps=False))) == 2          # what the slide itself asks for
    pages = pages_of(text_render(raw))
    assert len(pages) == 4 and "A" in pages[0] and "D" in pages[3] and "D" not in pages[2]


def test_a_slidestep_call_keeps_its_steps_unless_all_steps_is_asked_for(slide_file):
    slide_file(FRAME)
    assert len(pages_of(call_render("slidestep", steps="1", all_steps=False))) == 1
    assert len(pages_of(call_render("slidestep", steps="1", all_steps=True))) == 3


def test_the_final_state_flag_does_not_cut_a_student_render_to_the_last_step(slide_file):
    slide_file("\\SMFinalStateForStudents\n" + FRAME)
    assert len(pages_of(call_render(view="instructor", all_steps=True))) == 3
    assert len(pages_of(call_render(view="during-course", all_steps=True))) == 3


def test_a_conditional_pause_counts_only_in_the_versions_that_pause():
    body = "\\begin{standardframe}{Steps}\nQuestion\\conditionalpause\\par Answer\n\\end{standardframe}\n"
    assert len(pages_of(text_render(body, "instructor"))) == 2
    assert len(pages_of(text_render(body, "during-course"))) == 1
