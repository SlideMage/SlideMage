# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
import pytest

from slidemage import deck_new, deck_scan


def test_new_deck_is_scanned_and_refuses_invalid_names_or_overwrites(ctx):
    ctx.decks_dir.mkdir(exist_ok=True)
    dest = deck_new.new_deck(ctx, " Lecture 1 ", "acme", "Course")
    assert dest == ctx.decks_dir / "Lecture 1.tex"
    text = dest.read_text(encoding="utf-8")
    assert "\\input{SlideMage_template_acme}" in text
    assert "\\decktags{course}" in text
    assert "\\newcommand{\\FooterText}{Lecture 1}" in text
    assert text.index("\\decktags") < text.index("\\begin{document}") < text.index("\\end{document}")
    assert [d.name for d in deck_scan.scan_decks(ctx)] == ["Lecture 1"]

    for bad in ("Lecture 1", "", "x/y"):
        with pytest.raises(ValueError):
            deck_new.new_deck(ctx, bad, "slidemage")
    assert dest.read_text(encoding="utf-8") == text
