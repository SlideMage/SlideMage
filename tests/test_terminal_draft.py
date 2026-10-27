# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""terminal/draft.py: the unsent prompt read off Claude Code's screen, for Switch now."""
from slidemage.ui.workspace.terminal import draft


def lines(*shown, dim=None):
    """Screen lines as terminal.js gives them; `dim` maps a line index to its text without the dim cells."""
    dim = dim or {}
    return [[text, dim.get(i, text)] for i, text in enumerate(shown)]


RULE = "─" * 40


def test_a_one_line_draft_between_rules():
    screen = lines("> an earlier prompt", "  An earlier answer.", "", RULE, "> Make the title shorter", RULE,
                   "  ? for shortcuts")
    assert draft.prompt_draft(screen) == "Make the title shorter"      # the transcript's "> " line is not the box
    assert not draft.input_box_shown(screen)


def test_a_multi_line_draft_in_a_bordered_box():
    screen = lines("╭" + RULE + "╮", "│ > First line" + " " * 20 + "│", "│   second line" + " " * 19 + "│",
                   "╰" + RULE + "╯")
    assert draft.prompt_draft(screen) == "First line\nsecond line"


def test_the_dim_placeholder_is_no_draft_and_shows_the_box_is_ready():
    screen = lines(RULE, '> Try "fix the overflow on this slide"', RULE, dim={1: ">" + " " * 37})
    assert draft.prompt_draft(screen) == ""
    assert draft.input_box_shown(screen)


def test_no_box_on_the_screen():
    assert draft.prompt_draft(lines("Starting…", "")) == "" and not draft.input_box_shown(lines("Starting…"))


def test_a_draft_with_line_ends_is_pasted_and_one_without_is_typed():
    assert draft.paste_bytes("one line") == b"one line"
    assert draft.paste_bytes("a\nb") == b"\x1b[200~a\rb\x1b[201~"
