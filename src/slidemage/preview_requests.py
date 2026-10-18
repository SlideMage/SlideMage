"""In-flight preview sharing; pixels and build state keep their existing caches.

Requests own immutable source/context keys. Consumers may await the same build,
while the pane alone decides whether to publish its image and snapshots.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
import json
from pathlib import Path
import hashlib
from importlib.metadata import version, PackageNotFoundError
import threading
import shutil
import time
import weakref

from . import compiler, preview_build, preview_cache, preview_equivalence, preview_target, slide_snapshot
from .preview_metrics import PreviewMetrics

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
        return cls(path.resolve(), text, hashlib.sha256(text.encode("utf-8")).hexdigest(), mtime)


@dataclass(frozen=True)
class RenderOptions:
    footer_timestamp: bool = False
    saved: bool = False
    presenter: bool = False
    mode: str = "slide"
    overlay: int | None = None
    force: bool = False
    render_stamp: str | None = None


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


@dataclass(frozen=True)
class PreviewResult:
    request: PreviewRequest
    status: str = "rendered"
    pdf: Path | None = None
    page_images: tuple = ()
    dependencies: tuple[Path, ...] = ()
    publication_status: str = "unpublished"
    error: str | None = None
    display_png: bytes | None = None
    secondary_png: bytes | None = None
    render_stamp: str | None = None
    _artifact_owner: object | None = field(default=None, repr=False, compare=False)

    @classmethod
    def from_artifact(cls, request, artifact):
        return cls(request, pdf=artifact[0], display_png=artifact[1],
                   page_images=tuple(artifact[2]), secondary_png=artifact[3])

    def artifact(self):
        return self.pdf, self.display_png, self.page_images, self.secondary_png


def resolve_requests(ctx, deck, path, view, language, *, selected_view="instructor",
                     occurrence_key=None, options=RenderOptions(), read_source=None):
    """Capture each distinct source once for a selected/all-view request.

    `read_source` may return an editor buffer; pinned calls always use their own source path.
    """
    targets = preview_target.resolve_views(ctx, deck, path, view, language,
                                          selected_view=selected_view, occurrence_key=occurrence_key)
    revisions = {}
    capture_errors = {}
    result = []
    for canonical, target in targets:
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


def cache_identity(spec: PreviewRequest) -> dict:
    """Exclude creation time/force: a hit keeps the original PDF and its timestamp."""
    options = spec.options
    from .preview_raster import SEQUENCE_SCHEMA, SEQUENCE_DPI
    try:
        raster_version = version('pymupdf')
    except PackageNotFoundError:
        raster_version = 'unavailable'
    return json.loads(json.dumps({
        'schema': preview_cache.SCHEMA, 'root': str(spec.target.context.root.resolve()),
        'source': {'path': str(spec.revision.path), 'content_hash': spec.revision.content_hash},
        'target': spec.target.key, 'view': spec.view, 'language': spec.language,
        'raster': {'renderer': raster_version, 'sequence_schema': SEQUENCE_SCHEMA,
                   'sequence_dpi': SEQUENCE_DPI, 'full_size': slide_snapshot.FULL_SIZE,
                   'thumbnail_size': slide_snapshot.THUMB_SIZE, 'display_widths': [slide_snapshot.FULL_SIZE[0], 1280]},
        'options': {'footer_timestamp': options.footer_timestamp,
                    'presenter': options.presenter, 'mode': options.mode, 'overlay': options.overlay},
    }))


def image_group(spec: PreviewRequest, identity=None):
    """A timeless, pre-render group key, or None when equivalence is unknown."""
    if (spec.target.hidden or spec.options.presenter or spec.options.mode != 'slide'
            or spec.options.overlay is not None or spec.capture_error):
        return None
    classified = preview_equivalence.classify_views((spec,))
    decision = classified.decisions[0]
    if not decision.certain or decision.group is None:
        return None
    identity = identity or cache_identity(spec)
    key = preview_cache.digest({'classifier_group': decision.group, 'raster': identity['raster'],
                                'cache_schema': preview_cache.SCHEMA})
    return 'group-' + key, classified.evidence


class _ArtifactLease:
    """Shared by the future and immutable results, without a reference cycle."""
    def __init__(self, context):
        self._context = context
        context.__enter__()

    def close(self):
        context, self._context = self._context, None
        if context is not None:
            context.__exit__(None, None, None)

    def __del__(self):
        self.close()


class RenderRequest:
    def __init__(self, work, finished):
        self.cancel = compiler.CancelToken()
        self.done = threading.Event()
        self.result = None
        self.error = None
        self.metrics = None
        self.spec = None
        self.preview_result = None
        self._cache_entry = None
        self._artifact_lease = None
        self._delivery = None
        self._representative_identity = None
        self._representative_view = None
        self._representative_evidence = None
        self._consumers = {}
        self._work, self._finished = work, finished
        self._start_lock = threading.Lock()
        self._started = False

    def _run(self):
        with PreviewMetrics() as metrics:
            try:
                preview_build.check_cancel(self.cancel)
                self.result = self._work(self.cancel)
                if self.spec is not None:
                    self.preview_result = PreviewResult.from_artifact(self.spec, self.result)
                    if self._cache_entry is not None:
                        from dataclasses import replace
                        self.preview_result = replace(self.preview_result, status=self._cache_status,
                            dependencies=tuple(Path(path) for path in self._cache_entry.dependencies),
                            render_stamp=self._cache_entry.render_stamp, _artifact_owner=self._artifact_lease)
                preview_build.check_cancel(self.cancel)
            except Exception as exc:  # noqa: BLE001 -- forwarded to every consumer
                self.error = exc
                self.release_artifact()
        self.metrics = metrics.to_dict()
        self.metrics['cache_hit'] = self._cache_entry is not None and self._cache_status == 'cached'
        self.metrics['compile_avoided'] = int(self.metrics['cache_hit'])
        self.metrics['deduplicated_images'] = (self._cache_entry.deduplicated_images
                                                if self._cache_entry is not None and not self.metrics['cache_hit'] else 0)
        self._finished()
        self._work = self._finished = None
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

    def wait(self, cancel=None, timeout=TIMEOUT):
        """Attach this consumer until completion, cancellation or timeout.

        Only active waiters reserve a build; merely holding a request before
        calling wait does not prevent its last active waiter from stopping it.
        """
        consumer = object()
        deadline = time.monotonic() + timeout
        with self._start_lock:
            self._consumers[consumer] = cancel
        try:
            with self._start_lock:
                if self.cancel.is_set() or (cancel is not None and cancel.is_set()):
                    raise RuntimeError('Preview cancelled')
                if not self._started:
                    self._started = True
                    threading.Thread(target=self._run, daemon=True).start()
            while True:
                if self.cancel.is_set() or (cancel is not None and cancel.is_set()):
                    raise RuntimeError('Preview cancelled')
                if self.done.wait(.05):
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError('Preview timed out')
            if self.cancel.is_set() or (cancel is not None and cancel.is_set()):
                raise RuntimeError('Preview cancelled')
            if self.error is not None:
                raise self.error
            if self._delivery is not None:
                try:
                    self._delivery(self)
                except Exception:  # noqa: BLE001 -- display history cannot fail the render
                    pass  # Display history never changes a successful render.
            return self.result
        finally:
            with self._start_lock:
                self._consumers.pop(consumer, None)
                if not self.done.is_set() and not self._consumers:
                    self.cancel.request_stop()
                    if not self._started and self._finished is not None:
                        self._finished()
                        self._work = self._finished = None

    def release_artifact(self):
        lease, self._artifact_lease = self._artifact_lease, None
        if lease is not None:
            lease.close()


class _ImageConsumer:
    """A view-specific waiter for another view's shared image build.

    The underlying PDF belongs to the representative view. The adapter owns
    its request/result provenance and never exposes that foreign PDF.
    """
    def __init__(self, source: RenderRequest, spec: PreviewRequest, group=None, fallback=None,
                 require_pdf=False, delivery=None):
        self.source, self.spec = source, spec
        self.same_view = source.spec.view == spec.view
        self.done, self.cancel = threading.Event(), source.cancel
        self.error = None
        self.preview_result = None
        self._group, self._fallback = group, fallback
        self._require_pdf = require_pdf
        self._delivery = delivery
        self._settled = None
        self._fallback_request = None
        self._cancelled = False

    @property
    def metrics(self):
        return self._fallback_request.metrics if self._fallback_request is not None else self.source.metrics

    @property
    def result(self):
        return self._settled

    def cancelled(self):
        return self._cancelled or self.source.cancelled() or (
            self._fallback_request is not None and self._fallback_request.cancelled())

    def forget_unstarted(self):
        self.source.forget_unstarted()

    def wait(self, cancel=None, timeout=TIMEOUT):
        try:
            artifact = self.source.wait(cancel, timeout)
            if ((self._group is not None and image_group(self.spec) != self._group)
                    or (self._require_pdf and artifact[0] is None)):
                # A relevant rule/input changed while the representative built.
                # Obtain this consumer's own view before publishing pixels.
                exact = self._fallback_request = self._fallback()
                self._settled = exact.wait(cancel, timeout)
                self.preview_result = replace(exact.preview_result, request=self.spec) if exact.preview_result else \
                                      PreviewResult.from_artifact(self.spec, self._settled)
                return self._settled
            aliased = artifact if self.same_view else (None, *artifact[1:])
            original = self.source.preview_result
            self.preview_result = replace(original, request=self.spec, pdf=aliased[0],
                                          status='cached' if original.status == 'cached' else 'rendered') if original else \
                                  PreviewResult.from_artifact(self.spec, aliased)
            self._settled = aliased
            if self._delivery is not None:
                try:
                    self._delivery(self)
                except Exception:  # noqa: BLE001 -- display history cannot fail the render
                    pass
            return aliased
        except Exception as exc:
            self.error = exc
            self._cancelled = cancel is not None and cancel.is_set()
            raise
        finally:
            self.done.set()


class RenderService:
    def __init__(self):
        self._requests = {}
        self._lock = threading.Lock()
        self._completed = weakref.WeakSet()
        self._closed = False
        self._display_lease = None
        self._display_entry = None

    def close(self):
        with self._lock:
            self._closed = True
            requests = tuple(self._requests.values())
            self._requests.clear()
        for request in requests:
            request.cancel.request_stop()
        for request in tuple(self._completed):
            request.release_artifact()
        if self._display_lease is not None:
            self._display_lease.__exit__(None, None, None)
            self._display_lease = None

    def _retain_display(self, cache, entry, *, blocking=True):
        if self._display_entry is not None and self._display_entry.directory == entry.directory:
            return entry
        lease = cache.lease(entry, blocking=blocking)
        lease.__enter__()
        previous, self._display_lease = self._display_lease, lease
        self._display_entry = entry
        if previous is not None:
            previous.__exit__(None, None, None)
        return entry

    def cached_spec(self, spec):
        cache = preview_cache.PreviewCache(spec.target.context.root)
        identity = cache_identity(spec)
        env = compiler.build_env(spec.target.context)
        group = image_group(spec, identity)
        if group is not None:
            found = cache.group_lookup(group[0], env)
            if found is not None:
                entry, representative, _, _ = found
                self._retain_display(cache, entry)
                return replace(entry, pdf=entry.pdf if representative == spec.view else None, request_spec=spec)
        entry = cache.lookup(identity, env)
        return replace(self._retain_display(cache, entry), request_spec=spec) if entry is not None else None

    def cached_preview(self, target, text, view, language, timestamp):
        """Read-only pane lookup; no Qt objects and no compile or selection changes."""
        spec = PreviewRequest(target, SourceRevision.capture(target.source_path, text), view, language,
                              RenderOptions(timestamp, saved=True))
        return self.cached_spec(spec)

    def selected_preview(self, target, text, view, language, timestamp, *, reference=None):
        """Read-only whole-slide selection shared with the list policy."""
        from .preview_selection import select_image

        revision = SourceRevision.capture(target.source_path, text)
        specs = (PreviewRequest(target, revision, view, language, RenderOptions(timestamp, saved=True)),)
        cache = preview_cache.PreviewCache(target.context.root)
        selection = select_image(cache, specs, compiler.build_env(target.context), reference=reference)
        if selection.cache_entry is not None and selection.cache_entry.pdf is not None:
            try:
                self._retain_display(cache, selection.cache_entry, blocking=False)
            except OSError:
                selection = replace(selection, pdf=None)  # image bytes remain usable
        return selection

    def remember_group_alias(self, spec, *, observed_at=None):
        """Record a forced batch's locally reused image for its requested view."""
        group = image_group(spec)
        if group is None:
            return
        cache = preview_cache.PreviewCache(spec.target.context.root)
        found = cache.group_lookup(group[0], compiler.build_env(spec.target.context))
        if found is not None:
            cache.remember_display(cache_identity(spec), found[2], found[1],
                                   evidence=found[3], observed_at=observed_at)

    def previous_preview(self, target, text, view, language, timestamp):
        """Historical display fallback only; never used to skip rendering."""
        cache = preview_cache.PreviewCache(target.context.root)
        spec = PreviewRequest(target, SourceRevision.capture(target.source_path, text), view, language,
                              RenderOptions(timestamp, saved=True))
        entry = cache.previous(cache_identity(spec))
        return self._retain_display(cache, entry) if entry is not None else None

    def request(self, target, text, view, language, timestamp, log, *, saved=False,
                presenter=False, mode='slide', overlay=None, spec=None, force=False, render_stamp=None,
                require_pdf=False):
        captured = spec is not None
        spec = spec or PreviewRequest(target, SourceRevision.capture(target.source_path, text), view, language,
                                      RenderOptions(timestamp, saved, presenter, mode, overlay, force, render_stamp))
        target, text, view, language = spec.target, spec.revision.text, spec.view, spec.language
        options = spec.options
        timestamp, saved, presenter, mode, overlay = (options.footer_timestamp, options.saved,
                                                     options.presenter, options.mode, options.overlay)
        if target.hidden and not presenter:
            raise ValueError(f'Slide {target.id_slug} is hidden in {view}')
        identity = cache_identity(spec)
        group = image_group(spec, identity)
        group_key = group[0] if group is not None else None
        key = (('pdf', preview_cache.digest(identity)) if require_pdf or group_key is None
               else ('image', group_key), options.force)
        cache = preview_cache.PreviewCache(target.context.root)
        observed_at = time.time_ns()

        def delivered(waiter):
            source = waiter.source if isinstance(waiter, _ImageConsumer) else waiter
            if source._cache_entry is not None:
                cache.remember_display(identity, source._representative_identity or identity,
                                       source._representative_view or view,
                                       evidence=source._representative_evidence, observed_at=observed_at)
            elif waiter.result is not None:
                from .preview_selection import remember_transient
                remember_transient(spec, waiter.result[1], waiter.result[0], observed_at=observed_at)

        def pin(entry, status, *, representative=view, representative_identity=None, evidence=None):
            lease = _ArtifactLease(cache.lease(entry))
            request._artifact_lease = lease
            request._cache_entry, request._cache_status = entry, status
            request._representative_identity = representative_identity or identity
            request._representative_view = representative
            request._representative_evidence = evidence
            with self._lock:
                if self._closed:
                    request.release_artifact()
                    raise RuntimeError('Preview service closed')
                self._completed.add(request)
            return (entry.pdf if representative == view else None,
                    entry.display_png, entry.page_images, entry.secondary_png)

        def work(cancel):
            env = compiler.build_env(target.context)
            if not options.force:
                if group_key is not None and not require_pdf:
                    found = cache.group_lookup(group_key, env)
                    if found is not None and image_group(spec, identity) == group:
                        try:
                            return pin(found[0], 'cached', representative=found[1],
                                       representative_identity=found[2], evidence=found[3])
                        except OSError:
                            pass
                entry = cache.lookup(identity, env)
                if entry is not None:
                    try:
                        return pin(entry, 'cached')
                    except OSError:
                        pass  # eviction won the interval between lookup and pin
            before = cache.begin(env)
            stamp = options.render_stamp or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            if saved and not captured:
                if target.source_path.read_text(encoding='utf-8') != text:
                    raise RuntimeError('Preview superseded: saved source changed before rendering')
            # Saved and draft requests execute the same immutable captured text.
            # The saved flag controls publication guards, never TeX semantics.
            pdf = preview_target.render_text(
                target, text, view, language, footer_timestamp=timestamp, log=log,
                presenter=presenter, mode=mode, overlay=overlay, capture_snapshot=False, cancel=cancel,
                render_stamp=stamp, force_build=True)
            snapshots = (view == 'instructor' or group_key is not None) and not target.is_frozen_alone \
                        and not presenter and mode == 'slide' and overlay is None
            try:
                preview_build.check_cancel(cancel)
                if presenter:
                    displays, images = (None, None), ()
                else:
                    displays, images = slide_snapshot.prepare_preview_images(pdf, snapshots, (slide_snapshot.FULL_SIZE[0], 1280))
                try:
                    dependencies = json.loads(pdf.with_suffix('.inputs.json').read_text())
                except (OSError, ValueError):
                    dependencies = ()
                if saved and not captured and target.source_path.read_text(encoding='utf-8') != text:
                    before = None  # publication reports superseded; never persist mixed saved input
                sequence = None
                if dependencies and before is not None and not presenter and mode == 'slide' and overlay is None:
                    try:
                        sequence = slide_snapshot.preview_sequence(pdf)
                    except (OSError, RuntimeError, ValueError):
                        pass  # optional equality evidence must not fail a valid preview
                entry = cache.store(identity, env, pdf=pdf, display_png=displays[0], secondary_png=displays[1],
                                    page_images=images, dependencies=dependencies, render_stamp=stamp, before=before,
                                    raster_sequence=sequence,
                                    audited_resolution=group is not None and image_group(spec, identity) == group)
                if entry is not None:
                    result = pin(entry, 'rendered')
                    if group_key is not None and not require_pdf:
                        # Recorder checks above guard TeX inputs. Reclassify
                        # as well: an included rule may have changed during
                        # the build even if the source buffer was captured.
                        if image_group(spec, identity) == group:
                            cache.publish_group(group_key, identity, view, evidence=group[1])
                    if pdf.parent.name.startswith('slidemage_preview_'):
                        shutil.rmtree(pdf.parent, ignore_errors=True)
                    cache.prune()
                    return result
                return pdf, displays[0], images, displays[1]
            except Exception:
                if pdf.parent.name.startswith('slidemage_preview_'):
                    shutil.rmtree(pdf.parent, ignore_errors=True)
                raise

        def finished():
            with self._lock:
                if self._requests.get(key) is request:
                    del self._requests[key]

        with self._lock:
            if self._closed:
                raise RuntimeError('Preview service closed')
            request = self._requests.get(key)
            if request is None and require_pdf and group_key is not None:
                image_request = self._requests.get((('image', group_key), options.force))
                if image_request is not None and not image_request.cancel.is_set() and image_request.spec.view == view:
                    return _ImageConsumer(image_request, spec, group,
                                          fallback=lambda: self.request(target, text, view, language, timestamp, log,
                                                                        spec=spec, require_pdf=True), require_pdf=True,
                                          delivery=delivered)
            if request is None or request.cancel.is_set():
                request = RenderRequest(work, finished)
                request.spec = spec
                request._delivery = delivered
                self._requests[key] = request
            if request.spec == spec:
                return request
            return _ImageConsumer(request, spec, group,
                                  fallback=lambda: self.request(target, text, view, language, timestamp, log,
                                                                spec=spec, require_pdf=True), delivery=delivered)
