# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Cancellable orchestration of immutable per-view preview requests, several renders at once (parallel_runs)."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import threading
import time

from .preview_requests import PreviewResult
from .preview_requests import image_group


@dataclass(frozen=True)
class BatchProgress:
    view: str
    index: int
    total: int
    status: str
    done: int = 0       # how many requests had finished: several run at once, so `index` is not that


def render_batch(service, requests, *, cancel=None, progress=None, publish=None, log=None, workers=None,
                 may_add=None):
    """Return one result per request, preserving order and successful partial results.

    Requests are resolved/captured before entering this function. Independent requests render several at once
    (parallel_runs.run_all: up to `workers`, each beyond the first only while the CPU has room); the service shares
    work with other consumers. Forced requests whose views share one image stay one unit, in order, so the first
    renders and the others reuse it; so do unforced ones, which then find it cached. Cancellation detaches the waiters and marks the views not yet done cancelled.
    """
    from . import parallel_runs

    requests = tuple(requests)
    batch_observed_at = time.time_ns()
    stamp = datetime.now().strftime('%Y-%m-%d %H:%M')
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

    def one(index, original, forced_groups):
        spec = replace(original, options=replace(original.options,
                       render_stamp=original.options.render_stamp or stamp))
        if spec.target.hidden and not spec.options.presenter:
            result = PreviewResult(spec, status='hidden')
        elif cancel is not None and cancel.is_set():
            result = PreviewResult(spec, status='cancelled', error='Preview cancelled')
        elif spec.capture_error is not None:
            result = PreviewResult(spec, status='failed', error=spec.capture_error)
        else:
            notify(BatchProgress(spec.view, index, len(requests), 'rendering'))
            try:
                options = spec.options
                group = image_group(spec) if options.force else None
                previous = forced_groups.get(group[0]) if group else None
                if previous is not None and image_group(spec) == group:
                    result = replace(previous, request=spec,
                                     pdf=previous.pdf if previous.request.view == spec.view else None,
                                     publication_status='unpublished')
                    remember = getattr(service, 'remember_group_alias', None)
                    if remember is not None:
                        remember(spec, observed_at=batch_observed_at)
                else:
                    request = service.request(spec.target, spec.revision.text, spec.view, spec.language,
                                              log or (lambda _: None),
                                              saved=options.saved, presenter=options.presenter,
                                              mode=options.mode, overlay=options.overlay, spec=spec)
                    artifact = request.wait(cancel)
                    result = request.preview_result or PreviewResult.from_artifact(spec, artifact)
                    if group is not None and image_group(spec) == group:
                        forced_groups[group[0]] = result
                # An in-flight request can belong to another batch timestamp. Keep
                # its actual immutable identity and original cached render stamp.
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

    # Units: views that make the same image (one image group) are one unit, in order: the first renders, the others
    # find it (cached, or shared when forced). Every other request is a unit of its own; units run in parallel.
    units: dict = {}
    for index, original in enumerate(requests, 1):
        try:
            group = image_group(original)
        except Exception:  # noqa: BLE001 -- not classifiable: render it on its own
            group = None
        units.setdefault(group[0] if group else ('alone', index), []).append((index, original))

    def unit_task(members):
        def run():
            forced_groups = {}
            for index, original in members:
                one(index, original, forced_groups)
        return run

    parallel_runs.run_all([unit_task(members) for members in units.values()], workers=workers,
                          may_add=may_add or parallel_runs.cpu_has_room)
    for index, original in enumerate(requests, 1):          # a unit that never started (cancelled first)
        if results[index - 1] is None:
            results[index - 1] = PreviewResult(original, status='cancelled', error='Preview cancelled')
    return tuple(results)
