# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Protected regions of a slide (protected_regions.py) and the edit rule built on them (edits.protected_problem)."""
from __future__ import annotations

from conftest import SLIDE_TEXT

from slidemage.slide_protection import PROTECTED_MESSAGE, protected_problem
from slidemage.protected_regions import mask_protected_regions, protected_spans

TEXT = SLIDE_TEXT.replace("\r\n", "\n")


def test_the_masked_parts_are_header_and_version_line_only():
    parts = list(mask_protected_regions(TEXT).placeholders.values())
    assert [p[:8] for p in parts] == ["%% Inclu", "\\setSlid"]
    assert "\\vbox to 0pt" in TEXT and "\\vbox to 0pt" in mask_protected_regions(TEXT).masked_text


def test_a_byte_order_mark_does_not_hide_the_header_comment():
    masked = mask_protected_regions("\ufeff" + TEXT)
    assert masked.masked_text.startswith("\ufeff%%%PROTECTED_0%%%")
    assert "%% Included in decks" in masked.placeholders["%%%PROTECTED_0%%%"]


def test_overlay_blocks_are_editable_since_2026_10_30():
    text = "\\begin{x}\n\\vbox to 0pt{\\vss % a { brace in a comment\n\\hbox{a}\\hbox{b}}\n\\end{x}\n"
    assert not mask_protected_regions(text).placeholders and protected_spans(text) == []
    assert protected_problem(TEXT, TEXT.replace("{overlay}", "{moved}")) is None
    assert protected_problem(TEXT, TEXT.replace("\t\\vbox to 0pt{\\vss\\hbox{overlay}}\n", "")) is None


def test_moving_the_header_or_the_version_line_is_refused():
    assert protected_problem(TEXT, TEXT.replace("First", "1st")) is None
    assert protected_problem(TEXT, "\\documentclass{x}\n" + TEXT) == PROTECTED_MESSAGE      # header no longer first
    swapped = "\\begin{standardframe}{Hello}\n" + TEXT.replace("\\begin{standardframe}{Hello}\n", "", 1)
    assert protected_problem(TEXT, swapped) == PROTECTED_MESSAGE
    assert protected_problem("\ufeff" + TEXT, "\ufeff" + TEXT.replace("First", "1st")) is None


# v0.14.25: a slide's own notes at the top (single '%') are its text; only SlideMage's '%%' lines are protected.
NOTED = ("% Source: a paper, slide 3.\n% The chart is to stay this size (2026-07-06, direct instruction).\n%\n"
         "%% Included in decks: test\n%%\n\n\\setSlideVersion{1-0-1}\n\\begin{standardframe}{Hello}\n"
         "\t\\item First point\n\\end{standardframe}\n")


def test_only_the_managed_lines_of_the_header_are_protected():
    parts = list(mask_protected_regions(NOTED).placeholders.values())
    assert parts == ["%% Included in decks: test\n%%\n", "\\setSlideVersion{1-0-1}"]
    assert "% Source: a paper" in mask_protected_regions(NOTED).masked_text


def test_the_notes_above_the_managed_lines_may_change_or_go():
    assert protected_problem(NOTED, NOTED.replace("a paper, slide 3", "Smith (2020), slide 3")) is None
    assert protected_problem(NOTED, NOTED.replace("% The chart is to stay this size (2026-07-06, direct instruction).\n", "")) is None
    without_notes = NOTED[NOTED.index("%% Included"):]
    assert protected_problem(NOTED, without_notes) is None                     # the managed lines now start the file
    assert protected_problem(NOTED, "% A new first note\n" + NOTED) is None


def test_the_managed_lines_stay_protected_and_inside_the_header():
    assert protected_problem(NOTED, NOTED.replace("decks: test", "decks: other")) == PROTECTED_MESSAGE
    assert protected_problem(NOTED, NOTED.replace("%% Included in decks: test\n%%\n", "")) == PROTECTED_MESSAGE
    moved = NOTED.replace("%% Included in decks: test\n%%\n", "").replace(
        "\\begin{standardframe}{Hello}\n", "\\begin{standardframe}{Hello}\n%% Included in decks: test\n%%\n")
    assert protected_problem(NOTED, moved) == PROTECTED_MESSAGE                # out of the leading comment block
    assert protected_problem(NOTED, "\\relax\n" + NOTED) == PROTECTED_MESSAGE   # a non-comment line above them
    assert protected_problem(NOTED, NOTED.replace("1-0-1", "1-0-2")) == PROTECTED_MESSAGE


def test_a_note_in_the_header_can_be_selected():
    from slidemage import selection
    start = NOTED.index("a paper")
    assert not any(a < start + 7 and start < b for a, b in protected_spans(NOTED))
    managed = NOTED.index("Included")
    assert any(a <= managed < b for a, b in protected_spans(NOTED))
    assert selection.PROTECTED.startswith("The selection touches a protected part")
