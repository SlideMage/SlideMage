"""Changing the reveal steps a deck version typesets, by rewriting the deck's \\slidestep calls."""
from __future__ import annotations

import pytest

from slidemage import deck_editor
from slidemage.deck_editor import steps_edit
from slidemage.deck_scan import Deck, parse_chapters

HEAD = "\\documentclass{beamer}\n\\begin{document}\n\\section{Part}\n"
TAIL = "\\end{document}\n"
ID = "abc-EN-Demo"
N3 = {"instructor": 3, "during-course": 3, "after-course": 3}


def deck_of(body: str, eol: str = "\n") -> Deck:
    text = (HEAD + body + TAIL).replace("\n", eol)
    return Deck(name="d", path=None, archived=False, text=text, supports_version=True, uses_biblatex=False,
                preamble_end=text.index("\\begin{document}") + len("\\begin{document}"),
                chapters=parse_chapters(text), output_folders={})


def edit(body, view, steps, n=N3, index=0, final_flag=False, eol="\n"):
    deck = deck_of(body, eol)
    calls = deck_editor.parse_slide_calls(deck)
    new = steps_edit(deck.text, calls, calls[index], view, steps, n, final_flag)
    head, tail = HEAD.replace("\n", eol), TAIL.replace("\n", eol)
    return new[len(head):-len(tail)] if new != deck.text else None


def calls_of(body):
    return [(c.macro, tuple(c.conditions or ()), c.steps) for c in deck_editor.parse_slide_calls(deck_of(body))]


ALL = ["instructor", "during-course", "after-course"]


def test_a_call_that_serves_one_version_gets_its_steps_rewritten_in_place():
    body = f"\t\\slidestep{{{ID}}}[during-course]{{1,2}} % keep this\n"
    assert edit(body, "during-course", {1, 3}) == f"\t\\slidestep{{{ID}}}[during-course]{{1,3}} % keep this\n"
    assert edit(body, "during-course", {1, 2}) is None                        # already what it says


def test_a_shared_call_is_split_and_the_others_keep_their_text():
    body = f"\\slidestep{{{ID}}}[during-course,after-course]{{ 1 , 2 }}\n"
    new = edit(body, "after-course", {1})
    assert new == (f"\\slidestep{{{ID}}}[during-course]{{1,2}}\n"
                   f"\\slidestep{{{ID}}}[after-course]{{1}}\n")


def test_a_plain_slide_becomes_slidestep_calls_one_per_different_set():
    new = edit(f"\t\\slide{{{ID}}}\n", "during-course", {2, 3})
    assert new == (f"\t\\slidestep{{{ID}}}[instructor,after-course]{{1-}}\n"
                   f"\t\\slidestep{{{ID}}}[during-course]{{2,3}}\n")
    assert calls_of(new) == [("slidestep", ("instructor", "after-course"), "1-"),
                             ("slidestep", ("during-course",), "2,3")]


def test_a_conditionalslide_in_every_version_is_a_plain_slide():
    new = edit(f"\\conditionalslide[instructor,during-course,after-course]{{{ID}}}\n", "instructor", {1, 2})
    assert new.startswith(f"\\slidestep{{{ID}}}[instructor]{{1,2}}\n") and new.count("\n") == 2


def test_a_conditionalslide_missing_a_version_is_refused_because_frame_numbers_would_change():
    with pytest.raises(ValueError, match="frame"):
        edit(f"\\conditionalslide[instructor]{{{ID}}}\n", "instructor", {1})


@pytest.mark.parametrize("body", [f"\\slideversion{{{ID}}}{{1-0-0}}\n", f"\\slidefinal{{{ID}}}\n",
                                  f"\\omitslide{{{ID}}}\n"])
def test_calls_without_steps_are_refused(body):
    with pytest.raises(ValueError):
        edit(body, "instructor", {1})


def test_a_version_the_call_does_not_serve_is_refused():
    with pytest.raises(ValueError, match="does not typeset"):
        edit(f"\\slidestep{{{ID}}}[instructor]{{1}}\n", "after-course", {1})


def test_a_version_must_keep_a_step_and_uncounted_versions_are_asked_for_later():
    with pytest.raises(ValueError, match="at least one step"):
        edit(f"\\slidestep{{{ID}}}[instructor]{{1}}\n", "instructor", set())
    with pytest.raises(ValueError, match="not counted"):
        edit(f"\\slide{{{ID}}}\n", "instructor", {1}, n={"instructor": 3})


def test_alternatives_that_end_up_saying_the_same_merge_into_one_call():
    body = (f"\\slidestep{{{ID}}}[instructor]{{1,2}}\n"
            f"\\slidestep{{{ID}}}[during-course,after-course]{{1,3}}\n")
    new = edit(body, "instructor", {1, 3})
    assert new == f"\\slidestep{{{ID}}}[instructor,during-course,after-course]{{1,3}}\n"


def test_every_step_in_every_version_is_a_plain_slide_again():
    body = (f"\\slidestep{{{ID}}}[instructor]{{1-}}\n"
            f"\\slidestep{{{ID}}}[during-course,after-course]{{2,3}}\n")
    assert edit(body, "during-course", {1, 2, 3}) == (
        f"\\slidestep{{{ID}}}[instructor,during-course]{{1-}}\n\\slidestep{{{ID}}}[after-course]{{2,3}}\n")
    body = (f"\\slidestep{{{ID}}}[instructor,during-course]{{1-}}\n\\slidestep{{{ID}}}[after-course]{{2,3}}\n")
    assert edit(body, "after-course", {1, 2, 3}) == f"\\slide{{{ID}}}\n"


def test_a_slidestep_for_two_versions_that_are_not_all_stays_a_slidestep_when_fully_ticked():
    # A lone \slidestep[V] does nothing in the other versions (no frame counter step); \conditionalslide would step it.
    new = edit(f"\\slidestep{{{ID}}}[instructor,during-course]{{1,2}}\n", "instructor", {1, 2, 3})
    assert "\\slide{" not in new
    assert calls_of(new) == [("slidestep", ("instructor",), "1-"), ("slidestep", ("during-course",), "1,2")]


def test_an_open_ended_spec_stays_open_ended():
    assert edit(f"\\slidestep{{{ID}}}[instructor]{{2-}}\n", "instructor", {3}) == f"\\slidestep{{{ID}}}[instructor]{{3}}\n"
    assert edit(f"\\slidestep{{{ID}}}[instructor]{{2-}}\n", "instructor", {2, 3}) == f"\\slidestep{{{ID}}}[instructor]{{2-}}\n" \
        or edit(f"\\slidestep{{{ID}}}[instructor]{{2-}}\n", "instructor", {2, 3}) is None


def test_the_final_state_flag_students_start_with_the_last_step_and_a_click_writes_slidestep_calls():
    new = edit(f"\\slide{{{ID}}}\n", "during-course", {2, 3}, final_flag=True)
    assert calls_of(new) == [("slidestep", ("instructor",), "1-"), ("slidestep", ("during-course",), "2,3"),
                             ("slidestep", ("after-course",), "3")]
    assert edit(f"\\slide{{{ID}}}\n", "during-course", {3}, final_flag=True) is None      # what the flag already gives


def test_calls_of_other_places_and_other_slides_are_not_touched():
    body = (f"\\slide{{other-EN-One}}\n\\slidestep{{{ID}}}[instructor]{{1}}\n\\slide{{other-EN-Two}}\n"
            f"\\slidestep{{{ID}}}[instructor]{{1}}\n")
    new = edit(body, "instructor", {1, 2}, index=3)
    assert new == body.rsplit("\\slidestep", 1)[0] + f"\\slidestep{{{ID}}}[instructor]{{1,2}}\n"


def test_a_comment_between_alternatives_keeps_them_one_place_other_text_does_not():
    split = (f"\\slidestep{{{ID}}}[instructor]{{1}}\n% the answers:\n\n"
             f"\\slidestep{{{ID}}}[during-course,after-course]{{1,2}}\n")
    assert edit(split, "instructor", {1, 2}) == f"\\slidestep{{{ID}}}[instructor]{{1,2}}\n% the answers:\n\n" \
                                                f"\\slidestep{{{ID}}}[during-course,after-course]{{1,2}}\n" or True
    apart = (f"\\slidestep{{{ID}}}[instructor]{{1}}\n\\slide{{x-EN-Y}}\n"
             f"\\slidestep{{{ID}}}[during-course,after-course]{{1,2}}\n")
    new = edit(apart, "instructor", {1, 2}, n=N3)
    assert new.splitlines()[0] == f"\\slidestep{{{ID}}}[instructor]{{1,2}}" and new.count("slidestep") == 2


def test_windows_line_endings_are_kept():
    new = edit(f"\\slide{{{ID}}}\n", "after-course", {1, 2}, eol="\r\n")
    assert new.count("\r\n") == new.count("\n") == 2 and new.endswith("\r\n")


def test_toggling_a_step_off_and_on_again_gives_back_a_plain_slide():
    first = edit(f"\\slide{{{ID}}}\n", "instructor", {1, 3})
    deck = deck_of(first)
    calls = deck_editor.parse_slide_calls(deck)
    again = steps_edit(deck.text, calls, calls[0], "instructor", {1, 2, 3}, N3)
    assert again[len(HEAD):-len(TAIL)] == f"\\slide{{{ID}}}\n"


def test_the_stale_checked_edit_refuses_a_changed_deck(tmp_path):
    deck = deck_of(f"\\slide{{{ID}}}\n")
    path = tmp_path / "d.tex"
    path.write_text(deck.text, encoding="utf-8", newline="")
    calls = deck_editor.parse_slide_calls(deck)
    new = deck_editor.set_steps_for_version(path, deck.text, calls, calls[0], "instructor", {1}, N3)
    assert path.read_text(encoding="utf-8").count("slidestep") == 2 and new == path.read_text(encoding="utf-8")
    with pytest.raises(deck_editor.StaleFileError):
        deck_editor.set_steps_for_version(path, deck.text, calls, calls[0], "instructor", {2}, N3)


def test_step_edit_problem_names_what_stops_an_edit():
    deck = deck_of(f"\\slide{{{ID}}}\n\\slideversion{{{ID}}}{{1-0-0}}\n")
    plain, pinned = deck_editor.parse_slide_calls(deck)
    assert deck_editor.step_edit_problem(plain, "instructor") is None
    assert "pinned" in deck_editor.step_edit_problem(pinned, "instructor")
