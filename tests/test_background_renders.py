"""Idle-time rendering: what is outstanding, in which order, what a render stores (a fake TeX; MuPDF writes the PDFs)."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path

import pymupdf
import pytest

from conftest import EXAMPLE
from slidemage import background_renders, deck_scan, render_store
from slidemage.background_renders import BackgroundRenderer
from slidemage.compiler import CancelToken
from slidemage.deck_editor import VIEWS
from slidemage.idle_gate import IdleGate
from slidemage.preview_raster_client import RasterClient
from slidemage.project import ProjectContext
from slidemage.render_key import Freshness
from slidemage.render_scheduler import P_IDLE


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    shutil.copytree(EXAMPLE, root)
    old = time.time() - 3600
    for path in root.rglob("*"):
        if path.is_file():
            os.utime(path, (old, old))          # nothing is "just written"
    return ProjectContext.at(root)


@pytest.fixture
def store(project, tmp_path):
    s = render_store.RenderStore(project, tmp_path / "local")
    yield s
    s.close()


class FakeTeX:
    """Stands for slide_preview.render_slide_to_pdf: a PDF of `pages` pages and the recorded inputs, in a folder
    like the real one's; `fail` maps a slide id-slug to the error to raise."""

    def __init__(self, project, pages=3):
        self.project, self.pages, self.calls, self.fail = project, pages, [], {}

    def __call__(self, unit, cancel):
        self.calls.append((unit.id_slug, unit.view, unit.language))
        if unit.id_slug in self.fail:
            raise RuntimeError(self.fail[unit.id_slug])
        folder = Path(tempfile.mkdtemp(prefix="slidemage_preview_"))
        pdf = folder / (unit.id_slug + ".pdf")
        doc = pymupdf.open()
        for number in range(self.pages):
            doc.new_page(width=453, height=255).insert_text((20, 40), f"{unit.id_slug} step {number + 1}")
        doc.save(pdf)
        doc.close()
        pdf.with_suffix(".inputs.json").write_text(json.dumps([str(unit.source_path)]), encoding="utf-8")
        return pdf


@pytest.fixture
def raster():
    client = RasterClient()
    yield client
    client.close()


def make(project, store, raster, tex=None, **kwargs):
    decks = deck_scan.scan_decks(project)
    open_deck = kwargs.pop("open_deck", None)
    gate = IdleGate(enabled=lambda: True, only_on_mains=lambda: False, idle_after=30, startup_delay=0,
                    clock=lambda: 1000.0, on_battery=lambda: False, cpu_load=lambda: 0.0, is_busy=lambda: [])
    gate.last_input = 0.0
    renderer = BackgroundRenderer(project, store, gate=gate, decks=lambda: decks, open_deck=lambda: open_deck,
                                  engine_fp=lambda: "LuaHBTeX 1.22|Windows", renderer=tex or FakeTeX(project), raster=raster, **kwargs)
    renderer.test_decks = decks
    return renderer


def drain(renderer):
    while renderer.scheduler.run_next():
        pass


def deck_named(renderer, name):
    return next(d for d in renderer.test_decks if d.name == name)


def test_units_of_a_deck_follow_deck_order_and_start_at_the_last_slide(project, store, raster):
    r = make(project, store, raster)
    deck = deck_named(r, "slidemage-manual")
    units = background_renders.deck_units(project, deck, "instructor", "EN")
    assert len(units) > 20 and units[0].frame_number == 1 and all(u.view == "instructor" for u in units)
    middle = units[10].id_slug
    bare = middle.split("-")[0]
    wrapped = background_renders.deck_units(project, deck, "instructor", "EN", bare)
    assert wrapped[0].id_slug == middle and [u.id_slug for u in wrapped] == [u.id_slug for u in units[10:] + units[:10]]


def test_a_view_that_does_not_typeset_a_call_has_no_unit(project, store, raster):
    r = make(project, store, raster)
    deck = deck_named(r, "slidemage-manual")
    counts = {view: len(background_renders.deck_units(project, deck, view, "EN")) for view in VIEWS}
    assert counts["instructor"] >= counts["during-course"] >= 1 and counts["instructor"] >= counts["after-course"] >= 1


def test_decks_are_ordered_open_deck_first_then_by_recency_and_archived_or_switched_off_are_left_out(project, store, raster):
    r = make(project, store, raster)
    names = [d.name for d in r.ordered_decks()]
    assert set(names) >= {"slidemage-manual", "slidemage-manual-copy"}
    store.touch_deck("slidemage-manual-copy", opened=True)
    assert r.ordered_decks()[0].name == "slidemage-manual-copy"
    r2 = make(project, store, raster, open_deck=deck_named(r, "slidemage-manual"))
    assert r2.ordered_decks()[0].name == "slidemage-manual"
    background_renders.app_settings.set(project, background_renders.DECKS_OFF_KEY, ["slidemage-manual"])
    assert "slidemage-manual" not in [d.name for d in r2.ordered_decks()]
    deck_named(r, "slidemage-manual-copy").archived = True
    assert "slidemage-manual-copy" not in [d.name for d in r.ordered_decks()]


def test_the_plan_is_instructor_first_then_the_other_versions_deck_by_deck(project, store, raster):
    r = make(project, store, raster)
    store.touch_deck("slidemage-manual", opened=True)
    plan = r.scan()
    views = [unit.view for _, unit in plan if unit.deck == "slidemage-manual"]
    assert views[0] == "instructor"
    order = [v for i, v in enumerate(views) if i == 0 or v != views[i - 1]]
    assert order == [v for v in VIEWS if v in order]                                  # instructor, during, after
    decks_seen = [unit.deck for _, unit in plan]
    assert decks_seen.index("slidemage-manual") < decks_seen.index("slidemage-manual-copy")
    keys = [k for k, _ in plan]
    assert keys == sorted(keys)


def test_rendering_a_unit_stores_every_step_and_then_it_is_fresh(project, store, raster):
    tex = FakeTeX(project, pages=3)
    r = make(project, store, raster, tex=tex)
    unit = background_renders.deck_units(project, deck_named(r, "slidemage-manual"), "instructor", "EN")[0]
    name = r.render_unit(unit, background_renders.ORIGIN_BACKGROUND, CancelToken())
    assert name.endswith(".bg")
    found = r.resolver.lookup(unit)
    assert found.state is Freshness.FRESH and found.final and found.record["pages"] == 3
    assert store.page(found.record, 3).startswith(b"\x89PNG") and store.page(found.record, 4) is None
    assert not list(Path(tempfile.gettempdir()).glob("slidemage_preview_*"))          # the temp folder is gone
    r.render_unit(unit, background_renders.ORIGIN_BACKGROUND, CancelToken())
    assert len(tex.calls) == 1                                                        # nothing to do the second time


def test_editing_the_slide_or_what_it_reads_makes_it_outstanding_again(project, store, raster):
    tex = FakeTeX(project)
    r = make(project, store, raster, tex=tex)
    unit = background_renders.deck_units(project, deck_named(r, "slidemage-manual"), "instructor", "EN")[2]
    r.render_unit(unit, background_renders.ORIGIN_BACKGROUND, CancelToken())
    assert r.resolver.lookup(unit).final
    unit.source_path.write_text(unit.source_path.read_text(encoding="utf-8") + "\n% edited\n", encoding="utf-8")
    time.sleep(0.01)
    old = time.time() - 60
    os.utime(unit.source_path, (old, old))
    again = r.resolver.lookup(unit)
    assert again.state is Freshness.MISSING or again.state is Freshness.STALE
    assert not again.final


def test_a_render_by_the_slider_is_provisional_and_the_sweep_replaces_it(project, store, raster):
    tex = FakeTeX(project)
    r = make(project, store, raster, tex=tex)
    unit = background_renders.deck_units(project, deck_named(r, "slidemage-manual"), "instructor", "EN")[1]
    cancel = CancelToken
    r.render_unit(unit, background_renders.ORIGIN_REVEAL, cancel())
    first = r.resolver.lookup(unit)
    assert first.state is Freshness.FRESH and not first.final and first.record["origin"] == "reveal"
    r.render_unit(unit, background_renders.ORIGIN_BACKGROUND, cancel())
    assert r.resolver.lookup(unit).final and len(tex.calls) == 2
    r.render_unit(unit, background_renders.ORIGIN_REVEAL, cancel())                 # the slider on an unchanged slide: no render
    assert len(tex.calls) == 2 and store.count() == 1


def test_a_page_number_that_moved_is_refreshed_last(project, store, raster):
    tex = FakeTeX(project)
    r = make(project, store, raster, tex=tex)
    deck = deck_named(r, "slidemage-manual")
    units = background_renders.deck_units(project, deck, "instructor", "EN")
    r.render_unit(units[3], background_renders.ORIGIN_BACKGROUND, CancelToken())
    from dataclasses import replace
    moved = replace(units[3], frame_number=units[3].frame_number + 1)
    assert r.resolver.lookup(moved).state is Freshness.FRESH_NUMBERING_DIFFERS
    r.render_unit(moved, background_renders.ORIGIN_BACKGROUND, CancelToken())
    assert r.resolver.lookup(moved).state is Freshness.FRESH and len(tex.calls) == 2
    assert store.count() == 1


def test_a_failing_slide_is_remembered_and_not_planned_again_until_it_changes(project, store, raster):
    tex = FakeTeX(project)
    r = make(project, store, raster, tex=tex)
    deck = deck_named(r, "slidemage-manual")
    unit = background_renders.deck_units(project, deck, "instructor", "EN")[0]
    tex.fail[unit.id_slug] = "Render failed for x:\n! Undefined control sequence."
    with pytest.raises(RuntimeError):
        r.render_unit(unit, background_renders.ORIGIN_BACKGROUND, CancelToken())
    assert r.resolver.lookup(unit).state is Freshness.FAILED
    plan = r.scan()
    assert unit.label not in [u.label for _, u in plan]
    assert r.progress.deck("slidemage-manual").failed >= 1
    assert r.render_unit(unit, background_renders.ORIGIN_BACKGROUND, CancelToken()) is None   # no loop
    assert len(tex.calls) == 1
    unit.source_path.write_text(unit.source_path.read_text(encoding="utf-8") + "\n% fixed\n", encoding="utf-8")
    old = time.time() - 60
    os.utime(unit.source_path, (old, old))
    assert r.resolver.lookup(unit).state is not Freshness.FAILED


def test_the_planner_feeds_the_scheduler_and_the_progress_goes_down(project, store, raster):
    tex = FakeTeX(project, pages=1)
    r = make(project, store, raster, tex=tex)
    deck = deck_named(r, "slidemage-manual")
    store.touch_deck(deck.name, opened=True)
    r.tick()
    first_left = r.progress.left
    assert first_left > 0 and r.scheduler.pending(P_IDLE) == background_renders.QUEUE_AHEAD
    assert r.progress.paused_because is None
    for _ in range(5):
        r.scheduler.run_next()
    assert r.progress.deck(deck.name).fresh >= 5 and r.progress.left <= first_left - 5
    assert [c[1] for c in tex.calls][:5] == ["instructor"] * 5


def test_nothing_runs_while_the_gate_says_no(project, store, raster):
    tex = FakeTeX(project)
    r = make(project, store, raster, tex=tex)
    r.gate.last_input = 999.0                                # the user just did something
    r.tick()
    assert r.scheduler.pending() == 0 and r.progress.paused_because == "you are working"
    r.gate.last_input = 0.0
    r.tick()
    assert r.scheduler.pending(P_IDLE) > 0 and tex.calls == []
    drain_one = r.scheduler.run_next()
    assert drain_one and len(tex.calls) == 1


def test_archiving_a_deck_removes_its_renders_and_stops_planning_it(project, store, raster):
    tex = FakeTeX(project, pages=1)
    r = make(project, store, raster, tex=tex)
    deck = deck_named(r, "slidemage-manual-copy")
    unit = background_renders.deck_units(project, deck, "instructor", "EN")[0]
    r.render_unit(unit, background_renders.ORIGIN_BACKGROUND, CancelToken())
    assert store.count() == 1
    deck.archived = True
    r.deck_archived(deck)
    assert store.count() == 0 and deck.name not in [d.name for d in r.ordered_decks()]


def test_the_slider_goes_before_the_sweep(project, store, raster):
    tex = FakeTeX(project, pages=1)
    r = make(project, store, raster, tex=tex)
    deck = deck_named(r, "slidemage-manual")
    units = background_renders.deck_units(project, deck, "instructor", "EN")
    r.tick()
    r.submit_neighbours(units[7])
    assert r.scheduler.queued_keys()[0] == units[7].label
    r.scheduler.run_next()
    assert tex.calls[0][0] == units[7].id_slug and r.resolver.lookup(units[7]).record["origin"] == "reveal"


def test_a_slide_with_no_page_in_the_view_is_a_failure_not_an_empty_render(project, store, raster):
    r = make(project, store, raster, tex=FakeTeX(project, pages=1))
    r._rasterise = lambda pdf, cancel: []
    unit = background_renders.deck_units(project, deck_named(r, "slidemage-manual"), "instructor", "EN")[0]
    with pytest.raises(RuntimeError):
        r.render_unit(unit, background_renders.ORIGIN_BACKGROUND, CancelToken())
    assert r.resolver.lookup(unit).state is Freshness.FAILED


def test_a_deck_whose_course_meets_soon_comes_after_the_open_deck_and_before_the_rest(project, store, raster):
    r = make(project, store, raster, soon=lambda deck: deck.name == "slidemage-manual-copy")
    store.touch_deck("slidemage-manual", opened=True)
    assert [d.name for d in r.ordered_decks()][:2] == ["slidemage-manual-copy", "slidemage-manual"]


def test_the_course_schedule_is_only_read_from_the_copy_kept_when_it_was_fetched():
    from datetime import date

    from slidemage import course_schedule
    url = "https://online.uni-graz.at/kfu_online/ee/ui/ca2/app/desktop/#/slc.tm.cp/student/courses/12345?pStpSpNr=12345"
    url = "https://online.uni-graz.at/kfu_online/pl/ui/$ctx/wbLv.wbShowLVDetail?pStpSpNr=12345"
    assert course_schedule.session_soon(url) is False                             # nothing fetched yet: no boost, no network
    sessions = tuple(course_schedule.CourseSession(d, "10:00", "11:30", "", "", "") for d in ("20.10.2026", "01.12.2026"))
    course_schedule.remember_schedule(url, course_schedule.CourseSchedule((course_schedule.CourseGroup("G", sessions),)))
    assert course_schedule.session_soon(url, today=date(2026, 10, 18)) is True        # in two days
    assert course_schedule.session_soon(url, today=date(2026, 10, 22)) is False       # the next is six weeks away
    assert course_schedule.session_soon(None) is False and course_schedule.session_soon("not a url") is False


def test_a_scan_counts_each_deck_by_version_and_lists_the_decks_left_out(project, store, raster):
    tex = FakeTeX(project, pages=1)
    r = make(project, store, raster, tex=tex)
    deck = deck_named(r, "slidemage-manual")
    units = background_renders.deck_units(project, deck, "instructor", "EN")
    for unit in units[:5]:
        r.render_unit(unit, background_renders.ORIGIN_BACKGROUND, CancelToken())
    background_renders.app_settings.set(project, background_renders.DECKS_OFF_KEY, ["slidemage-manual-copy"])
    r.scan()
    progress = r.progress
    mine = progress.deck("slidemage-manual")
    assert mine.views["instructor"][:2] == [len(units), 5] and set(mine.views) == set(VIEWS)
    assert mine.total == sum(v[0] for v in mine.views.values()) and mine.fresh == 5
    assert progress.deck("slidemage-manual-copy").off and progress.decks_counted == 1
    assert progress.total == mine.total and progress.fresh == 5 and 0 < progress.percent < 10
    assert progress.decks_up_to_date == 0 and not mine.up_to_date
    assert progress.scanned_at > 0


@pytest.mark.skipif(shutil.which("latexmk") is None or shutil.which("lualatex") is None, reason="needs a TeX installation")
def test_a_real_background_render_creates_nothing_in_the_project_and_matches_the_foreground_render(project, store, tmp_path):
    """The wrapper, the build caches and the format are in the store's work folder; TeX still runs in decks/, so the
    pages are what the foreground Preview renders."""
    from slidemage import slide_preview

    os.environ.setdefault("SLIDEMASTER_LATEX", str(Path(__file__).resolve().parent.parent / "latex"))
    decks = deck_scan.scan_decks(project)
    gate = IdleGate(startup_delay=0, idle_after=0, only_on_mains=lambda: False, cpu_load=lambda: 0.0, is_busy=lambda: [])
    renderer = BackgroundRenderer(project, store, gate=gate, decks=lambda: decks)
    deck = next(d for d in decks if d.name == "slidemage-manual")
    units = background_renders.deck_units(project, deck, "instructor", "EN")
    unit = next(u for u in units if "Reveal" in u.id_slug or "Title" in u.id_slug)

    def listing():
        return {p.relative_to(project.root).as_posix() for p in project.root.rglob("*")}

    before = listing()
    name = renderer.render_unit(unit, background_renders.ORIGIN_BACKGROUND, CancelToken())
    assert name is not None and listing() == before                                  # not one file in the project
    assert (store.work_dir / "decks").is_dir() and list((store.work_dir / "decks").glob("_slidemage_preview-*.tex"))
    assert [d.name for d in deck_scan.scan_decks(project)] == [d.name for d in decks]
    found = renderer.resolver.lookup(unit)
    assert found.final and found.record["pages"] >= 1

    foreground = slide_preview.render_slide_to_pdf(
        project, unit.macro, unit.id_slug, unit.version, unit.render_conditions, deck_version=unit.view,
        deck_language=unit.language.lower(), preamble_text=unit.preamble_text, frame_number=unit.frame_number,
        log=lambda line: None, capture_snapshot=False, all_steps=True)
    with pymupdf.open(foreground) as theirs, pymupdf.open(store.pdf_path(found.record)) as ours:
        assert len(ours) == len(theirs) == found.record["pages"]
        assert [p.get_text() for p in ours] == [p.get_text() for p in theirs]
