"""In-flight preview sharing; pixels and build state keep their existing caches.

Requests own immutable source/context keys. Consumers may await the same build,
while the pane alone decides whether to publish its image and snapshots.
"""
from __future__ import annotations

import threading
import shutil
import time

from . import compiler, preview_build, preview_target, slide_snapshot
from .preview_metrics import PreviewMetrics

TIMEOUT = 300


class RenderRequest:
    def __init__(self, work, finished):
        self.cancel = compiler.CancelToken()
        self.done = threading.Event()
        self.result = None
        self.error = None
        self.metrics = None
        self._consumers = []
        self._work, self._finished = work, finished
        self._start_lock = threading.Lock()
        self._started = False

    def _run(self):
        with PreviewMetrics() as metrics:
            try:
                preview_build.check_cancel(self.cancel)
                self.result = self._work(self.cancel)
                preview_build.check_cancel(self.cancel)
            except Exception as exc:  # noqa: BLE001 -- forwarded to every consumer
                self.error = exc
        self.metrics = metrics.to_dict()
        self._finished()
        self.done.set()

    def cancelled(self):
        return self.cancel.is_set() or any(token.is_set() for token in self._consumers)

    def forget_unstarted(self):
        with self._start_lock:
            if not self._started:
                self._finished()

    def wait(self, cancel=None, timeout=TIMEOUT):
        if cancel is not None:
            self._consumers.append(cancel)
        deadline = time.monotonic() + timeout
        with self._start_lock:
            if self.cancelled():
                self.cancel.request_stop()
                raise RuntimeError('Preview cancelled')
            if not self._started:
                self._started = True
                threading.Thread(target=self._run, daemon=True).start()
        while True:
            if self.cancelled():
                self.cancel.request_stop()
                raise RuntimeError('Preview cancelled')
            if self.done.wait(.05):
                break
            if time.monotonic() >= deadline:
                self.cancel.request_stop()
                raise RuntimeError('Preview timed out')
        if self.cancelled():
            self.cancel.request_stop()
            raise RuntimeError('Preview cancelled')
        if self.error is not None:
            raise self.error
        return self.result


class RenderService:
    def __init__(self):
        self._requests = {}
        self._lock = threading.Lock()

    def close(self):
        with self._lock:
            requests = tuple(self._requests.values())
            self._requests.clear()
        for request in requests:
            request.cancel.request_stop()

    def request(self, target, text, view, language, timestamp, log, *, saved=False,
                presenter=False, mode='slide', overlay=None):
        revision = target.source_path.stat().st_mtime_ns
        key = (target.source_path.resolve(), target.key, text, revision, view, language,
               timestamp, presenter, mode, overlay, saved if target.macro != "slide" or target.conditions else None)

        def work(cancel):
            if saved:
                pdf = preview_target.render(target, view, language, footer_timestamp=timestamp,
                                            log=log, capture_snapshot=False, cancel=cancel)
            else:
                pdf = preview_target.render_text(
                    target, text, view, language, footer_timestamp=timestamp, log=log,
                    presenter=presenter, mode=mode, overlay=overlay, capture_snapshot=False, cancel=cancel)
            snapshots = view == 'instructor' and not target.is_frozen_alone and not presenter and mode == 'slide' and overlay is None
            try:
                preview_build.check_cancel(cancel)
                if presenter:
                    return pdf, None, (), None
                displays, images = slide_snapshot.prepare_preview_images(pdf, snapshots, (slide_snapshot.FULL_SIZE[0], 1280))
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
            request = self._requests.get(key)
            if request is None or request.cancel.is_set():
                request = RenderRequest(work, finished)
                self._requests[key] = request
            return request
