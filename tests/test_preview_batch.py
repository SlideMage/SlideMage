# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Batch ordering, partial results and shared-request consumer lifetimes."""
from dataclasses import replace
import os
import threading
from types import SimpleNamespace

import pytest

from slidemage import compiler, preview_batch, preview_requests, preview_target
from slidemage.ai.workspace import Workspace, WorkspaceContext
from slidemage.project import ProjectContext


def specs(tmp_path):
    ctx = ProjectContext.at(tmp_path)
    ctx.slides_dir.mkdir(exist_ok=True)
    source = ctx.slides_dir / 'abc-EN-One-current.tex'
    source.write_text('BODY')
    return preview_requests.resolve_requests(ctx, None, source, 'all', 'EN')


class Service:
    def __init__(self, *, fail=None, cancel=None):
        self.calls = []
        self.fail, self.cancel = fail, cancel

    def request(self, *args, spec, **kwargs):
        self.calls.append(spec)

        def work(token):
            if spec.view == self.fail:
                raise RuntimeError('bad TeX')
            if self.cancel is not None:
                self.cancel.request_stop()
            return spec.target.source_path.with_suffix('.pdf'), b'image', (), b'tool image'

        request = preview_requests.RenderRequest(work, lambda: None)
        request.spec = spec
        if spec.view == 'instructor':
            # Simulate the completed cache adapter without skipping the waiter.
            original = work
            def cached(token):
                artifact = original(token)
                request._cache_entry = SimpleNamespace(dependencies=(), render_stamp='original')
                request._cache_status = 'cached'
                return artifact
            request._work = cached
        return request


def test_mixed_cached_failed_hidden_batch_keeps_order(tmp_path):
    requests = specs(tmp_path)
    requests = (*requests[:2], replace(requests[2], target=replace(requests[2].target, hidden=True)))
    service, events, published = Service(fail='during-course'), [], []
    results = preview_batch.render_batch(service, requests, progress=events.append,
                                         publish=lambda result: published.append(result.request.view) or 'cached')
    assert [r.status for r in results] == ['cached', 'failed', 'hidden']
    assert [r.request.view for r in results] == ['instructor', 'during-course', 'after-course']
    assert published == ['instructor']
    assert results[0].display_png == b'image' and results[1].error == 'bad TeX'
    assert len({r.options.render_stamp for r in service.calls}) == 1
    assert [e.status for e in events] == ['rendering', 'cached', 'rendering', 'failed', 'hidden']


def test_stop_retains_completed_result_and_cancels_remaining(tmp_path):
    cancel = compiler.CancelToken()
    service = Service(cancel=cancel)
    results = preview_batch.render_batch(service, specs(tmp_path), cancel=cancel)
    # Cancellation during the first waiter stops its publication; no later compile starts.
    assert [r.status for r in results] == ['cancelled', 'cancelled', 'cancelled']
    assert len(service.calls) == 1


def test_stop_between_views_preserves_completed_result(tmp_path):
    cancel = compiler.CancelToken()
    def progress(event):
        if event.status == 'cached':
            cancel.request_stop()
    results = preview_batch.render_batch(Service(), specs(tmp_path), cancel=cancel, progress=progress)
    assert [r.status for r in results] == ['cached', 'cancelled', 'cancelled']
    assert results[0].display_png == b'image'


@pytest.mark.parametrize('timeout', [False, True])
def test_one_cancelled_waiter_does_not_stop_other_consumer(timeout):
    started, release = threading.Event(), threading.Event()
    def work(token):
        started.set()
        assert release.wait(3)
        assert not token.is_set()
        return 'artifact'
    request = preview_requests.RenderRequest(work, lambda: None)
    live, stopped = [], []
    first = threading.Thread(target=lambda: live.append(request.wait(timeout=3)))
    first.start()
    assert started.wait(1)
    cancel = compiler.CancelToken()
    if not timeout:
        cancel.request_stop()
    def waiter():
        try:
            request.wait(cancel, timeout=.02 if timeout else 3)
        except RuntimeError as exc:
            stopped.append(str(exc))
    second = threading.Thread(target=waiter)
    second.start()
    second.join(1)
    assert stopped == ['Preview timed out' if timeout else 'Preview cancelled']
    assert not request.cancel.is_set()
    release.set()
    first.join(1)
    assert live == ['artifact'] and request.done.is_set()


def test_hidden_missing_source_does_not_fail_capture(tmp_path, monkeypatch):
    request = specs(tmp_path)[0]
    request.target.source_path.unlink()
    target = replace(request.target, hidden=True)
    monkeypatch.setattr(preview_target, 'resolve_views', lambda *a, **k: (('instructor', target),))
    captured = preview_requests.resolve_requests(target.context, None, target.source_path, 'instructor', 'EN')
    assert captured[0].target.hidden and captured[0].revision.text == ''
    assert preview_batch.render_batch(Service(), captured)[0].status == 'hidden'


def test_workspace_captures_buffer_once_and_preserves_selection(tmp_path):
    request = specs(tmp_path)[0]
    context = WorkspaceContext(path=request.target.source_path, slide_id='abc', view='during-course')
    workspace = Workspace(request.target.context, context)
    reads = []
    workspace.is_open = lambda path: True
    workspace.buffer_snapshot = lambda path: (reads.append(path) or 'DRAFT', True)
    service = Service()
    workspace._preview_service = service
    results = workspace.render_preview_batch(request.target.source_path)
    assert len(reads) == 1 and workspace.context() is context
    assert [r.request.revision.text for r in results] == ['DRAFT'] * 3
    assert [r.publication_status for r in results] == ['cached'] * 3


def test_headless_publication_only_refreshes_current_instructor_snapshot(tmp_path, monkeypatch):
    from slidemage import slide_snapshot
    requests = specs(tmp_path)
    workspace = Workspace(requests[0].target.context)
    published = []
    monkeypatch.setattr(slide_snapshot, 'publish_preview', lambda *args: published.append(args))
    for request in requests:
        assert workspace.publish_preview_result(preview_requests.PreviewResult(request), None) == 'cached'
    assert len(published) == 1
    edit_later(requests[0].target.source_path, 'NEW SOURCE')
    assert workspace.publish_preview_result(preview_requests.PreviewResult(requests[0]), None) == 'superseded'
    assert len(published) == 1


def edit_later(path, text):
    """Edit `path` as a user would, after the capture: an edit in the same instant can keep Windows' file time
    unchanged, and the file time is what tells a captured draft that the file moved on."""
    path.write_text(text)
    stamp = path.stat().st_mtime_ns + 2_000_000_000
    os.utime(path, ns=(stamp, stamp))


def test_prepared_batch_uses_click_time_text_after_source_edit(tmp_path):
    request = specs(tmp_path)[0]
    workspace = Workspace(request.target.context)
    workspace._preview_service = Service()
    captured = workspace.prepare_preview_batch(request.target.source_path)
    edit_later(request.target.source_path, 'LATER EDIT')
    results = workspace.render_preview_batch(request.target.source_path, requests=captured)
    assert [r.request.revision.text for r in results] == ['BODY'] * 3
    assert [r.publication_status for r in results] == ['superseded'] * 3


def test_missing_hidden_then_visible_source_reports_per_view_failure(tmp_path, monkeypatch):
    request = specs(tmp_path)[0]
    request.target.source_path.unlink()
    monkeypatch.setattr(preview_target, 'resolve_views', lambda *a, **k: (
        ('instructor', replace(request.target, hidden=True)),
        ('during-course', request.target)))
    captured = preview_requests.resolve_requests(request.target.context, None,
                                                request.target.source_path, 'all', 'EN')
    service = Service()
    results = preview_batch.render_batch(service, captured)
    assert [r.status for r in results] == ['hidden', 'failed']
    assert results[1].error and not service.calls
