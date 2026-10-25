# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
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


def make(project, store, raster, tex=None, batch=1, **kwargs):
    decks = deck_scan.scan_decks(project)
    open_deck = kwargs.pop("open_deck", None)
    background_renders.app_settings.set(project, background_renders.BATCH_SIZE_KEY, batch)
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


def test_a_full_store_renders_only_the_protected_decks_and_says_why_the_rest_waits(project, store, raster):
    tex = FakeTeX(project, pages=1)
    r = make(project, store, raster, tex=tex)
    manual, copy = deck_named(r, "slidemage-manual"), deck_named(r, "slidemage-manual-copy")
    unit = background_renders.deck_units(project, copy, "instructor", "EN")[0]
    r.render_unit(unit, background_renders.ORIGIN_BACKGROUND, CancelToken())
    background_renders.app_settings.set(project, background_renders.LIMIT_GB_KEY, store.total_bytes() / 1024 ** 3)

    def queued_decks():
        return {job.group for job in r.scheduler._queue.values()}

    r.tick()                                     # no deck opened yet: rendering any would push another one out
    assert queued_decks() == set() and r.progress.left > 0
    assert r.progress.paused_because == background_renders.STORE_FULL and not r.sweeping()
    store.touch_deck(manual.name, opened=True)
    r.replan()
    r.tick()                                     # the deck in use may push out the others' renders
    assert queued_decks() == {manual.name} and r.progress.paused_because is None
    r.scheduler.cancel_priority(P_IDLE)
    background_renders.app_settings.set(project, background_renders.LIMIT_GB_KEY, 1.0)
    r.replan()
    r.tick()                                     # room again: the sweep goes on with every deck, nothing was pushed out
    assert r.progress.paused_because is None and store.count() == 1
    r.scheduler.cancel_priority(P_IDLE)
    with r._plan_lock:
        r._plan = [item for item in r._plan if item[1].deck == copy.name]
    r._top_up()
    assert queued_decks() == {copy.name}


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

    os.environ.setdefault("SLIDEMAGE_LATEX", str(Path(__file__).resolve().parent.parent / "latex"))
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


# -- the slides of a deck compile ------------------------------------------------------------


def _compiled_pdf(tmp_path, units):
    """A deck PDF as a compile makes it: every slide's pages (two steps each) with their slide id in the footer."""
    pdf = tmp_path / "deck.pdf"
    doc = pymupdf.open()
    for unit in units:
        for step in (1, 2):
            page = doc.new_page(width=453, height=255)
            page.insert_text((20, 40), f"slide id: {unit.id_slug.split('-')[0]}  step {step}")
    doc.save(pdf)
    doc.close()
    return pdf


def _record(pdf, deck, units, ctx):
    from slidemage import compile_records

    paths = [deck.path, *{u.source_path for u in units}, ctx.root / "SlideMage.bib"]
    return {"pdf_sha256": compile_records.sha256(pdf),
            "inputs": [{"path": str(p), "sha256": compile_records.sha256(p)} for p in paths if p.is_file()]}


def test_a_deck_compile_gives_the_preview_current_pages_until_what_the_slide_depends_on_changes(project, store, raster, tmp_path):
    from slidemage.compiler import CompileJob

    r = make(project, store, raster)
    deck = deck_named(r, "slidemage-manual")
    units = background_renders.deck_units(project, deck, "instructor", "EN")[:6]
    pdf = _compiled_pdf(tmp_path, units)
    job = CompileJob(deck, "instructor", None)
    assert r.ingest_compile(job, pdf, _record(pdf, deck, units, project)) >= 1
    unit = units[0]
    found = r.resolver.lookup(unit)
    assert found.usable and found.record["partial"] and found.record["origin"] == render_store.ORIGIN_COMPILE
    assert store.page(found.record, 1) is not None and found.record["pages"] == 1
    assert not found.final                     # the idle sweep still renders it in full
    # another slide changing does not change this slide's page ...
    other = units[1].source_path
    other.write_text(other.read_text(encoding="utf-8") + "\n% edited\n", encoding="utf-8")
    assert r.resolver.lookup(unit).usable
    # ... the slide itself does
    unit.source_path.write_text(unit.source_path.read_text(encoding="utf-8") + "\n% edited\n", encoding="utf-8")
    assert not r.resolver.lookup(unit).usable


def test_a_compile_page_is_not_a_list_of_steps_and_gives_way_to_the_steps_render(project, store, raster, tmp_path):
    from slidemage.compiler import CompileJob

    r = make(project, store, raster)
    deck = deck_named(r, "slidemage-manual")
    units = background_renders.deck_units(project, deck, "instructor", "EN")[:3]
    pdf = _compiled_pdf(tmp_path, units)
    assert r.ingest_compile(CompileJob(deck, "instructor", None), pdf, _record(pdf, deck, units, project)) >= 1
    unit = units[0]
    assert r.resolver.lookup(unit).record["partial"]
    steps_pdf = _compiled_pdf(tmp_path / "x", [unit]) if (tmp_path / "x").mkdir() is None else None
    pages = [b"png1", b"png2"]
    r.store_reveal(unit, steps_pdf, pages)
    record = r.resolver.lookup(unit).record
    assert not record.get("partial") and record["pages"] == 2


# -- batches: several slides in one document -----------------------------------------------------


class FakeBatchTeX:
    """Stands for slide_preview.render_slides_to_pdf: one PDF with `pages` pages per unit, each naming its slide id in
    the footer text, and the files the document read (every unit's slide, the alt texts, the bibliography)."""

    def __init__(self, project, pages=2):
        self.project, self.pages, self.calls, self.during = project, pages, [], None
        self.order = None                       # a function of the ids that scrambles them, to break the split

    def __call__(self, units, cancel):
        self.calls.append([u.id_slug for u in units])
        if self.during:
            self.during(units)
        ids = [u.id_slug.split("-")[0] for u in units]
        if self.order:
            ids = self.order(ids)
        folder = Path(tempfile.mkdtemp(prefix="slidemage_preview_"))
        pdf = folder / "batch-x.pdf"
        doc = pymupdf.open()
        for bare in ids:
            for number in range(self.pages):
                doc.new_page(width=453, height=255).insert_text((20, 40), f"slide id: {bare}  step {number + 1}")
        doc.save(pdf)
        doc.close()
        files = [u.source_path for u in units] + [self.project.root / "media" / "alt-text.csv", self.project.root / "SlideMage.bib"]
        pdf.with_suffix(".inputs.json").write_text(json.dumps([str(f) for f in files]), encoding="utf-8")
        return pdf


def batch_units(project, r, count=4, view="instructor"):
    units = background_renders.deck_units(project, deck_named(r, "slidemage-manual"), view, "EN")
    chosen, seen = [], set()
    for unit in units:
        bare = unit.id_slug.split("-")[0]
        if bare not in seen:
            seen.add(bare)
            chosen.append(unit)
    return chosen[:count]


def test_the_planner_hands_over_consecutive_units_of_one_deck_view_and_language_up_to_the_batch_size(project, store, raster):
    from dataclasses import replace

    r = make(project, store, raster, batch=4)
    instructor = batch_units(project, r, 12)
    during = batch_units(project, r, 12, "during-course")
    twin = replace(instructor[1], id_slug=instructor[1].id_slug.split("-")[0] + "-twin")       # the same bare slide id
    plan = instructor[:3] + [twin] + instructor[3:6] + during[:2] + instructor[6:8]
    r._plan = [((n,), unit) for n, unit in enumerate(plan)]
    r._single = {instructor[4].label}                                                          # failed before: on its own
    r._top_up()
    batches = [job.payload[0] for job in sorted(r.scheduler._queue.values(), key=lambda j: j.order())]
    labels = [[u.label for u in batch] for batch in batches]
    assert labels[0] == [u.label for u in instructor[:3]] + [instructor[3].label]               # the twin waits, the next one fills up
    assert all(len(batch) <= 4 and len({(u.deck, u.view, u.language) for u in batch}) == 1 for batch in batches)
    assert all(len({u.id_slug.split("-")[0] for u in batch}) == len(batch) for batch in batches)
    assert [instructor[4].label] in labels and all(instructor[4].label not in l for l in labels if len(l) > 1)
    assert [u.label for u in during[:2]] in labels                                              # another view: its own job
    flat = [label for batch in labels for label in batch]
    assert flat.index(instructor[0].label) < flat.index(instructor[3].label) < flat.index(during[0].label)
    assert r.scheduler.pending(P_IDLE) == min(background_renders.QUEUE_AHEAD, r.scheduler.workers + 2) or not r._plan


def test_units_already_queued_are_not_batched_again_after_a_replan(project, store, raster):
    r = make(project, store, raster, batch=4)
    units = batch_units(project, r, 6)
    r._plan = [((n,), unit) for n, unit in enumerate(units)]
    r._top_up()
    queued = r.scheduler.pending(P_IDLE)
    r._plan = [((n,), unit) for n, unit in enumerate(units)]                  # a new scan finds them outstanding again
    r._top_up()
    assert r.scheduler.pending(P_IDLE) == queued and r._plan == []


def test_a_batch_stores_each_slide_as_a_single_render_would(project, store, raster):
    single, batch = FakeTeX(project, pages=2), FakeBatchTeX(project, pages=2)
    r = make(project, store, raster, tex=single, batch_renderer=batch)
    units = batch_units(project, r, 4)
    r.render_unit(units[3], background_renders.ORIGIN_BACKGROUND, CancelToken())
    r.render_batch(tuple(units[:3]), (), CancelToken())
    assert batch.calls == [[u.id_slug for u in units[:3]]] and r.scheduler.pending() == 0
    reference = r.resolver.lookup(units[3]).record
    for unit in units[:3]:
        found = r.resolver.lookup(unit)
        record = found.record
        assert found.state is Freshness.FRESH and found.final and record["origin"] == "background" and record["name"].endswith(".bg")
        assert record["pages"] == 2 and store.page(record, 2).startswith(b"\x89PNG") and store.page(record, 3) is None
        for field in ("format", "width", "machine", "engine_fp", "unstable", "decks", "pages", "origin"):
            assert record[field] == reference[field]
        assert set(record) == set(reference) and record["unit"] == unit.label and record["frame_number"] == unit.frame_number
        with pymupdf.open(store.pdf_path(record)) as own:                              # its own pages only
            assert [p.get_text().split()[2] for p in own] == [unit.id_slug.split("-")[0]] * 2
        files = {entry[1] for entry in record["manifest"]}
        assert "media/alt-text.csv" in files and "SlideMage.bib" in files
        assert unit.source_path.relative_to(project.root).as_posix() in files
        assert not any(other.source_path.relative_to(project.root).as_posix() in files for other in units if other is not unit)
    assert not list(Path(tempfile.gettempdir()).glob("slidemage_preview_*"))


def test_a_batch_leaves_out_what_is_current_and_counts_what_it_stores(project, store, raster):
    batch = FakeBatchTeX(project)
    r = make(project, store, raster, tex=FakeTeX(project, pages=2), batch_renderer=batch)
    units = batch_units(project, r, 4)
    r.scan()
    before = r.progress.deck("slidemage-manual").fresh
    r.render_unit(units[1], background_renders.ORIGIN_BACKGROUND, CancelToken())
    r.render_batch(tuple(units), (), CancelToken())
    assert batch.calls == [[units[0].id_slug, units[2].id_slug, units[3].id_slug]]
    assert all(r.resolver.lookup(u).final for u in units) and r.progress.deck("slidemage-manual").fresh == before + 4   # 3 stored, 1 found current
    r.render_batch(tuple(units), (), CancelToken())
    assert len(batch.calls) == 1                                                  # all current: no document at all


def test_a_slide_edited_while_the_batch_renders_is_not_stored(project, store, raster):
    batch = FakeBatchTeX(project)
    r = make(project, store, raster, batch_renderer=batch)
    units = batch_units(project, r, 3)

    def edit(_units):
        units[1].source_path.write_text(units[1].source_path.read_text(encoding="utf-8") + "\n% edited\n", encoding="utf-8")
        old = time.time() - 60
        os.utime(units[1].source_path, (old, old))

    batch.during = edit
    r.render_batch(tuple(units), (), CancelToken())
    assert r.resolver.lookup(units[0]).final and r.resolver.lookup(units[2]).final
    assert not r.resolver.lookup(units[1]).usable and store.count() == 2
    assert r.scheduler.pending() == 0 and store.failures() == []              # left for the next plan


@pytest.mark.parametrize("how", ["compile fails", "wrong order", "missing slide"])
def test_a_batch_that_cannot_be_split_or_compiled_stores_nothing_and_its_slides_run_singly(project, store, raster, how):
    batch = FakeBatchTeX(project)
    r = make(project, store, raster, batch_renderer=batch)
    units = batch_units(project, r, 3)
    if how == "compile fails":
        batch.during = lambda _units: (_ for _ in ()).throw(RuntimeError("Render failed for batch:\n! Undefined control sequence."))
    elif how == "wrong order":
        batch.order = lambda ids: ids[::-1]
    else:
        batch.order = lambda ids: ids[:-1]
    r.render_batch(tuple(units), ("rank",), CancelToken())
    assert store.count() == 0 and store.failures() == [] and r.progress.failures == 0
    jobs = sorted(r.scheduler._queue.values(), key=lambda j: j.order())
    assert sorted(job.key for job in jobs) == sorted(u.label for u in units) and all(len(job.payload[0]) == 1 for job in jobs)
    assert all(job.rank == ("rank",) and job.group == "slidemage-manual" and job.priority == P_IDLE for job in jobs)
    assert not list(Path(tempfile.gettempdir()).glob("slidemage_preview_*"))


def test_a_cancelled_batch_stores_nothing_more_and_leaves_its_slides_outstanding(project, store, raster):
    batch = FakeBatchTeX(project)
    r = make(project, store, raster, batch_renderer=batch)
    units = batch_units(project, r, 3)
    cancel = CancelToken()
    batch.during = lambda _units: cancel.request_stop()
    with pytest.raises(RuntimeError):
        r.render_batch(tuple(units), (), cancel)
    assert store.count() == 0 and r.scheduler.pending() == 0 and store.failures() == []


def test_a_batch_job_shows_as_one_running_entry(project, store, raster):
    batch = FakeBatchTeX(project)
    r = make(project, store, raster, batch_renderer=batch, tex=FakeTeX(project, pages=1))
    units = batch_units(project, r, 3)
    seen = []
    batch.during = lambda _units: seen.extend(r.running())
    r.scheduler.submit("batch", (tuple(units), background_renders.ORIGIN_BACKGROUND), P_IDLE, (1,), group="slidemage-manual")
    r.scheduler.run_next()
    assert [e["slide"] for e in seen] == ["3 slides"] and seen[0]["deck"] == "slidemage-manual" and r.progress.working is None
    assert all(r.resolver.lookup(u).final for u in units)


def test_the_compile_manifest_keeps_the_alt_texts_every_render_reads(project, store, raster):
    from slidemage import compile_records
    from slidemage.dep_hash import norm

    r = make(project, store, raster)
    units = batch_units(project, r, 2)
    root = project.root
    named = next(p for p in (root / "media").iterdir() if p.suffix == ".png")
    unit = units[0]
    unit.source_path.write_text(unit.source_path.read_text(encoding="utf-8") + f"\n% {named.stem}\n", encoding="utf-8")
    paths = [unit.source_path, units[1].source_path, root / "media" / "alt-text.csv", root / "media" / "alt-text.json",
             named, root / "media" / "illustration-bar-chart.pdf", root / "SlideMage.bib"]
    recorded = {norm(p): (p, compile_records.sha256(p)) for p in paths}
    files = {entry[1] for entry in r._compile_manifest(recorded, unit)}
    assert files == {unit.source_path.relative_to(root).as_posix(), "media/alt-text.csv", "media/alt-text.json",
                     f"media/{named.name}", "SlideMage.bib"}


@pytest.mark.skipif(shutil.which("latexmk") is None or shutil.which("lualatex") is None, reason="needs a TeX installation")
def test_a_real_batch_gives_the_pages_and_the_evidence_of_the_single_renders(project, store, tmp_path):
    os.environ.setdefault("SLIDEMAGE_LATEX", str(Path(__file__).resolve().parent.parent / "latex"))
    decks = deck_scan.scan_decks(project)
    gate = IdleGate(startup_delay=0, idle_after=0, only_on_mains=lambda: False, cpu_load=lambda: 0.0, is_busy=lambda: [])
    batched = BackgroundRenderer(project, store, gate=gate, decks=lambda: decks)
    batched.test_decks = decks
    other = render_store.RenderStore(project, tmp_path / "local-singles")
    singles = BackgroundRenderer(project, other, gate=gate, decks=lambda: decks)
    try:
        units = [u for u in batch_units(project, batched, 40) if u.macro != "slidestep"][3:6]
        batched.render_batch(tuple(units), (), CancelToken())
        assert batched.scheduler.pending() == 0, "the batch fell back to single renders"
        for unit in units:
            singles.render_unit(unit, background_renders.ORIGIN_BACKGROUND, CancelToken())
            ours, theirs = batched.resolver.lookup(unit).record, singles.resolver.lookup(unit).record
            assert ours["pages"] == theirs["pages"] >= 1
            assert [store.page(ours, n) for n in range(1, ours["pages"] + 1)] == [other.page(theirs, n) for n in range(1, theirs["pages"] + 1)]
            assert ours["manifest"] == theirs["manifest"] and ours["frame_number"] == theirs["frame_number"]
            assert not ours["unstable"] and ours["origin"] == theirs["origin"] == "background"
    finally:
        other.close()
        singles.stop()
        batched.stop()


def test_what_runs_comes_from_the_workers_not_from_a_copy_of_the_progress(project, store, raster, tmp_path):
    # A render that ended while the planner rebuilt the progress stayed "working" in the copy: the chip said
    # "Preparing previews" with nothing running until the next render, and in front of the window none starts.
    r = make(project, store, raster)
    r.progress = background_renders.Progress([background_renders.DeckProgress("a", total=10, fresh=4)],
                                             working="a:1jh:instructor:EN", scanned_at=1.0)
    r.gate.sweep_until = 0.0
    assert not r.sweeping()
    from slidemage.compiler import CancelToken
    from slidemage.render_scheduler import Job
    job = Job("b:2:instructor:EN", None, background_renders.P_IDLE)
    job.cancel, job.started, job.cancelled_for_requeue = CancelToken(), 0.0, False
    r.scheduler._running[job.key] = job                         # a render runs
    assert r.sweeping()
    assert r.scheduler.interrupt(background_renders.P_IDLE) == 1 and job.cancel.is_set()
    assert not r.sweeping()                                      # told to stop: no longer "Preparing", however long it takes
    del r.scheduler._running[job.key]
    r.scan()
    assert r.progress.working is None                          # the new progress names what runs, from the workers
    r._trace = background_renders.Trace(tmp_path / "trace.log")
    r.window_focus(True)
    r.trace("chip: Previews wait while you use SlideMage")
    lines = (tmp_path / "trace.log").read_text(encoding="utf-8").splitlines()
    assert "focus in: stopped 0 | in_front=True" in lines[0] and "running=0" in lines[0]
    assert lines[1].split(" ", 2)[2].startswith("chip: Previews wait")


def test_a_slide_the_plan_counted_as_fresh_is_not_counted_again_when_its_page_number_is_refreshed(project, store, raster):
    r = make(project, store, raster)
    deck = deck_named(r, "slidemage-manual")
    first, second = background_renders.deck_units(project, deck, "instructor", "EN")[:2]
    r.progress = background_renders.Progress([background_renders.DeckProgress(deck.name, total=10, fresh=4)])
    r._counted = {first.label}                                   # right apart from its page number: counted already
    r._count_fresh(first)
    assert r.progress.deck(deck.name).fresh == 4
    r._count_fresh(second)                                       # a slide really rendered now
    assert r.progress.deck(deck.name).fresh == 5
