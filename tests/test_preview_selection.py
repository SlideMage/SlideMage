# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared image provenance, including display-only history of group aliases."""
from dataclasses import replace
import hashlib
import os

from slidemage import preview_cache, preview_requests, preview_selection, preview_target, slide_snapshot
from slidemage.project import ProjectContext


def setup(tmp_path, monkeypatch):
    ctx = ProjectContext.at(tmp_path / 'project')
    ctx.slides_dir.mkdir(parents=True)
    source = ctx.slides_dir / 'abc-EN-One-current.tex'
    source.write_text('First text plus marker 1.0+')
    framework = tmp_path / 'framework'
    framework.mkdir()
    package = framework / 'theme.tex'
    package.write_text('Framework')
    env = {'SLIDEMAGE_LATEX': str(framework), 'PATH': '', 'HOME': str(tmp_path)}
    cache = preview_cache.PreviewCache(ctx.root)
    target = preview_target.for_path(ctx, source)
    state = {'group': 'group-old'}
    monkeypatch.setattr(preview_selection, 'image_group', lambda spec: (state['group'], 'audited evidence'))
    return ctx, source, package, env, cache, target, state


def spec(target, text, view='during-course', *, saved=True):
    return preview_requests.PreviewRequest(
        target, preview_requests.SourceRevision.capture(target.source_path, text), view, 'EN',
        preview_requests.RenderOptions(saved=saved))


def store(cache, env, package, request, tmp_path, pixels=b'page'):
    pdf = tmp_path / ('source-' + request.view + '-' + hashlib.sha256(pixels).hexdigest()[:8] + '.pdf')
    pdf.write_bytes(b'PDF')
    result = cache.store(preview_requests.cache_identity(request), env, pdf=pdf, display_png=pixels,
                         dependencies=(request.target.source_path, package), before=cache.begin(env))
    assert result is not None
    return result


def select(cache, request, env, *, thumbnail=False, reference=None):
    return preview_selection.select_image(cache, (request,), env, thumbnail=thumbnail, reference=reference)


def test_group_alias_history_survives_source_edit_restart_and_keeps_view_provenance(tmp_path, monkeypatch):
    _, source, package, env, cache, target, state = setup(tmp_path, monkeypatch)
    original = spec(target, source.read_text(), 'instructor')
    during = spec(target, source.read_text())
    entry = store(cache, env, package, original, tmp_path, b'original pixels')
    cache.publish_group('group-old', preview_requests.cache_identity(original), 'instructor',
                        evidence='audited evidence')
    pane = select(cache, during, env)
    thumbnail = select(cache, during, env, thumbnail=True)
    assert pane.fresh and thumbnail.fresh and pane.artifact_id == thumbnail.artifact_id
    assert pane.image == entry.display_png and pane.pdf is None
    assert pane.representative_view == 'instructor' and pane.request.view == 'during-course'

    old_stat = source.stat()
    source.write_text('Other text plus marker 1.0+')  # unchanged version marker
    os.utime(source, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    state['group'] = 'group-new'
    revised = spec(target, source.read_text())
    reopened = preview_cache.PreviewCache(cache.project_root)
    old_pane = select(reopened, revised, env)
    old_thumb = select(reopened, revised, env, thumbnail=True)
    assert old_pane.state == old_thumb.state == 'previous'
    assert old_pane.artifact_id == old_thumb.artifact_id == pane.artifact_id
    assert old_pane.request.revision.content_hash == revised.revision.content_hash
    assert old_pane.artifact_revision_hash == original.revision.content_hash
    assert old_pane.representative_view == 'instructor' and old_pane.pdf is None
    assert reopened.lookup(preview_requests.cache_identity(revised), env) is None


def test_view_specific_history_and_context_boundaries(tmp_path, monkeypatch):
    _, source, package, env, cache, target, state = setup(tmp_path, monkeypatch)
    during = spec(target, source.read_text())
    store(cache, env, package, during, tmp_path, b'during only')
    current = select(cache, during, env)
    assert current.fresh
    old_stat = package.stat()
    package.write_text('Otherwork')
    os.utime(package, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    state['group'] = 'group-new'
    assert select(cache, during, env).state == 'previous'
    assert select(cache, spec(target, source.read_text(), 'after-course'), env).state == 'missing'
    pinned = replace(target, version='1-0-0')
    assert select(cache, spec(pinned, source.read_text()), env).state == 'missing'
    other_occurrence = replace(target, occurrence_key=('other deck call',))
    assert select(cache, spec(other_occurrence, source.read_text()), env).state == 'missing'
    hidden = replace(target, hidden=True)
    assert select(cache, spec(hidden, source.read_text()), env).state == 'hidden'


def test_newer_buffer_history_wins_and_old_writer_cannot_replace_it(tmp_path, monkeypatch):
    _, source, package, env, cache, target, state = setup(tmp_path, monkeypatch)
    saved = spec(target, source.read_text(), saved=True)
    store(cache, env, package, saved, tmp_path, b'saved')
    assert select(cache, saved, env).fresh
    draft = spec(target, 'Unsaved different text', saved=False)
    store(cache, env, package, draft, tmp_path, b'draft')
    assert select(cache, draft, env).fresh
    state['group'] = 'group-new'
    revised = 'Third revision same marker 1.0+'
    choices = (spec(target, revised, saved=True), spec(target, revised, saved=False))
    history = preview_selection.select_image(cache, choices, env)
    assert history.state == 'previous' and history.image == b'draft'
    assert history.artifact_revision_hash == draft.revision.content_hash
    # A slower selection that began earlier cannot overwrite the newer pointer.
    cache.remember_display(preview_requests.cache_identity(draft), preview_requests.cache_identity(saved),
                           'instructor', observed_at=1)
    assert preview_selection.select_image(cache, choices, env).image == b'draft'


def test_legacy_reference_has_same_identity_for_full_and_thumbnail_sizes(tmp_path, monkeypatch):
    _, source, _, env, cache, target, _ = setup(tmp_path, monkeypatch)
    full = slide_snapshot.snapshot_path(target.context, target.bare_id, target.template,
                                        slide_snapshot.FULL_SIZE, target.id_slug)
    thumb = slide_snapshot.snapshot_path(target.context, target.bare_id, target.template,
                                         slide_snapshot.THUMB_SIZE, target.id_slug)
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(b'full reference')
    thumb.write_bytes(b'thumbnail reference')
    request = spec(target, source.read_text())
    canonical = preview_selection.legacy_reference(target.context, target.bare_id, target.template, target.id_slug)
    main = select(cache, request, env, reference=canonical)
    list_row = select(cache, request, env, thumbnail=True, reference=canonical)
    assert main.state == list_row.state == 'reference'
    assert main.image == list_row.image == full
    assert main.artifact_id == list_row.artifact_id == str(full.resolve())
    assert main.representative_view == list_row.representative_view == 'instructor'
    assert main.pdf is None and list_row.pdf is None
    full.unlink()
    assert preview_selection.legacy_reference(target.context, target.bare_id, target.template, target.id_slug) == thumb


def test_accepted_uncached_whole_slide_is_shared_display_history(tmp_path, monkeypatch):
    _, source, _, env, cache, target, state = setup(tmp_path, monkeypatch)
    current = spec(target, source.read_text())
    pdf = tmp_path / 'transient.pdf'
    pdf.write_bytes(b'PDF for during course')
    preview_selection.remember_transient(current, b'transient pixels', pdf)
    full = select(cache, current, env)
    thumb = select(cache, current, env, thumbnail=True)
    assert full.state == thumb.state == 'previous' and not full.fresh
    assert full.artifact_id == thumb.artifact_id
    assert full.image == b'transient pixels' and thumb.image.read_bytes() == full.image
    assert full.pdf == pdf and full.representative_view == 'during-course'
    old_stat = source.stat()
    source.write_text('Other text plus marker 1.0+')
    os.utime(source, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    state['group'] = 'group-new'
    revised = spec(target, source.read_text())
    preview_selection._transient_pdfs.clear()  # simulate restart
    reopened = select(preview_cache.PreviewCache(cache.project_root), revised, env)
    assert reopened.state == 'previous' and reopened.artifact_id == full.artifact_id
    assert reopened.artifact_revision_hash == current.revision.content_hash and reopened.pdf is None


def test_late_uncached_completion_does_not_replace_newer_transient(tmp_path, monkeypatch):
    _, source, _, env, cache, target, _ = setup(tmp_path, monkeypatch)
    request = spec(target, source.read_text())
    preview_selection.remember_transient(request, b'newer pixels', observed_at=200)
    preview_selection.remember_transient(request, b'older pixels', observed_at=100)
    selected = select(cache, request, env)
    assert selected.image == b'newer pixels'


def test_worker_validation_reports_separate_costs_without_rendering(tmp_path, monkeypatch):
    from slidemage import compiler, preview_target

    _, source, package, env, cache, target, _ = setup(tmp_path, monkeypatch)
    request = spec(target, source.read_text())
    store(cache, env, package, request, tmp_path, b'pixels')
    monkeypatch.setattr(compiler, 'build_env', lambda _ctx: env)
    monkeypatch.setattr(preview_target, 'render', lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError('selection must not compile')))
    selected, metrics = preview_selection.validate_captured((request,))
    assert selected.fresh and selected.image == b'pixels'
    assert metrics['validation_seconds'] >= metrics['dependency_hash_seconds'] >= 0
    assert metrics['stability_seconds'] >= 0
    assert metrics['dependency_bytes'] > 0 and metrics['hashed_bytes'] >= metrics['dependency_bytes']
    assert metrics['unstable'] is False
