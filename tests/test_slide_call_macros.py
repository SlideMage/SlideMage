# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The slide-call macros live in deck_editor; every other module that lists them must follow that table."""
import pytest

from slidemage import deck_editor, deck_language, latex_edit, prose_spans, slide_usage
from slidemage.deck_editor import ALL_MACROS, PINNED_TO_PLAIN

SAMPLES = {"slideversion": r"\slideversion{a-b}{v1}", "omitslideversion": r"\omitslideversion{a-b}{v1}",
           "slidestep": r"\slidestep{a-b}{1}"}


def sample(macro: str) -> str:
    return SAMPLES.get(macro, "\\" + macro + "{a-b}")


@pytest.mark.parametrize("macro", sorted(ALL_MACROS))
def test_every_user_of_the_table_knows_the_macro(macro):
    call = sample(macro)
    match = deck_editor.SLIDE_CALL_RE.fullmatch(call)
    assert match is not None
    assert deck_editor.DECK_CALL_RE.match(call)
    assert latex_edit._DECK_CALL_RE.match(call)
    assert macro in prose_spans.NO_PROSE


def test_the_deck_call_pattern_ends_at_the_macro_name():
    assert deck_editor.DECK_CALL_RE.match(r"\SMReview[note]{")
    assert not deck_editor.DECK_CALL_RE.match(r"\slidefoo{a-b}")
    assert not deck_editor.DECK_CALL_RE.match(r"\sli")


def test_the_pinned_tables_are_views_of_the_one_table():
    assert slide_usage.PINNED is PINNED_TO_PLAIN and deck_language.PARTNER_MACROS is PINNED_TO_PLAIN
    assert slide_usage.PINNABLE == {plain: pinned for pinned, plain in PINNED_TO_PLAIN.items()}
    assert set(PINNED_TO_PLAIN) | set(PINNED_TO_PLAIN.values()) <= ALL_MACROS
    assert set(PINNED_TO_PLAIN) == deck_editor.VERSIONED_MACROS
