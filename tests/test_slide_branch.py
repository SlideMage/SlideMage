# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Update version → New slide: the edits become a slide of their own, the old slide goes back to its version, and
the decks asked for load the new slide (slide_branch.py, v8.58.0)."""
from __future__ import annotations

import pytest

from slidemage import deck_editor, slide_branch, slide_versioning
from slidemage.deck_scan import scan_decks
from slidemage.fileio import read_text_exact
from slidemage.slide_source import read_slide_source

OLD = "abc-EN-Demo"
HEADER = "%% Included in decks: talk, course\n%%\n\n"


@pytest.fixture
def project(ctx, tmp_path):
    slides, decks = tmp_path / "slides", tmp_path / "decks"
    (slides / ".backups").mkdir(parents=True)
    decks.mkdir()
    (tmp_path / "slide_ids.csv").write_text('"id"\r\n"abc"\r\n', encoding="utf-8", newline="")
    (slides / f"{OLD}-current.tex").write_text(HEADER + "\\setSlideVersion{1-0-0+}\nedited text\n", encoding="utf-8")
    (slides / f"{OLD}-v1-0-0.tex").write_text("%% Included in decks: talk\n%%\n\n\\setSlideVersion{1-0-0}\nold text\n",
                                              encoding="utf-8")
    deck = "\\documentclass{{beamer}}\n\\begin{{document}}\n{}\\end{{document}}\n"
    (decks / "talk.tex").write_text(deck.format(
        f"\\slide{{{OLD}}}\n\\slidestep{{{OLD}}}[instructor]{{2}}\n\\slideversion{{{OLD}}}{{1-0-0}}\n"),
        encoding="utf-8", newline="")
    (decks / "course.tex").write_text(deck.format(f"\\conditionalslide[after-course]{{{OLD}}}\n"),
                                      encoding="utf-8", newline="")
    return ctx


def deck_text(ctx, name):
    return read_text_exact(ctx.decks_dir / f"{name}.tex")


def test_the_edits_become_a_new_slide_and_the_old_one_is_its_version_again(project):
    result = slide_branch.save_as_new_slide(project, OLD, "Demo", ["talk"])
    new = result.created.id_slug
    assert new != OLD and new.endswith("-EN-Demo")
    assert "edited text" in result.created.path.read_text(encoding="utf-8")
    assert "\\setSlideVersion" not in result.created.path.read_text(encoding="utf-8")      # its own history
    old_text = read_slide_source(project.slides_dir / f"{OLD}-current.tex")[0]
    assert "old text" in old_text and "edited text" not in old_text
    assert slide_versioning.parse_marker(old_text) == ((1, 0, 0), False)                     # no "+" any more
    assert old_text.startswith(HEADER)                                                       # its own header kept
    assert result.reverted_to == (1, 0, 0)
    assert result.created.id_slug.split("-")[0] in read_text_exact(project.slide_ids_csv)


def test_only_the_decks_asked_for_load_the_new_slide_and_pinned_calls_stay(project):
    talk_before = deck_text(project, "talk")
    result = slide_branch.save_as_new_slide(project, OLD, "Demo-revised", ["talk"])
    new = result.created.id_slug
    talk = deck_text(project, "talk")
    assert f"\\slide{{{new}}}" in talk and f"\\slidestep{{{new}}}[instructor]{{2}}" in talk
    assert f"\\slideversion{{{OLD}}}{{1-0-0}}" in talk                       # a pinned version stays the old slide's
    assert f"\\conditionalslide[after-course]{{{OLD}}}" in deck_text(project, "course")
    assert result.decks == {"talk": 2} and result.previous_texts == {"talk": talk_before}


def test_other_decks_can_switch_too(project):
    result = slide_branch.save_as_new_slide(project, OLD, "Demo", ["talk", "course"])
    assert f"\\conditionalslide[after-course]{{{result.created.id_slug}}}" in deck_text(project, "course")


def test_a_slide_without_edits_since_its_version_cannot_branch(project):
    current = project.slides_dir / f"{OLD}-current.tex"
    current.write_text(HEADER + "\\setSlideVersion{1-0-0}\nold text\n", encoding="utf-8")
    assert slide_branch.can_branch(project, OLD)
    with pytest.raises(ValueError):
        slide_branch.save_as_new_slide(project, OLD, "Demo", ["talk"])
    assert len(list(project.slides_dir.glob("*-current.tex"))) == 1             # nothing was created


def test_an_unusable_name_is_refused_before_anything_changes(project):
    with pytest.raises(ValueError, match="not a usable name"):
        slide_branch.save_as_new_slide(project, OLD, "two words", ["talk"])
    assert "edited text" in (project.slides_dir / f"{OLD}-current.tex").read_text(encoding="utf-8")


def test_a_changed_deck_is_not_overwritten(project):
    talk = scan_decks(project)[[d.name for d in scan_decks(project)].index("talk")]
    calls = [c for c in deck_editor.parse_slide_calls(talk) if c.macro == "slide"]
    (project.decks_dir / "talk.tex").write_text(talk.text + "% edited elsewhere\n", encoding="utf-8", newline="")
    with pytest.raises(deck_editor.StaleFileError):
        deck_editor.retarget_slide_calls(talk.path, talk.text, calls, "new-EN-X")
