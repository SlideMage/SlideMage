# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Cancellation reaches lock waits and the complete TeX process tree, without sockets."""
from types import SimpleNamespace
import os
import shutil
import sys
import threading

import pytest

from slidemage import compiler, preview_build, preview_requests, preview_target, slide_preview
from slidemage.project import ProjectContext


def test_cancel_waiting_build_releases_reservations(tmp_path, monkeypatch):
    monkeypatch.setenv('SLIDEMAGE_PREVIEW_FORMAT', '0')
    ctx = ProjectContext.at(tmp_path)
    wrapper = r'\begin{document}hello'
    key = preview_build.configuration_key(wrapper, 'abc', ctx.root, {})
    lock = ctx.build_dir / 'preview-cache' / key / 'build.lock'
    cancel = compiler.CancelToken()
    entered = threading.Event()
    errors = []
    monkeypatch.setattr(compiler, 'run_latexmk', lambda *a, **k: pytest.fail('cancelled waiter compiled'))

    def render():
        entered.set()
        try:
            preview_build.compile_cached(wrapper, 'abc', lambda _: None, ctx=ctx, env={}, cancel=cancel)
        except RuntimeError as exc:
            errors.append(str(exc))

    with preview_build.build_lock(lock):
        worker = threading.Thread(target=render)
        worker.start()
        assert entered.wait(2)
        cancel.request_stop()
        worker.join(2)
        assert not worker.is_alive() and errors == ['Preview cancelled']
    with preview_build.build_lock(lock, blocking=False) as acquired:
        assert acquired
    assert not preview_build.is_active(ctx.build_dir)


@pytest.mark.parametrize('reuse', [False, True])
def test_cancel_running_latexmk_kills_children_and_frees_lock(tmp_path, monkeypatch, reuse):
    monkeypatch.setenv('SLIDEMAGE_PREVIEW_FORMAT', '0')
    ctx = ProjectContext.at(tmp_path)
    started = threading.Event()
    cancel = compiler.CancelToken()
    errors = []
    script = 'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); print("ready",flush=True); time.sleep(60)'
    monkeypatch.setattr(compiler, 'latexmk_command', lambda *a, **k: [sys.executable, '-c', script])

    def log(line):
        if line == 'ready':
            started.set()

    def render():
        try:
            slide_preview.compile_and_extract(ctx, r'\begin{document}hello', 'abc', log,
                                               reuse_build=reuse, cancel=cancel)
        except RuntimeError as exc:
            errors.append(str(exc))

    worker = threading.Thread(target=render)
    worker.start()
    try:
        assert started.wait(5)
    finally:
        cancel.request_stop()
        worker.join(5)
    assert not worker.is_alive() and errors == ['Preview cancelled']
    assert cancel._proc is None and not preview_build.is_active(ctx.build_dir)
    for lock in ctx.build_dir.rglob('build.lock'):
        with preview_build.build_lock(lock, blocking=False) as acquired:
            assert acquired


@pytest.mark.parametrize('timeout', [False, True])
def test_tool_wait_cancels_shared_running_request(tmp_path, monkeypatch, timeout):
    ctx = ProjectContext.at(tmp_path)
    ctx.slides_dir.mkdir()
    path = ctx.slides_dir / 'abc-EN-One-current.tex'
    path.write_text('BODY')
    target = preview_target.for_path(ctx, path)
    started = threading.Event()

    def render(*a, cancel, **kw):
        started.set()
        assert cancel._event.wait(5)
        preview_build.check_cancel(cancel)

    monkeypatch.setattr(preview_target, 'render_text', render)
    service = preview_requests.RenderService()
    request = service.request(target, 'BODY', 'instructor', 'EN', lambda _: None)
    cancel = compiler.CancelToken()
    if not timeout:
        stopper = threading.Thread(target=lambda: (started.wait(2), cancel.request_stop()))
        stopper.start()
    with pytest.raises(RuntimeError, match='timed out' if timeout else 'cancelled'):
        request.wait(cancel, timeout=.1 if timeout else 5)
    assert request.done.wait(2) and request.cancel.is_set() and not service._requests
    if not timeout:
        stopper.join(2)


def test_cancel_before_process_registration_kills_new_process(tmp_path):
    cancel = compiler.CancelToken()
    cancel.request_stop()
    import subprocess
    proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                            start_new_session=os.name != 'nt')
    cancel._set_process(proc)
    assert proc.wait(timeout=2) != 0
    cancel._set_process(None)


def test_terminal_stop_cancels_current_toolbox(qapp, tmp_path):
    from slidemage.ai.workspace import Workspace
    from slidemage.ui.workspace.terminal.session import ClaudeCodeSession

    session = ClaudeCodeSession.__new__(ClaudeCodeSession)
    # No terminal, WebEngine view, listening server, or paid model is started.
    session._lock, session._generation = threading.Lock(), 0
    session._cancel = compiler.CancelToken()
    session.workspace = Workspace(ProjectContext.at(tmp_path))
    session.workspace.on_gui = lambda fn, default=None: fn()
    session.scope = "deck"
    session.workspace.begin_request = lambda: None
    session._timer = SimpleNamespace(stop=lambda: None)
    session._sync = SimpleNamespace(stop=lambda **k: None)
    session._process = None
    box = session._toolbox()
    session.stop()
    assert box.ctx.cancel.is_set()
    session._cancel = compiler.CancelToken()
    assert not session._toolbox().ctx.cancel.is_set()


def test_cancel_preamble_build_propagates_and_releases_format_lock(tmp_path, monkeypatch):
    from slidemage import preview_format

    monkeypatch.delenv('SLIDEMAGE_PREVIEW_FORMAT', raising=False)
    monkeypatch.setattr(shutil, 'which', lambda *a, **k: '/fake/lualatex')
    cancel = compiler.CancelToken()

    def run(*a, **kw):
        assert kw['cancel'] is cancel
        cancel.request_stop()
        return -1

    monkeypatch.setattr(preview_format, 'run_streamed', run)
    with pytest.raises(RuntimeError, match='cancelled'):
        preview_format.ensure(r'\documentclass{beamer}', 'key', project_root=tmp_path,
                              build_dir=tmp_path / '.build', env={}, log=lambda _: None,
                              lock=preview_build.build_lock, cancel=cancel)
    lock = tmp_path / '.build' / 'preview-formats' / f'{preview_format.SCHEMA}-key' / 'build.lock'
    with preview_build.build_lock(lock, blocking=False) as acquired:
        assert acquired
    assert not (lock.parent / 'format.bad').exists()


def test_completed_service_cache_survives_restart_and_validates_content(tmp_path, monkeypatch):
    import json
    from slidemage import slide_snapshot

    root = tmp_path / 'project'
    ctx = ProjectContext.at(root)
    ctx.slides_dir.mkdir(parents=True)
    source = ctx.slides_dir / 'abc-EN-One-current.tex'
    source.write_text('1.2.0+ FIRST')
    framework = tmp_path / 'framework'
    framework.mkdir()
    theme = framework / 'theme.tex'
    theme.write_text('THEME ONE')
    env = {'SLIDEMASTER_LATEX': str(framework), 'PATH': '', 'HOME': str(tmp_path)}
    monkeypatch.setattr(compiler, 'build_env', lambda _: env)
    monkeypatch.setattr(slide_snapshot, 'prepare_preview_images', lambda *a: ((b'page', b'tool'), ()))
    monkeypatch.setattr(slide_snapshot, 'preview_sequence', lambda _: None)
    calls = []
    pdf = tmp_path / 'result.pdf'

    def render(*args, **kwargs):
        calls.append(kwargs)
        pdf.write_bytes(b'PDF ' + str(len(calls)).encode())
        pdf.with_suffix('.inputs.json').write_text(json.dumps([str(source), str(theme)]))
        return pdf

    monkeypatch.setattr(preview_target, 'render_text', render)
    target = preview_target.for_path(ctx, source)

    def request(service, force=False, stamp=None):
        pending = service.request(target, source.read_text(), 'instructor', 'EN',
                                  lambda _: None, saved=True, force=force, render_stamp=stamp)
        pending.wait()
        return pending

    first_service = preview_requests.RenderService()
    first = request(first_service, stamp='2026-10-15 10:00:00')
    assert first.preview_result.status == 'rendered'
    assert first.preview_result.dependencies == (theme, source)
    from slidemage.project import preview_cache_dir
    assert first.result[0].is_relative_to(preview_cache_dir(root)) and not (root / '.previews' / 'render-results').exists()
    # Immutable result records keep their PDF alive after the future is released.
    import gc
    from slidemage.preview_cache import PreviewCache
    retained = first.preview_result
    del first
    gc.collect()
    PreviewCache(root).prune(max_bytes=0)
    assert retained.pdf.exists()
    first_service.close()
    service = preview_requests.RenderService()
    cached = request(service)
    assert len(calls) == 1 and cached.preview_result.status == 'cached'
    assert cached.metrics['compile_avoided'] == 1
    assert cached.preview_result.render_stamp == '2026-10-15 10:00:00'
    forced = request(service, force=True, stamp='2026-10-15 11:00:00')
    assert len(calls) == 2 and forced.result[0] != cached.result[0]
    assert forced.preview_result.render_stamp == '2026-10-15 11:00:00'
    assert all(call['force_build'] for call in calls)
    old = theme.stat()
    theme.write_text('THEME TWO')
    os.utime(theme, ns=(old.st_atime_ns, old.st_mtime_ns))
    assert request(service).preview_result.status == 'rendered' and len(calls) == 3
    old = source.stat()
    source.write_text('1.2.0+ OTHER')
    os.utime(source, ns=(old.st_atime_ns, old.st_mtime_ns))
    assert request(service).preview_result.status == 'rendered' and len(calls) == 4
    service.close()


def test_saved_request_changed_before_start_never_compiles(tmp_path, monkeypatch):
    ctx = ProjectContext.at(tmp_path)
    ctx.slides_dir.mkdir()
    source = ctx.slides_dir / 'abc-EN-One-current.tex'
    source.write_text('old')
    target = preview_target.for_path(ctx, source)
    request = preview_requests.RenderService().request(target, 'old', 'instructor', 'EN',
                                                      lambda _: None, saved=True)
    source.write_text('new')
    monkeypatch.setattr(preview_target, 'render', lambda *a, **kw: pytest.fail('superseded source compiled'))
    with pytest.raises(RuntimeError, match='superseded'):
        request.wait()


def test_cache_identity_tracks_raster_version_and_ignores_forced_stamp(tmp_path, monkeypatch):
    from dataclasses import replace
    ctx = ProjectContext.at(tmp_path)
    ctx.slides_dir.mkdir()
    source = ctx.slides_dir / 'abc-EN-One-current.tex'
    source.write_text('body')
    target = preview_target.for_path(ctx, source)
    spec = preview_requests.PreviewRequest(target, preview_requests.SourceRevision.capture(source), 'instructor', 'EN')
    initial = preview_requests.cache_identity(spec)
    forced = replace(spec, options=replace(spec.options, force=True, render_stamp='different time'))
    assert preview_requests.cache_identity(forced) == initial
    monkeypatch.setattr(preview_requests, 'version', lambda _: 'new renderer')
    preview_requests._raster_version.cache_clear()     # the version is read once per process (conftest clears it per test)
    changed = preview_requests.cache_identity(spec)
    assert changed != initial and changed['raster']['renderer'] == 'new renderer'


def test_cache_identity_reads_the_raster_version_once(tmp_path, monkeypatch):
    from importlib.metadata import version as installed
    ctx = ProjectContext.at(tmp_path)
    ctx.slides_dir.mkdir()
    source = ctx.slides_dir / 'abc-EN-One-current.tex'
    source.write_text('body')
    spec = preview_requests.PreviewRequest(preview_target.for_path(ctx, source),
                                           preview_requests.SourceRevision.capture(source), 'instructor', 'EN')
    reads = []
    monkeypatch.setattr(preview_requests, 'version', lambda name: reads.append(name) or installed(name))
    first = preview_requests.cache_identity(spec)
    assert preview_requests.cache_identity(spec) == first and reads == ['pymupdf']
    assert first['raster']['renderer'] == installed('pymupdf')


@pytest.fixture
def recorded(tmp_path, monkeypatch):
    """A service whose renders land in a `slidemage_preview_` temp folder; `store` can be held back."""
    import json
    from slidemage import slide_snapshot
    from slidemage.preview_cache import PreviewCache

    ctx = ProjectContext.at(tmp_path / 'project')
    ctx.slides_dir.mkdir(parents=True)
    source = ctx.slides_dir / 'abc-EN-One-current.tex'
    source.write_text('1.2.0+ FIRST')
    framework = tmp_path / 'framework'
    framework.mkdir()
    env = {'SLIDEMASTER_LATEX': str(framework), 'PATH': '', 'HOME': str(tmp_path)}
    monkeypatch.setattr(compiler, 'build_env', lambda _: env)
    monkeypatch.setattr(slide_snapshot, 'prepare_preview_images', lambda *a: ((b'page', b'tool', b'thumb'), ()))
    monkeypatch.setattr(slide_snapshot, 'preview_sequence', lambda _: None)
    folder = tmp_path / 'slidemage_preview_one'
    calls = []

    def render(*args, **kwargs):
        calls.append(kwargs)
        folder.mkdir(exist_ok=True)
        pdf = folder / 'slide.pdf'
        pdf.write_bytes(b'PDF')
        pdf.with_suffix('.inputs.json').write_text(json.dumps([str(source)]))
        return pdf

    monkeypatch.setattr(preview_target, 'render_text', render)
    target = preview_target.for_path(ctx, source)
    gate = SimpleNamespace(entered=threading.Event(), release=threading.Event(), fail=False, stored=[])
    store = PreviewCache.store

    def held_store(self, *args, **kwargs):
        gate.entered.set()
        assert gate.release.wait(10)
        if gate.fail:
            raise RuntimeError('disk gone')
        gate.stored.append(kwargs)
        return store(self, *args, **kwargs)

    monkeypatch.setattr(PreviewCache, 'store', held_store)
    service = preview_requests.RenderService()
    yield SimpleNamespace(
        service=service, folder=folder, calls=calls, gate=gate,
        request=lambda: service.request(target, source.read_text(), 'instructor', 'EN', lambda _: None, saved=True))
    gate.release.set()
    service.close()


def test_pixels_only_wait_returns_before_the_cache_record(recorded):
    import gc
    request = recorded.request()
    pdf, display, images, secondary = request.wait(pixels_only=True, timeout=10)
    assert recorded.gate.entered.wait(10)            # the worker is inside store()
    assert (display, secondary) == (b'page', b'tool') and pdf == recorded.folder / 'slide.pdf' and pdf.exists()
    assert request.delivered.is_set() and not request.done.is_set() and request._cache_entry is None
    assert request.preview_result.status == 'rendered' and request.preview_result.pdf == pdf
    # An identical request while the record runs shares the build; a plain wait() gets the recorded result.
    assert recorded.request() is request
    plain = []
    waiter = threading.Thread(target=lambda: plain.append(request.wait(timeout=10)))
    waiter.start()
    recorded.gate.release.set()
    waiter.join(10)
    assert request.done.wait(10) and len(recorded.calls) == 1
    assert request._cache_entry is not None and request.preview_result.status == 'rendered'
    assert plain[0][0] == request._cache_entry.pdf != pdf
    assert recorded.gate.stored[0]['thumbnail'] == b'thumb'
    # The pane was handed the temp PDF, so the folder lives as long as the request does.
    assert recorded.folder.exists()
    request = plain = waiter = None
    gc.collect()
    assert not recorded.folder.exists()
    cached = recorded.request()
    cached.wait()
    assert cached.preview_result.status == 'cached' and len(recorded.calls) == 1


def test_plain_wait_removes_the_temp_folder_once_recorded(recorded):
    recorded.gate.release.set()
    request = recorded.request()
    result = request.wait(timeout=10)
    assert result[0] == request._cache_entry.pdf and not recorded.folder.exists()
    assert request.done.is_set() and request.preview_result.status == 'rendered'


def test_record_failure_keeps_the_delivered_render(recorded):
    recorded.gate.fail = True
    recorded.gate.release.set()
    request = recorded.request()
    request.wait(pixels_only=True, timeout=10)
    assert request.done.wait(10) and request.error is None
    assert request.result[1] == b'page' and request.result[0].exists() and request._cache_entry is None
    assert request.preview_result.status == 'rendered'
    recorded.gate.fail = False
    again = recorded.request()
    again.wait(timeout=10)
    assert len(recorded.calls) == 2 and again._cache_entry is not None
