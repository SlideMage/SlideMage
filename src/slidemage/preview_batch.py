"""Sequential, cancellable orchestration of immutable per-view preview requests."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import time

from .preview_requests import PreviewResult
from .preview_requests import image_group


@dataclass(frozen=True)
class BatchProgress:
    view: str
    index: int
    total: int
    status: str


def render_batch(service, requests, *, cancel=None, progress=None, publish=None, log=None):
    """Return one result per request, preserving order and successful partial results.

    Requests are resolved/captured before entering this function. Each missing view is
    awaited before requesting the next, while the service shares work with other
    consumers. Cancellation detaches this waiter and marks remaining views cancelled.
    """
    requests = tuple(requests)
    batch_observed_at = time.time_ns()
    stamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    results = []
    forced_groups = {}

    def notify(event):
        if progress is not None:
            try:
                progress(event)
            except Exception:  # noqa: BLE001 -- observers do not own batch lifetime
                pass

    for index, original in enumerate(requests, 1):
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
        results.append(result)
        notify(BatchProgress(spec.view, index, len(requests), result.status))
    return tuple(results)
