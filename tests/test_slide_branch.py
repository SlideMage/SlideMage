# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Update version → New slide: the edits become a slide of their own, the old slide goes back to its version, and
the decks asked for load the new slide (slide_branch.py, v8.58.0)."""
from __future__ import annotations

import pytest

from slidemage import slide_branch, slide_versioning
from slidemage.fileio import read_text_exact, write_texts
from slidemage.slide_source import read_slide_source

OLD = "abc-EN-Demo"
HEADER = "%% Included in decks: talk, course\n%%\n\n"


@pytest.fixture
def project(ctx, tmp_path):
    slides, decks = tmp_path / "slides", tmp_path / "decks"
    (slides / ".backups").mkdir(parents=True)
    decks.mkdir()
    (tmp_path / "slide_ids.csv").write_text('"id"\r\n"abc"\r\n', encoding="utf-8", newline="")
    (slides / f"{OLD}-current.tex").write_text(HEADER.rstrip() + "\n%% DE translation: def-DE-Demo\n%%\n\n\\setSlideVersion{1-0-0+}\nedited text\n", encoding="utf-8")
    (slides / f"{OLD}-v1-0-0.tex").write_text("%% Included in decks: talk\n%%\n%% DE translation: old-DE-Demo\n%%\n\n\\setSlideVersion{1-0-0}\nold text\n",
                                              encoding="utf-8")
    deck = "\\documentclass{{beamer}}\n\\begin{{document}}\n{}\\end{{document}}\n"
    (decks / "talk.tex").write_text(deck.format(
        f"\\slide{{{OLD}}}\n\\slidestep  {{{OLD}}} [instructor, during-course] {{ 2 }}\n\\slideversion{{{OLD}}}{{1-0-0}}\n"),
        encoding="utf-8", newline="")
    (decks / "course.tex").write_text(deck.format(f"\\conditionalslide[after-course]{{{OLD}}}\n"),
                                      encoding="utf-8", newline="")
    return ctx


def deck_text(ctx, name):
    return read_text_exact(ctx.decks_dir / f"{name}.tex")


def branch(ctx, slug, decks):
    current = ctx.slides_dir / f"{OLD}-current.tex"
    cap = slide_versioning.capture(ctx, "new_slide", [current])
    proposal = slide_branch.branch(cap, current, ctx.slide_ids_csv, slug, [ctx.decks_dir / f"{name}.tex" for name in decks])
    write_texts(proposal.edits)
    return proposal


def test_branch_restores_the_old_version_and_switches_only_selected_unpinned_calls(project):
    talk_before = deck_text(project, "talk")
    result = branch(project, "Demo-revised", ["talk"])
    new = result.created.id_slug
    talk = deck_text(project, "talk")
    assert f"\\slide{{{new}}}" in talk and f"\\slidestep  {{{new}}} [instructor, during-course] {{ 2 }}" in talk
    assert f"\\slideversion{{{OLD}}}{{1-0-0}}" in talk                       # a pinned version stays the old slide's
    assert f"\\conditionalslide[after-course]{{{OLD}}}" in deck_text(project, "course")
    assert result.edits[project.decks_dir / "talk.tex"] == (talk_before, talk)

    assert new != OLD and new.endswith("-EN-Demo-revised")
    new_text = result.created.path.read_text(encoding="utf-8")
    assert "edited text" in new_text and "\\setSlideVersion" not in new_text
    old_text = read_slide_source(project.slides_dir / f"{OLD}-current.tex")[0]
    assert "old text" in old_text and "edited text" not in old_text
    assert slide_versioning.parse_marker(old_text) == ((1, 0, 0), False)                     # no "+" any more
    assert old_text.startswith(HEADER.rstrip()) and "%% DE translation: def-DE-Demo" in old_text
    assert "old-DE-Demo" not in old_text
    assert new.split("-")[0] in read_text_exact(project.slide_ids_csv)


def test_other_decks_can_switch_too(project):
    result = branch(project, "Demo", ["talk", "course"])
    assert f"\\conditionalslide[after-course]{{{result.created.id_slug}}}" in deck_text(project, "course")


def test_a_slide_without_edits_since_its_version_cannot_branch(project):
    current = project.slides_dir / f"{OLD}-current.tex"
    current.write_text(HEADER + "\\setSlideVersion{1-0-0}\nold text\n", encoding="utf-8")
    with pytest.raises(ValueError):
        branch(project, "Demo", ["talk"])
    assert len(list(project.slides_dir.glob("*-current.tex"))) == 1             # nothing was created


def test_an_unusable_name_is_refused_before_anything_changes(project):
    with pytest.raises(ValueError, match="not a usable name"):
        branch(project, "two words", ["talk"])
    assert "edited text" in (project.slides_dir / f"{OLD}-current.tex").read_text(encoding="utf-8")
