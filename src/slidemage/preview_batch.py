# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Cancellable orchestration of immutable per-view preview requests, several renders at once (parallel_runs)."""
from __future__ import annotations

from dataclasses import dataclass, replace
import shutil
import threading

from . import batch_render
from .preview_requests import PreviewResult


@dataclass(frozen=True)
class BatchProgress:
    view: str
    index: int
    total: int
    status: str
    done: int = 0       # how many requests had finished: several run at once, so `index` is not that


def render_batch(service, requests, *, cancel=None, progress=None, publish=None, log=None, workers=None,
                 may_add=None, batch_size=1):
    """Return one result per request, preserving order and successful partial results.

    Requests are resolved/captured before entering this function. Independent requests render several at once
    (parallel_runs.run_all: up to `workers`, each beyond the first only while the CPU has room); the service shares
    work with other consumers. Cancellation detaches the waiters and marks the views not yet done cancelled.

    `batch_size` > 1 compiles the renders still to do, up to that many slides of one view, language and preamble, in
    one document (batch_render) and records each slide from it like a render of its own; a document that does not
    compile or split is left to the single renders.
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

    def unit_task(index, spec, prebuilt=None, announced=False):
        def run():
            try:
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
                        options = spec.options
                        request = service.request(spec.target, spec.revision.text, spec.view, spec.language,
                                                  log or (lambda _: None),
                                                  saved=options.saved, presenter=options.presenter,
                                                  mode=options.mode, overlay=options.overlay, spec=spec,
                                                  **({'prebuilt': prebuilt} if prebuilt is not None else {}))
                        artifact = request.wait(cancel)
                        result = (replace(request.preview_result, request=spec) if request.preview_result else
                                  PreviewResult.from_artifact(spec, artifact))
                        if publish is not None:
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
                evidence = {index: service._renderer(spec.target.context).resolver.capture(spec.unit, spec.revision.text)
                            for index, spec in batch}
                built = batch_render.build(batch, cancel, log)
                for index, prebuilt in built.items():
                    prebuilt.evidence = evidence[index]
            except Exception:  # noqa: BLE001 -- whatever went wrong, the requests render singly
                pass
            for index, spec in batch:
                unit_task(index, spec, built.pop(index, None), announced=True)()
        return run

    batches = ([] if cancel is not None and cancel.is_set() else
               batch_render.groups(service, list(enumerate(requests, 1)), batch_size))
    batched = {index for batch in batches for index, _spec in batch}
    tasks = ([batch_task(batch) for batch in batches]
             + [unit_task(index, spec) for index, spec in enumerate(requests, 1) if index not in batched])
    if len(requests) == 1:
        tasks[0]()                            # a single tool request may join the pane's foreground build
    else:
        parallel_runs.run_all(tasks, workers=workers, may_add=may_add or parallel_runs.cpu_has_room, cancel=cancel)
    for index, original in enumerate(requests, 1):          # a unit that never started (cancelled first)
        if results[index - 1] is None:
            results[index - 1] = PreviewResult(original, status='cancelled', error='Preview cancelled')
    return tuple(results)
