# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""New deck: an empty, valid deck file in a template, tagged with its group."""
import pytest

from slidemage import deck_new, deck_scan


def test_new_deck_is_written_scanned_and_tagged(tmp_path):
    from slidemage import project
    root = tmp_path / "proj"
    (root / "decks").mkdir(parents=True)
    ctx = project.ProjectContext(root)
    dest = deck_new.new_deck(ctx, " Lecture 1 ", "acme", "Course")
    assert dest == root / "decks" / "Lecture 1.tex"
    text = dest.read_text(encoding="utf-8")
    assert "\\input{SlideMage_template_acme}" in text
    assert "\\decktags{course}" in text
    assert "\\newcommand{\\FooterText}{Lecture 1}" in text
    assert text.index("\\decktags") < text.index("\\begin{document}") < text.index("\\end{document}")
    assert [d.name for d in deck_scan.scan_decks(ctx)] == ["Lecture 1"]


def test_new_deck_refuses_existing_and_invalid_names(tmp_path):
    from slidemage import project
    root = tmp_path / "proj"
    (root / "decks").mkdir(parents=True)
    ctx = project.ProjectContext(root)
    deck_new.new_deck(ctx, "a", "slidemage")
    for bad in ("a", "", "x/y"):
        with pytest.raises(ValueError):
            deck_new.new_deck(ctx, bad, "slidemage")
    assert "\\decktags" not in (root / "decks" / "a.tex").read_text(encoding="utf-8")
