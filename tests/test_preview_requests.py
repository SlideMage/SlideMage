"""Cancellation reaches lock waits and the complete TeX process tree, without sockets."""
from types import SimpleNamespace
import os
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
    request = service.request(target, 'BODY', 'instructor', 'EN', False, lambda _: None)
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
    session.workspace.on_gui = lambda fn: fn()
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
    monkeypatch.setattr(preview_format.shutil, 'which', lambda *a, **k: '/fake/lualatex')
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
