"""Protected regions of a slide (protected_regions.py) and the edit rule built on them (edits.protected_problem)."""
from __future__ import annotations

from conftest import SLIDE_TEXT

from slidemage.slide_protection import PROTECTED_MESSAGE, protected_problem
from slidemage.protected_regions import mask_protected_regions

TEXT = SLIDE_TEXT.replace("\r\n", "\n")


def test_the_masked_parts_are_header_version_and_overlay():
    parts = list(mask_protected_regions(TEXT).placeholders.values())
    assert [p[:8] for p in parts] == ["%% Inclu", "\\setSlid", "\\vbox to"]


def test_a_byte_order_mark_does_not_hide_the_header_comment():
    masked = mask_protected_regions("\ufeff" + TEXT)
    assert masked.masked_text.startswith("\ufeff%%%PROTECTED_0%%%")
    assert "%% Included in decks" in masked.placeholders["%%%PROTECTED_0%%%"]


def test_a_comment_in_an_overlay_block_does_not_end_it_early():
    text = "\\begin{x}\n\\vbox to 0pt{\\vss % a { brace in a comment\n\\hbox{a}\\hbox{b}}\n\\end{x}\n"
    (part,) = mask_protected_regions(text).placeholders.values()
    assert part.endswith("\\hbox{b}}") and part.count("{") == 4
    escaped = "\\vbox to 0pt{\\vss \\{ \\% \\hbox{c}}\n"
    assert list(mask_protected_regions(escaped).placeholders.values()) == [escaped.strip()]


def test_moving_the_header_or_a_protected_block_is_refused():
    assert protected_problem(TEXT, TEXT.replace("First", "1st")) is None
    assert protected_problem(TEXT, "\\documentclass{x}\n" + TEXT) == PROTECTED_MESSAGE      # header no longer first
    swapped = "\\begin{standardframe}{Hello}\n" + TEXT.replace("\\begin{standardframe}{Hello}\n", "", 1)
    assert protected_problem(TEXT, swapped) == PROTECTED_MESSAGE
    assert protected_problem("\ufeff" + TEXT, "\ufeff" + TEXT.replace("First", "1st")) is None
