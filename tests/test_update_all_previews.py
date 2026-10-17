"""Update previews narrowed to one deck (update_all_previews.rerender_deck): only that deck's slides
are compiled, other decks' cached previews survive (nothing is pruned), and the result says which
slides' snapshots were written. The compile is replaced by a script that writes the snapshots a real
run's background capture writes."""
from __future__ import annotations

import os
import threading
import time

import pytest

from slidemage import slide_snapshot, update_all_previews
from slidemage.deck_scan import scan_decks
from slidemage.project import ProjectContext

OTHER_DECK = "\\documentclass{beamer}\n\\begin{document}\n\\slide{abd-EN-Second}\n\\slide{zzz-EN-Zed}\n\\end{document}\n"
TEMPLATE = "uni-graz"      # what a deck without an \input of a template detects


@pytest.fixture
def project(root):
    (root / "decks" / "other.tex").write_text(OTHER_DECK, encoding="utf-8")
    return ProjectContext.at(root)


def deck_named(project, name):
    return next(d for d in scan_decks(project) if d.name == name)


def snapshot(project, bare_id, id_slug):
    return slide_snapshot.snapshot_path(project, bare_id, TEMPLATE, id_slug=id_slug)


def write_snapshot(project, id_slug):
    path = snapshot(project, id_slug.split("-")[0], id_slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"png")
    return path


class Compiles:
    """A run_job that records the slides it was asked to typeset and writes their snapshots in a
    background thread, like the real run's PDF relocation, calling on_relocated at the end."""

    def __init__(self, project, monkeypatch, skip=()):
        self.project, self.skip, self.slides = project, set(skip), []
        monkeypatch.setattr(update_all_previews, "run_job", self)

    def __call__(self, ctx, job, log, cancel=None, dest_override=None, on_relocated=None):
        slugs = [line[len("\\slide{"):-1] for line in job.deck.text.splitlines() if line.startswith("\\slide{")]
        self.slides.append(slugs)
        log(f"==== Compiling {job.deck.name} -> {job.jobname} ====")

        def relocate():
            time.sleep(0.05)
            for slug in slugs:
                if slug not in self.skip:
                    write_snapshot(self.project, slug)
            on_relocated(True, job.deck.path)

        threading.Thread(target=relocate, daemon=True).start()
        return True


def test_the_needed_set_narrows_to_one_decks_slides(project):
    test, other = deck_named(project, "test"), deck_named(project, "other")
    assert update_all_previews.needed_slides_by_template(project, test) == {TEMPLATE: {"abc-EN-Hello", "abd-EN-Second"}}
    assert update_all_previews.needed_slides_by_template(project, other) == {TEMPLATE: {"abd-EN-Second", "zzz-EN-Zed"}}
    assert update_all_previews.needed_slides_by_template(project) == {
        TEMPLATE: {"abc-EN-Hello", "abd-EN-Second", "zzz-EN-Zed"}}


def test_a_deck_rerender_compiles_only_its_slides_and_prunes_nothing(project, monkeypatch):
    compiles = Compiles(project, monkeypatch)
    other_slide = write_snapshot(project, "zzz-EN-Zed")           # only the other deck needs it
    stale = write_snapshot(project, "qqq-EN-Gone")                # no deck needs it: the project-wide run deletes it
    lines: list[str] = []
    result = update_all_previews.rerender_deck(project, deck_named(project, "test"), lines.append)
    assert compiles.slides == [["abc-EN-Hello", "abd-EN-Second"]]
    assert other_slide.read_bytes() == b"png" and stale.is_file()
    assert result and result.refreshed == ["abc-EN-Hello", "abd-EN-Second"] and result.failed == []
    assert snapshot(project, "abc", "abc-EN-Hello").is_file()      # written before the call returned
    assert any("Rerender previews of test: 2 slide(s)" in line for line in lines)
    assert not any("removed" in line for line in lines)


def test_the_project_wide_run_still_prunes(project, monkeypatch):
    compiles = Compiles(project, monkeypatch)
    stale = write_snapshot(project, "qqq-EN-Gone")
    lines: list[str] = []
    assert update_all_previews.run(project, lines.append)
    assert compiles.slides == [["abc-EN-Hello", "abd-EN-Second", "zzz-EN-Zed"]]
    assert not stale.exists() and any("removed 1 stale" in line for line in lines)


def test_a_slide_whose_snapshot_was_not_written_is_reported_failed_with_the_first_error(project, monkeypatch):
    Compiles(project, monkeypatch, skip={"abd-EN-Second"})
    old = write_snapshot(project, "abd-EN-Second")                 # from an earlier run: not fresh
    old_time = time.time() - 3600
    os.utime(old, (old_time, old_time))

    result = update_all_previews.rerender_deck(project, deck_named(project, "test"), lambda _line: None)
    assert not result and result.refreshed == ["abc-EN-Hello"] and result.failed == ["abd-EN-Second"]


def test_the_first_tex_error_line_is_kept(project, monkeypatch):
    def failing(ctx, job, log, cancel=None, dest_override=None, on_relocated=None):
        for line in ("! Undefined control sequence.", "*** FAIL: x -- see .build/x.log ***", "! Second error."):
            log(line)
        return False

    monkeypatch.setattr(update_all_previews, "run_job", failing)
    result = update_all_previews.rerender_deck(project, deck_named(project, "test"), lambda _line: None)
    assert result.error == "! Undefined control sequence." and result.failed == ["abc-EN-Hello", "abd-EN-Second"]
