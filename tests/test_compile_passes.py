# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The progress bar's pass count comes from the deck's last compile (v5.15.0)."""
from types import SimpleNamespace

from slidemage import compile_passes, compile_progress
from conftest import EXAMPLE_PROJECT


def _job(name="deck", version="instructor", chapter=None, presenter=False, biblatex=True):
    deck = SimpleNamespace(name=name, uses_biblatex=biblatex, text="", chapters=[],
                           preamble_end=None)
    return SimpleNamespace(deck=deck, version=version, chapter=chapter, presenter=presenter)


def test_remembered_per_deck_and_job_kind(tmp_path, monkeypatch):
    instructor = _job()
    chapter = _job(version="after-course", chapter=object())
    presenter = _job(presenter=True)

    assert compile_passes.expected(EXAMPLE_PROJECT, instructor) is None
    compile_passes.remember(EXAMPLE_PROJECT, instructor, 6)
    compile_passes.remember(EXAMPLE_PROJECT, chapter, 5)
    compile_passes.remember(EXAMPLE_PROJECT, presenter, 7)
    assert compile_passes.expected(EXAMPLE_PROJECT, instructor) == 6
    assert compile_passes.expected(EXAMPLE_PROJECT, chapter) == 5
    assert compile_passes.expected(EXAMPLE_PROJECT, presenter) == 7
    assert compile_passes.expected(EXAMPLE_PROJECT, _job(version="during-course")) is None
    assert compile_passes.expected(EXAMPLE_PROJECT, _job(name="other")) is None


def test_run_lines_are_latexmk_passes():
    assert compile_passes.RUN_RE.match("Run number 6 of rule 'lualatex'").group(1) == "6"
    assert compile_passes.RUN_RE.match("Run number 1 of rule 'biber x'") is None


def test_label_says_estimated_until_the_deck_was_compiled_once(tmp_path, monkeypatch):
    job = _job()
    job.jobname = "deck-instructor"
    assert compile_progress.spec_for_job(EXAMPLE_PROJECT, job).passes == compile_progress.PASSES_WITH_BIBLIOGRAPHY

    def label_after_first_pass():
        progress = compile_progress.BatchProgress()
        progress.reset({job.jobname: compile_progress.spec_for_job(EXAMPLE_PROJECT, job)})
        progress.feed(f"==== Compiling deck -> {job.jobname} ====")
        progress.feed("Run number 1 of rule 'lualatex'")
        return progress.text

    assert label_after_first_pass() == "pass 1/4 (estimated)"
    compile_passes.remember(EXAMPLE_PROJECT, job, 6)
    assert compile_progress.spec_for_job(EXAMPLE_PROJECT, job).passes == 6
    assert label_after_first_pass() == "pass 1/6"


def test_presenter_and_instructor_share_their_count(tmp_path, monkeypatch):
    compile_passes.remember(EXAMPLE_PROJECT, _job(presenter=True), 5)
    assert compile_passes.predict(EXAMPLE_PROJECT, _job()) == (5, True)                  # instructor: known
    assert compile_passes.predict(EXAMPLE_PROJECT, _job(version="during-course")) == (5, False)   # a guess
    assert compile_passes.predict(EXAMPLE_PROJECT, _job(version="after-course", chapter=object())) == (5, False)
    compile_passes.remember(EXAMPLE_PROJECT, _job(version="after-course"), 6)
    assert compile_passes.predict(EXAMPLE_PROJECT, _job(version="during-course")) == (6, False)   # nearest kin
    assert compile_passes.predict(EXAMPLE_PROJECT, _job(version="after-course", chapter=object())) == (6, False)
    assert compile_passes.predict(EXAMPLE_PROJECT, _job(name="other")) == (None, False)


def test_label_raises_the_count_instead_of_an_extra_pass(tmp_path, monkeypatch):
    job = _job()
    job.jobname = "deck-instructor"
    compile_passes.remember(EXAMPLE_PROJECT, job, 4)
    progress = compile_progress.BatchProgress()
    progress.reset({job.jobname: compile_progress.spec_for_job(EXAMPLE_PROJECT, job)})
    progress.feed(f"==== Compiling deck -> {job.jobname} ====")
    fractions = []
    for n in range(1, 6):
        progress.feed(f"Run number {n} of rule 'lualatex'")
        fractions.append(progress._current_fraction())
    assert progress.text == "pass 5/5"
    assert fractions == sorted(fractions)          # the bar never moves backwards


def test_duplicated_deck_inherits_the_original_counts(ctx, tmp_path, monkeypatch):
    from slidemage import deck_duplicate
    original = tmp_path / "talk.tex"
    original.write_text("x", encoding="utf-8")
    deck = SimpleNamespace(name="talk", path=original)
    compile_passes.remember(ctx, _job(name="talk"), 6)
    compile_passes.remember(ctx, _job(name="talk", presenter=True), 7)

    deck_duplicate.duplicate_deck(ctx, deck, "talk-copy")
    assert compile_passes.expected(ctx, _job(name="talk-copy")) == 6
    assert compile_passes.expected(ctx, _job(name="talk-copy", presenter=True)) == 7

    # an original that was never compiled: nothing to inherit, nothing written
    other = SimpleNamespace(name="never", path=tmp_path / "never.tex")
    other.path.write_text("y", encoding="utf-8")
    deck_duplicate.duplicate_deck(ctx, other, "never-copy")
    assert compile_passes.expected(ctx, _job(name="never-copy")) is None
