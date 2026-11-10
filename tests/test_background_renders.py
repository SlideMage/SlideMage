# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Idle-time rendering: what is outstanding, in which order, what a render stores (a fake TeX; MuPDF writes the PDFs)."""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path

import pymupdf
import pytest

from conftest import EXAMPLE
from slidemage import background_renders, compile_records, compiler, deck_scan, render_evidence, render_store, slide_preview, slide_versioning
from slidemage.background_renders import BackgroundRenderer
from slidemage.compiler import CancelToken
from slidemage.deck_editor import VIEWS
from slidemage.idle_gate import IdleGate
from slidemage.preview_raster_client import RasterClient
from slidemage.project import ProjectContext
from slidemage.render_key import Freshness
from slidemage.render_scheduler import P_IDLE

# An edit that puts the mtime back changes only the ctime, and Windows' st_ctime is the creation time.
CTIME_SEES_EDITS = pytest.mark.skipif(os.name == 'nt', reason='st_ctime is the creation time on Windows')


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


def render_unit(renderer, unit):
    spec = renderer.request_for(unit)
    cancel = CancelToken()
    cancel.low_priority = True
    request = renderer.renders.request(spec.target, spec.revision.text, unit.view, unit.language, lambda _: None, spec=spec)
    try:
        request.wait(cancel)
    except RuntimeError:
        if request.preview_result is not None and request.preview_result.status == 'failed':
            return None
        raise
    stored = renderer.store.find(renderer.resolver.fast_key(unit, spec.revision.text))
    if stored is not None:
        renderer.store.link_decks(stored['name'], [unit.deck])
        return stored['name']
    return None


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
    name = render_unit(r, unit)
    assert name == r.resolver.fast_key(unit)
    found = r.resolver.lookup(unit)
    assert found.state is Freshness.FRESH and found.final and found.record["pages"] == 3
    assert store.page(found.record, 3).startswith(b"\x89PNG") and store.page(found.record, 4) is None
    assert not list(Path(tempfile.gettempdir()).glob("slidemage_preview_*"))          # the temp folder is gone
    render_unit(r, unit)
    assert len(tex.calls) == 1                                                        # nothing to do the second time


def test_editing_the_slide_or_what_it_reads_makes_it_outstanding_again(project, store, raster):
    tex = FakeTeX(project)
    r = make(project, store, raster, tex=tex)
    unit = background_renders.deck_units(project, deck_named(r, "slidemage-manual"), "instructor", "EN")[2]
    render_unit(r, unit)
    assert r.resolver.lookup(unit).final
    unit.source_path.write_text(unit.source_path.read_text(encoding="utf-8") + "\n% edited\n", encoding="utf-8")
    time.sleep(0.01)
    old = time.time() - 60
    os.utime(unit.source_path, (old, old))
    again = r.resolver.lookup(unit)
    assert again.state is Freshness.MISSING or again.state is Freshness.STALE
    assert not again.final


def test_a_page_number_that_moved_is_refreshed_last(project, store, raster):
    tex = FakeTeX(project)
    r = make(project, store, raster, tex=tex)
    deck = deck_named(r, "slidemage-manual")
    units = background_renders.deck_units(project, deck, "instructor", "EN")
    render_unit(r, units[3])
    from dataclasses import replace
    moved = replace(units[3], frame_number=units[3].frame_number + 1)
    assert r.resolver.lookup(moved).state is Freshness.FRESH_NUMBERING_DIFFERS
    render_unit(r, moved)
    assert r.resolver.lookup(moved).state is Freshness.FRESH and len(tex.calls) == 2
    assert store.count() == 1


def test_a_failing_slide_is_remembered_and_not_planned_again_until_it_changes(project, store, raster):
    tex = FakeTeX(project)
    r = make(project, store, raster, tex=tex)
    deck = deck_named(r, "slidemage-manual")
    unit = background_renders.deck_units(project, deck, "instructor", "EN")[0]
    tex.fail[unit.id_slug] = "Render failed for x:\n! Undefined control sequence."
    with pytest.raises(RuntimeError):
        render_unit(r, unit)
    assert r.resolver.lookup(unit).state is Freshness.FAILED
    plan = r.scan()
    assert unit.label not in [u.label for _, u in plan]
    assert r.progress.deck("slidemage-manual").failed >= 1
    assert render_unit(r, unit) is None   # no loop
    assert len(tex.calls) == 1
    unit.source_path.write_text(unit.source_path.read_text(encoding="utf-8") + "\n% fixed\n", encoding="utf-8")
    old = time.time() - 60
    os.utime(unit.source_path, (old, old))
    assert r.resolver.lookup(unit).state is not Freshness.FAILED


@pytest.mark.parametrize("repair", ["edit dependency", "restore missing input"])
def test_failed_background_build_tracks_its_own_inputs_and_retries_after_repair(project, store, raster, monkeypatch, repair):
    from slidemage import compiler

    r = make(project, store, raster)
    r._render = None
    monkeypatch.setenv("SLIDEMAGE_PREVIEW_FORMAT", "0")
    unit = background_renders.deck_units(project, deck_named(r, "slidemage-manual"), "instructor", "EN")[0]
    dependency = project.root / "preview-shared.tex"
    dependency.write_text("broken dependency")
    os.utime(dependency, (time.time() - 60,) * 2)
    missing = project.root / "preview-restored.tex"
    unrelated = project.root / "unrelated.tex"
    unrelated.write_text("another concurrent job")
    calls = []

    def fail(command, *, jobname, outdir, **kwargs):
        calls.append(command)
        (outdir / (jobname + ".fls")).write_text(
            f"PWD {project.decks_dir}\nINPUT {unit.source_path}\nINPUT {dependency}\n")
        other = store.work_dir / "build/preview-cache/other/other.fls"
        other.parent.mkdir(parents=True, exist_ok=True)
        other.write_text(f"INPUT {unrelated}\n")
        # The useful error may be long before the stored tail of the log.
        log = "! LaTeX Error: File `preview-restored.tex' not found.\n" + "memory statistics\n" * 30
        return compiler.Build(1, outdir / (jobname + ".pdf"), outdir / (jobname + ".log"), log, False)

    monkeypatch.setattr(compiler, "run_latexmk", fail)
    with pytest.raises(RuntimeError, match="Render failed"):
        render_unit(r, unit)
    failure = r.resolver.lookup(unit).failure
    assert failure is not None
    assert any(entry[1] == dependency.name for entry in failure["manifest"])
    assert not any(entry[1] == unrelated.name for entry in failure["manifest"])
    assert render_unit(r, unit) is None
    assert len(calls) == 1
    if repair == "edit dependency":
        _edit(dependency, "\nfixed dependency")
    else:
        missing.write_text("restored dependency")
        os.utime(missing, (time.time() - 60,) * 2)
    assert r.resolver.lookup(unit).state is not Freshness.FAILED
    with pytest.raises(RuntimeError, match="Render failed"):
        render_unit(r, unit)
    assert len(calls) == 2
    assert r.resolver.lookup(unit).state is Freshness.FAILED
    assert render_unit(r, unit) is None


def test_failure_count_and_details_ignore_obsolete_and_changed_inputs(project, store, raster):
    tex = FakeTeX(project)
    r = make(project, store, raster, tex=tex)
    unit = background_renders.deck_units(project, deck_named(r, "slidemage-manual"), "instructor", "EN")[0]
    tex.fail[unit.id_slug] = "Render failed for x:\n! Bad dependency."
    store.record_failure("obsolete", render_store.DETERMINISTIC, "an old request", [])
    with pytest.raises(RuntimeError):
        render_unit(r, unit)
    r.scan()
    assert r.progress.failures == 1
    assert [f["key"] for f in r.current_failures()] == [r.resolver.fast_key(unit)]
    _edit(unit.source_path)
    r.scan()
    assert r.progress.failures == 0 and r.current_failures() == []
    assert len(store.failures()) == 2                     # historical records do not affect the warning


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
    render_unit(r, unit)
    background_renders.app_settings.set(project, background_renders.LIMIT_GB_KEY, store.total_bytes() / 1024 ** 3)

    def queued_decks():
        return {job.group for job in r.scheduler._queue.values()}

    def drop_queued():
        for group in queued_decks():
            r.scheduler.cancel_group(group)

    r.tick()                                     # no deck opened yet: rendering any would push another one out
    assert queued_decks() == set() and r.progress.left > 0
    assert r.progress.paused_because == background_renders.STORE_FULL and not r.sweeping()
    store.touch_deck(manual.name, opened=True)
    r.replan()
    r.tick()                                     # the deck in use may push out the others' renders
    assert queued_decks() == {manual.name} and r.progress.paused_because is None
    drop_queued()
    background_renders.app_settings.set(project, background_renders.LIMIT_GB_KEY, 1.0)
    r.replan()
    r.tick()                                     # room again: the sweep goes on with every deck, nothing was pushed out
    assert r.progress.paused_because is None and store.count() == 1
    drop_queued()
    with r._plan_lock:
        r._plan = [item for item in r._plan if item[1].deck == copy.name]
    r._top_up()
    assert queued_decks() == {copy.name}


def test_archiving_a_deck_removes_its_renders_and_stops_planning_it(project, store, raster):
    tex = FakeTeX(project, pages=1)
    r = make(project, store, raster, tex=tex)
    deck = deck_named(r, "slidemage-manual-copy")
    unit = background_renders.deck_units(project, deck, "instructor", "EN")[0]
    render_unit(r, unit)
    assert store.count() == 1
    deck.archived = True
    r.deck_archived(deck)
    assert store.count() == 0 and deck.name not in [d.name for d in r.ordered_decks()]


def test_a_slide_with_no_page_in_the_view_is_a_failure_not_an_empty_render(project, store, raster):
    r = make(project, store, raster, tex=FakeTeX(project, pages=1))
    r._rasterise = lambda pdf, cancel: []
    unit = background_renders.deck_units(project, deck_named(r, "slidemage-manual"), "instructor", "EN")[0]
    with pytest.raises(RuntimeError):
        render_unit(r, unit)
    assert r.resolver.lookup(unit).state is Freshness.FAILED


def test_a_deck_a_plugin_wants_soon_comes_after_the_open_deck_and_before_the_rest(project, store, raster):
    r = make(project, store, raster, plugin_soon=lambda deck: deck.name == "slidemage-manual-copy")
    store.touch_deck("slidemage-manual", opened=True)
    assert [d.name for d in r.ordered_decks()][:2] == ["slidemage-manual-copy", "slidemage-manual"]





def test_a_scan_counts_each_deck_by_version_and_lists_the_decks_left_out(project, store, raster):
    tex = FakeTeX(project, pages=1)
    r = make(project, store, raster, tex=tex)
    deck = deck_named(r, "slidemage-manual")
    units = background_renders.deck_units(project, deck, "instructor", "EN")
    for unit in units[:5]:
        render_unit(r, unit)
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
def test_a_real_background_render_creates_nothing_in_the_project_and_matches_the_foreground_render(project, store):
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
    name = render_unit(renderer, unit)
    assert name is not None and listing() == before                                  # not one file in the project
    assert (store.work_dir / "decks").is_dir() and list((store.work_dir / "decks").glob("_slidemage_preview-*.tex"))
    assert [d.name for d in deck_scan.scan_decks(project)] == [d.name for d in decks]
    found = renderer.resolver.lookup(unit)
    assert found.final and found.record["pages"] >= 1

    foreground = slide_preview.render_slide_to_pdf(
        project, unit.macro, unit.id_slug, unit.version, list(unit.conditions) or None, deck_version=unit.view,
        deck_language=unit.language.lower(), preamble_text=unit.preamble_text, frame_number=unit.frame_number,
        log=lambda line: None, all_steps=True)
    with store.lock, pymupdf.open(foreground) as theirs, pymupdf.open(Path(found.record["dir"]) / "slide.pdf") as ours:
        assert len(ours) == len(theirs) == found.record["pages"]
        assert [p.get_text() for p in ours] == [p.get_text() for p in theirs]


# -- the slides of a deck compile ------------------------------------------------------------


def _compiled_pdf(tmp_path, units, steps=2):
    """A deck PDF as a compile makes it: every slide's pages (`steps` of them) with their slide id in the footer."""
    pdf = tmp_path / "deck.pdf"
    doc = pymupdf.open()
    for unit in units:
        for step in range(1, steps + 1):
            page = doc.new_page(width=453, height=255)
            page.insert_text((20, 40), f"slide id: {unit.id_slug.split('-')[0]}  step {step}")
    doc.save(pdf)
    doc.close()
    return pdf


def _record(pdf, job, units, ctx, paths=None):
    paths = paths or [job.deck.path, *{u.source_path for u in units}, ctx.root / "SlideMage.bib"]
    invocation = ctx.build_dir / f"{job.jobname}-test"
    invocation.mkdir(parents=True, exist_ok=True)
    (invocation / f"{job.jobname}.fls").write_text(
        "".join(f"INPUT {path}\n" for path in paths if path.is_file()), encoding="utf-8")
    (invocation / f"{job.jobname}.log").write_text("ok\n", encoding="utf-8")
    started = time.time()
    env = compiler.build_env(ctx)
    inventory = render_evidence.search_inventory(ctx.root, env)
    configuration = render_evidence.digest(render_evidence.configuration_state(ctx.root, env))
    assert compile_records.write_record(ctx, job.jobname, invocation, job.deck.path, "", pdf, started, inventory, configuration,
                                        deck_path=job.deck.path)
    return compile_records.read_record(ctx.build_dir, job.jobname)


def test_a_deck_compile_gives_the_preview_current_pages_until_what_the_slide_depends_on_changes(project, store, raster, tmp_path):
    from slidemage.compiler import CompileJob

    r = make(project, store, raster)
    deck = deck_named(r, "slidemage-manual")
    units = background_renders.deck_units(project, deck, "instructor", "EN")[:6]
    pdf = _compiled_pdf(tmp_path, units)
    job = CompileJob(deck, "instructor", None)
    assert r.ingest_compile(job, pdf, _record(pdf, job, units, project)) >= 1
    unit = units[0]
    found = r.resolver.lookup(unit)
    assert found.usable and found.record["origin"] == render_store.ORIGIN_COMPILE
    assert store.page(found.record, 1) is not None and found.record["pages"] == 2
    assert found.final                          # a plain \slide call: the compile already has every one of its steps
    # another slide changing does not change this slide's page ...
    other = units[1].source_path
    other.write_text(other.read_text(encoding="utf-8") + "\n% edited\n", encoding="utf-8")
    assert r.resolver.lookup(unit).usable
    # ... the slide itself does
    unit.source_path.write_text(unit.source_path.read_text(encoding="utf-8") + "\n% edited\n", encoding="utf-8")
    assert not r.resolver.lookup(unit).usable


@CTIME_SEES_EDITS
def test_a_compile_with_an_input_changed_during_it_imports_nothing(project, store, raster, tmp_path):
    r = make(project, store, raster)
    deck = deck_named(r, "slidemage-manual")
    units = background_renders.deck_units(project, deck, "instructor", "EN")[:2]
    job = compiler.CompileJob(deck, "instructor", None)
    pdf = _compiled_pdf(tmp_path, units)
    external = tmp_path / "references.bib"
    external.write_text("@book{x}\n", encoding="utf-8")
    record = _record(pdf, job, units, project, [deck.path, *[u.source_path for u in units], external])
    # Restoring mtime does not hide changed external content from the recorded hash.
    before = external.stat()
    external.write_text("@book{y}\n", encoding="utf-8")
    os.utime(external, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert r.ingest_compile(job, pdf, record) == 0 and store.count() == 0
    assert compile_records.write_record(project, job.jobname, project.build_dir / f"{job.jobname}-test",
                                        deck.path, "", pdf, record["started"], record["inventory"], record["configuration"]) is None
    assert compile_records.read_record(project.build_dir, job.jobname) is None


def test_a_deck_compile_imports_other_slides_but_skips_a_frozen_plus_slide(project, store, raster, tmp_path):
    r = make(project, store, raster)
    deck = deck_named(r, "slidemage-manual")
    units = background_renders.deck_units(project, deck, "instructor", "EN")[:4]
    changed, other, _, unrelated = units
    text = changed.source_path.read_text(encoding="utf-8")
    frozen = slide_versioning.frozen_path(changed.source_path, changed.id_slug, (1, 0, 0))
    frozen.write_text(slide_versioning.set_marker(text, (1, 0, 0)), encoding="utf-8")
    changed.source_path.write_text(slide_versioning.set_marker(text + "\nChanged content\n", (1, 0, 0), changed=True),
                                   encoding="utf-8")
    assert frozen.name in "\n".join(slide_versioning.saved_version_lines(project, deck, "EN"))
    # The other slide's canonical text hash also works with Windows line endings.
    other.source_path.write_bytes(other.source_path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    job = compiler.CompileJob(deck, "instructor", None)
    pdf = _compiled_pdf(tmp_path, units)
    record = _record(pdf, job, units, project, [deck.path, frozen, *[u.source_path for u in units[1:]]])
    unrelated.source_path.write_text(unrelated.source_path.read_text(encoding="utf-8") + "\n% edited\n", encoding="utf-8")
    assert r.ingest_compile(job, pdf, record) == 2
    assert store.latest_for_unit(changed.label) is None
    assert store.latest_for_unit(unrelated.label) is None
    assert all(r.resolver.lookup(unit).final for unit in units[1:3])


def test_a_slidestep_call_is_left_to_the_sweep_not_finished_by_a_compile(project, store, raster, tmp_path):
    """\\slidestep and \\slidefinal calls stay with the sweep (docs/plans/render-store-cleanup.md, step 4): their
    page in a deck compile is only a selection of the slide's steps, never every one, so the compile stores nothing
    for them, and the unit is not finished until the sweep's own all-steps render lands."""
    from slidemage.compiler import CompileJob

    r = make(project, store, raster, tex=FakeTeX(project))
    deck = deck_named(r, "slidemage-manual")
    units = background_renders.deck_units(project, deck, "instructor", "EN", context_ready=lambda: True)
    unit = next(u for u in units if u.macro == "slidestep")
    pdf = _compiled_pdf(tmp_path, [unit])
    job = CompileJob(deck, "instructor", None)
    assert r.ingest_compile(job, pdf, _record(pdf, job, [unit], project)) == 0
    found = r.resolver.lookup(unit)
    assert not found.usable and not found.final
    render_unit(r, unit)
    assert r.resolver.lookup(unit).final            # finished once the sweep's own all-steps render lands


def test_a_final_state_for_students_slide_is_finished_from_the_compile_with_one_page_for_students(project, store, raster, tmp_path):
    """\\SMFinalStateForStudents (D1): a student view's compile already shows only the slide's last step, so that one
    page is the whole of it and the unit is finished; the instructor view's compile shows every step, so it is
    finished too, with all of them."""
    from slidemage.compiler import CompileJob

    r = make(project, store, raster)
    deck = deck_named(r, "slidemage-manual")
    instructor_units = background_renders.deck_units(project, deck, "instructor", "EN")
    student_units = background_renders.deck_units(project, deck, "during-course", "EN")
    i_unit = next(u for u in instructor_units if "Final-State" in u.id_slug)
    s_unit = next(u for u in student_units if "Final-State" in u.id_slug)

    (tmp_path / "i").mkdir()
    i_pdf = _compiled_pdf(tmp_path / "i", [i_unit], steps=3)
    i_job = CompileJob(deck, "instructor", None)
    assert r.ingest_compile(i_job, i_pdf, _record(i_pdf, i_job, [i_unit], project)) == 1
    i_found = r.resolver.lookup(i_unit)
    assert i_found.final and i_found.record["pages"] == 3

    (tmp_path / "s").mkdir()
    s_pdf = _compiled_pdf(tmp_path / "s", [s_unit], steps=1)
    s_job = CompileJob(deck, "during-course", None)
    assert r.ingest_compile(s_job, s_pdf, _record(s_pdf, s_job, [s_unit], project)) == 1
    s_found = r.resolver.lookup(s_unit)
    assert s_found.final and s_found.record["pages"] == 1


def test_a_contents_slide_is_finished_from_the_compile_that_is_its_context(project, store, raster, tmp_path):
    """A slide that needs its deck (a contents or agenda slide, a section divider, D2) is typeset in this very
    compile, so it is included (deck_units' `context_ready`) and finished from it like any other slide."""
    from slidemage.compiler import CompileJob

    r = make(project, store, raster)
    deck = deck_named(r, "slidemage-manual")
    units = background_renders.deck_units(project, deck, "instructor", "EN", context_ready=lambda: True)
    unit = next(u for u in units if "Contents" in u.id_slug)
    assert unit.context                                  # needs its deck
    pdf = _compiled_pdf(tmp_path, [unit], steps=1)
    job = CompileJob(deck, "instructor", None)
    assert r.ingest_compile(job, pdf, _record(pdf, job, [unit], project)) == 1
    found = r.resolver.lookup(unit)
    assert found.final and found.record["pages"] == 1


# -- batches: several slides in one document -----------------------------------------------------


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


@CTIME_SEES_EDITS
def test_a_dependency_edited_during_the_render_is_never_stored(project, store, raster, monkeypatch):
    r = make(project, store, raster)
    unit = batch_units(project, r, 1)[0]
    dependency = project.root / "snippets/shared.tex"
    dependency.write_text("before", encoding="utf-8")
    old = dependency.stat()

    def compile(*args, **kwargs):
        pdf = FakeTeX(project)(unit, kwargs["cancel"])
        pdf.with_suffix(".inputs.json").write_text(json.dumps([str(unit.source_path), str(dependency)]))
        dependency.write_text("after!", encoding="utf-8")
        os.utime(dependency, ns=(old.st_atime_ns, old.st_mtime_ns))
        return pdf

    monkeypatch.setattr(slide_preview, "render_slide_text_to_pdf", compile)
    r._render = None
    assert render_unit(r, unit) is None
    assert store.count() == 0 and store.failures() == []
    assert not r.resolver.lookup(unit).usable


def test_what_runs_comes_from_the_workers_not_from_a_copy_of_the_progress(project, store, raster, caplog):
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
    with caplog.at_level(logging.DEBUG, logger="slidemage.background"):
        r.window_focus(True)
        r.trace("chip: Preview rendering waits while you use SlideMage")
    lines = [rec.getMessage() for rec in caplog.records if rec.name == "slidemage.background"]
    assert "focus in: stopped 0 | in_front=True" in lines[0] and "running=0" in lines[0]
    assert lines[1].startswith("chip: Preview rendering waits")


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


def test_a_failed_slide_is_tried_once_more_on_its_own_when_everything_else_is_rendered(project, store, raster, monkeypatch):
    tex = FakeTeX(project, pages=1)
    r = make(project, store, raster, tex=tex)
    deck = deck_named(r, "slidemage-manual")
    broken, other = background_renders.deck_units(project, deck, "instructor", "EN")[:2]
    real_units = background_renders.deck_units
    monkeypatch.setattr(background_renders, "deck_units", lambda *a, **k: [u for u in real_units(*a, **k)
                                                                            if u.id_slug in (broken.id_slug, other.id_slug)])
    monkeypatch.setattr(r, "ordered_decks", lambda: [deck])
    monkeypatch.setattr(r, "versions_for", lambda _deck: ["instructor"])
    monkeypatch.setattr(r, "languages_for", lambda _deck: ["EN"])
    tex.fail[broken.id_slug] = "Render failed for x:\n! Undefined control sequence."
    with pytest.raises(RuntimeError):
        render_unit(r, broken)
    plan = r.scan()                                              # the other slide first; the failed one waits
    assert [u.label for _, u in plan] == [other.label] and r.progress.deck(deck.name).failed == 1
    render_unit(r, other)
    plan = r.scan()                                              # nothing else left: one more try, on its own
    assert [u.label for _, u in plan] == [broken.label] and broken.label in r._single
    assert r.progress.deck(deck.name).failed == 0 and r.progress.left == 1
    with pytest.raises(RuntimeError):
        render_unit(r, broken)
    assert len([c for c in tex.calls if c[0] == broken.id_slug]) == 2
    assert r.scan() == [] and r.progress.deck(deck.name).failed == 1      # once only
    assert render_unit(r, broken) is None


def test_a_failed_slide_that_renders_on_its_last_try_is_no_longer_a_failure(project, store, raster, monkeypatch):
    tex = FakeTeX(project, pages=1)
    r = make(project, store, raster, tex=tex)
    deck = deck_named(r, "slidemage-manual")
    broken = background_renders.deck_units(project, deck, "instructor", "EN")[0]
    real_units = background_renders.deck_units
    monkeypatch.setattr(background_renders, "deck_units", lambda *a, **k: [u for u in real_units(*a, **k) if u.id_slug == broken.id_slug])
    monkeypatch.setattr(r, "ordered_decks", lambda: [deck])
    monkeypatch.setattr(r, "versions_for", lambda _deck: ["instructor"])
    monkeypatch.setattr(r, "languages_for", lambda _deck: ["EN"])
    tex.fail[broken.id_slug] = "Render failed for x:\n! A passing problem."
    with pytest.raises(RuntimeError):
        render_unit(r, broken)
    assert [u.label for _, u in r.scan()] == [broken.label]
    del tex.fail[broken.id_slug]
    assert render_unit(r, broken) is not None
    assert store.failures() == [] and r.resolver.lookup(broken).state is Freshness.FRESH
    r.scan()
    assert r.progress.deck(deck.name).fresh == 1 and r.progress.failures == 0


def _context_units(project, deck):
    plain = {u.label for u in background_renders.deck_units(project, deck, "instructor", "EN")}
    every = background_renders.deck_units(project, deck, "instructor", "EN", None, lambda: True)
    return [u for u in every if u.label not in plain], every


def test_a_slide_that_needs_its_deck_is_a_unit_only_when_the_deck_has_a_compile_to_typeset_it_in(project, store, raster):
    r = make(project, store, raster)
    deck = deck_named(r, "slidemage-manual")
    context, every = _context_units(project, deck)
    assert context and all(u.context == deck.name for u in context)
    assert not any(u.context for u in every if u not in context)
    assert background_renders.deck_units(project, deck, "instructor", "EN", None, lambda: False) == \
        background_renders.deck_units(project, deck, "instructor", "EN")
    assert r.resolver.fast_key(context[0]) != r.resolver.fast_key(
        __import__("dataclasses").replace(context[0], context=""))


def test_the_sweep_counts_and_renders_such_slides_on_their_own_once_the_deck_is_compiled(project, store, raster, monkeypatch):
    from slidemage import deck_context
    r = make(project, store, raster)
    deck = deck_named(r, "slidemage-manual")
    monkeypatch.setattr(r, "ordered_decks", lambda: [deck])
    monkeypatch.setattr(r, "versions_for", lambda _deck: ["instructor"])
    monkeypatch.setattr(r, "languages_for", lambda _deck: ["EN"])
    monkeypatch.setattr(deck_context, "in_deck_ready", lambda *a, **k: False)
    without = len(r.scan())
    monkeypatch.setattr(deck_context, "in_deck_ready", lambda *a, **k: True)
    plan = r.scan()
    context = {u.label for _, u in plan if u.context}
    assert len(plan) > without and context and context <= r._single


def test_a_slide_that_needs_its_deck_is_typeset_in_the_decks_compile_and_kept(project, store, raster, monkeypatch):
    from slidemage import deck_context
    tex = FakeTeX(project, pages=1)
    r = make(project, store, raster, tex=tex)
    deck = deck_named(r, "slidemage-manual")
    unit = _context_units(project, deck)[0][0]
    asked = []

    def in_deck(ctx, the_deck, view, slide_id, id_slug, log, cancel, *, all_steps=False, language=None):
        asked.append((the_deck.name, view, id_slug, all_steps, language))
        return FakeTeX(project, pages=1)(unit, cancel) if id_slug == unit.id_slug else None

    monkeypatch.setattr(deck_context, "render_in_deck", in_deck)
    r._render = None
    assert render_unit(r, unit) is not None
    assert asked == [(deck.name, "instructor", unit.id_slug, True, "EN")] and not tex.calls
    assert r.resolver.lookup(unit).state is Freshness.FRESH
    monkeypatch.setattr(deck_context, "render_in_deck", lambda *a, **k: None)
    other = _context_units(project, deck)[0][-1]
    if other.label != unit.label:
        with pytest.raises(RuntimeError, match="no compile"):
            render_unit(r, other)


def test_start_does_not_rescan_the_store_on_the_calling_thread_and_the_rescan_can_be_stopped(project, store, raster, monkeypatch):
    # 2026-10-29: the rescan of 6000 folders ran before the window opened; it runs on the planner's thread now.
    import threading
    r = make(project, store, raster)
    seen = []
    entered, release = threading.Event(), threading.Event()
    original = store.rescan

    def slow_rescan(should_stop=lambda: False):
        seen.append(threading.current_thread().name)
        entered.set()
        release.wait(5)
        return original(should_stop)

    monkeypatch.setattr(store, "rescan", slow_rescan)
    r.start()
    try:
        assert entered.wait(5) and r.rescanning                  # start() came back while the rescan was running
        assert seen == ["background-planner"]
    finally:
        release.set()
        r.stop()
    assert not r.rescanning and seen == ["background-planner"]


def test_a_deck_whose_template_is_nowhere_is_held_back_and_named_not_failed(project, store, raster, monkeypatch):
    # The project's template file deleted for a theme that is installed on another computer only (v0.14.1): every
    # render stopped at \input{SlideMage_template_<key>} and was stored as a failure, and the chip never said why.
    r = make(project, store, raster)
    deck = deck_named(r, "slidemage-manual")
    unit = background_renders.deck_units(project, deck, "instructor", "EN")[0]
    monkeypatch.setattr(background_renders.slide_templates, "available_templates", lambda root: ["somewhere-else"])
    assert r.scan() == []
    counted = r.progress.deck("slidemage-manual")
    assert counted.blocked == counted.total > 0 and counted.left == 0 and counted.failed == 0
    assert not counted.up_to_date
    assert "slidemage-manual" in r.progress.missing_templates[unit.template]
    assert r.progress.blocked >= counted.total and r.progress.left == 0


def test_a_failure_for_want_of_the_template_is_forgotten_once_the_template_is_found(project, store, raster):
    tex = FakeTeX(project)
    r = make(project, store, raster, tex=tex)
    unit = background_renders.deck_units(project, deck_named(r, "slidemage-manual"), "instructor", "EN")[0]
    tex.fail[unit.id_slug] = (f"Render failed for x:\nl.16 \\input{{SlideMage_template_{unit.template}}}\n"
                              "! Emergency stop.\n")
    with pytest.raises(RuntimeError):
        render_unit(r, unit)
    assert r.resolver.lookup(unit).state is Freshness.FAILED
    plan = r.scan()                       # the template is found now: tried again, not counted as failed
    assert unit.label in [u.label for _, u in plan]
    assert r.resolver.lookup(unit).state is not Freshness.FAILED and not r.progress.missing_templates


# -- stale renders go (docs/plans/render-store-cleanup.md, step 2) ----------------------------------------------------

def _edit(path, text="\n% edited\n"):
    """Change a file as a user would, with an mtime old enough that it is not "being written"."""
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")
    old = time.time() - 60
    os.utime(path, (old, old))


def _keys_of(store, label):
    return sorted(row[0] for row in store.db.execute("SELECT fast_key FROM renders WHERE unit=?", (label,)))


def _png():
    return pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 4, 4)).tobytes("png")


def _leftover(store, label, deck, key):
    """A render stored long ago under `key` (a key no deck uses now)."""
    meta = dict(unit=label, rendered_at=time.time() - 3600, manifest=[], tex_digest="", frame_number=1, unstable=False)
    pdf = store.local_dir / "leftover.pdf"
    with pymupdf.open() as doc:
        doc.new_page()
        doc.save(pdf)
    return store.put(key, render_store.ORIGIN_BACKGROUND, pdf, [_png()], meta, decks=[deck] if deck else [])


def _call_twice(project, slide="1cx-EN-Slide-IDs"):
    """The manual calls `slide` a second time, as \\slidefinal: one label, two calls, two current keys."""
    deck = project.root / "decks" / "slidemage-manual.tex"
    text = deck.read_text(encoding="utf-8").replace(f"\\slide{{{slide}}}", f"\\slide{{{slide}}}\n\t\\slidefinal{{{slide}}}")
    deck.write_text(text, encoding="utf-8")
    old = time.time() - 3600
    os.utime(deck, (old, old))


def test_a_slide_edited_and_rendered_again_leaves_one_render_and_the_old_one_is_shown_until_then(project, store, raster):
    r = make(project, store, raster)
    unit = background_renders.deck_units(project, deck_named(r, "slidemage-manual"), "instructor", "EN")[2]
    render_unit(r, unit)
    old_key = r.resolver.fast_key(unit)
    _edit(unit.source_path)
    r.scan()
    assert _keys_of(store, unit.label) == [old_key]                  # nothing new yet: the old one is "outdated"
    assert r.resolver.lookup(unit).state is Freshness.STALE
    render_unit(r, unit)
    assert _keys_of(store, unit.label) == [r.resolver.fast_key(unit)] != [old_key]


def test_a_render_stored_before_the_scan_saw_the_edit_has_its_old_one_cleared_by_the_next_scan(project, store, raster):
    r = make(project, store, raster)
    unit = background_renders.deck_units(project, deck_named(r, "slidemage-manual"), "instructor", "EN")[2]
    render_unit(r, unit)
    r.scan()
    _edit(unit.source_path)
    render_unit(r, unit)                                # stored before the next scan
    assert len(_keys_of(store, unit.label)) == 2                    # the last scan still had the old key as current
    r.scan()
    assert _keys_of(store, unit.label) == [r.resolver.fast_key(unit)]


def test_a_slide_called_twice_in_two_ways_keeps_both_current_renders_whichever_is_stored(project, store, raster):
    # One label, two current keys (a \slide and a \slidefinal of one slide): deleting by label alone would have each
    # render delete the other, for ever.
    _call_twice(project)
    tex = FakeTeX(project)
    r = make(project, store, raster, tex=tex)
    deck = deck_named(r, "slidemage-manual")
    both = [u for u in background_renders.deck_units(project, deck, "instructor", "EN") if u.id_slug == "1cx-EN-Slide-IDs"]
    assert len({u.label for u in both}) == 1 and len({r.resolver.fast_key(u) for u in both}) == 2
    keys = sorted(r.resolver.fast_key(u) for u in both)
    render_unit(r, both[0])
    r.scan()                                            # the one-off clearing runs here too
    render_unit(r, both[1])
    assert _keys_of(store, both[0].label) == keys
    for unit in both:                                   # storing either again (the reveal bar's render) keeps the other
        store.delete(r.resolver.fast_key(unit))
        render_unit(r, unit)
        assert _keys_of(store, unit.label) == keys
        r.scan()
        assert _keys_of(store, unit.label) == keys
    assert all(r.resolver.lookup(u).final for u in both)
    calls = len(tex.calls)
    plan = r.scan()
    assert not [u for _, u in plan if u.label == both[0].label] and len(tex.calls) == calls


def test_the_leftovers_in_a_store_are_cleared_once_and_only_what_the_scan_read(project, store, raster):
    background_renders.app_settings.set(project, background_renders.DECKS_OFF_KEY, ["slidemage-manual-copy"])
    r = make(project, store, raster)
    deck = deck_named(r, "slidemage-manual")
    unit = background_renders.deck_units(project, deck, "instructor", "EN")[1]
    render_unit(r, unit)
    current = r.resolver.fast_key(unit)
    r.scan()
    store.db.execute("DELETE FROM store_flags WHERE name=?", (render_store.LEFTOVERS_CLEARED,))
    stale = _leftover(store, unit.label, deck.name, "a" * 64)                                   # an old key
    removed = _leftover(store, "slidemage-manual:zzz-EN-Gone:instructor:EN", deck.name, "b" * 64)   # not in the deck
    german = _leftover(store, "slidemage-manual:1jh-EN-Title-Slide:instructor:DE", deck.name, "c" * 64)  # not swept
    off = _leftover(store, "slidemage-manual-copy:zzz-EN-Gone:instructor:EN", "slidemage-manual-copy", "d" * 64)
    shared = _leftover(store, "slidemage-manual:zzz-EN-Gone:during-course:EN", deck.name, "e" * 64)
    store.link_decks(shared, ["slidemage-manual-copy"])                     # also a render of the deck switched off
    no_deck = _leftover(store, "-:zzz-EN-Gone:instructor:EN", "", "9" * 64)
    r.scan()
    assert not store._exists(stale) and not store._exists(removed)
    assert all(store._exists(name) for name in (german, off, shared, no_deck))
    assert _keys_of(store, unit.label) == [current]
    assert store.flag(render_store.LEFTOVERS_CLEARED)
    later = _leftover(store, "slidemage-manual:zzz-EN-Other:instructor:EN", deck.name, "8" * 64)
    r.scan()
    assert store._exists(later)                         # once per store: after that, only by label, when stored


# -- the double renders stop (docs/plans/render-store-cleanup.md, step 3) ----------------------------------------------


def _one_pass(r, label):
    """Render what a scan plans for `label`, as the sweep would; returns how many units it planned."""
    planned = [unit for _, unit in r.scan() if unit.label == label]
    for unit in planned:
        render_unit(r, unit)
    return len(planned)


def test_a_slide_called_twice_with_one_key_has_nothing_outstanding_after_one_pass(project, store, raster):
    # Two \slidestep calls of one slide in one view: one key, two page numbers. Each render was out of step in its
    # page number for the other call, so each pass rendered it again, for ever, with the status at 100 %.
    tex = FakeTeX(project, pages=1)
    r = make(project, store, raster, tex=tex)
    deck = deck_named(r, "slidemage-manual")
    twins = [u for u in background_renders.deck_units(project, deck, "instructor", "EN") if u.id_slug == "1mu-EN-Slidestep-Demo"]
    assert len(twins) == 2 and twins[0].frame_number != twins[1].frame_number
    assert r.resolver.fast_key(twins[0]) == r.resolver.fast_key(twins[1])
    label = twins[0].label
    assert _one_pass(r, label) >= 1
    rendered = len(tex.calls)
    for _ in range(3):
        assert _one_pass(r, label) == 0
    assert len(tex.calls) == rendered
    assert store.find(r.resolver.fast_key(twins[0])) is not None          # one render, whichever page number it has
    states = sorted(r.resolver.lookup(u).state.value for u in twins)
    assert states == sorted([Freshness.FRESH.value, Freshness.FRESH_NUMBERING_DIFFERS.value])


def test_a_deck_the_scan_could_not_read_keeps_all_its_renders(project, store, raster, monkeypatch):
    r = make(project, store, raster)
    deck = deck_named(r, "slidemage-manual")
    units = background_renders.deck_units(project, deck, "instructor", "EN")[2:4]
    for unit in units:
        render_unit(r, unit)
    gone = _leftover(store, "slidemage-manual:zzz-EN-Gone:instructor:EN", deck.name, "f" * 64)
    real = background_renders.deck_units

    def unreadable(ctx, d, view, *args, **kwargs):
        if d.name == deck.name and view == "during-course":
            raise ValueError("cannot read the deck now")
        return real(ctx, d, view, *args, **kwargs)

    monkeypatch.setattr(background_renders, "deck_units", unreadable)
    before = store.count()
    for unit in units:
        _edit(unit.source_path)
    r.scan()
    assert store.count() == before and store._exists(gone)          # neither the scan nor the one-off clearing
    assert not store.flag(render_store.LEFTOVERS_CLEARED)           # left for a scan that reads every deck
    for unit in units:
        render_unit(r, unit)
        assert _keys_of(store, unit.label) == [r.resolver.fast_key(unit)]  # put clears the superseded key
    monkeypatch.setattr(background_renders, "deck_units", real)
    r.scan()
    assert not store._exists(gone) and store.flag(render_store.LEFTOVERS_CLEARED)
    assert all(_keys_of(store, u.label) == [r.resolver.fast_key(u)] for u in units)


def test_saving_the_captured_text_is_a_store_hit_without_tex(project, store, raster, monkeypatch):
    from slidemage import preview_requests, preview_target

    r = make(project, store, raster)
    deck = deck_named(r, 'slidemage-manual')
    unit = background_renders.deck_units(project, deck, 'instructor', 'EN')[0]
    target = preview_target.PreviewTarget(project, unit.macro, unit.id_slug, unit.version, unit.conditions,
                                         None, unit.frame_number, unit.preamble_text, deck=deck)
    text = unit.source_path.read_text(encoding='utf-8') + '\n% captured unsaved text\n'
    builds = []
    monkeypatch.setenv('SLIDEMAGE_PREVIEW_FORMAT', '0')

    def compile(command, *, jobname, outdir, **kwargs):
        wrapper = next(arg for arg in command if str(arg).endswith('.tex'))
        assert text in Path(wrapper).read_text(encoding='utf-8')
        builds.append(command)
        pdf = outdir / (jobname + '.pdf')
        with pymupdf.open() as doc:
            doc.new_page().insert_text((20, 40), 'captured unsaved text')
            doc.save(pdf)
        (outdir / (jobname + '.fls')).write_text(f'PWD {project.decks_dir}\n')
        return compiler.Build(0, pdf, outdir / (jobname + '.log'), 'clean compile', False)

    monkeypatch.setattr(compiler, 'run_latexmk', compile)
    pending = r.renders.request(target, text, 'instructor', 'EN', lambda _: None)
    # A later disk revision cannot change what this request compiles or keys.
    unit.source_path.write_text('a different saved revision', encoding='utf-8')
    pending.wait()
    key = r.resolver.fast_key(unit, text)
    assert store.find(key) is not None and len(builds) == 1
    r.renders.close()
    r.renders = preview_requests.RenderService()
    r.renders._background = r
    unit.source_path.write_text(text, encoding='utf-8')
    assert r.resolver.lookup(unit).final
    saved = r.renders.request(target, text, 'instructor', 'EN', lambda _: None, saved=True)
    saved.wait()
    assert saved.metrics['cache_hit'] and len(builds) == 1
    assert render_unit(r, unit) == key
    r.stop()


def test_a_render_stays_current_when_the_bundled_framework_moves(project, store, raster, tmp_path, monkeypatch):
    # a one-file build unpacks the framework into a new temporary folder at every start
    from slidemage import project as projects

    monkeypatch.delenv("SLIDEMAGE_LATEX")
    first, second = tmp_path / "_MEI1" / "latex", tmp_path / "_MEI2" / "latex"
    shutil.copytree(projects.template_dir("latex"), first)
    monkeypatch.setattr(projects, "template_dir", lambda name: first)

    class TeX(FakeTeX):
        def __call__(self, unit, cancel):
            pdf = super().__call__(unit, cancel)
            pdf.with_suffix(".inputs.json").write_text(json.dumps([str(unit.source_path),
                                                                   str(first / "SlideMage_base.tex")]))
            return pdf

    r = make(project, store, raster, tex=TeX(project))
    unit = batch_units(project, r, 1)[0]
    render_unit(r, unit)
    shutil.move(first, second)
    monkeypatch.setattr(projects, "template_dir", lambda name: second)
    assert r.resolver.lookup(unit, strict=True).usable

