# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared captured-text builds for the Preview and sweep, with guarded store publication."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from contextlib import ExitStack
import json
import logging
from pathlib import Path
import threading
import shutil
import time
import weakref

from . import diagnostics
from . import busy, compiler, deck_context, preview_build, preview_raster_client, preview_target, render_key, render_lookup, render_store, slide_snapshot, timing
from .fileio import text_sha256
from .preview_metrics import PreviewMetrics

_log = logging.getLogger("slidemage.preview")

TIMEOUT = 300


@dataclass(frozen=True)
class SourceRevision:
    path: Path
    text: str
    content_hash: str
    mtime_ns: int | None

    @classmethod
    def capture(cls, path: Path, text: str | None = None):
        if text is None:
            text = path.read_text(encoding="utf-8")
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            mtime = None
        return cls(path.resolve(), text, text_sha256(text), mtime)


@dataclass(frozen=True)
class RenderOptions:
    saved: bool = False
    presenter: bool = False
    mode: str = "slide"
    overlay: int | None = None
    force: bool = False
    all_steps: bool = False      # every reveal step, whatever the call restricts (the reveal-step bar)


@dataclass(frozen=True)
class PreviewRequest:
    target: preview_target.PreviewTarget
    revision: SourceRevision
    view: str
    language: str
    options: RenderOptions = RenderOptions()
    capture_error: str | None = None

    def __post_init__(self):
        preview_target.requested_views(self.view)
        if self.view == "all":
            raise ValueError("A preview request must have one canonical view")
        object.__setattr__(self, 'language', self.language.upper())

    @property
    def unit(self):
        return render_key.unit_for(self.target, self.view, self.language)

    @property
    def complete(self):
        options = self.options
        if (self.capture_error or self.target.hidden or options.presenter or options.mode != 'slide'
                or options.overlay is not None):
            return False
        if options.all_steps:
            return True
        from .reveal_steps import scan_slide
        return (self.target.macro != 'slidefinal'
                and not (self.target.macro == 'slidestep' and self.target.steps)
                and scan_slide(self.revision.text).own_frame_spec is None)


@dataclass(frozen=True)
class PreviewResult:
    request: PreviewRequest
    status: str = "rendered"
    pdf: Path | None = None
    page_images: tuple = ()
    publication_status: str = "unpublished"
    error: str | None = None
    display_png: bytes | Path | None = None
    secondary_png: bytes | None = None
    _artifact_owner: object | None = field(default=None, repr=False, compare=False)

    @classmethod
    def from_artifact(cls, request, artifact):
        return cls(request, pdf=artifact[0], display_png=artifact[1],
                   page_images=tuple(artifact[2]), secondary_png=artifact[3])

    def artifact(self):
        return self.pdf, self.display_png, self.page_images, self.secondary_png


class PrebuiltRender:
    """A slide's PDF made by a document of several slides (batch_render): RenderService.request records it like a
    render of its own. `dependencies` are the files its pages depend on. `used` tells the maker whether the request
    took it (a request already in flight does not)."""
    def __init__(self, pdf: Path, dependencies):
        self.pdf, self.dependencies = pdf, tuple(dependencies)
        self.used = False
        self.evidence = None


class RenderRequest:
    """One shared build. `done` means delivered and recorded; `delivered` is set earlier, as soon as a fresh
    render's pixels exist, and the worker then records it in the store.

    wait() returns when the request is done: `preview_result` and `result` are final. A consumer
    that needs only pixels (the Preview pane) calls wait(pixels_only=True): it returns at delivery with the
    image (raw when a pane is waiting at rasterization), without lending the temp PDF.
    """
    def __init__(self, work, finished):
        self.cancel = compiler.CancelToken()
        self.done = threading.Event()
        self.delivered = threading.Event()
        self.result = None
        self.error = None
        self.metrics = None
        self.spec = None
        self.preview_result = None
        self._store_record = None
        self._artifact_owner = None
        self._delivered_artifact = None     # the fresh render before it is recorded (its PDF is in the temp folder)
        self._collector = None
        self._consumers = {}
        self._work, self._finished = work, finished
        self._start_lock = threading.Lock()
        self._started = False

    def _result_of(self, artifact):
        result = PreviewResult.from_artifact(self.spec, artifact)
        return replace(result, status='cached' if self._store_record is not None else 'rendered',
                       _artifact_owner=self._artifact_owner)

    def _metrics_of(self, collector):
        metrics = collector.to_dict()
        metrics['cache_hit'] = self._store_record is not None
        metrics['compile_avoided'] = int(metrics['cache_hit'])
        return metrics

    def _run(self):
        with PreviewMetrics() as metrics:
            self._collector = metrics
            try:
                preview_build.check_cancel(self.cancel)
                self.result = self._work(self.cancel)
                if self.spec is not None:
                    self.preview_result = self._result_of(self.result)
                preview_build.check_cancel(self.cancel)
            except Exception as exc:  # noqa: BLE001 -- forwarded to every consumer
                self.error = exc
                if self._artifact_owner is not None:
                    self._artifact_owner.__exit__(None, None, None)
                self._artifact_owner = None
        self.metrics = self._metrics_of(metrics)
        if _log.isEnabledFor(logging.DEBUG) and self.spec is not None:
            _log.debug("preview %s view=%s language=%s seconds=%.2f cache_hit=%s error=%s stages=%s",
                       self.spec.target.key, self.spec.view, self.spec.language, self.metrics.get("seconds", 0),
                       self.metrics.get("cache_hit"), type(self.error).__name__ if self.error else None,
                       {k: round(v, 2) for k, v in self.metrics.get("stages", {}).items()})
        self._collector = None
        self._finished()
        self._work = self._finished = None
        self.delivered.set()
        self.done.set()

    def cancelled(self):
        """Whether the shared build has stopped, independent of individual waiters."""
        return self.cancel.is_set()

    def forget_unstarted(self):
        with self._start_lock:
            if not self._started and self._finished is not None:
                # Remove only the service registry entry. Another holder may
                # still start this request after a pane drops its queued job.
                self._finished()

    def wait(self, cancel=None, timeout=TIMEOUT, *, pixels_only=False):
        """Attach this consumer until completion, cancellation or timeout.

        Only active waiters reserve a build; merely holding a request before
        calling wait does not prevent its last active waiter from stopping it.
        `pixels_only` returns as soon as a fresh render's pixels exist, before it is recorded in the store:
        the artifact holds only the image, `preview_result` is not final and no store record exists yet.
        The raw file may be removed once recording finishes; a caller can then wait for the settled PNG.
        """
        if pixels_only:
            busy.acquire('foreground preview')
        consumer = object()
        deadline = time.monotonic() + timeout
        with self._start_lock:
            self._consumers[consumer] = pixels_only
        try:
            with self._start_lock:
                if self.cancel.is_set() or (cancel is not None and cancel.is_set()):
                    raise RuntimeError('Preview cancelled')
                if not self._started:
                    self._started = True
                    self.cancel.low_priority = getattr(cancel, 'low_priority', False)
                    threading.Thread(target=self._run, daemon=True).start()
            event = self.delivered if pixels_only else self.done
            while True:
                if self.cancel.is_set() or (cancel is not None and cancel.is_set()):
                    raise RuntimeError('Preview cancelled')
                if event.wait(.05):
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError('Preview timed out')
            if self.cancel.is_set() or (cancel is not None and cancel.is_set()):
                raise RuntimeError('Preview cancelled')
            if self.error is not None:
                raise self.error
            if pixels_only and self._delivered_artifact is not None and not self.done.is_set():
                return (None, *self._delivered_artifact[1:])
            return (None, *self.result[1:]) if pixels_only else self.result
        finally:
            if pixels_only:
                busy.release('foreground preview')
            with self._start_lock:
                self._consumers.pop(consumer, None)
                if not self.delivered.is_set() and not self._consumers:    # a delivered build is only recording: let it
                    self.cancel.request_stop()
                    if not self._started and self._finished is not None:
                        self._finished()
                        self._work = self._finished = None


class RenderService:
    def __init__(self):
        self._requests = {}
        self._lock = threading.Lock()
        self._completed = weakref.WeakSet()
        self._closed = False
        self._background = None
        self._owns_background = False

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            requests = list(self._requests.values())
            self._requests.clear()
        for request in requests:
            request.cancel.request_stop()
        for owner in tuple(self._completed):
            owner.__exit__(None, None, None)
        if self._background is not None:
            preview_build.set_focus(self._background.ctx, None)
        if self._owns_background:
            self._background.store.close()

    def _renderer(self, ctx):
        from .background_renders import BackgroundRenderer
        from .render_store import RenderStore

        with self._lock:
            if self._background is None:
                self._background = BackgroundRenderer(ctx, RenderStore(ctx), raster=preview_raster_client, renders=self)
                self._owns_background = True
            elif self._background.ctx.root.resolve() != ctx.root.resolve():
                raise ValueError('A render service handles one project')
            return self._background

    def request(self, target, text, view, language, log, *, saved=False,
                presenter=False, mode='slide', overlay=None, spec=None, force=False,
                all_steps=False, prebuilt=None):
        """`prebuilt` (PrebuiltRender): the slide's PDF is made already, by a document of several slides: record it
        instead of looking it up and rendering."""
        spec = spec or PreviewRequest(target, SourceRevision.capture(target.source_path, text), view, language,
                                      RenderOptions(saved, presenter, mode, overlay, force, all_steps))
        target, text, view, language = spec.target, spec.revision.text, spec.view, spec.language
        options = spec.options
        presenter, mode, overlay = options.presenter, options.mode, options.overlay
        if target.hidden and not presenter:
            raise ValueError(f'Slide {target.id_slug} is hidden in {view}')
        renderer = self._renderer(target.context)
        unit = spec.unit
        complete = spec.complete
        key = ((replace(unit, deck=""), spec.revision.content_hash) if complete else
               (target.key, spec.revision.content_hash, view, language,
                replace(options, saved=False, force=False)), options.force)

        def work(cancel):
            store_key = renderer.resolver.fast_key(unit, text) if complete else None
            background = cancel.low_priority
            cancel.preview_focus = (target, view, language)
            in_deck = target.needs_context and (background or (
                options.saved and options.all_steps and target.deck is not None
                and deck_context.in_deck_ready(target.context, target.deck, view, language)))
            publish = complete and (not target.needs_context or in_deck)
            if background and not options.force and store_key is not None and renderer.store.failure(store_key) is not None:
                found = renderer.resolver.lookup(unit, store_key, strict=True)
                if found.state is render_key.Freshness.FAILED and not renderer.store.may_retry(found.failure):
                    if unit.label not in renderer._last_try or renderer.store.tried_last(store_key):
                        request.preview_result = PreviewResult(spec, status='failed', error=found.failure['error'])
                        raise RuntimeError(found.failure['error'])
                    renderer.store.note_last_try(store_key)
            try:
                if (prebuilt is None and not options.force and publish and store_key is not None
                        and renderer.store.find(store_key) is not None):
                    state, stored = render_lookup.select(dict(resolver=renderer.resolver, unit=unit, spec=spec), strict=True)
                    if state == 'current' and (not background or stored.get('frame_number') == unit.frame_number):
                        owner = renderer.store.pdf_copy(stored)
                        pdf = owner.__enter__()
                        request._artifact_owner = owner
                        request._store_record = stored
                        with self._lock:
                            self._completed.add(owner)
                        png = renderer.store.page(stored, stored['pages'])
                        if pdf is not None and png is not None:
                            return pdf, png, (), png
                        owner.__exit__(None, None, None)
                        request._store_record = None

                if prebuilt is not None:
                    prebuilt.used = True
                evidence = (prebuilt.evidence if prebuilt is not None else
                            renderer.resolver.capture(unit, None if in_deck else text)) if publish else None
                cancel.preview_evidence = evidence
                if prebuilt is not None:
                    pdf = prebuilt.pdf
                elif background and renderer._render is not None:
                    pdf = renderer._render(unit, cancel)
                elif in_deck:
                    pdf = renderer._render_in_deck(unit, cancel)
                else:
                    pdf = preview_target.render_text(
                        target, text, view, language, log=log,
                        presenter=presenter, mode=mode, overlay=overlay, cancel=cancel,
                        all_steps=options.all_steps, force_build=True,
                        **({'workspace': renderer.store.work_dir} if background else {}))
                if pdf.parent.name.startswith(preview_build.RENDER_FOLDER_PREFIX):
                    owner = ExitStack()
                    owner.callback(weakref.finalize(owner, shutil.rmtree, pdf.parent, ignore_errors=True))
                    request._artifact_owner = owner
                    with self._lock:
                        self._completed.add(owner)
                preview_build.check_cancel(cancel)
                with request._start_lock:
                    raw = any(request._consumers.values())
                if presenter:
                    displays, images = (None, None), ()
                elif raw:
                    with timing.span('preview.raw'):
                        displays, images = slide_snapshot.prepare_preview_images(
                            pdf, False, (slide_snapshot.FULL_SIZE[0],), raw=True)
                else:
                    displays, images = slide_snapshot.prepare_preview_images(
                        pdf, False, (slide_snapshot.FULL_SIZE[0], 1280))
                artifact = pdf, displays[0], images, None if raw else displays[1]
                request.preview_result = request._result_of(artifact)
                request.metrics = request._metrics_of(request._collector)
                request._delivered_artifact = artifact
                timing.event(target.context.root, 'preview.delivered')
                request.delivered.set()
                if presenter:
                    return artifact
                pages = []
                if evidence is not None:
                    try:
                        dependencies = (prebuilt.dependencies if prebuilt is not None
                                        else json.loads(pdf.with_suffix('.inputs.json').read_text()))
                    except (OSError, ValueError):
                        dependencies = ()
                    source = unit.source_path.resolve()
                    manifest = renderer.resolver.build_manifest([path for path in dependencies if Path(path).resolve() != source])
                    manifest.entries.append([render_key.KIND_PROJECT, source.relative_to(target.context.root).as_posix(),
                                             spec.revision.content_hash])
                    manifest.entries.sort()
                    try:
                        with timing.span('preview.pages'):
                            pages = renderer._rasterise(pdf, cancel)
                        if not pages:
                            raise RuntimeError('Render failed: the render has no pages (the slide is not typeset in this view)')
                        from .render_store import ORIGIN_BACKGROUND, ORIGIN_REVEAL
                        renderer._store_render(
                            unit, ORIGIN_BACKGROUND if background else ORIGIN_REVEAL,
                            pdf, pages, manifest, evidence)
                    except Exception as exc:
                        if background:
                            exc.preview_inputs = dependencies
                            raise
                        log(f'Preview not recorded in the store: {exc}')
                if raw:
                    with timing.span('preview.png'):
                        displays, images = slide_snapshot.prepare_preview_images(
                            pdf, False, (1280,) if pages else (slide_snapshot.FULL_SIZE[0], 1280))
                    if pages:
                        displays = (pages[-1], *displays)
                elif pages:
                    displays = (pages[-1], *displays[1:])
                return pdf, displays[0], images, displays[1]
            except Exception as exc:
                if complete and store_key is not None and not cancel.is_set():
                    kind = getattr(exc, 'kind', None) or (render_store.DETERMINISTIC if str(exc).startswith('Render failed')
                                                       else render_store.TRANSIENT)
                    inputs = list(getattr(exc, 'preview_inputs', ()))
                    manifest = renderer.resolver.build_manifest(inputs).entries
                    source = unit.source_path.relative_to(target.context.root).as_posix()
                    manifest = [entry for entry in manifest if entry[:2] != [render_key.KIND_PROJECT, source]]
                    manifest.append([render_key.KIND_PROJECT, source, spec.revision.content_hash])
                    manifest += [renderer.resolver.missing_input_entry(name) for name in set(getattr(exc, 'missing_inputs', ()))]
                    renderer.store.record_failure(store_key, kind, str(exc), manifest)
                    with renderer._working_lock:
                        if renderer._current is None or store_key in renderer._current.keys:
                            renderer._failure_keys.add(store_key)
                raise

        def finished():
            with self._lock:
                if self._requests.get(key) is request:
                    del self._requests[key]

        with self._lock:
            if self._closed:
                raise RuntimeError('Preview service closed')
            request = self._requests.get(key)
            if request is None or request.cancel.is_set():
                diagnostics.event(_log, "preview requested", target=spec.target.key, view=spec.view,
                                  language=spec.language, force=options.force)
                request = RenderRequest(work, finished)
                request.spec = spec
                self._requests[key] = request
            return request
