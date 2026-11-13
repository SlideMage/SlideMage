# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Common batch fallback, bulk cancellation and the AI tools' existing result contracts."""
from functools import partial
from pathlib import Path
import shutil
import threading

import pymupdf
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from conftest import EXAMPLE, wait_until
from slidemage import batch_render, parallel_runs, preview_requests, preview_target, render_key
from slidemage.preview_requests import PreviewRequest, RenderOptions, SourceRevision
from slidemage.project import ProjectContext
from slidemage.ui.workspace import compile_actions
from test_agent_tools import SLIDE, box as box, fake_render  # noqa: F401 -- fixture
from test_workspace_window import window as window  # noqa: F401 -- fixture


def make_spec(ctx, slug, view='instructor', force=False):
    path = ctx.slides_dir / f'{slug}-current.tex'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'Body of {slug}')
    target = preview_target.PreviewTarget(ctx, 'slide', slug, None, None, None, 1, 'PRE')
    return PreviewRequest(target, SourceRevision.capture(path), view, 'EN', RenderOptions(saved=True, force=force))


def test_a_failed_batch_falls_back_to_forced_single_renders(tmp_path, monkeypatch):
    from test_background_renders import FakeTeX

    ctx = ProjectContext.at(tmp_path)
    specs = tuple(make_spec(ctx, f'a{n}-EN-X', force=True) for n in range(3))
    built, events = [], []
    def fail(service, batch, cancel=None, log=None):
        built.append([key for key, spec in batch])
        raise RuntimeError('Render failed')
    monkeypatch.setattr(batch_render, 'build', fail)
    service = preview_requests.RenderService()
    renderer = service.renderer(ctx)
    tex = FakeTeX(ctx, pages=1)
    for spec in specs:
        renderer.store.record_failure(renderer.resolver.fast_key(spec.unit, spec.revision.text),
                                      'deterministic', 'Render failed previously', [])
    monkeypatch.setattr(preview_target, 'render_text',
                        lambda target, text, view, language, **kw: tex(
                            render_key.unit_for(target, view, language), kw['cancel']))
    try:
        results = batch_render.render_batch(service, specs, batch_size=8, progress=events.append)
        assert built == [[1, 2, 3]] and len(tex.calls) == 3
        assert [result.request for result in results] == list(specs)
        assert [result.status for result in results] == ['rendered'] * 3
        assert renderer.store.failures() == []
        assert [[e.status for e in events if e.index == i] for i in (1, 2, 3)] == [['rendering', 'rendered']] * 3
    finally:
        service.close()


@pytest.mark.skipif(shutil.which('latexmk') is None or shutil.which('lualatex') is None, reason='needs a TeX installation')
def test_an_ordinary_slide_after_an_omitted_slide_is_stored_without_the_omitted_banner(tmp_path, monkeypatch):
    shutil.copytree(EXAMPLE, tmp_path / 'project')
    ctx = ProjectContext.at(tmp_path / 'project')
    specs = []
    for number, macro in enumerate(('omitslide', 'slide'), 1):
        slug = f'zz{number}-EN-Test'
        path = ctx.slides_dir / f'{slug}-current.tex'
        path.write_text('\\begin{standardframe}{Test}\nBody\n\\end{standardframe}\n')
        target = preview_target.PreviewTarget(ctx, macro, slug, None, None, None, number, None)
        specs.append(PreviewRequest(target, SourceRevision.capture(path), 'instructor', 'EN', RenderOptions(saved=True)))
    monkeypatch.setattr(preview_target, 'render_text', lambda *a, **kw: pytest.fail('The batch must not fall back'))
    service = preview_requests.RenderService()
    try:
        results = batch_render.render_batch(service, specs, batch_size=2)
        assert [result.status for result in results] == ['rendered', 'rendered']
        renderer = service.renderer(ctx)
        for spec, omitted in zip(specs, (True, False)):
            found = renderer.resolver.lookup(spec.unit)
            assert found.final
            with renderer.store.pdf_copy(found.record) as pdf, pymupdf.open(pdf) as doc:
                assert ('omitted from student deck' in doc[0].get_text()) is omitted
    finally:
        service.close()


def test_cancel_stops_a_bulk_action(window, monkeypatch):
    ctx = window.project
    requests = tuple(make_spec(ctx, 'aaa-EN-X', view=view) for view in batch_render.VIEWS)
    service = window.background.renderer.renders
    calls, results = [], []
    monkeypatch.setattr(batch_render, 'plan_project', lambda renderer: requests)
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(compile_actions, '_confirm_previews_lint', lambda *a: True)

    def request(*args, spec, **options):
        calls.append(spec)
        handle = preview_requests.RenderRequest(lambda token: (Path('slide.pdf'), b'image', (), None), lambda: None)
        handle.spec = spec
        return handle

    monkeypatch.setattr(service, 'request', request)
    original = batch_render.render_batch
    monkeypatch.setattr(parallel_runs, 'run_all', partial(parallel_runs.run_all, workers=1))

    def render(service, captured, *, cancel, progress, **options):
        def notify(event):
            progress(event)
            if event.done == 1:
                stopped = threading.Event()
                def stop():
                    compile_actions.stop_now(window)
                    stopped.set()
                QTimer.singleShot(0, window.compile, stop)
                assert stopped.wait(3)
        results.extend(original(service, captured, cancel=cancel, progress=notify))
        return tuple(results)

    monkeypatch.setattr(batch_render, 'render_batch', render)
    compile_actions.update_previews(window)
    wait_until(lambda: not window.compile.running)
    assert len(calls) == 1
    assert results[0].status == 'rendered' and all(r.status == 'cancelled' for r in results[1:])
    row, = window.compile.run.rows.values()
    assert row.label == 'Render all previews now' and row.state == 'stopped'


def test_refresh_deck_previews_reports_counts_and_lists(box):
    box.ws.refresh_result = batch_render.DeckResult(refreshed=["abc-EN-Hello"], failed=["abd-EN-Second"],
                                                           error="! Undefined control sequence.")
    out = box.ok("refresh_deck_previews")                                       # the open deck
    assert box.ws.refreshed == ["test"]
    assert out == ("test: 1 of 2 slide preview(s) refreshed, 1 failed.\nRefreshed: abc\nFailed: abd\n"
                   "First error: ! Undefined control sequence.")
    box.ws.refresh_result = batch_render.DeckResult(refreshed=["abc-EN-Hello", "abd-EN-Second"])
    assert box.ok("refresh_deck_previews", deck="test") == "test: 2 of 2 slide preview(s) refreshed, 0 failed.\nRefreshed: abc, abd"
    box.ws.refresh_result = batch_render.DeckResult()
    assert "no slides to refresh" in box.ok("refresh_deck_previews")
    assert "There is no deck 'nope'" in box.error("refresh_deck_previews", deck="nope")
    assert box.ws.refreshed == ["test"] * 3


@pytest.mark.parametrize('args', [{}, {'view': 'all'}])
def test_refresh_all_views_uses_saved_source_and_returns_statuses_only(box, root, monkeypatch, args):
    seen = fake_render(monkeypatch, root)
    box.ws.open(root / SLIDE, 'UNSAVED')
    captures = []
    render = preview_target.render_text

    def capture(target, text, *args, **kwargs):
        captures.append(text)
        return render(target, text, *args, **kwargs)

    monkeypatch.setattr(preview_target, 'render_text', capture)
    result = box.run('refresh_preview', **args)
    assert not result.is_error and result.images == []
    assert sorted(row[2] for row in seen) == sorted(['instructor', 'during-course', 'after-course'])          # the views render at once, in any order
    assert all(text == (root / SLIDE).read_text() for text in captures)
    assert 'saved source' in result.text and 'cached for after-course' in result.text
