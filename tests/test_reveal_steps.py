# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Reveal steps: reading overlay specs, what a slide's text says about its steps, which steps a deck call includes."""
from __future__ import annotations

import pytest

from slidemage import deck_editor, reveal_steps
from slidemage.deck_editor import expand_steps, format_steps


@pytest.mark.parametrize("spec, n, expected", [
    ("1", 5, {1}),
    ("2-", 5, {2, 3, 4, 5}),
    ("-3", 5, {1, 2, 3}),
    (" 1 , 3 - 4 ", 5, {1, 3, 4}),
    ("4-9", 5, {4, 5}),              # clipped to the steps there are
    ("7", 5, set()),
    (None, 3, {1, 2, 3}),
])
def test_expand_steps(spec, n, expected):
    assert expand_steps(spec, n) == frozenset(expected)


@pytest.mark.parametrize("spec", ["a", "1,,2", "1--2"])
def test_expand_steps_refuses_what_it_cannot_read(spec):
    with pytest.raises(ValueError):
        expand_steps(spec, 5)


@pytest.mark.parametrize("steps, n, like, expected", [
    ({1}, 5, None, "1"),
    ({1, 2}, 5, None, "1,2"),
    ({1, 2, 3}, 5, None, "1-3"),
    ({1, 3, 4, 5}, 5, None, "1,3-5"),
    ({2, 3, 4, 5}, 5, "2-", "2-"),          # an open spec stays open when the set still reaches the end
    ({2, 3, 4, 5}, 5, "2-5", "2-5"),
    ({2, 3, 4}, 5, "2-", "2-4"),
    ({5}, 5, "5-", "5"),
])
def test_format_steps(steps, n, like, expected):
    spec = format_steps(steps, n, like)
    assert spec == expected and expand_steps(spec, n) == frozenset(steps)


def test_format_steps_needs_a_step():
    with pytest.raises(ValueError):
        format_steps(set(), 3)


def test_scan_reads_the_things_that_matter_and_ignores_comments():
    plain = reveal_steps.scan_slide("\\begin{standardframe}{T}\n\\only<2>{x}\\pause y <+->\n\\end{standardframe}\n")
    assert plain == reveal_steps.SlideScan(may_reveal=True)       # plain beamer reveals: no version logic
    assert not reveal_steps.scan_slide("\\begin{standardframe}{T}\nText, a < b > c\n\\end{standardframe}\n").may_reveal
    scan = reveal_steps.scan_slide(
        "\\SMFinalStateForStudents\n\\begin{frame}<2-3>{T}\n\\conditionalpause\n\\deckitem<3-> x\n\\end{frame}\n")
    assert scan.final_flag and scan.version_dependent and scan.own_frame_spec == "2-3"
    commented = reveal_steps.scan_slide("% \\conditionalpause and \\SMFinalStateForStudents\n\\pause\n")
    assert not commented.version_dependent and not commented.final_flag
    assert reveal_steps.scan_slide("\\begin{frame}[allowframebreaks]{T}\n\\end{frame}").frame_breaks
    for macro in ("deckonly<2>[instructor]{x}", "ifSMInstructorVersion x", "deckrevealfinal[2]{x}", "deckreveal[4]{x}"):
        assert reveal_steps.scan_slide("\\" + macro).version_dependent, macro
    assert not reveal_steps.scan_slide("\\decktags{a}").version_dependent


def call(macro="slidestep", conditions=None, steps="1,2", version=None):
    return deck_editor.SlideCall(
        macro=macro, id="abc", slug="Demo", version=version, conditions=conditions, steps=steps, call_start=0,
        call_end=1, line_start=0, line_end=1, indent="", editable=True, readonly_reason=None, chapter=None)


def test_plan_of_a_slidestep_call_marks_what_it_includes_per_version():
    scan = reveal_steps.SlideScan()
    both = call(conditions=["instructor"], steps="1,3")
    plan = reveal_steps.plan_for(both, "instructor", 4, scan)
    assert plan.included == {1, 3} and plan.marked and plan.shown and plan.n == 4
    assert plan.stops(deck_only=False) == [1, 2, 3, 4] and plan.stops(deck_only=True) == [1, 3]
    elsewhere = reveal_steps.plan_for(both, "during-course", 4, scan)
    assert not elsewhere.shown and elsewhere.included == frozenset()
    assert elsewhere.stops(deck_only=True) == [1, 2, 3, 4]            # nothing to narrow to: all steps stay


def test_a_slide_opens_at_a_step_the_deck_includes_when_only_deck_steps_are_offered():
    assert reveal_steps.snap_to_stops(1, [2, 4]) == 2           # forward from the first step: the first included one
    assert reveal_steps.snap_to_stops(5, [2, 4]) == 4           # back from the last step: the last included one
    assert reveal_steps.snap_to_stops(1, [1, 3]) == 1 and reveal_steps.snap_to_stops(4, [1, 3, 4]) == 4


def test_final_state_flag_leaves_students_the_last_step_unless_a_slidestep_overrides_it():
    scan = reveal_steps.SlideScan(final_flag=True)
    plain = call(macro="slide", steps=None)
    assert reveal_steps.plan_for(plain, "instructor", 4, scan).included == {1, 2, 3, 4}
    student = reveal_steps.plan_for(plain, "during-course", 4, scan)
    assert student.included == {4} and student.final_only and student.marked
    step = call(conditions=["during-course", "after-course"], steps="2-")
    assert reveal_steps.plan_for(step, "during-course", 4, scan).included == {2, 3, 4}


def test_the_slides_own_frame_spec_is_marked_apart_from_the_deck():
    scan = reveal_steps.SlideScan(own_frame_spec="2-3")
    plan = reveal_steps.plan_for(call(macro="slide", steps=None), "instructor", 4, scan)
    assert plan.slide_excluded == {1, 4} and plan.marked and plan.reliable
    odd = reveal_steps.plan_for(call(macro="slide", steps=None), "instructor", 4, reveal_steps.SlideScan(own_frame_spec="\\n"))
    assert not odd.reliable and not odd.slide_excluded
    assert not reveal_steps.plan_for(None, "instructor", 4, reveal_steps.SlideScan(frame_breaks=True)).reliable


def test_unreadable_steps_in_a_deck_call_are_not_guessed():
    plan = reveal_steps.plan_for(call(steps="x"), "instructor", 3, reveal_steps.SlideScan())
    assert not plan.marked and not plan.reliable and plan.note
