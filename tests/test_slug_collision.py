# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""An old untagged slug that starts with a capital word ("x7k-IT-Governance") would be read as a language once
the project has that language: slide_rename finds such slides before the language is added and tags them."""
from __future__ import annotations

import pytest

from slidemage import slide_language, slide_rename
from slidemage.project import ProjectContext


@pytest.fixture
def ctx(tmp_path):
    root = tmp_path / "proj"
    (root / "slides").mkdir(parents=True)
    (root / "decks").mkdir()
    slides = {
        "x7k-IT-Governance": "\\begin{standardframe}{IT}\\end{standardframe}\n",
        "x7k-IT-Governance-v1-0-0": "old\n",
        "y8m-EN-IT-Strategy": "tagged\n",                           # a language segment first: never at risk
        "z9n-ITs-Plan": "no\n",                                     # another word
        "a1b-AI-Tools": "no\n",
        "b2c-IT": "\\begin{standardframe}{x}\\end{standardframe}\n",       # nothing but the word
        "ddd-DE-Eins": "%% Translation of: x7k-IT-Governance\n",
    }
    for name, text in slides.items():
        suffix = "" if name.endswith("-v1-0-0") else "-current"
        (root / "slides" / f"{name}{suffix}.tex").write_text(text, encoding="utf-8")
    (root / "decks" / "course.tex").write_text(
        "\\begin{document}\n\\slide{x7k-IT-Governance}\n\\slideversion{x7k-IT-Governance}{1-0-0}\n"
        "\\slide{y8m-EN-IT-Strategy}\n\\end{document}\n", encoding="utf-8")
    return ProjectContext.at(root)


def test_the_slides_that_would_become_italian_are_listed(ctx):
    assert slide_rename.untagged_slugs_matching(ctx, "it") == ["b2c-IT", "x7k-IT-Governance"]
    assert slide_rename.untagged_slugs_matching(ctx, "IT") == ["b2c-IT", "x7k-IT-Governance"]
    assert slide_rename.untagged_slugs_matching(ctx, "ai") == ["a1b-AI-Tools"]
    assert slide_rename.untagged_slugs_matching(ctx, "fr") == []                # the usual case: nothing to show


def test_a_tagged_slide_is_never_listed_for_its_own_language(ctx):
    assert slide_rename.untagged_slugs_matching(ctx, "en") == []
    assert slide_rename.untagged_slugs_matching(ctx, "de") == []


def test_without_it_in_the_list_the_slug_is_no_language(ctx):
    assert slide_language.own_language("x7k-IT-Governance") is None


def test_tagging_renames_every_file_and_call_and_keeps_the_links(ctx):
    new = slide_rename.tag_untagged(ctx, "x7k-IT-Governance", "EN")
    assert new == "x7k-EN-IT-Governance"
    names = sorted(p.name for p in ctx.slides_dir.glob("x7k-*"))
    assert names == ["x7k-EN-IT-Governance-current.tex", "x7k-EN-IT-Governance-v1-0-0.tex"]
    deck = (ctx.decks_dir / "course.tex").read_text(encoding="utf-8")
    assert "\\slide{x7k-EN-IT-Governance}" in deck and "\\slideversion{x7k-EN-IT-Governance}{1-0-0}" in deck
    assert "x7k-IT-Governance" not in deck
    assert "%% Translation of: x7k-EN-IT-Governance" in (ctx.slides_dir / "ddd-DE-Eins-current.tex").read_text(encoding="utf-8")
    assert slide_language.own_language(new) == "EN"
    assert slide_rename.untagged_slugs_matching(ctx, "it") == ["b2c-IT"]


def test_a_slide_that_is_nothing_but_the_word_is_tagged_too(ctx):
    assert slide_rename.tag_untagged(ctx, "b2c-IT", "DE") == "b2c-DE-IT"
    assert (ctx.slides_dir / "b2c-DE-IT-current.tex").is_file()


def test_tagging_refuses_a_bad_language_and_an_existing_file(ctx):
    for bad in ("en", "ENG", "", "E1"):
        with pytest.raises(ValueError):
            slide_rename.tag_untagged(ctx, "x7k-IT-Governance", bad)
    (ctx.slides_dir / "x7k-EN-IT-Governance-current.tex").write_text("in the way\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        slide_rename.tag_untagged(ctx, "x7k-IT-Governance", "EN")
    assert (ctx.slides_dir / "x7k-IT-Governance-current.tex").is_file()
