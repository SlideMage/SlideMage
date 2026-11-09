# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The scheduler shares proven images while keeping exact-view PDF provenance."""
import json
import threading

import pytest

from slidemage import compiler, preview_batch, preview_requests, preview_target, slide_snapshot
from slidemage.project import ProjectContext


VIEWS = ('instructor', 'during-course', 'after-course')


def fixture(tmp_path, monkeypatch):
    ctx = ProjectContext.at(tmp_path / 'project')
    ctx.slides_dir.mkdir(parents=True)
    source = ctx.slides_dir / 'abc-EN-One-current.tex'
    source.write_text('Plain source')
    framework = tmp_path / 'framework'
    framework.mkdir()
    theme = framework / 'theme.tex'
    theme.write_text('audited fixture')
    env = {'SLIDEMAGE_LATEX': str(framework), 'PATH': '', 'HOME': str(tmp_path)}
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
    def group(spec, identity=None):
        return 'group-0', 'fixture evidence'
    monkeypatch.setattr(preview_requests, 'image_group', group)
    monkeypatch.setattr(preview_batch, 'image_group', group)
    target = preview_target.for_path(ctx, source)
    return ctx, target, source, calls, group


def test_force_batch_shares_once_but_later_force_builds_again(tmp_path, monkeypatch):
    _, target, source, calls, _ = fixture(tmp_path, monkeypatch)
    specs = tuple(preview_requests.PreviewRequest(target, preview_requests.SourceRevision.capture(source), view,
                  'EN', preview_requests.RenderOptions(saved=True, force=True)) for view in VIEWS)
    first = preview_batch.render_batch(preview_requests.RenderService(), specs)
    assert len(calls) == 1 and [r.pdf is not None for r in first] == [True, False, False]
    assert all(r.page_images for r in first)
    second = preview_batch.render_batch(preview_requests.RenderService(), specs)
    assert len(calls) == 2 and second[0].pdf != first[0].pdf


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
