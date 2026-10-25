# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Several slides of a deck refresh in one document (batch_render): which requests share one, how the PDF is split and
recorded like single renders (a fake TeX; MuPDF writes the PDFs), and with the real TeX tools the same pixels."""
from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import tempfile

import pymupdf
import pytest

from conftest import EXAMPLE
from slidemage import (batch_render, compiler, deck_preview_refresh, deck_scan, preview_batch, preview_cache,
                       preview_requests, preview_target, slide_preview, slide_snapshot)
from slidemage.preview_requests import PreviewRequest, RenderOptions, SourceRevision
from slidemage.project import ProjectContext

VIEWS = ('instructor', 'during-course', 'after-course')


def make_spec(ctx, slug, view='instructor', language='EN', text=None, preamble='PRE', frame=1, hidden=False, **options):
    path = ctx.slides_dir / f'{slug}-current.tex'
    path.parent.mkdir(parents=True, exist_ok=True)
    text = f'Body of {slug}' if text is None else text
    path.write_text(text)
    target = preview_target.PreviewTarget(ctx, 'slide', slug, None, None, None, frame, preamble, ((slug, 1),), hidden)
    return PreviewRequest(target, SourceRevision.capture(path, text), view, language, RenderOptions(saved=True, **options))


class CachedSet:
    """A service that only knows which specs have a verified preview."""
    def __init__(self, cached=()):
        self.cached = set(cached)

    def is_cached(self, spec):
        return spec.target.id_slug in self.cached


def keys(batches):
    return [[key for key, _spec in batch] for batch in batches]


def test_a_document_holds_the_misses_of_one_view_language_and_preamble_up_to_the_size(tmp_path):
    ctx = ProjectContext.at(tmp_path)
    specs = [make_spec(ctx, f'a{n}-EN-X') for n in range(5)]
    specs += [make_spec(ctx, 'b1-EN-X', view='during-course'), make_spec(ctx, 'b2-EN-X', view='during-course'),
              make_spec(ctx, 'c1-EN-X', language='DE'), make_spec(ctx, 'c2-EN-X', language='DE'),
              make_spec(ctx, 'd1-EN-X', preamble='OTHER'), make_spec(ctx, 'd2-EN-X', preamble='OTHER')]
    found = batch_render.groups(CachedSet(), list(enumerate(specs, 1)), 3)
    assert keys(found) == [[1, 2, 3], [4, 5], [6, 7], [8, 9], [10, 11]]
    assert batch_render.groups(CachedSet(), list(enumerate(specs, 1)), 1) == []


def test_a_bare_slide_id_is_once_per_document_and_a_lone_slide_renders_singly(tmp_path):
    ctx = ProjectContext.at(tmp_path)
    specs = [make_spec(ctx, 'aaa-EN-X'), make_spec(ctx, 'aaa-EN-Y'), make_spec(ctx, 'bbb-EN-X'), make_spec(ctx, 'ccc-EN-X'),
             make_spec(ctx, 'ddd-EN-X', view='after-course')]
    found = batch_render.groups(CachedSet(), list(enumerate(specs, 1)), 16)
    assert keys(found) == [[1, 3, 4]]                   # the second aaa has nothing to share a document with; ddd is alone


def test_the_second_showing_of_an_id_goes_to_the_next_document_with_room(tmp_path):
    ctx = ProjectContext.at(tmp_path)
    specs = [make_spec(ctx, slug) for slug in ('aaa-EN-X', 'bbb-EN-X', 'aaa-EN-Y', 'ccc-EN-X', 'ddd-EN-X')]
    assert keys(batch_render.groups(CachedSet(), list(enumerate(specs, 1)), 2)) == [[1, 2], [3, 4]]
    assert keys(batch_render.groups(CachedSet(), list(enumerate(specs, 1)), 3)) == [[1, 2, 4], [3, 5]]


def test_requests_with_a_verified_preview_are_left_out_unless_forced(tmp_path):
    ctx = ProjectContext.at(tmp_path)
    specs = [make_spec(ctx, f'a{n}-EN-X') for n in range(4)]
    service = CachedSet({'a1-EN-X', 'a2-EN-X'})
    assert keys(batch_render.groups(service, list(enumerate(specs, 1)), 8)) == [[1, 4]]
    service = CachedSet({'a1-EN-X'})
    assert keys(batch_render.groups(service, list(enumerate(specs, 1)), 8)) == [[1, 3, 4]]
    forced = [replace(spec, options=replace(spec.options, force=True)) for spec in specs]
    assert keys(batch_render.groups(service, list(enumerate(forced, 1)), 8)) == [[1, 2, 3, 4]]


@pytest.mark.parametrize('change', [
    lambda spec: replace(spec, target=replace(spec.target, hidden=True)),
    lambda spec: replace(spec, target=replace(spec.target, needs_context=('contents',))),
    lambda spec: replace(spec, revision=replace(spec.revision, text='\\SMDeckAgenda')),
    lambda spec: replace(spec, revision=replace(spec.revision, text='see \\ref{x}')),
    lambda spec: replace(spec, capture_error='gone'),
    lambda spec: replace(spec, options=replace(spec.options, presenter=True)),
    lambda spec: replace(spec, options=replace(spec.options, overlay=2)),
    lambda spec: replace(spec, options=replace(spec.options, mode='region')),
    lambda spec: replace(spec, options=replace(spec.options, all_steps=True)),
])
def test_a_slide_that_is_not_a_plain_slide_of_the_deck_renders_singly(tmp_path, change):
    ctx = ProjectContext.at(tmp_path)
    specs = [make_spec(ctx, 'aaa-EN-X'), change(make_spec(ctx, 'bbb-EN-X')), make_spec(ctx, 'ccc-EN-X')]
    assert keys(batch_render.groups(CachedSet(), list(enumerate(specs, 1)), 8)) == [[1, 3]]


def test_a_service_that_cannot_tell_leaves_the_request_to_a_single_render(tmp_path):
    class Broken:
        def is_cached(self, spec):
            if spec.target.id_slug == 'bbb-EN-X':
                raise ValueError('odd')

    ctx = ProjectContext.at(tmp_path)
    specs = [make_spec(ctx, slug) for slug in ('aaa-EN-X', 'bbb-EN-X', 'ccc-EN-X')]
    assert keys(batch_render.groups(Broken(), list(enumerate(specs, 1)), 8)) == [[1, 3]]


# -- splitting the document ---------------------------------------------------------------------

class FakeDocument:
    """Stands for slide_preview.render_slide_texts_to_pdf: pages named by `ids` (one slide id per page), recorded inputs
    `inputs`, in a folder like the real one's."""
    def __init__(self, ids, inputs, monkeypatch):
        self.ids, self.inputs, self.calls, self.folder = ids, inputs, [], None
        monkeypatch.setattr(slide_preview, 'render_slide_texts_to_pdf', self)

    def __call__(self, ctx, slides, view, language, preamble, log=None, cancel=None):
        self.calls.append((slides, view, language, preamble))
        self.folder = Path(tempfile.mkdtemp(prefix='slidemage_preview_'))
        document = pymupdf.open()
        for slide_id in self.ids:
            document.new_page().insert_text((72, 72), f'footer slide id: {slide_id}  step 1')
        pdf = self.folder / 'batch.pdf'
        document.save(pdf)
        pdf.with_suffix('.inputs.json').write_text(json.dumps([str(path) for path in self.inputs]))
        return pdf


@pytest.fixture
def made_folders(monkeypatch):
    """The temporary folders batch_render makes for the slides."""
    real, made = tempfile.mkdtemp, []
    monkeypatch.setattr(tempfile, 'mkdtemp', lambda *args, **kwargs: made.append(real(*args, **kwargs)) or made[-1])
    return made


def split_fixture(tmp_path, monkeypatch, ids):
    ctx = ProjectContext.at(tmp_path / 'project')
    (ctx.root / 'media').mkdir(parents=True)
    for name in ('named.png', 'other.png', 'logo.png', 'alt-text.csv'):
        (ctx.root / 'media' / name).write_bytes(b'x')
    theme = tmp_path / 'framework' / 'theme.tex'
    theme.parent.mkdir()
    theme.write_text('theme')
    monkeypatch.setattr(compiler, 'build_env', lambda _: {'SLIDEMAGE_LATEX': str(theme.parent), 'PATH': '', 'HOME': str(tmp_path)})
    specs = [make_spec(ctx, 'aaa-EN-X', text='\\includegraphics{named}', preamble='\\includegraphics{logo}', frame=3),
             make_spec(ctx, 'bbb-EN-X', text='Plain', preamble='\\includegraphics{logo}', frame=4)]
    inputs = [ctx.root / 'media' / name for name in ('named.png', 'other.png', 'logo.png', 'alt-text.csv')]
    inputs += [ctx.slides_dir / 'bbb-EN-X-current.tex', theme]
    return ctx, list(enumerate(specs, 1)), FakeDocument(ids, inputs, monkeypatch), theme


def test_the_document_is_split_by_the_slide_ids_into_a_pdf_and_the_dependencies_of_each_slide(tmp_path, monkeypatch, made_folders):
    ctx, batch, document, theme = split_fixture(tmp_path, monkeypatch, ['aaa', 'aaa', 'bbb'])
    built = batch_render.build(batch, compiler.CancelToken())
    slides, view, language, preamble = document.calls[0]
    assert [slide[:3] for slide in slides] == [('aaa-EN-X', '\\includegraphics{named}', 3), ('bbb-EN-X', 'Plain', 4)]
    assert (view, language, preamble) == ('instructor', 'en', '\\includegraphics{logo}')
    assert [len(pymupdf.open(built[key].pdf)) for key in (1, 2)] == [2, 1]
    assert built[1].pdf.parent.name.startswith('slidemage_preview_') and built[1].pdf.name == 'aaa-EN-X.pdf'
    media = ctx.root / 'media'
    assert set(built[1].dependencies) == {str(media / 'named.png'), str(media / 'logo.png'), str(media / 'alt-text.csv'), str(theme)}
    assert set(built[2].dependencies) == {str(media / 'logo.png'), str(media / 'alt-text.csv'), str(theme),
                                          str(ctx.slides_dir / 'bbb-EN-X-current.tex')}
    assert built[1].before is built[2].before is not None and not document.folder.exists()


@pytest.mark.parametrize('ids', [['aaa', 'bbb', 'ccc'], ['bbb', 'aaa'], ['aaa', 'bbb', 'aaa'], ['aaa']])
def test_pages_that_are_not_those_of_the_slides_in_order_give_nothing_and_leave_no_folders(tmp_path, monkeypatch, made_folders, ids):
    _ctx, batch, document, _theme = split_fixture(tmp_path, monkeypatch, ids)
    with pytest.raises(RuntimeError, match='not those of its slides'):
        batch_render.build(batch)
    assert made_folders and not any(Path(folder).exists() for folder in made_folders) and not document.folder.exists()


def test_a_document_that_does_not_compile_gives_nothing(tmp_path, monkeypatch):
    _ctx, batch, _document, _theme = split_fixture(tmp_path, monkeypatch, ['aaa', 'bbb'])

    def broken(*args, **kwargs):
        raise RuntimeError('Render failed')

    monkeypatch.setattr(slide_preview, 'render_slide_texts_to_pdf', broken)
    with pytest.raises(RuntimeError, match='Render failed'):
        batch_render.build(batch)


def test_each_slide_of_the_document_is_the_text_a_single_render_would_compile(tmp_path, monkeypatch):
    """Steps, version, omitted and final slides set the same state in both wrappers."""
    wrappers = []
    monkeypatch.setattr(slide_preview, 'compile_and_extract', lambda ctx, text, *args, **kwargs: wrappers.append(text) or Path(text))
    ctx = ProjectContext.at(tmp_path)
    slides = [('aaa-EN-X', 'Plain', 3, None, None, False, False), ('bbb-EN-X', 'Steps', 4, '1,3', '1.2.0', False, False),
              ('ccc-EN-X', 'Omitted', 5, None, None, True, False), ('ddd-EN-X', 'Final', 6, None, '2.0.0', False, True)]
    slide_preview.render_slide_texts_to_pdf(ctx, slides, 'during-course', 'de', 'PRE\n')
    document = wrappers.pop()
    assert 'SMSlideSteps{1,3}' in document and 'setSlideVersion{1.2.0}' in document and 'SMOmittedSlidetrue' in document
    for id_slug, text, frame, steps, version, omitted, final in slides:
        slide_preview.render_slide_text_to_pdf(ctx, id_slug, text, deck_version='during-course', deck_language='de',
                                               preamble_text='PRE\n', frame_number=frame, steps=steps, slide_version=version,
                                               omitted=omitted, final=final, capture_snapshot=False)
        single = wrappers.pop().split('\\decklanguage[de]\n', 1)[1].removesuffix('\\end{document}\n')
        assert single in document, id_slug


# -- render_batch ---------------------------------------------------------------------------------

class Service:
    """A service that renders nothing: it records what it was asked and which requests came with a made PDF."""
    def __init__(self, cached=()):
        self.cached, self.requests = set(cached), []

    def is_cached(self, spec):
        return spec.target.id_slug in self.cached

    def request(self, *args, spec, prebuilt=None, **kwargs):
        self.requests.append((spec, prebuilt))

        def work(token):
            if prebuilt is not None:
                prebuilt.used = True
            return spec.target.source_path.with_suffix('.pdf'), b'image', (), None

        request = preview_requests.RenderRequest(work, lambda: None)
        request.spec = spec
        return request


def fake_build(monkeypatch, fail=False):
    built = []

    def build(batch, cancel=None, log=None):
        built.append([key for key, _spec in batch])
        if fail:
            raise RuntimeError('Render failed')
        return {key: preview_requests.PrebuiltRender(Path(tempfile.mkdtemp(prefix='slidemage_preview_')) / 'x.pdf', (), 'guard')
                for key, _spec in batch}

    monkeypatch.setattr(batch_render, 'build', build)
    return built


def test_requests_to_render_share_documents_and_each_is_recorded_from_its_slides_pdf(tmp_path, monkeypatch):
    ctx = ProjectContext.at(tmp_path)
    specs = tuple(make_spec(ctx, f'a{n}-EN-X') for n in range(5))
    built, events = fake_build(monkeypatch), []
    service = Service(cached={'a1-EN-X'})
    results = preview_batch.render_batch(service, specs, batch_size=3, progress=events.append, workers=1)
    assert built == [[1, 3, 4]]                     # a1 has its preview, a4 would be alone
    taken = {spec.target.id_slug: prebuilt is not None for spec, prebuilt in service.requests}
    assert taken == {'a0-EN-X': True, 'a1-EN-X': False, 'a2-EN-X': True, 'a3-EN-X': True, 'a4-EN-X': False}
    assert [result.status for result in results] == ['rendered'] * 5
    for index in range(1, 6):                       # one 'rendering' before one final event per request
        mine = [event.status for event in events if event.index == index]
        assert mine == ['rendering', 'rendered'], (index, mine)


def test_without_a_batch_size_or_with_everything_current_nothing_is_compiled_together(tmp_path, monkeypatch):
    ctx = ProjectContext.at(tmp_path)
    specs = tuple(make_spec(ctx, f'a{n}-EN-X') for n in range(3))
    built = fake_build(monkeypatch)
    preview_batch.render_batch(Service(), specs)
    preview_batch.render_batch(Service(cached={spec.target.id_slug for spec in specs}), specs, batch_size=8)
    assert built == []


def test_a_document_that_fails_leaves_every_request_to_its_own_render(tmp_path, monkeypatch):
    ctx = ProjectContext.at(tmp_path)
    specs = tuple(make_spec(ctx, f'a{n}-EN-X') for n in range(3))
    built, events = fake_build(monkeypatch, fail=True), []
    service = Service()
    results = preview_batch.render_batch(service, specs, batch_size=8, progress=events.append)
    assert built == [[1, 2, 3]] and all(prebuilt is None for _spec, prebuilt in service.requests)
    assert [result.status for result in results] == ['rendered'] * 3
    assert [[e.status for e in events if e.index == i] for i in (1, 2, 3)] == [['rendering', 'rendered']] * 3


def test_views_that_make_one_image_follow_the_first_which_alone_comes_from_the_document(tmp_path, monkeypatch):
    ctx = ProjectContext.at(tmp_path)
    specs = tuple(make_spec(ctx, slug, view=view) for slug in ('aaa-EN-X', 'bbb-EN-X') for view in VIEWS)
    group = lambda spec, identity=None: (f'group-{spec.target.id_slug}', 'evidence')        # noqa: E731
    monkeypatch.setattr(preview_batch, 'image_group', group)
    built = fake_build(monkeypatch)
    service = Service()
    preview_batch.render_batch(service, specs, batch_size=8, workers=1)
    assert built == [[1, 4]]
    assert [(spec.view, prebuilt is not None) for spec, prebuilt in service.requests if spec.target.id_slug == 'aaa-EN-X'] == [
        ('instructor', True), ('during-course', False), ('after-course', False)]


def test_a_made_pdf_nobody_took_is_removed(tmp_path, monkeypatch):
    class Joined(Service):
        def request(self, *args, spec, prebuilt=None, **kwargs):
            self.requests.append((spec, prebuilt))
            request = preview_requests.RenderRequest(lambda token: (spec.target.source_path.with_suffix('.pdf'), b'image', (), None), lambda: None)
            request.spec = spec         # another request of the same render is in flight: prebuilt stays unused
            return request

    ctx = ProjectContext.at(tmp_path)
    specs = tuple(make_spec(ctx, f'a{n}-EN-X') for n in range(2))
    fake_build(monkeypatch)
    service = Joined()
    preview_batch.render_batch(service, specs, batch_size=8)
    assert [prebuilt.pdf.parent.exists() for _spec, prebuilt in service.requests] == [False, False]


def test_a_cancelled_refresh_compiles_nothing(tmp_path, monkeypatch):
    ctx = ProjectContext.at(tmp_path)
    specs = tuple(make_spec(ctx, f'a{n}-EN-X') for n in range(3))
    built, cancel = fake_build(monkeypatch), compiler.CancelToken()
    cancel.request_stop()
    results = preview_batch.render_batch(Service(), specs, batch_size=8, cancel=cancel)
    assert built == [] and [result.status for result in results] == ['cancelled'] * 3


# -- the service records a made PDF like a render of its own ----------------------------------------

def service_fixture(tmp_path, monkeypatch):
    ctx = ProjectContext.at(tmp_path / 'project')
    framework = tmp_path / 'framework'
    framework.mkdir()
    theme = framework / 'theme.tex'
    theme.write_text('fixture')
    env = {'SLIDEMAGE_LATEX': str(framework), 'PATH': '', 'HOME': str(tmp_path)}
    monkeypatch.setattr(compiler, 'build_env', lambda _: env)
    monkeypatch.setattr(slide_snapshot, 'preview_sequence', lambda _: None)
    monkeypatch.setattr(slide_snapshot, 'prepare_preview_images',
                        lambda pdf, *a: ((b'page', b'tool', b'thumb'), (((200, 100), b'snapshot'),)))
    monkeypatch.setattr(preview_target, 'render_text', lambda *a, **k: pytest.fail('a made PDF was rendered again'))
    return ctx, theme, env


def test_a_made_pdf_is_stored_like_a_render_and_a_later_request_finds_it(tmp_path, monkeypatch):
    ctx, theme, env = service_fixture(tmp_path, monkeypatch)
    spec = make_spec(ctx, 'abc-EN-One')
    service = preview_requests.RenderService()
    assert not service.is_cached(spec)
    folder = Path(tempfile.mkdtemp(prefix='slidemage_preview_'))
    pdf = folder / 'abc-EN-One.pdf'
    pdf.write_bytes(b'PDF')
    before = preview_cache.PreviewCache(ctx.root).begin(env)
    prebuilt = preview_requests.PrebuiltRender(pdf, [str(theme)], before)
    request = service.request(spec.target, spec.revision.text, spec.view, spec.language, lambda _: None, spec=spec, prebuilt=prebuilt)
    request.wait()
    assert prebuilt.used and request.preview_result.status == 'rendered' and request.preview_result.dependencies == (theme,)
    assert request.preview_result.display_png == b'page' and not folder.exists()
    assert service.is_cached(spec)
    later = service.request(spec.target, spec.revision.text, spec.view, spec.language, lambda _: None, spec=spec)
    later.wait()
    assert later.preview_result.status == 'cached' and later.preview_result.display_png == b'page'
    service.close()


def test_a_guard_taken_before_the_input_changed_stores_nothing(tmp_path, monkeypatch):
    ctx, theme, env = service_fixture(tmp_path, monkeypatch)
    spec = make_spec(ctx, 'abc-EN-One')
    service = preview_requests.RenderService()
    pdf = Path(tempfile.mkdtemp(prefix='slidemage_preview_')) / 'abc-EN-One.pdf'
    pdf.write_bytes(b'PDF')
    before = preview_cache.PreviewCache(ctx.root).begin(env)
    theme.write_text('edited while the document compiled')
    prebuilt = preview_requests.PrebuiltRender(pdf, [str(theme)], before)
    service.request(spec.target, spec.revision.text, spec.view, spec.language, lambda _: None, spec=spec, prebuilt=prebuilt).wait()
    assert not service.is_cached(spec)
    service.close()


# -- with the real TeX tools -------------------------------------------------------------------------

def manual_requests(root, count):
    ctx = ProjectContext.at(root)
    deck = next(d for d in deck_scan.scan_decks(ctx) if d.name == 'slidemage-manual')
    seen, found = set(), []
    for spec in deck_preview_refresh.plan(ctx, deck, scope='selected', selected_view='instructor', language='EN'):
        if batch_render.eligible(spec) and spec.target.bare_id not in seen:
            seen.add(spec.target.bare_id)
            found.append(spec)
    stepped = next(spec for spec in found if spec.target.steps)           # a slide with a \\slidestep call (steps)
    return ctx, [spec for spec in found[3:] if spec is not stepped][:count - 1] + [stepped]


@pytest.mark.skipif(shutil.which('latexmk') is None or shutil.which('lualatex') is None, reason='needs a TeX installation')
def test_a_real_document_stores_the_images_and_the_evidence_of_the_single_renders(tmp_path, monkeypatch):
    os.environ.setdefault('SLIDEMAGE_LATEX', str(Path(__file__).resolve().parent.parent / 'latex'))
    results, entries, spy = {}, {}, []
    real_texts, real_text = slide_preview.render_slide_texts_to_pdf, slide_preview.render_slide_text_to_pdf
    monkeypatch.setattr(slide_preview, 'render_slide_texts_to_pdf', lambda *a, **k: spy.append('batch') or real_texts(*a, **k))
    monkeypatch.setattr(slide_preview, 'render_slide_text_to_pdf', lambda *a, **k: spy.append('single') or real_text(*a, **k))
    for name, size in (('batched', 3), ('singles', 1)):
        root = tmp_path / name
        shutil.copytree(EXAMPLE, root)
        ctx, requests = manual_requests(root, 3)
        assert len(requests) == 3
        spy.clear()
        service = preview_requests.RenderService()
        try:
            results[name] = preview_batch.render_batch(service, requests, batch_size=size)
            assert spy == (['batch'] if size > 1 else ['single'] * 3), [r.error for r in results[name]]
            cache, env = preview_cache.PreviewCache(ctx.root), compiler.build_env(ctx)
            entries[name] = [cache.lookup(preview_requests.cache_identity(spec), env) for spec in requests]
            if size > 1:        # a later request of the same slide finds the stored entry, the same pixels
                for spec, result in zip(requests, results[name]):
                    again = service.request(spec.target, spec.revision.text, spec.view, spec.language, lambda _: None, spec=spec)
                    again.wait()
                    assert again.preview_result.status == 'cached' and again.preview_result.display_png == result.display_png
        finally:
            service.close()
    for batched, single in zip(results['batched'], results['singles']):
        assert batched.status == single.status == 'rendered' and batched.display_png and batched.page_images
        assert batched.display_png == single.display_png and batched.secondary_png == single.secondary_png
        assert batched.page_images == single.page_images
    for batched, single in zip(entries['batched'], entries['singles']):
        assert batched is not None and single is not None and batched.page_images == single.page_images
        relative = lambda entry, name: {os.path.relpath(path, tmp_path / name) for path in entry.dependencies  # noqa: E731
                                        if str(tmp_path / name) in str(path)}
        assert relative(single, 'singles') <= relative(batched, 'batched')         # evidence at least as strict
        assert len(pymupdf.open(batched.pdf)) == len(pymupdf.open(single.pdf))
