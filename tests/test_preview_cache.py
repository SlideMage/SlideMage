# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

from slidemage.preview_cache import PreviewCache, file_state, input_state


def fixture(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    source = root / 'slide.tex'
    source.write_text('version 1.2.0+ FIRST')
    framework = tmp_path / 'framework'
    framework.mkdir()
    package = framework / 'theme.tex'
    package.write_text('THEME ONE')
    pdf = tmp_path / 'render.pdf'
    pdf.write_bytes(b'PDF')
    env = {'SLIDEMASTER_LATEX': str(framework), 'PATH': '', 'HOME': str(tmp_path)}
    cache = PreviewCache(root)
    identity = {'source': 'content-hash', 'view': 'instructor', 'options': [False]}
    return cache, identity, env, pdf, source, package


def store(cache, identity, env, pdf, source, package):
    return cache.store(identity, env, pdf=pdf, display_png=b'PNG',
                       page_images=(((100, 50), b'thumbnail'),),
                       dependencies=(str(source), str(package)), render_stamp='2026-10-15 12:00',
                       before=cache.begin(env))


def test_persistent_result_hits_and_keeps_render_time(tmp_path):
    cache, identity, env, pdf, source, package = fixture(tmp_path)
    result = store(cache, identity, env, pdf, source, package)
    assert result is not None
    reopened = PreviewCache(cache.project_root).lookup(identity, env)
    assert reopened.pdf.read_bytes() == b'PDF'
    assert reopened.display_png == b'PNG'
    assert reopened.page_images == (((100, 50), b'thumbnail'),)
    assert reopened.render_stamp == '2026-10-15 12:00'


def test_content_changes_with_identical_version_size_and_mtime_miss(tmp_path):
    cache, identity, env, pdf, source, package = fixture(tmp_path)
    assert store(cache, identity, env, pdf, source, package)
    old = source.stat()
    source.write_text('version 1.2.0+ OTHER')
    os.utime(source, ns=(old.st_atime_ns, old.st_mtime_ns))
    assert cache.lookup(identity, env) is None


def test_external_framework_changes_invalidate_without_source_change(tmp_path):
    cache, identity, env, pdf, source, package = fixture(tmp_path)
    assert store(cache, identity, env, pdf, source, package)
    old = package.stat()
    package.write_text('THEME TWO')
    os.utime(package, ns=(old.st_atime_ns, old.st_mtime_ns))
    assert cache.lookup(identity, env) is None


def test_validation_pass_rejects_same_mtime_dependency_edit_before_publication(tmp_path):
    from slidemage import preview_cache

    cache, identity, env, pdf, source, package = fixture(tmp_path)
    assert store(cache, identity, env, pdf, source, package)
    validation = preview_cache.ValidationPass()
    assert cache.display_lookup(identity, env, validation=validation) is not None
    old = package.stat()
    package.write_text('THEME TWO')  # same byte length
    os.utime(package, ns=(old.st_atime_ns, old.st_mtime_ns))
    assert not validation.stable(cache, env)
    assert validation.stability_bytes > 0 and validation.dependency_bytes > 0


def test_new_shadow_missing_input_and_search_change_miss(tmp_path):
    cache, identity, env, pdf, source, package = fixture(tmp_path)
    missing = cache.project_root / 'optional.tex'
    result = cache.store(identity, env, pdf=pdf, dependencies=(str(package), str(missing)), before=cache.begin(env))
    assert result and cache.lookup(identity, env)
    missing.write_text('new optional')
    assert cache.lookup(identity, env) is None
    missing.unlink()
    assert cache.lookup(identity, env)
    (cache.project_root / package.name).write_text('project shadows framework')
    assert cache.lookup(identity, env) is None
    assert cache.lookup(identity, {**env, 'TEXINPUTS': str(tmp_path)}) is None


def test_corrupt_or_missing_artifacts_are_misses(tmp_path):
    cache, identity, env, pdf, source, package = fixture(tmp_path)
    result = store(cache, identity, env, pdf, source, package)
    result.pdf.write_bytes(b'corrupt')
    assert cache.lookup(identity, env) is None


def test_small_thumbnail_keeps_final_page_identity_and_reads_only_its_blob(tmp_path, monkeypatch):
    import hashlib
    import subprocess
    from io import BytesIO
    from PIL import Image
    from slidemage import preview_cache, preview_requests, preview_selection, preview_target
    from slidemage.project import ProjectContext

    ctx = ProjectContext.at(tmp_path / 'project')
    ctx.slides_dir.mkdir(parents=True)
    source = ctx.slides_dir / 'abc-EN-One-current.tex'
    source.write_text('plain source')
    package = tmp_path / 'framework.tex'
    package.write_text('framework')
    env = {'PATH': '', 'HOME': str(tmp_path)}
    cache = preview_cache.PreviewCache(ctx.root)
    request = preview_requests.PreviewRequest(
        preview_target.for_path(ctx, source), preview_requests.SourceRevision.capture(source),
        'instructor', 'EN')
    identity = preview_requests.cache_identity(request)
    pixels = BytesIO()
    Image.new('RGB', (1600, 900), 'navy').save(pixels, 'PNG')
    pdf = tmp_path / 'source.pdf'
    pdf.write_bytes(b'PDF')
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError('thumbnail derivation must not start a raster process')))
    entry = cache.store(identity, env, pdf=pdf, display_png=pixels.getvalue(), secondary_png=b'other',
                        dependencies=(source, package), before=cache.begin(env))
    assert entry is not None
    thumb = cache.thumbnail_path(identity, env, preview_cache.ValidationPass())
    original_id = hashlib.sha256(pixels.getvalue()).hexdigest()
    assert thumb is not None and thumb != cache.root / 'images' / (original_id + '.png')
    with Image.open(thumb) as image:
        assert image.size == (320, 180)
    assert cache.canonical_image_id(thumb) == original_id
    thumb_bytes = thumb.read_bytes()
    thumb.write_bytes(b'broken thumbnail')
    assert cache.lookup(identity, env) is not None  # full consumers never require the small derivative
    assert cache.thumbnail_path(identity, env, preview_cache.ValidationPass()).read_bytes() == pixels.getvalue()
    thumb.write_bytes(thumb_bytes)
    # A thumbnail remains displayable when a non-display artifact is damaged;
    # whole-result consumers and sequence comparisons still fail validation.
    (entry.directory / 'preview.pdf').write_bytes(b'broken')
    assert cache.thumbnail_path(identity, env, preview_cache.ValidationPass()) == thumb
    main = preview_selection.select_image(cache, (request,), env)
    listed = preview_selection.select_image(cache, (request,), env, thumbnail=True,
                                            validation=preview_cache.ValidationPass())
    assert main.fresh and listed.fresh and main.artifact_id == listed.artifact_id == original_id
    assert main.pdf is None
    assert cache.lookup(identity, env) is None
    thumb.write_bytes(b'broken')
    fallback = cache.thumbnail_path(identity, env, preview_cache.ValidationPass())
    assert fallback is not None and fallback.read_bytes() == pixels.getvalue()
    assert cache.canonical_image_id(fallback) == original_id
    result = store(cache, identity, env, pdf, source, package)
    (result.directory / 'manifest.json').write_text(json.dumps({'schema': 1}))
    assert cache.lookup(identity, env) is None


def test_changed_input_during_compile_is_not_stored(tmp_path):
    cache, identity, env, pdf, source, package = fixture(tmp_path)
    before = cache.begin(env)
    # A different length: an edit of the same size in the same instant can keep Windows' file time unchanged.
    package.write_text('THEME TWO, edited')
    assert cache.store(identity, env, pdf=pdf, dependencies=(str(package),), before=before) is None


def test_prune_preserves_only_live_leased_artifacts(tmp_path):
    cache, identity, env, pdf, source, package = fixture(tmp_path)
    first = store(cache, identity, env, pdf, source, package)
    second = store(cache, identity, env, pdf, source, package)
    with cache.lease(first):
        cache.prune(max_bytes=0)
        assert first.pdf.exists()
        assert not second.pdf.exists()
    cache.prune(max_bytes=0)
    assert not first.pdf.exists()


def test_overlapping_leases_have_independent_locks(tmp_path):
    cache, identity, env, pdf, source, package = fixture(tmp_path)
    entry = store(cache, identity, env, pdf, source, package)
    with cache.lease(entry):
        with cache.lease(entry):
            assert len(list(entry.directory.glob('.lease-*.lock'))) == 2
            cache.prune(max_bytes=0)
            assert entry.pdf.exists()
        cache.prune(max_bytes=0)
        assert entry.pdf.exists()
    cache.prune(max_bytes=0)
    assert not entry.pdf.exists()


def test_unsupported_search_and_missing_recorder_are_not_cacheable(tmp_path):
    cache, identity, env, pdf, source, package = fixture(tmp_path)
    assert cache.begin({**env, 'TEXINPUTS': '$TEXMF//:{one,two}'}) is None
    assert cache.store(identity, env, pdf=pdf, before=cache.begin(env)) is None


def test_matching_sequences_share_blobs_and_keep_view_pdfs(tmp_path):
    from slidemage import preview_cache, preview_raster
    import pymupdf

    cache, identity, env, pdf, source, package = fixture(tmp_path)
    identity['options'] = {'presenter': False, 'mode': 'slide', 'overlay': None}
    with pymupdf.open() as doc:
        for text in ('first', 'last'):
            doc.new_page(width=100, height=50).insert_text((5, 20), text)
        sequence = preview_raster.sequence(doc.tobytes())
    entries = []
    for view in ('instructor', 'during-course', 'after-course'):
        pdf.write_bytes(view.encode())
        entries.append(cache.store({**identity, 'view': view}, env, pdf=pdf,
                       display_png=sequence['images'][-1], raster_sequence=sequence,
                       dependencies=(str(source), str(package)), before=cache.begin(env)))
    assert all(entries)
    assert len(list((cache.root / 'images').glob('*.png'))) == 2
    assert [entry.pdf.read_bytes() for entry in entries] == [b'instructor', b'during-course', b'after-course']
    assert entries[-1].deduplicated_images == 4  # final-page thumbnail shares this already-small blob
    assert cache.equivalent_views(identity, env) == ('instructor', 'during-course', 'after-course')
    assert cache.lookup(identity, env).raster_sequence['signature'] == sequence['signature']
    # An unrelated reveal corruption cannot change the final image shown by
    # either surface, but it invalidates a full sequence/equality consumer.
    manifest = json.loads((entries[0].directory / 'manifest.json').read_text())
    first_reveal = cache.root / 'images' / (manifest['blobs']['sequence-0.png'] + '.png')
    first_reveal.write_bytes(b'corrupt reveal')
    assert cache.display_lookup(identity, env).display_png == sequence['images'][-1]
    assert cache.thumbnail_path(identity, env, preview_cache.ValidationPass()) is not None
    assert cache.lookup(identity, env) is None
    assert cache.equivalent_views(identity, env) == ()
    # An input edit revokes all equality evidence, even unchanged pixel content.
    package.write_text('THEME TWO')
    assert cache.equivalent_views(identity, env) == ()


def test_prune_shared_blobs_honors_live_generation_and_corruption_misses(tmp_path):
    cache, identity, env, pdf, source, package = fixture(tmp_path)
    first = store(cache, identity, env, pdf, source, package)
    second = store(cache, {**identity, 'view': 'during-course'}, env, pdf, source, package)
    with cache.lease(first):
        cache.prune(max_bytes=0)
        assert first.pdf.exists() and not second.pdf.exists()
        assert cache.lookup(identity, env)
        assert len(list((cache.root / 'images').glob('*.png'))) == 2
    blob = next((cache.root / 'images').glob('*.png'))
    blob.write_bytes(b'corruption')
    assert cache.lookup(identity, env) is None
    cache.prune(max_bytes=0)
    assert not list((cache.root / 'images').glob('*.png'))


def count_manifest_reads(monkeypatch):
    reads = []
    original = Path.read_text

    def read_text(self, *args, **kwargs):
        if self.name == 'manifest.json':
            reads.append(self)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', read_text)
    return reads


def test_prune_reads_no_manifest_unless_a_generation_was_deleted(tmp_path, monkeypatch):
    cache, identity, env, pdf, source, package = fixture(tmp_path)
    old = store(cache, identity, env, pdf, source, package)
    survivor = store(cache, {**identity, 'view': 'during-course'}, env, pdf, source, package)
    reads = count_manifest_reads(monkeypatch)
    cache.prune()
    assert not reads and old.pdf.exists() and survivor.pdf.exists()
    os.utime(old.directory / 'manifest.json', (1, 1))
    cache.prune(max_age=3600)
    assert reads == [survivor.directory / 'manifest.json'] and not old.pdf.exists() and survivor.pdf.exists()


def test_prune_after_deleting_one_generation_keeps_survivors_blobs(tmp_path):
    cache, identity, env, pdf, source, package = fixture(tmp_path)
    old = store(cache, identity, env, pdf, source, package)
    shared = store(cache, {**identity, 'view': 'during-course'}, env, pdf, source, package)
    pdf.write_bytes(b'PDF')
    only_old = cache.store({**identity, 'view': 'after-course'}, env, pdf=pdf, display_png=b'ONLY OLD',
                           dependencies=(str(source), str(package)), before=cache.begin(env))
    os.utime(old.directory / 'manifest.json', (1, 1))
    os.utime(only_old.directory / 'manifest.json', (2, 2))
    cache.prune(max_age=3600)
    assert not old.directory.exists() and not only_old.directory.exists() and shared.directory.exists()
    kept = json.loads((shared.directory / 'manifest.json').read_text())['blobs']
    assert {path.stem for path in (cache.root / 'images').glob('*.png')} == set(kept.values())
    assert cache.lookup({**identity, 'view': 'during-course'}, env).display_png == b'PNG'


def test_maybe_prune_runs_first_then_after_the_interval_or_when_over_the_limit(tmp_path, monkeypatch):
    from slidemage import preview_cache
    cache, identity, env, pdf, source, package = fixture(tmp_path)
    clock = [1000.0]
    monkeypatch.setattr(preview_cache.time, 'monotonic', lambda: clock[0])
    runs = []
    original = PreviewCache.prune
    monkeypatch.setattr(PreviewCache, 'prune', lambda self, **kwargs: (runs.append(1), original(self, **kwargs)))
    cache.maybe_prune()
    assert len(runs) == 1
    store(cache, identity, env, pdf, source, package)
    clock[0] += preview_cache.PRUNE_INTERVAL - 1
    cache.maybe_prune()
    assert len(runs) == 1
    clock[0] += 1
    cache.maybe_prune()
    assert len(runs) == 2
    # Inside the interval, the store() estimate going over the limit forces a prune.
    monkeypatch.setattr(preview_cache, 'MAX_BYTES', preview_cache._PRUNED[str(cache.root)][1] + 1)
    cache.maybe_prune()
    assert len(runs) == 2
    store(cache, {**identity, 'view': 'during-course'}, env, pdf, source, package)
    cache.maybe_prune()
    assert len(runs) == 3


def test_sequence_evidence_rejects_malformed_manifests():
    from slidemage.preview_cache import valid_sequence

    for value in (None, [], {'configuration': 'invalid'}, {'configuration': [], 'pages': []},
                  {'configuration': {}, 'pages': [None]},
                  {'configuration': {}, 'pages': [{'size': None, 'pixels': [], 'sha256': ''}]}):
        assert not valid_sequence(value)


def test_frame_and_scope_keep_separate_equivalence_identities(tmp_path):
    import pymupdf
    from slidemage.preview_raster import sequence

    cache, identity, env, pdf, source, package = fixture(tmp_path)
    identity.update(options={'mode': 'slide'}, target={'frame_number': 1})
    with pymupdf.open() as doc:
        doc.new_page(width=100, height=50)
        raster = sequence(doc.tobytes())
    for view, frame in (('instructor', 1), ('during-course', 2)):
        assert cache.store({**identity, 'view': view, 'target': {'frame_number': frame}}, env,
                           pdf=pdf, raster_sequence=raster, dependencies=(str(source), str(package)),
                           before=cache.begin(env))
    assert cache.equivalent_views(identity, env) == ('instructor',)
    for options in ({'mode': 'region'}, {'presenter': True}, {'overlay': 2}, {'mode': 'element'}):
        assert cache.store({**identity, 'options': options}, env, pdf=pdf, raster_sequence=raster,
                           dependencies=(str(source),), before=cache.begin(env)) is None


def test_historical_display_is_exact_and_integrity_checked_but_never_a_fresh_hit(tmp_path):
    cache, identity, env, pdf, source, package = fixture(tmp_path)
    result = store(cache, identity, env, pdf, source, package)
    package.write_text('Changed theme')
    (cache.project_root / 'new-frozen-version.tex').write_text('new file')
    assert cache.lookup(identity, env) is None
    assert cache.previous(identity).display_png == b'PNG'
    assert cache.previous({**identity, 'view': 'during-course'}) is None
    result.pdf.write_bytes(b'corrupt')
    assert cache.previous(identity) is None



# ---- system files: remembered by their stat; the user's own files: always read ----------------------------------

@pytest.fixture
def settled(monkeypatch):
    """Files written by a test are 'racy' (changed so recently that their stat could still move) and never
    remembered; these tests act as if they had been there for a while."""
    from slidemage import preview_cache

    monkeypatch.setattr(preview_cache, 'MEMO_RACY_SECONDS', -1)


def later(path, seconds):
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + seconds * 10 ** 9))


def bytes_read(function, *args):
    from slidemage.preview_metrics import PreviewMetrics

    with PreviewMetrics() as metrics:
        result = function(*args)
    return result, metrics.counters.get('content_bytes_read', 0)


def states_for(tmp_path):
    from slidemage.preview_cache import FileStates

    root = tmp_path / 'project'
    root.mkdir(exist_ok=True)
    system = tmp_path / 'texlive'
    system.mkdir(exist_ok=True)
    return FileStates([root]), root, system


def test_a_file_outside_the_roots_is_read_once_while_its_stat_is_unchanged(settled, tmp_path):
    states, _, system = states_for(tmp_path)
    package = system / 'beamer.sty'
    package.write_text('PACKAGE')
    first, read = bytes_read(states, package)
    assert read == len('PACKAGE')
    second, read = bytes_read(states, package)
    assert (second, read) == (first, 0)


def test_a_file_outside_the_roots_is_hashed_again_when_its_size_or_mtime_changes(settled, tmp_path):
    states, _, system = states_for(tmp_path)
    package = system / 'beamer.sty'
    package.write_text('PACKAGE')
    first = states(package)
    package.write_text('PACKAGE 2')                 # another size
    second, read = bytes_read(states, package)
    assert second != first and second == file_state(package) and read == len('PACKAGE 2')
    package.write_text('PACKAGE 3')                 # the same size, another mtime
    later(package, 10)
    third, read = bytes_read(states, package)
    assert third != second and third == file_state(package) and read == len('PACKAGE 3')


@pytest.mark.skipif(sys.platform == 'win32', reason='ctime is the creation time on Windows')
def test_a_file_outside_the_roots_changed_with_its_mtime_restored_is_hashed_again(settled, tmp_path):
    states, _, system = states_for(tmp_path)
    package = system / 'beamer.sty'
    package.write_text('PACKAGE 1')
    first = states(package)
    old = package.stat()
    package.write_text('PACKAGE 2')
    os.utime(package, ns=(old.st_atime_ns, old.st_mtime_ns))
    assert states(package) != first


def test_a_file_changed_a_moment_ago_is_not_remembered(tmp_path):
    states, _, system = states_for(tmp_path)
    package = system / 'cache.luc'
    package.write_text('LUA')
    assert bytes_read(states, package)[1] == bytes_read(states, package)[1] == 3


def test_a_file_inside_the_roots_is_always_read(settled, tmp_path):
    states, root, _ = states_for(tmp_path)
    theme = root / 'theme.sty'
    theme.write_text('THEME ONE')
    assert bytes_read(states, theme)[1] == bytes_read(states, theme)[1] == len('THEME ONE')
    linked = tmp_path / 'elsewhere.sty'                 # outside, but reached through a link in the project
    linked.write_text('LINKED')
    link = root / 'linked.sty'
    link.symlink_to(linked)
    assert bytes_read(states, link)[1] == bytes_read(states, link)[1] == len('LINKED')


def test_a_missing_file_has_no_state_and_is_not_remembered(settled, tmp_path):
    states, _, system = states_for(tmp_path)
    package = system / 'later.sty'
    assert states(package) is None
    package.write_text('LATER')
    assert states(package) == file_state(package)


def test_remembered_states_have_the_stored_shape(settled, tmp_path):
    states, root, system = states_for(tmp_path)
    package = system / 'beamer.sty'
    package.write_text('PACKAGE')
    states(package)
    assert states(package) == file_state(package) == [str(package.resolve()), hashlib.sha256(b'PACKAGE').hexdigest()]
    assert input_state([package], states) == input_state([package])


def test_the_memo_is_bounded(settled, tmp_path, monkeypatch):
    from slidemage import preview_cache

    monkeypatch.setattr(preview_cache, 'MEMO_LIMIT', 2)
    states, _, system = states_for(tmp_path)
    for index in range(4):
        package = system / f'{index}.sty'
        package.write_text('x')
        states(package)
    assert len(preview_cache._MEMO) <= 2


def test_configuration_state_reads_the_tool_binaries_once(settled, tmp_path):
    from slidemage.preview_cache import configuration_state

    cache, identity, env, pdf, source, package = fixture(tmp_path)
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    latexmk = bin_dir / 'latexmk'
    latexmk.write_bytes(b'x' * 5000)
    latexmk.chmod(0o755)
    env = dict(env, PATH=str(bin_dir))
    first, read = bytes_read(configuration_state, cache.project_root, env)
    assert read >= 5000 and first['tools']['latexmk'] == file_state(latexmk)
    again, read = bytes_read(configuration_state, cache.project_root, env)
    assert again == first and read < 5000
    latexmk.write_bytes(b'y' * 5001)
    assert configuration_state(cache.project_root, env) != first


def test_a_dependency_outside_the_roots_hits_until_it_changes(settled, tmp_path):
    cache, identity, env, pdf, source, package = fixture(tmp_path)
    system = tmp_path / 'texlive'
    system.mkdir()
    beamer = system / 'beamer.sty'
    beamer.write_text('BEAMER 1')
    assert cache.store(identity, env, pdf=pdf, display_png=b'PNG', dependencies=(str(source), str(beamer)),
                       before=cache.begin(env))
    entry, read = bytes_read(cache.lookup, identity, env)
    assert entry is not None and read < 1000 and str(beamer) in entry.dependencies
    assert PreviewCache(cache.project_root).lookup(identity, env) is not None
    beamer.write_text('BEAMER 2 (an update)')
    assert cache.lookup(identity, env) is None


def test_the_tool_lookup_is_remembered_per_path(tmp_path, monkeypatch):
    from slidemage import preview_cache

    calls = []
    monkeypatch.setattr(preview_cache.shutil, 'which', lambda name, path=None: calls.append((name, path)) or f'/bin/{name}')
    assert preview_cache.find_tool('lualatex', 'A') == preview_cache.find_tool('lualatex', 'A') == '/bin/lualatex'
    preview_cache.find_tool('lualatex', 'B')
    assert calls == [('lualatex', 'A'), ('lualatex', 'B')]
