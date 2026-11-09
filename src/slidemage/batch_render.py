# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Captured preview planning and one cancellable batch routine for every producer."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import shutil
import tempfile
import threading
import time
from pathlib import Path

from . import busy, deck_context, deck_outline, preview_build, preview_raster_client, preview_target, render_key, slide_language, slide_preview, slide_snapshot, slide_templates
from .deck_editor import VIEWS
from .preview_requests import PrebuiltRender, PreviewRequest, PreviewResult, RenderOptions, SourceRevision

ALL_PAGES = 100000


def eligible(spec) -> bool:
    """Whether a request's render can be one slide of a document of several: a whole, visible slide of a deck in
    its plain editor-style render, that needs nothing of the deck around it (a contents or agenda slide would show its
    links on every slide of the document)."""
    options, target = spec.options, spec.target
    return options.saved and not (target.hidden or target.needs_context or spec.capture_error or options.presenter or options.mode != 'slide'
                or options.overlay is not None or deck_context.reasons(spec.revision.text))


def groups(service, candidates, size: int) -> list[list]:
    """The documents to compile for `candidates`, [(key, request)] in plan order: the eligible requests the service
    finds no verified preview of (all, when forced), `size` at most per document, of one view, language and preamble, and
    one per bare slide id (the pages of a repeated one could not be told apart; it waits for a later document).
    A request that would be alone in its document is left out: it renders singly."""
    batches: dict[tuple, list[list]] = {}
    for key, spec in candidates:
        if size < 2 or not eligible(spec):
            continue
        try:
            if not spec.options.force:
                resolver = service._renderer(spec.target.context).resolver
                found = resolver.lookup(spec.unit, resolver.fast_key(spec.unit, spec.revision.text), strict=True)
                if found.final:
                    continue
        except Exception:  # noqa: BLE001 -- not classifiable: it renders singly
            continue
        open_ = batches.setdefault((spec.view, spec.language, spec.target.preamble_text, spec.options.all_steps), [])
        for batch in open_:
            if len(batch) < size and all(other.target.bare_id != spec.target.bare_id for _key, other in batch):
                batch.append((key, spec))
                break
        else:
            open_.append([(key, spec)])
    return sorted((batch for open_ in batches.values() for batch in open_ if len(batch) > 1),
                  key=lambda batch: batch[0][0])


def build(service, batch: list, cancel=None, log=None) -> dict:
    """Compile the requests of `batch` (one of `groups`') in one document and split it: {key: PrebuiltRender}. The
    publication evidence is captured before the compile. Each slide's dependencies are the
    files the document read that its pages depend on (render_key.unit_inputs; the preamble's text counts as the
    slide's, so a picture only the preamble names stays one). RuntimeError when the document does not compile or its
    pages are not those of its slides."""
    first = batch[0][1]
    ctx, target = first.target.context, first.target
    renderer = service._renderer(ctx)
    evidence = {key: renderer.resolver.capture(spec.unit, spec.revision.text) for key, spec in batch}
    slides = [(spec.target.id_slug, spec.revision.text, spec.target.frame_number, None if spec.options.all_steps else spec.target.steps, spec.target.version,
               spec.target.macro in ('omitslide', 'omitslideversion'), spec.target.macro == 'slidefinal' and not spec.options.all_steps)
              for _key, spec in batch]
    pdf = slide_preview.render_slide_texts_to_pdf(ctx, slides, first.view, first.language.lower(), target.preamble_text,
                                                  log=log, cancel=cancel, all_steps=first.options.all_steps,
                                                  workspace=renderer.store.work_dir if getattr(cancel, 'low_priority', False) else None)
    folders, built = [], {}
    try:
        texts = preview_raster_client.read_document(pdf, 'pdf', 1, ALL_PAGES)['texts']
        runs = slide_snapshot.batch_runs(texts, [spec.target.bare_id for _key, spec in batch])
        inputs = [Path(name) for name in json.loads(pdf.with_suffix('.inputs.json').read_text())]
        captured = {spec.target.source_path: spec.revision.text + (spec.target.preamble_text or "")
                    for _key, spec in batch}
        for (key, spec), pages in zip(batch, runs):
            preview_build.check_cancel(cancel)
            folders.append(Path(tempfile.mkdtemp(prefix=preview_build.RENDER_FOLDER_PREFIX)))
            own = folders[-1] / f'{spec.target.id_slug}.pdf'
            preview_raster_client.read_document(pdf, 'extract_pages', pages[0] + 1, len(pages), out=own)
            files = render_key.unit_inputs(ctx, inputs, spec.target.source_path, captured)
            built[key] = PrebuiltRender(own, map(str, files))
            built[key].evidence = evidence[key]
        return built
    except BaseException:
        for folder in folders:
            shutil.rmtree(folder, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(pdf.parent, ignore_errors=True)


@dataclass(frozen=True)
class BatchProgress:
    view: str
    index: int
    total: int
    status: str
    done: int = 0       # how many requests had finished: several run at once, so `index` is not that


def render_batch(service, requests, *, cancel=None, progress=None, publish=None, log=None, workers=None,
                 may_add=None, batch_size=1):
    """Render captured requests in order, preserving partial results and cancellation.

    Compatible saved requests share documents of at most `batch_size`; a failed document falls back to single
    service requests. Independent jobs share parallel_runs' worker and CPU budget.
    """
    from . import parallel_runs

    requests = tuple(requests)
    results: list = [None] * len(requests)
    notify_lock = threading.Lock()
    finished = {"n": 0}

    def notify(event, finishing=False):
        with notify_lock:
            if finishing:
                finished["n"] += 1
            event = replace(event, done=finished["n"])
            if progress is not None:
                try:
                    progress(event)
                except Exception:  # noqa: BLE001 -- observers do not own batch lifetime
                    pass

    def wait_turn():
        while 'foreground preview' in busy.reasons():
            if cancel is not None and cancel.is_set():
                return
            time.sleep(parallel_runs.POLL)

    def unit_task(index, spec, prebuilt=None, announced=False):
        def run():
            try:
                if len(requests) > 1:
                    wait_turn()
                if spec.target.hidden and not spec.options.presenter:
                    result = PreviewResult(spec, status='hidden')
                elif cancel is not None and cancel.is_set():
                    result = PreviewResult(spec, status='cancelled', error='Preview cancelled')
                elif spec.capture_error is not None:
                    result = PreviewResult(spec, status='failed', error=spec.capture_error)
                else:
                    if not announced:
                        notify(BatchProgress(spec.view, index, len(requests), 'rendering'))
                    try:
                        request = service.request(spec.target, spec.revision.text, spec.view, spec.language,
                                                  log or (lambda _: None), spec=spec,
                                                  **({'prebuilt': prebuilt} if prebuilt is not None else {}))
                        artifact = request.wait(cancel)
                        result = (replace(request.preview_result, request=spec) if request.preview_result else
                                  PreviewResult.from_artifact(spec, artifact))
                        if publish is not None and result.status in ('rendered', 'cached'):
                            try:
                                result = replace(result, publication_status=publish(result))
                            except Exception as exc:  # noqa: BLE001 -- retain the valid artifact
                                result = replace(result, publication_status='failed', error=str(exc))
                    except Exception as exc:  # noqa: BLE001 -- a failed view must not lose the others
                        stopped = cancel is not None and cancel.is_set()
                        result = PreviewResult(spec, status='cancelled' if stopped else 'failed', error=str(exc))
                results[index - 1] = result
                notify(BatchProgress(spec.view, index, len(requests), result.status), finishing=True)
            finally:
                if prebuilt is not None and not prebuilt.used:      # cancelled, or another request of it took over
                    shutil.rmtree(prebuilt.pdf.parent, ignore_errors=True)
        return run

    def batch_task(batch):
        """Compile one document, then record each slide as its own request."""
        def run():
            built = {}
            for index, spec in batch:
                notify(BatchProgress(spec.view, index, len(requests), 'rendering'))
            try:
                wait_turn()
                if cancel is None or not cancel.is_set():
                    built = build(service, batch, cancel, log)
            except Exception:  # noqa: BLE001 -- whatever went wrong, the requests render singly
                pass
            for index, spec in batch:
                unit_task(index, spec, built.pop(index, None), announced=True)()
        return run

    batches = ([] if cancel is not None and cancel.is_set() else
               groups(service, list(enumerate(requests, 1)), batch_size))
    batched = {index for batch in batches for index, _spec in batch}
    tasks = ([batch_task(batch) for batch in batches]
             + [unit_task(index, spec) for index, spec in enumerate(requests, 1) if index not in batched])
    if getattr(cancel, 'low_priority', False):
        for task in tasks:       # the sweep's scheduler already holds a worker and budget place
            task()
    elif len(requests) == 1:
        tasks[0]()                            # a single tool request may join the pane's foreground build
    else:
        parallel_runs.run_all(tasks, workers=workers, may_add=may_add or parallel_runs.cpu_has_room, cancel=cancel)
    for index, original in enumerate(requests, 1):          # a unit that never started (cancelled first)
        if results[index - 1] is None:
            results[index - 1] = PreviewResult(original, status='cancelled', error='Preview cancelled')
    return tuple(results)


@dataclass(frozen=True)
class DeckRefreshResult:
    scope: str
    language: str
    results: tuple

    @property
    def total(self) -> int:
        return len(self.results)

    def count(self, status: str) -> int:
        return sum(result.status == status for result in self.results)

    @property
    def failed(self) -> tuple:
        return tuple(result for result in self.results if result.status in ('failed', 'cancelled')
                     or result.publication_status in ('failed', 'superseded'))


@dataclass
class DeckResult:
    """The AI tools' slide-level summary and per-request outcomes."""
    refreshed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    error: str = ""
    details: DeckRefreshResult | None = None

    def __bool__(self) -> bool:
        return not self.failed

    @classmethod
    def from_results(cls, results, scope, language):
        details = DeckRefreshResult(scope, language, tuple(results))
        failures = {r.request.target.id_slug for r in details.failed}
        slugs = sorted({r.request.target.id_slug for r in details.results})
        return cls(refreshed=[slug for slug in slugs if slug not in failures],
                   failed=[slug for slug in slugs if slug in failures],
                   error=next((r.error for r in details.results if r.error), ''), details=details)


def plan_project(renderer) -> tuple:
    """Capture the decks, views and languages the sweep prepares, in its priority order."""
    from . import background_renders

    requests = []
    templates = set(slide_templates.available_templates(renderer.ctx.root))
    for deck in renderer.ordered_decks():
        for language in renderer.languages_for(deck):
            for view in renderer.versions_for(deck):
                ready = background_renders._Once(lambda: deck_context.in_deck_ready(renderer.ctx, deck, view, language))
                units = background_renders.deck_units(renderer.ctx, deck, view, language, context_ready=ready)
                requests.extend(renderer.request_for(unit) for unit in units if unit.template in templates)
    return tuple(requests)


def plan_deck(ctx, deck, *, scope='all', selected_view='instructor', language='EN',
              force=False) -> tuple[PreviewRequest, ...]:
    """Capture saved sources for every occurrence, including hidden and pinned calls."""
    if scope not in ('selected', 'all'):
        raise ValueError("scope must be 'selected' or 'all'")
    if selected_view not in VIEWS:
        raise ValueError(f'Unknown course view: {selected_view}')
    views = VIEWS if scope == 'all' else (selected_view,)
    links = slide_language.links_for(ctx)
    slots = {view: deck_outline.resolve_slots(ctx, deck, view, language, links=links) for view in views}
    instructor_frames = {row.key: row.frame_number for row in
                         deck_outline.resolve_slots(ctx, deck, 'instructor', language, links=links)}
    revisions: dict[Path, SourceRevision] = {}
    errors: dict[Path, str] = {}
    requests = []
    for index in range(max((len(rows) for rows in slots.values()), default=0)):
        for view in views:
            if index >= len(slots[view]):
                continue
            row = slots[view][index]
            call = row.slot.call  # translated/pinned call chosen for this language
            target = preview_target.for_call(ctx, deck, call, row.position, frame_number=row.frame_number,
                                             hidden=row.hidden)
            target = replace(target, occurrence_key=row.key, presenter_frame_number=instructor_frames.get(row.key))
            source = target.source_path.resolve()
            if source not in revisions:
                try:
                    revisions[source] = SourceRevision.capture(source)
                except OSError as exc:
                    revisions[source] = SourceRevision.capture(source, '')
                    errors[source] = str(exc)
            requests.append(PreviewRequest(target, revisions[source], view, language,
                                           RenderOptions(saved=True, force=force),
                                           errors.get(source)))
    return tuple(requests)


def plan_slide(ctx, deck, path, view, language, *, selected_view="instructor",
               occurrence_key=None, options=RenderOptions(), read_source=None):
    """Capture each distinct source once for a selected/all-view request.

    `read_source` may return an editor buffer; pinned calls always use their own source path.
    """
    revisions, capture_errors, result = {}, {}, []
    for canonical in preview_target.requested_views(view, selected_view):
        row = (deck_outline.slide_row(ctx, deck, slide_language.bare_id(path.name), canonical, language,
                                      occurrence_key=occurrence_key) if deck is not None else None)
        if row is not None and (row.call.source_filename == path.name or '-current.tex' in path.name):
            target = preview_target.for_call(ctx, deck, row.call, row.position, frame_number=row.frame_number,
                                             occurrence_key=row.key, hidden=row.hidden)
        else:
            target = preview_target.for_path(ctx, path)
        if target is None:
            raise ValueError(f"{path.name} is not a slide file")
        source = target.source_path.resolve()
        if source not in revisions:
            try:
                text = read_source(source) if read_source is not None else None
                revisions[source] = SourceRevision.capture(source, text)
            except OSError as exc:
                # Visibility is resolvable without a slide file. Record capture
                # failures per view so other views can still complete normally.
                revisions[source] = SourceRevision.capture(source, '')
                capture_errors[source] = str(exc)
        result.append(PreviewRequest(target, revisions[source], canonical, language, options,
                                     capture_errors.get(source)))
    return tuple(result)
