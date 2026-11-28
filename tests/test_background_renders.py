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
from dataclasses import replace
from pathlib import Path

import pymupdf
import pytest

from conftest import EXAMPLE
from slidemage import background_renders, compile_records, compiler, deck_outline, deck_scan, render_evidence, render_store, slide_preview, slide_versioning
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
    """Produce a preview PDF and recorder inputs, or raise the configured error for a slide."""

    def __init__(self, project, pages=3, inputs=()):
        self.project, self.pages, self.calls, self.fail, self.inputs = project, pages, [], {}, list(inputs)

    def __call__(self, unit, cancel):
        self.calls.append((unit.id_slug, unit.view, unit.language))
        if unit.id_slug in self.fail:
            raise RuntimeError(self.fail[unit.id_slug])
        folder = Path(tempfile.mkdtemp(prefix="slidemage_preview_"))
        pdf = self.last_pdf = folder / (unit.id_slug + ".pdf")
        with pymupdf.open() as doc:
            for number in range(self.pages):
                doc.new_page(width=453, height=255).insert_text((20, 40), f"{unit.id_slug} step {number + 1}")
            doc.save(pdf)
        pdf.with_suffix(".inputs.json").write_text(json.dumps([str(unit.source_path), *map(str, self.inputs)]), encoding="utf-8")
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
                                  engine_fp=lambda: "LuaHBTeX 1.22|Windows", render_override=tex or FakeTeX(project), raster=raster, **kwargs)
    renderer.test_decks = decks
    return renderer


def render_unit(renderer, unit):
    spec = renderer._sweep_request(unit)          # the request as the sweep builds it
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
        renderer.store.link_decks(stored['key'], [unit.deck])
        return stored['key']
    return None


def deck_named(renderer, name):
    return next(d for d in renderer.test_decks if d.name == name)


def limit_to_instructor(renderer, deck, monkeypatch):
    monkeypatch.setattr(renderer, "ordered_decks", lambda: [deck])
    monkeypatch.setattr(renderer, "versions_for", lambda _deck: ["instructor"])
    monkeypatch.setattr(renderer, "languages_for", lambda _deck: ["EN"])


def manual_units(project, renderer, view="instructor", *, start_at=None, context_ready=None):
    deck = deck_named(renderer, "slidemage-manual")
    return background_renders.deck_units(project, deck, view, "EN", start_at, context_ready)


def test_units_of_a_deck_follow_deck_order_and_start_at_the_last_slide(project, store, raster):
    r = make(project, store, raster)
    deck = deck_named(r, "slidemage-manual")
    units = manual_units(project, r)
    assert len(units) > 20 and units[0].frame_number == 1 and all(u.view == "instructor" for u in units)
    middle = units[10].id_slug
    bare = middle.split("-")[0]
    wrapped = manual_units(project, r, start_at=bare)
    assert wrapped[0].id_slug == middle and [u.id_slug for u in wrapped] == [u.id_slug for u in units[10:] + units[:10]]
    for view in VIEWS:
        units = background_renders.deck_units(project, deck, view, "EN", context_ready=lambda: True)
        rows = deck_outline.outline_rows(project, deck, view, "EN")
        visible = [row for row in rows if not row.hidden and (project.slides_dir / row.call.source_filename).is_file()]
        assert [(u.id_slug, u.frame_number) for u in units] == [(row.call.id_slug, row.frame_number) for row in visible]
        # The manual repeats \slidestep calls, with hidden steps between the visible ones.
        assert any(row.frame_number != row.position for row in visible)


def test_inserting_a_slide_plans_only_the_new_numbers_and_units(project, store, raster):
    tex = FakeTeX(project, pages=1)
    r = make(project, store, raster, tex=tex)
    deck = deck_named(r, "slidemage-manual")
    body = "\\slide{1cx-EN-Slide-IDs}\n\\end{document}\n"
    deck.path.write_text(deck.preamble_text + "\n" + body, encoding="utf-8")
    r.test_decks[:] = [deck_scan.read_deck(deck.path)]
    for _, unit in r.scan():
        render_unit(r, unit)
    assert r.scan() == [] and r.progress.fresh == 3

    inserted = "zzz-EN-Inserted"
    (project.slides_dir / f"{inserted}-current.tex").write_text("\\begin{frame}New\\end{frame}\n", encoding="utf-8")
    deck.path.write_text(deck.preamble_text + f"\n\\slide{{{inserted}}}\n" + body, encoding="utf-8")
    r.test_decks[:] = [deck_scan.read_deck(deck.path)]
    plan = r.scan()
    assert len(plan) == 3 and {u.id_slug for _, u in plan} == {inserted}
    assert r.progress.total == 6 and r.progress.fresh == r.progress.left == 3
    moved = next(u for u in manual_units(project, r) if u.id_slug != inserted)
    assert r.resolver.lookup(moved).state is Freshness.FRESH_NUMBERING_DIFFERS
    r._count_fresh(moved)
    assert r.progress.fresh == 3
    r._count_fresh(plan[0][1])
    assert r.progress.fresh == 4
    render_unit(r, moved)
    assert r.resolver.lookup(moved).state is Freshness.FRESH and len(tex.calls) == 4 and store.count() == 3


def test_new_project_names_only_stale_renders_they_can_affect(project, store, raster):
    picture = project.root / "sources/picture.png"
    picture.parent.mkdir()
    picture.write_bytes(b"picture")
    r = make(project, store, raster, tex=FakeTeX(project, pages=1, inputs=[picture]))
    unit = manual_units(project, r)[0]
    render_unit(r, unit)
    assert r.resolver.lookup(unit).state is Freshness.FRESH
    fresh = ("sources/paper.pdf", "decks/NewDeck.tex", "decks/archive/Old.tex", "notes.txt",
             "sources/SlideMage_project_macros.tex")
    stale = ("SlideMage_project_macros.tex", "decks/SlideMage_project_macros.tex", "references.bib",
             "decks/references.bib", "sources/picture.pdf", "picture.pdf")
    for names, state in ((fresh, Freshness.FRESH), (stale, Freshness.STALE)):
        for name in names:
            added = project.root / name
            added.parent.mkdir(parents=True, exist_ok=True)
            added.write_text("new candidate", encoding="utf-8")
            assert r.resolver.lookup(unit, strict=True).state is state, name
            added.unlink()


@pytest.mark.parametrize("repair", ["edit dependency", "restore missing input"])
def test_failed_background_build_tracks_its_own_inputs_and_retries_after_repair(project, store, raster, monkeypatch, repair):
    r = make(project, store, raster)
    r.render_override = None
    monkeypatch.setenv("SLIDEMAGE_PREVIEW_FORMAT", "0")
    unit = manual_units(project, r)[0]
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


def test_the_planner_orders_decks_and_views_and_counts_scheduled_renders(project, store, raster, monkeypatch):
    tex = FakeTeX(project)
    r = make(project, store, raster, tex=tex)
    manual, copy = (deck_named(r, name) for name in ("slidemage-manual", "slidemage-manual-copy"))
    clock = [100.0]
    store._clock = lambda: clock[0]
    store.touch_deck(manual.name, opened=True)
    clock[0] += 1
    store.touch_deck(copy.name, opened=True)
    clock[0] += 1
    store.touch_deck(manual.name, slide="tnb")
    assert r.ordered_decks()[0] == copy
    r.plugin_soon = lambda deck: deck == manual
    assert r.ordered_decks()[:2] == [manual, copy]
    monkeypatch.setattr(r, "_open_deck", lambda: copy)
    assert r.ordered_decks()[:2] == [copy, manual]
    monkeypatch.setattr(r, "_open_deck", lambda: manual)
    background_renders.app_settings.set(project, background_renders.DECKS_OFF_KEY, [copy.name])

    plan = r.scan()
    ranks, units = zip(*plan, strict=True)
    assert list(ranks) == sorted(ranks)
    assert list(dict.fromkeys(unit.view for unit in units if unit.deck == manual.name)) == list(VIEWS)
    assert copy not in r.ordered_decks() and r.progress.deck(copy.name).off
    assert all(unit.deck != copy.name for unit in units)
    assert r.progress.total == r.progress.left == len(plan)

    r.gate.last_input = 999.0
    r.tick()
    assert r.scheduler.pending() == 0 and r.progress.paused_because == "you are working"
    r.gate.last_input = 0.0
    r.tick()
    assert r.scheduler.pending(P_IDLE) == background_renders.QUEUE_AHEAD and r.progress.paused_because is None
    assert not tex.calls
    first = r.scheduler.jobs(P_IDLE)[0].payload[0][0]
    for _ in range(5):
        assert r.scheduler.run_next()
    assert r.progress.deck(manual.name).fresh == 5 and r.progress.left == len(plan) - 5
    assert [c[1] for c in tex.calls] == ["instructor"] * 5
    assert not tex.last_pdf.parent.exists()
    found = r.resolver.lookup(first)
    assert found.final and found.record["pages"] == 3 and store.page(found.record, 4) is None
    assert render_unit(r, first) == r.resolver.fast_key(first) and len(tex.calls) == 5
    counts = r.progress.deck(manual.name).views
    assert counts["instructor"][1] == 5 and sum(v[0] for v in counts.values()) == r.progress.deck(manual.name).total


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

    copy.archived = True
    r.deck_archived(copy)
    assert copy not in r.ordered_decks() and store.count() == 0


def test_a_slide_with_no_page_in_the_view_is_a_failure_not_an_empty_render(project, store, raster):
    r = make(project, store, raster, tex=FakeTeX(project, pages=1))
    r.rasterise = lambda pdf, cancel: []
    unit = manual_units(project, r)[0]
    with pytest.raises(RuntimeError):
        render_unit(r, unit)
    assert r.resolver.lookup(unit).state is Freshness.FAILED


@pytest.mark.skipif(shutil.which("latexmk") is None or shutil.which("lualatex") is None, reason="needs a TeX installation")
def test_a_real_background_render_creates_nothing_in_the_project_and_matches_the_foreground_render(project, store, monkeypatch):
    if not os.environ.get("SLIDEMAGE_LATEX"):
        monkeypatch.setenv("SLIDEMAGE_LATEX", str(Path(__file__).resolve().parent.parent / "latex"))
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


def _compiled_pdf(tmp_path, units, steps=2):
    """A deck PDF as a compile makes it: every slide's pages (`steps` of them) with their slide id in the footer."""
    pdf = tmp_path / "deck.pdf"
    with pymupdf.open() as doc:
        for unit in units:
            for step in range(1, steps + 1):
                page = doc.new_page(width=453, height=255)
                page.insert_text((20, 40), f"slide id: {unit.id_slug.split('-')[0]}  step {step}")
        doc.save(pdf)
    return pdf


def _record(pdf, job, units, ctx, paths=None, *, started=None):
    paths = paths or [job.deck.path, *{u.source_path for u in units}, ctx.root / "SlideMage.bib"]
    invocation = ctx.build_dir / f"{job.jobname}-test"
    invocation.mkdir(parents=True, exist_ok=True)
    (invocation / f"{job.jobname}.fls").write_text(
        "".join(f"INPUT {path}\n" for path in paths if path.is_file()), encoding="utf-8")
    (invocation / f"{job.jobname}.log").write_text("ok\n", encoding="utf-8")
    started = started if started is not None else time.time()
    env = compiler.build_env(ctx)
    inventory = render_evidence.search_inventory(ctx.root, env)
    configuration = render_evidence.digest(render_evidence.configuration_state(ctx.root, env))
    assert compile_records.write_record(ctx, job.jobname, invocation, job.deck.path, "", pdf, started, inventory, configuration,
                                        deck_path=job.deck.path)
    return compile_records.read_record(ctx.build_dir, job.jobname)


@CTIME_SEES_EDITS
def test_a_compile_with_an_input_changed_during_it_imports_nothing(project, store, raster, tmp_path):
    r = make(project, store, raster)
    deck = deck_named(r, "slidemage-manual")
    units = manual_units(project, r)[:2]
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
    # Written again now, the changed file is in the record without a hash (v0.17.17): still nothing is taken, since
    # every slide reads the bibliography.
    assert compile_records.write_record(project, job.jobname, project.build_dir / f"{job.jobname}-test",
                                        deck.path, "", pdf, record["started"], record["inventory"], record["configuration"])
    again = compile_records.read_record(project.build_dir, job.jobname)
    assert next(e for e in again["inputs"] if Path(e["path"]).name == "references.bib")["sha256"] is None
    assert r.ingest_compile(job, pdf, again) == 0 and store.count() == 0


def test_a_compile_imports_unchanged_slides_and_skips_frozen_plus_or_edited_slides(project, store, raster, tmp_path, caplog):
    r = make(project, store, raster)
    deck = deck_named(r, "slidemage-manual")
    units = manual_units(project, r)[:5]
    changed, crlf, saved, later, unchanged = units
    text = changed.source_path.read_text(encoding="utf-8")
    frozen = slide_versioning.frozen_path(changed.source_path, changed.id_slug, (1, 0, 0))
    frozen.write_text(slide_versioning.set_marker(text, (1, 0, 0)), encoding="utf-8")
    changed.source_path.write_text(slide_versioning.set_marker(text + "\nChanged content\n", (1, 0, 0), changed=True),
                                   encoding="utf-8")
    assert frozen.name in "\n".join(slide_versioning.saved_version_lines(project, deck, "EN"))
    crlf.source_path.write_bytes(crlf.source_path.read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8"))
    started = time.time()
    job = compiler.CompileJob(deck, "instructor", None)
    pdf = _compiled_pdf(tmp_path, units)
    time.sleep(0.05)
    # A mid-compile save once discarded all of a deck's previews.
    with saved.source_path.open("a", encoding="utf-8") as slide:
        slide.write("\n% saved during compile\n")
    record = _record(pdf, job, units, project, [deck.path, frozen, *[u.source_path for u in units[1:]]], started=started)
    _edit(later.source_path)
    with caplog.at_level(logging.INFO, logger="slidemage.background"):
        assert r.ingest_compile(job, pdf, record) == 2
    assert "3 its file changed during or since the compile" in caplog.text
    assert all(store.latest_for_unit(u.label) is None for u in (changed, saved, later))
    assert all(r.resolver.lookup(u).final for u in (crlf, unchanged))


def test_a_compile_finishes_full_slides_and_leaves_step_calls_for_the_sweep(project, store, raster, tmp_path):
    tex = FakeTeX(project)
    r = make(project, store, raster, tex=tex)
    deck = deck_named(r, "slidemage-manual")
    instructor = manual_units(project, r, context_ready=lambda: True)
    regular, other = manual_units(project, r)[:2]
    contents = next(u for u in instructor if "Contents" in u.id_slug)
    final = next(u for u in instructor if "Final-State" in u.id_slug)
    step = next(u for u in instructor if u.macro == "slidestep")
    assert contents.context == deck.name
    tex.fail[regular.id_slug] = "Render failed for x:\\n! Undefined control sequence."
    with pytest.raises(RuntimeError):
        render_unit(r, regular)
    assert r.resolver.lookup(regular).state is Freshness.FAILED

    student = next(u for u in manual_units(project, r, "during-course") if u.id_slug == final.id_slug)
    for view, units, steps in (("instructor", [regular, other, contents, final], 3),
                               ("during-course", [student], 1)):
        compiled = [*units, step] if view == "instructor" else units
        pdf = _compiled_pdf(tmp_path, compiled, steps)
        job = compiler.CompileJob(deck, view, None)
        assert r.ingest_compile(job, pdf, _record(pdf, job, compiled, project)) == len(units)
        for unit in units:
            found = r.resolver.lookup(unit)
            assert found.final and found.record["pages"] == steps

    skipped = r.resolver.lookup(step)
    assert not skipped.usable and not skipped.final
    assert render_unit(r, step) and r.resolver.lookup(step).final
    assert store.failure(r.resolver.fast_key(regular)) is None
    _edit(other.source_path)
    assert r.resolver.lookup(regular).usable
    _edit(regular.source_path)
    assert not r.resolver.lookup(regular).usable


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
    queued = r.scheduler.jobs(P_IDLE)
    assert len(queued) == min(background_renders.QUEUE_AHEAD, r.scheduler.workers + 2) or not r._plan

    r._plan = [((n,), unit) for n, unit in enumerate(unit for job in queued for unit in job.payload[0])]
    r._top_up()
    assert r.scheduler.jobs(P_IDLE) == queued and not r._plan


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
    r.render_override = None
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


@pytest.mark.parametrize("recovers", [False, True])
def test_a_failed_slide_gets_one_last_try_after_other_slides_render(project, store, raster, monkeypatch, recovers):
    tex = FakeTeX(project, pages=1)
    r = make(project, store, raster, tex=tex)
    deck = deck_named(r, "slidemage-manual")
    broken, other = manual_units(project, r)[:2]
    real_units = background_renders.deck_units
    monkeypatch.setattr(background_renders, "deck_units", lambda *a, **k: [u for u in real_units(*a, **k)
                                                                            if u.id_slug in (broken.id_slug, other.id_slug)])
    limit_to_instructor(r, deck, monkeypatch)
    tex.fail[broken.id_slug] = "Render failed for x:\n! Undefined control sequence."
    with pytest.raises(RuntimeError):
        render_unit(r, broken)
    assert r.resolver.lookup(broken).state is Freshness.FAILED
    plan = r.scan()
    assert [u.label for _, u in plan] == [other.label] and r.progress.deck(deck.name).failed == 1
    assert render_unit(r, broken) is None and len(tex.calls) == 1
    render_unit(r, other)
    plan = r.scan()                                              # nothing else left: one more try, on its own
    assert [u.label for _, u in plan] == [broken.label] and broken.label in r._single
    assert r.progress.deck(deck.name).failed == 0 and r.progress.left == 1
    if recovers:
        del tex.fail[broken.id_slug]
        assert render_unit(r, broken)
        assert not store.failures() and r.resolver.lookup(broken).state is Freshness.FRESH
        assert r.scan() == [] and r.progress.deck(deck.name).fresh == 2 and r.progress.failures == 0
    else:
        with pytest.raises(RuntimeError):
            render_unit(r, broken)
        assert r.scan() == [] and r.progress.deck(deck.name).failed == 1
        assert render_unit(r, broken) is None
    assert sum(call[0] == broken.id_slug for call in tex.calls) == 2
    if not recovers:
        _edit(broken.source_path)
        assert r.resolver.lookup(broken).state is not Freshness.FAILED


def test_a_slide_that_needs_its_deck_is_typeset_in_the_decks_compile_and_kept(project, store, raster, monkeypatch):
    from slidemage import deck_context
    r = make(project, store, raster)
    deck = deck_named(r, "slidemage-manual")
    limit_to_instructor(r, deck, monkeypatch)
    ready = False
    monkeypatch.setattr(deck_context, "in_deck_ready", lambda *a, **k: ready)
    without = len(r.scan())
    ready = True
    plan = r.scan()
    contextual = [u for _, u in plan if u.context]
    assert len(plan) > without and contextual and {u.label for u in contextual} <= r._single
    unit, other = contextual[0], contextual[-1]
    assert unit.context == deck.name
    assert r.resolver.fast_key(unit) != r.resolver.fast_key(replace(unit, context=""))
    asked = []

    def in_deck(ctx, the_deck, view, slide_id, id_slug, log, cancel, *, all_steps=False, language=None):
        asked.append((the_deck.name, view, id_slug, all_steps, language))
        return FakeTeX(project, pages=1)(unit, cancel) if id_slug == unit.id_slug else None

    monkeypatch.setattr(deck_context, "render_in_deck", in_deck)
    r.render_override = None
    assert render_unit(r, unit) is not None
    assert asked == [(deck.name, "instructor", unit.id_slug, True, "EN")]
    assert r.resolver.lookup(unit).state is Freshness.FRESH
    monkeypatch.setattr(deck_context, "render_in_deck", lambda *a, **k: None)
    assert other.label != unit.label
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


def test_missing_templates_block_rendering_until_they_are_found(project, store, raster, monkeypatch):
    tex = FakeTeX(project)
    r = make(project, store, raster, tex=tex)
    unit = manual_units(project, r)[0]
    with monkeypatch.context() as patch:
        patch.setattr(background_renders.slide_templates, "available_templates", lambda root: ["somewhere-else"])
        assert r.scan() == []
        counted = r.progress.deck(unit.deck)
        assert counted.blocked == counted.total > 0 and counted.left == counted.failed == 0
        assert not counted.up_to_date and unit.deck in r.progress.missing_templates[unit.template]
        assert r.progress.blocked >= counted.total and r.progress.left == 0

    tex.fail[unit.id_slug] = (f"Render failed for x:\nl.16 \\input{{SlideMage_template_{unit.template}}}\n"
                              "! Emergency stop.\n")
    with pytest.raises(RuntimeError):
        render_unit(r, unit)
    assert r.resolver.lookup(unit).state is Freshness.FAILED
    plan = r.scan()                       # the template is found now: tried again, not counted as failed
    assert unit.label in [u.label for _, u in plan]
    assert r.resolver.lookup(unit).state is not Freshness.FAILED and not r.progress.missing_templates


def _edit(path, text="\n% edited\n"):
    """Change a file as a user would, with an mtime old enough that it is not "being written"."""
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")
    old = time.time() - 60
    os.utime(path, (old, old))


def _keys_of(store, label):
    return sorted(row[0] for row in store.db.execute("SELECT key FROM renders WHERE unit=?", (label,)))


def _png():
    return pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 4, 4)).tobytes("png")


def _leftover(store, label, deck, key):
    """A render stored long ago under `key` (a key no deck uses now)."""
    meta = dict(unit=label, rendered_at=time.time() - 3600, manifest=[], tex_digest="", frame_number=1, unstable=False)
    pdf = store.root / "leftover.pdf"
    with pymupdf.open() as doc:
        doc.new_page()
        doc.save(pdf)
    return store.put(key, pdf, [_png()], meta, decks=[deck] if deck else [])


def _call_twice(project, slide="1cx-EN-Slide-IDs"):
    """The manual calls `slide` a second time, as \\slidefinal: one label, two calls, two current keys."""
    deck = project.root / "decks" / "slidemage-manual.tex"
    text = deck.read_text(encoding="utf-8").replace(f"\\slide{{{slide}}}", f"\\slide{{{slide}}}\n\t\\slidefinal{{{slide}}}")
    deck.write_text(text, encoding="utf-8")
    old = time.time() - 3600
    os.utime(deck, (old, old))


def test_a_slide_keeps_one_render_after_the_edit_is_seen_by_the_scan(project, store, raster):
    r = make(project, store, raster)
    unit = manual_units(project, r)[2]
    render_unit(r, unit)
    old_key = r.resolver.fast_key(unit)
    _edit(unit.source_path)
    r.scan()
    assert _keys_of(store, unit.label) == [old_key] and r.resolver.lookup(unit).state is Freshness.STALE
    current = render_unit(r, unit)
    assert _keys_of(store, unit.label) == [current] != [old_key]

    r.scan()
    _edit(unit.source_path)
    new = render_unit(r, unit)
    assert _keys_of(store, unit.label) == sorted([current, new])
    r.scan()
    assert _keys_of(store, unit.label) == [new]


def test_repeated_slide_calls_keep_their_current_renders_and_stop_replanning(project, store, raster):
    # One label, two current keys (a \slide and a \slidefinal of one slide): deleting by label alone would have each
    # render delete the other, for ever.
    _call_twice(project)
    tex = FakeTeX(project)
    r = make(project, store, raster, tex=tex)
    both = [u for u in manual_units(project, r) if u.id_slug == "1cx-EN-Slide-IDs"]
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

    # Repeated \slidestep calls share a key and must not re-render forever.
    twins = [u for u in manual_units(project, r) if u.id_slug == "1mu-EN-Slidestep-Demo"]
    assert len(twins) == 2 and twins[0].frame_number != twins[1].frame_number
    assert r.resolver.fast_key(twins[0]) == r.resolver.fast_key(twins[1])
    planned = [u for _, u in plan if u.label == twins[0].label]
    assert planned
    for unit in planned:
        render_unit(r, unit)
    assert len(_keys_of(store, twins[0].label)) == 1
    assert all(u.label != twins[0].label for _, u in r.scan())
    assert {r.resolver.lookup(u).state for u in twins} == {Freshness.FRESH, Freshness.FRESH_NUMBERING_DIFFERS}


def test_the_leftovers_in_a_store_are_cleared_once_and_only_what_the_scan_read(project, store, raster):
    background_renders.app_settings.set(project, background_renders.DECKS_OFF_KEY, ["slidemage-manual-copy"])
    r = make(project, store, raster)
    deck = deck_named(r, "slidemage-manual")
    unit = manual_units(project, r)[1]
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


def test_only_a_complete_scan_clears_unused_renders_failures_and_texsets(project, store, raster, tmp_path, monkeypatch):
    old_pkg, new_pkg = tmp_path / "old.cls", tmp_path / "new.cls"
    for path in (old_pkg, new_pkg):
        path.write_text("package", encoding="utf-8")
    tex = FakeTeX(project, inputs=[old_pkg])
    r = make(project, store, raster, tex=tex)
    deck = deck_named(r, "slidemage-manual")
    broken, unit = manual_units(project, r)[:2]
    render_unit(r, unit)
    old_digest = r.resolver.lookup(unit).record["tex_digest"]
    gone = _leftover(store, f"{deck.name}:zzz-EN-Gone:instructor:EN", deck.name, "f" * 64)
    store.record_failure("obsolete", render_store.DETERMINISTIC, "an old request", [])
    tex.fail[broken.id_slug] = "Render failed for x:\\n! Bad dependency."
    with pytest.raises(RuntimeError):
        render_unit(r, broken)
    real_units = background_renders.deck_units

    def unreadable(ctx, candidate, view, *args, **kwargs):
        if candidate.name == deck.name and view == "during-course":
            raise ValueError("cannot read the deck now")
        return real_units(ctx, candidate, view, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(background_renders, "deck_units", unreadable)
        _edit(unit.source_path)
        r.scan()
        assert store.count() == 2 and store._exists(gone)
        assert not store.flag(render_store.LEFTOVERS_CLEARED)
        assert store.failure("obsolete") and store.tex_files(old_digest)
        tex.inputs = [new_pkg]
        current = render_unit(r, unit)
        assert _keys_of(store, unit.label) == [current]
    current_digest = r.resolver.lookup(unit).record["tex_digest"]
    assert old_digest != current_digest and store.tex_files(old_digest)

    r.scan()
    assert not store._exists(gone) and store.flag(render_store.LEFTOVERS_CLEARED)
    assert _keys_of(store, unit.label) == [current]
    assert store.failure("obsolete") is None and store.tex_files(old_digest) is None and store.tex_files(current_digest)
    assert r.progress.failures == 1 and [f["key"] for f in r.current_failures()] == [r.resolver.fast_key(broken)]
    _edit(broken.source_path)
    r.scan()
    assert r.progress.failures == 0 and not r.current_failures() and not store.failures()


def test_saving_the_captured_text_is_a_store_hit_without_tex(project, store, raster, monkeypatch):
    from slidemage import preview_requests

    r = make(project, store, raster)
    unit = manual_units(project, r)[0]
    target = r.request_for(unit).target
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

    r = make(project, store, raster, tex=FakeTeX(project, inputs=[first / "SlideMage_base.tex"]))
    unit = manual_units(project, r)[0]
    render_unit(r, unit)
    shutil.move(first, second)
    monkeypatch.setattr(projects, "template_dir", lambda name: second)
    assert r.resolver.lookup(unit, strict=True).usable


class HangingTeX(FakeTeX):
    """A TeX that never finishes by itself: it returns only once the job was stopped."""

    def __call__(self, unit, cancel):
        self.calls.append((unit.id_slug, unit.view, unit.language))
        deadline = time.monotonic() + 20
        while not cancel.is_set() and time.monotonic() < deadline:
            time.sleep(0.02)
        raise RuntimeError("stopped")


def test_watchdog_retries_a_hung_batch_one_slide_at_a_time_and_stops_retrying(project, store, raster, monkeypatch):
    monkeypatch.setattr(background_renders, "JOB_SECONDS", 0.4)
    monkeypatch.setattr(background_renders, "UNIT_SECONDS", 0.0)
    r = make(project, store, raster, tex=HangingTeX(project, pages=1), batch=4)
    deck = deck_named(r, "slidemage-manual")
    store.touch_deck(deck.name, opened=True)
    r.tick()
    job = min(r.scheduler.jobs(P_IDLE), key=lambda job: job.order())
    labels = {unit.label for unit in job.payload[0]}
    assert len(labels) > 1
    started = time.monotonic()
    assert r.scheduler.run_next()
    assert time.monotonic() - started < 10
    assert labels <= r._slow and all(r._timeouts[label] == 1 for label in labels)
    assert not labels & r._gave_up

    r.scheduler.cancel_group(deck.name)
    r.tick()
    assert labels <= r._single
    retry = min(r.scheduler.jobs(P_IDLE), key=lambda job: job.order())
    [unit] = retry.payload[0]
    assert unit.label in labels
    assert r.scheduler.run_next()
    assert unit.label in r._gave_up
    assert all(planned.label != unit.label for _, planned in r.scan())


def test_editing_the_open_deck_replans_at_once_and_drops_the_queued_renders_of_its_old_text(project, store, raster):
    deck = deck_named(make(project, store, raster), "slidemage-manual")
    r = make(project, store, raster, open_deck=deck)
    r.tick()                                                  # the first step notes the deck file
    for key, group in (("stale-open", deck.name), ("stale-other", "slidemage-manual-copy")):
        r.scheduler.submit(key, (("x",), ()), P_IDLE, (0,), group=group)
    stat = deck.path.stat()
    os.utime(deck.path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))      # edited: another mtime
    r.tick()
    queued = {job.key for job in r.scheduler.jobs(P_IDLE)}
    assert "stale-open" not in queued and "stale-other" not in queued
