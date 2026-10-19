# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The scheduler shares proven images while keeping exact-view PDF provenance."""
import json
import threading
import time

import pytest

from slidemage import compiler, preview_batch, preview_requests, preview_target, slide_snapshot
from slidemage.project import ProjectContext


VIEWS = ('instructor', 'during-course', 'after-course')


def fixture(tmp_path, monkeypatch, groups=(0, 0, 0)):
    ctx = ProjectContext.at(tmp_path / 'project')
    ctx.slides_dir.mkdir(parents=True)
    source = ctx.slides_dir / 'abc-EN-One-current.tex'
    source.write_text('Plain source')
    framework = tmp_path / 'framework'
    framework.mkdir()
    theme = framework / 'theme.tex'
    theme.write_text('audited fixture')
    env = {'SLIDEMASTER_LATEX': str(framework), 'PATH': '', 'HOME': str(tmp_path)}
    monkeypatch.setattr(compiler, 'build_env', lambda _: env)
    monkeypatch.setattr(slide_snapshot, 'preview_sequence', lambda _: None)
    monkeypatch.setattr(slide_snapshot, 'prepare_preview_images',
                        lambda pdf, *a: ((b'page', b'tool'), (((200, 100), b'snapshot'),)))
    calls = []

    def render(_target, _text=None, view='instructor', *args, **kwargs):
        # render() receives view as its second positional argument.
        if _text in VIEWS:
            view = _text
        calls.append(view)
        pdf = tmp_path / f'result-{len(calls)}.pdf'
        pdf.write_bytes(f'PDF {view} {len(calls)}'.encode())
        pdf.with_suffix('.inputs.json').write_text(json.dumps([str(source), str(theme)]))
        return pdf

    monkeypatch.setattr(preview_target, 'render_text', render)
    monkeypatch.setattr(preview_target, 'render_text', render)
    def group(spec, identity=None):
        return f'group-{groups[VIEWS.index(spec.view)]}', 'fixture evidence'
    monkeypatch.setattr(preview_requests, 'image_group', group)
    monkeypatch.setattr(preview_batch, 'image_group', group)
    target = preview_target.for_path(ctx, source)
    return ctx, target, source, calls, group


@pytest.mark.parametrize('groups,expected', [((0, 0, 0), 1), ((0, 1, 1), 2), ((0, 1, 2), 3)])
def test_cold_batch_group_count_restart_and_exact_pdf(tmp_path, monkeypatch, groups, expected):
    ctx, target, source, calls, _ = fixture(tmp_path, monkeypatch, groups)
    rasters = []
    prepare = slide_snapshot.prepare_preview_images
    def raster(*args):
        rasters.append(1)
        return prepare(*args)
    monkeypatch.setattr(slide_snapshot, 'prepare_preview_images', raster)
    specs = tuple(preview_requests.PreviewRequest(target, preview_requests.SourceRevision.capture(source), view,
                  'EN', preview_requests.RenderOptions(saved=True)) for view in VIEWS)
    initial_service = preview_requests.RenderService()
    first = preview_batch.render_batch(initial_service, specs)
    assert len(calls) == len(rasters) == expected
    assert [r.request.view for r in first] == list(VIEWS)
    assert all(r.status == 'rendered' if groups[VIEWS.index(r.request.view)] not in groups[:VIEWS.index(r.request.view)]
               else r.status == 'cached' for r in first)
    assert all(r.display_png is not None and r.page_images for r in first)
    assert all(r.pdf is None or r.pdf.read_bytes().startswith(f'PDF {r.request.view}'.encode()) for r in first)

    warm = preview_batch.render_batch(initial_service, specs)
    assert len(calls) == len(rasters) == expected
    assert all(result.status == 'cached' for result in warm)
    initial_service.close()

    restarted = preview_requests.RenderService()
    again = preview_batch.render_batch(restarted, specs)
    assert len(calls) == len(rasters) == expected
    assert all(result.status == 'cached' for result in again)
    later = restarted.request(target, source.read_text(), 'after-course', 'EN', lambda _: None, saved=True)
    later.wait()
    assert len(calls) == len(rasters) == expected and later.preview_result.status == 'cached'
    if groups[2] != groups[0] and groups[2] != groups[1]:
        assert later.result[0] is not None
    else:
        assert later.result[0] is None
        exact = restarted.request(target, source.read_text(), 'after-course', 'EN',
                                  lambda _: None, saved=True, require_pdf=True)
        exact.wait()
        assert len(calls) == expected + 1
        assert exact.result[0].read_bytes().startswith(b'PDF after-course')
        assert restarted.cached_spec(specs[2]).display_png == later.result[1]
    restarted.close()


def test_force_batch_shares_once_but_later_force_builds_again(tmp_path, monkeypatch):
    _, target, source, calls, _ = fixture(tmp_path, monkeypatch)
    specs = tuple(preview_requests.PreviewRequest(target, preview_requests.SourceRevision.capture(source), view,
                  'EN', preview_requests.RenderOptions(saved=True, force=True)) for view in VIEWS)
    first = preview_batch.render_batch(preview_requests.RenderService(), specs)
    assert len(calls) == 1 and [r.pdf is not None for r in first] == [True, False, False]
    assert all(r.page_images for r in first)
    second = preview_batch.render_batch(preview_requests.RenderService(), specs)
    assert len(calls) == 2 and second[0].pdf != first[0].pdf


def test_group_cache_rechecks_dependencies_and_source_revision(tmp_path, monkeypatch):
    _, target, source, calls, _ = fixture(tmp_path, monkeypatch)
    service = preview_requests.RenderService()

    def request(view):
        result = service.request(target, source.read_text(), view, 'EN', lambda _: None, saved=True)
        result.wait()
        return result

    request('instructor')
    assert request('after-course').preview_result.status == 'cached' and len(calls) == 1
    theme = tmp_path / 'framework' / 'theme.tex'
    theme.write_text('changed dependency')
    assert request('after-course').preview_result.status == 'rendered' and len(calls) == 2
    source.write_text('new revision')
    assert request('during-course').preview_result.status == 'rendered' and len(calls) == 3
    service.close()


def test_during_first_keeps_legacy_instructor_snapshot_sizes(tmp_path, monkeypatch):
    _, target, source, calls, _ = fixture(tmp_path, monkeypatch)
    flags = []
    original = slide_snapshot.prepare_preview_images
    def prepare(pdf, snapshots, sizes):
        flags.append(snapshots)
        return original(pdf, snapshots, sizes)
    monkeypatch.setattr(slide_snapshot, 'prepare_preview_images', prepare)
    service = preview_requests.RenderService()
    first = service.request(target, source.read_text(), 'during-course', 'EN', lambda _: None, saved=True)
    first.wait()
    instructor = service.request(target, source.read_text(), 'instructor', 'EN', lambda _: None, saved=True)
    instructor.wait()
    assert len(calls) == 1 and flags == [True]
    assert instructor.preview_result.page_images == first.preview_result.page_images
    assert instructor.preview_result.pdf is None
    service.close()


def test_batch_alias_history_survives_edit_before_view_is_selected(tmp_path, monkeypatch):
    from slidemage import preview_cache, preview_selection

    ctx, target, source, calls, _ = fixture(tmp_path, monkeypatch)
    specs = tuple(preview_requests.PreviewRequest(target, preview_requests.SourceRevision.capture(source), view,
                  'EN', preview_requests.RenderOptions(saved=True)) for view in VIEWS)
    service = preview_requests.RenderService()
    results = preview_batch.render_batch(service, specs)
    assert len(calls) == 1 and all(result.display_png == b'page' for result in results)
    service.close()
    source.write_text('Different source')
    revised = preview_requests.PreviewRequest(target, preview_requests.SourceRevision.capture(source),
                                               'during-course', 'EN', preview_requests.RenderOptions(saved=True))
    env = compiler.build_env(ctx)
    reopened = preview_selection.select_image(preview_cache.PreviewCache(ctx.root), (revised,), env)
    assert reopened.state == 'previous' and reopened.image == b'page'
    assert reopened.representative_view == 'instructor' and reopened.pdf is None
    assert reopened.artifact_revision_hash == specs[0].revision.content_hash


def test_changed_classification_during_build_retries_foreign_consumer(tmp_path, monkeypatch):
    _, target, source, calls, group = fixture(tmp_path, monkeypatch)
    changed = threading.Event()
    started = threading.Event()
    release = threading.Event()
    original = preview_target.render_text

    def render(*args, **kwargs):
        started.set()
        assert release.wait(3)
        return original(*args, **kwargs)

    monkeypatch.setattr(preview_target, 'render_text', render)
    monkeypatch.setattr(preview_requests, 'image_group',
                        lambda spec, identity=None: None if changed.is_set() else group(spec, identity))
    service = preview_requests.RenderService()
    first = service.request(target, source.read_text(), 'instructor', 'EN', lambda _: None, saved=True)
    other = service.request(target, source.read_text(), 'during-course', 'EN', lambda _: None, saved=True)
    results = []
    thread = threading.Thread(target=lambda: results.append(other.wait()))
    thread.start()
    assert started.wait(2)
    changed.set()
    release.set()
    first.wait()
    thread.join(3)
    assert not thread.is_alive() and len(calls) == 2
    assert results[0][0].read_bytes().startswith(b'PDF during-course')
    assert other.preview_result.request.view == 'during-course'
    service.close()


def test_exact_pdf_waiter_joins_same_view_image_build(tmp_path, monkeypatch):
    _, target, source, calls, _ = fixture(tmp_path, monkeypatch)
    service = preview_requests.RenderService()
    image = service.request(target, source.read_text(), 'instructor', 'EN', lambda _: None, saved=True)
    exact = service.request(target, source.read_text(), 'instructor', 'EN',
                            lambda _: None, saved=True, require_pdf=True)
    assert exact is not image
    assert exact.wait()[0] is not None
    assert len(calls) == 1
    service.close()


def test_failed_retry_has_no_exposable_representative_artifact(tmp_path, monkeypatch):
    _, target, source, _, _ = fixture(tmp_path, monkeypatch)
    first = preview_requests.PreviewRequest(target, preview_requests.SourceRevision.capture(source),
                                            'instructor', 'EN')
    other = preview_requests.PreviewRequest(target, first.revision, 'during-course', 'EN')
    representative = preview_requests.RenderRequest(lambda _: (source, b'wrong view', (), None), lambda: None)
    representative.spec = first
    retry = preview_requests.RenderRequest(lambda _: (_ for _ in ()).throw(RuntimeError('retry failed')),
                                           lambda: None)
    retry.spec = other
    monkeypatch.setattr(preview_requests, 'image_group', lambda *a: None)
    alias = preview_requests._ImageConsumer(representative, other, ('group', 'evidence'), lambda: retry)
    with pytest.raises(RuntimeError, match='retry failed'):
        alias.wait()
    assert alias.done.is_set() and alias.result is None and alias.preview_result is None
    assert isinstance(alias.error, RuntimeError) and alias.metrics is retry.metrics


def test_cross_view_cancel_detaches_only_that_waiter(tmp_path, monkeypatch):
    _, target, source, calls, _ = fixture(tmp_path, monkeypatch)
    started, release = threading.Event(), threading.Event()
    original = preview_target.render_text

    def render(*args, **kwargs):
        started.set()
        assert release.wait(3)
        return original(*args, **kwargs)

    monkeypatch.setattr(preview_target, 'render_text', render)
    service = preview_requests.RenderService()
    handles = [service.request(target, source.read_text(), view, 'EN', lambda _: None, saved=True)
               for view in VIEWS]
    cancelled = compiler.CancelToken()
    finished, errors = {}, {}

    def wait(index):
        try:
            finished[index] = handles[index].wait(cancelled if index == 1 else None)
        except RuntimeError as exc:
            errors[index] = str(exc)

    threads = [threading.Thread(target=wait, args=(index,)) for index in range(3)]
    threads[0].start()
    assert started.wait(2)
    threads[2].start()
    deadline = time.monotonic() + 2
    while len(handles[0]._consumers) < 2 and time.monotonic() < deadline:
        time.sleep(.005)
    assert len(handles[0]._consumers) == 2
    threads[1].start()
    while len(handles[0]._consumers) < 3 and time.monotonic() < deadline:
        time.sleep(.005)
    assert len(handles[0]._consumers) == 3
    cancelled.request_stop()
    threads[1].join(2)
    release.set()
    for thread in threads:
        thread.join(3)
    assert all(not thread.is_alive() for thread in threads)
    assert errors == {1: 'Preview cancelled'} and set(finished) == {0, 2}
    assert len(calls) == 1 and finished[0][0] is not None and finished[2][0] is None
    assert handles[0].preview_result.request.view == 'instructor'
    assert handles[2].preview_result.request.view == 'after-course'
    service.close()


@pytest.mark.parametrize('classified', [False, True])
def test_saved_and_identical_draft_share_cache_and_keep_provenance(tmp_path, monkeypatch, classified):
    ctx, target, source, calls, group = fixture(tmp_path, monkeypatch)
    if classified:
        monkeypatch.setattr(preview_requests, 'image_group', lambda spec, identity=None:
                            (group(spec, identity)[0] + spec.revision.content_hash, group(spec, identity)[1]))
    else:
        monkeypatch.setattr(preview_requests, 'image_group', lambda *a: None)
    service = preview_requests.RenderService()
    saved = service.request(target, source.read_text(), 'instructor', 'EN', lambda _: None, saved=True)
    saved.wait()
    draft = service.request(target, source.read_text(), 'instructor', 'EN', lambda _: None)
    draft.wait()
    assert len(calls) == 1
    assert saved.preview_result.request.options.saved
    assert not draft.preview_result.request.options.saved
    assert draft.preview_result.status == 'cached'
    service.close()
    restarted = preview_requests.RenderService()
    same = restarted.request(target, source.read_text(), 'instructor', 'EN', lambda _: None)
    same.wait()
    assert len(calls) == 1
    changed = restarted.request(target, 'Actual unsaved change', 'instructor', 'EN', lambda _: None)
    changed.wait()
    assert len(calls) == 2
    restarted.close()


def test_saved_and_draft_join_inflight_exact_work(tmp_path, monkeypatch):
    _, target, source, calls, _ = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(preview_requests, 'image_group', lambda *a: None)
    started, release = threading.Event(), threading.Event()
    render = preview_target.render_text
    def held(*args, **kwargs):
        started.set()
        assert release.wait(3)
        return render(*args, **kwargs)
    monkeypatch.setattr(preview_target, 'render_text', held)
    service = preview_requests.RenderService()
    saved = service.request(target, source.read_text(), 'instructor', 'EN', lambda _: None, saved=True)
    thread = threading.Thread(target=saved.wait)
    thread.start()
    assert started.wait(2)
    draft = service.request(target, source.read_text(), 'instructor', 'EN', lambda _: None)
    assert draft.source is saved
    release.set()
    draft.wait()
    thread.join(3)
    assert len(calls) == 1
    assert not draft.preview_result.request.options.saved
    service.close()


def test_new_frozen_sibling_retains_audited_pinned_result_but_shadow_and_content_edits_miss(tmp_path, monkeypatch):
    from dataclasses import replace
    _, target, source, calls, _ = fixture(tmp_path, monkeypatch)
    pinned = source.with_name('abc-EN-One-v1-0-0.tex')
    pinned.write_text('Frozen source')
    # Retain the real dependency check: this fixture's renderer records its source.
    source.write_text('Frozen source')
    target = replace(target, version='1-0-0', preamble_text='audited fixture')
    service = preview_requests.RenderService()
    def request():
        handle = service.request(target, pinned.read_text(), 'instructor', 'EN', lambda _: None,
                                 saved=True)
        handle.wait()
        return handle
    first = request()
    assert first.preview_result.status == 'rendered'
    source.with_name('abc-EN-One-v1-0-1.tex').write_text('Newly frozen current')
    assert request().preview_result.status == 'cached' and len(calls) == 1
    # A candidate with an actual recorder basename must still invalidate.
    (source.parent / 'shadow').mkdir()
    (source.parent / 'shadow' / source.name).write_text('Could shadow a recorded input')
    assert request().preview_result.status == 'rendered' and len(calls) == 2
    source.write_text('Changed dependency')
    assert request().preview_result.status == 'rendered' and len(calls) == 3
    service.close()


def test_unknown_pinned_tex_keeps_conservative_search_invalidation(tmp_path, monkeypatch):
    from dataclasses import replace
    _, target, source, calls, _ = fixture(tmp_path, monkeypatch)
    pinned = source.with_name('abc-EN-One-v1-0-0.tex')
    pinned.write_text('Custom TeX')
    target = replace(target, version='1-0-0', preamble_text='custom definitions')
    monkeypatch.setattr(preview_requests, 'image_group', lambda *a: None)
    service = preview_requests.RenderService()
    def request():
        handle = service.request(target, pinned.read_text(), 'instructor', 'EN', lambda _: None)
        handle.wait()
    request()
    source.with_name('abc-EN-One-v1-0-1.tex').write_text('New version')
    request()
    assert len(calls) == 2
    service.close()
