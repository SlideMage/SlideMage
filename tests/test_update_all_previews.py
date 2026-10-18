"""Exact deck request routing, partial outcomes, reuse and legacy project pruning."""
from __future__ import annotations

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


def test_the_project_wide_run_still_prunes(project, monkeypatch):
    compiles = Compiles(project, monkeypatch)
    stale = write_snapshot(project, "qqq-EN-Gone")
    lines: list[str] = []
    assert update_all_previews.run(project, lines.append)
    assert compiles.slides == [["abc-EN-Hello", "abd-EN-Second", "zzz-EN-Zed"]]
    assert not stale.exists() and any("removed 1 stale" in line for line in lines)


def test_deck_refresh_uses_exact_requests_and_keeps_partial_results(project):
    from test_preview_batch import Service
    service = Service(fail='during-course')
    events = []
    result = update_all_previews.rerender_deck(
        project, deck_named(project, 'test'), lambda _: None, service=service,
        progress=events.append, publish=lambda _: 'cached')
    assert len(result.details.results) == 6
    assert result.failed == ['abc-EN-Hello', 'abd-EN-Second']
    assert len(result.details.failed) == 2
    assert result.error == 'bad TeX'
    assert events[-1].index == events[-1].total == 6
    assert {r.target.frame_number for r in service.calls} == {1, 2}


def test_selected_scope_and_hidden_calls_do_not_compile(project):
    from test_preview_batch import Service
    from dataclasses import replace
    deck = deck_named(project, 'test')
    deck = replace(deck, text=deck.text.replace(r'\slide{abc-EN-Hello}', r'\omitslide{abc-EN-Hello}'))
    service = Service()
    result = update_all_previews.rerender_deck(
        project, deck, lambda _: None, service=service, scope='selected',
        selected_view='after-course', publish=lambda _: 'cached')
    assert result.details.count('hidden') == 1
    assert len(service.calls) == 1
    assert service.calls[0].view == 'after-course'
    assert result


def test_resolver_keeps_repeated_and_pinned_sources_separate(project):
    from slidemage import deck_preview_refresh
    from dataclasses import replace
    deck = deck_named(project, 'test')
    frozen = project.slides_dir / 'abc-EN-Hello-v1-0-0.tex'
    frozen.write_text('FROZEN')
    deck = replace(deck, text=deck.text.replace(r'\slide{abd-EN-Second}',
        r'\slideversion{abc-EN-Hello}{1-0-0}' + '\n' + r'\slide{abc-EN-Hello}'))
    requests = deck_preview_refresh.plan(project, deck)
    assert len(requests) == 9
    assert len({r.target.occurrence_key for r in requests}) == 3
    assert {r.target.frame_number for r in requests} == {1, 2, 3}
    pinned = [r for r in requests if r.target.version]
    assert len(pinned) == 3
    assert all(r.revision.text == 'FROZEN' and r.revision.path == frozen.resolve() for r in pinned)


def test_missing_source_does_not_abort_other_occurrences(project):
    from test_preview_batch import Service
    (project.slides_dir / 'abc-EN-Hello-current.tex').unlink()
    result = update_all_previews.rerender_deck(
        project, deck_named(project, 'test'), lambda _: None, service=Service(),
        publish=lambda _: 'cached')
    assert result.failed == ['abc-EN-Hello']
    assert result.refreshed == ['abd-EN-Second']


def test_unchanged_deck_refresh_reuses_groups_after_restart(tmp_path, monkeypatch):
    from test_preview_image_groups import fixture
    from test_preview_target import make_deck
    ctx, _target, _source, compiles, _group = fixture(tmp_path, monkeypatch)
    deck = make_deck('\\slide{abc-EN-One}\n')
    first = update_all_previews.rerender_deck(ctx, deck, lambda _: None,
                                            publish=lambda _: 'cached')
    assert first and len(compiles) == 1
    second = update_all_previews.rerender_deck(ctx, deck, lambda _: None,
                                             publish=lambda _: 'cached')
    assert second and len(compiles) == 1
    assert second.details.count('cached') == 3


def test_deck_resolver_uses_translation_and_reveal_selection(project):
    from dataclasses import replace
    from slidemage import deck_preview_refresh
    deck = deck_named(project, 'test')
    (project.slides_dir / 'abc-EN-Hello-current.tex').write_text(
        '%% Language: EN\n%% DE translation: bbb-DE-Hallo\nEnglish')
    (project.slides_dir / 'bbb-DE-Hallo-current.tex').write_text(
        '%% Language: DE\n%% Translation of: abc-EN-Hello\nGerman')
    deck = replace(deck, text=deck.text.replace(r'\slide{abc-EN-Hello}',
                                               r'\slidestep{abc-EN-Hello}[instructor]{2,4}'))
    specs = deck_preview_refresh.plan(project, deck, language='DE')
    translated = [r for r in specs if r.target.id_slug == 'bbb-DE-Hallo']
    assert len(translated) == 3
    assert all(r.target.steps == '2,4' and r.revision.text.endswith('German') for r in translated)
