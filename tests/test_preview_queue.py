# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Newest-request publication, source/context changes, and image reuse."""

import gc
import hashlib
from types import SimpleNamespace
import threading
import time
from threading import Thread as WorkerThread

import pymupdf
import pytest
from PySide6.QtTest import QTest

from slidemage import preview_target, slide_snapshot
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.workspace import preview_view
from slidemage.ui.workspace.state import WorkspaceState
from slidemage.project import ProjectContext
from conftest import EXAMPLE_PROJECT


@pytest.fixture(autouse=True)
def collect_garbage_first():
    """Qt wrappers that earlier tests left as cyclic garbage must not be freed by a render worker's garbage
    collection: PySide then deletes them on the main thread after Qt did, and crashes the run."""
    gc.collect()


@pytest.fixture
def pane(qapp, tmp_path, monkeypatch, ctx):
    logged, launched = [], []
    app = SimpleNamespace(
        theme=ThemeManager(),
        log=logged.append,
        project=ctx,
    )
    ctx = ProjectContext.at(tmp_path)
    monkeypatch.setattr(preview_target, "cached_image", lambda target: None)
    # Thread creation is controlled; finishing a job exercises the real worker/GUI handoff.
    monkeypatch.setattr(
        preview_view,
        "Thread",
        lambda **kw: SimpleNamespace(start=lambda: launched.append(kw["args"])),
    )
    buffer = ["BODY"]
    view = preview_view.PreviewPane(app, WorkspaceState(ctx), lambda: (buffer[0], ""))
    view._background_validation = False  # these worker/pane tests control the synchronous selector
    path = tmp_path / "slides" / "abc-EN-One-current.tex"
    path.parent.mkdir()
    path.write_text("BODY")
    target = preview_target.for_path(ctx, path)
    view.show_slide(target, None, "One", "")
    view.launched, view.buffer, view.logged = launched, buffer, logged
    yield view, target, path
    # Destroy the Qt objects on the GUI thread before later HTTP workers can
    # trigger cyclic collection of this fixture's widgets and pixmaps.
    from PySide6.QtCore import QCoreApplication, QEvent
    view._dispose()
    view._pixmaps.clear()
    view._adhoc = None
    view._page.pixmap = None
    from shiboken6 import isValid
    if isValid(view):
        view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()


def pdf_at(path, text="hello", height=180):
    with pymupdf.open() as doc:
        page = doc.new_page(width=320, height=height)
        if text:
            page.insert_text((30, 30), text)
        doc.save(path)
    return path


def test_three_requests_compile_only_first_and_latest_and_publish_latest(
    pane, tmp_path, monkeypatch
):
    view, target, _ = pane
    publications = []
    monkeypatch.setattr(
        slide_snapshot, "publish_preview", lambda *a: publications.append(a)
    )
    pdf1, pdf2 = (
        pdf_at(tmp_path / "old.pdf", "old"),
        pdf_at(tmp_path / "new.pdf", "new"),
    )
    first = view._job(target, snapshot_template=target.template)
    newest = view._job(target, snapshot_template=target.template)
    view._start(lambda: pdf1, first)
    view._start(lambda: pytest.fail("superseded middle request ran"), view._job(target))
    view._start(lambda: pdf2, newest)
    assert len(view.launched) == 1 and view._busy
    view._run(*view.launched[0])
    assert len(view.launched) == 2 and not publications and view._last_pdf is None
    view._run(*view.launched[1])
    assert view._last_pdf == pdf2 and len(publications) == 1 and not view._busy


@pytest.mark.parametrize(
    "change", ["slide", "view", "language", "preamble", "disk", "buffer"]
)
def test_obsolete_results_never_replace_the_page_or_publish_snapshots(
    pane, tmp_path, monkeypatch, change
):
    view, target, path = pane
    publications = []
    monkeypatch.setattr(
        slide_snapshot, "publish_preview", lambda *a: publications.append(a)
    )
    job = view._job(
        target,
        snapshot_template=target.template,
        buffer_text="BODY" if change == "buffer" else None,
    )
    pdf = pdf_at(tmp_path / "old.pdf")
    view._start(lambda: pdf, job)
    if change == "slide":
        view.show_slide(
            preview_target.for_path(EXAMPLE_PROJECT, tmp_path / "slides" / "bbb-EN-Two-current.tex"),
            None,
            "Two",
            "",
        )
        assert "No preview" in view._page.message
        assert not view._page.render_button.isHidden()
        assert view._busy  # the obsolete compiler is still finishing in the background
    elif change == "view":
        view.state.set_view("after-course")
    elif change == "language":
        view.state.set_language("DE")
    elif change == "preamble":
        from dataclasses import replace

        view.show_slide(
            replace(target, preamble_text="changed theme settings"), None, "One", ""
        )
    elif change == "disk":
        path.write_text("different saved content")
    else:
        view.buffer[0] = "newer unsaved content"
    view._run(*view.launched[0])
    assert not publications and view._last_pdf is None and not view._busy


def test_old_error_is_ignored_but_current_error_keeps_previous_preview(pane, tmp_path):
    view, target, _ = pane
    pdf = pdf_at(tmp_path / "good.pdf")
    view._last_pdf = pdf

    def broken():
        raise RuntimeError("broken edit")

    view._start(broken, view._job(target))
    view._start(broken, view._job(target))
    view._run(*view.launched[0])
    assert view._error == "" and view._busy
    view._run(*view.launched[1])
    assert "broken edit" in view._error and view._last_pdf == pdf


def test_repeated_automatic_requests_are_debounced_and_can_be_invalidated(
    pane, tmp_path
):
    view, target, _ = pane
    work = lambda: pdf_at(tmp_path / "p.pdf")
    view._start(work, view._job(target), debounce=True)
    view._start(work, view._job(target), debounce=True)
    assert not view.launched
    QTest.qWait(350)
    assert len(view.launched) == 1
    view._start(work, view._job(target), debounce=True)
    view.state.set_language("DE")
    view._run(*view.launched[0])
    QTest.qWait(350)
    assert len(view.launched) == 1 and not view._busy


def test_presentation_opens_pdf_without_rasterizing(pane, tmp_path, monkeypatch):
    view, target, _ = pane
    pdf = pdf_at(tmp_path / "presenter.pdf")
    opened = []
    monkeypatch.setattr(preview_view.slide_preview, "open_pdf", opened.append)
    monkeypatch.setattr(
        slide_snapshot,
        "prepare_preview",
        lambda *a: pytest.fail("presenter rasterized"),
    )
    view._start(lambda: pdf, view._job(target, external=True))
    view._run(*view.launched[0])
    assert opened == [pdf]


def test_open_pdf_for_shared_buffer_image_requests_exact_buffer_view(pane, monkeypatch):
    from PySide6.QtGui import QPixmap
    from slidemage.preview_requests import RenderRequest

    view, target, path = pane
    view.buffer[0] = 'UNSAVED DRAFT'
    key = (target.key, view.state.view, view.language)
    view._adhoc = (key, QPixmap(2, 2), 'Rendered from the editor buffer')
    view._adhoc_text = view.buffer[0]
    view._adhoc_spec = None
    view._page.show_image(view._adhoc[1])
    captured = []

    def request(*args, **kwargs):
        captured.append((args, kwargs))
        result = RenderRequest(lambda _: None, lambda: None)
        result.spec = None
        return result

    monkeypatch.setattr(view._renders, 'request', request)
    view._open_pdf()
    assert len(captured) == 1
    args, kwargs = captured[0]
    assert args[1] == 'UNSAVED DRAFT' and args[2] == view.state.view
    assert kwargs['saved'] is False and kwargs['require_pdf'] is True
    assert path.read_text() == 'BODY'


def test_failed_alias_retry_cannot_publish_representative_image(pane, monkeypatch):
    from slidemage import preview_requests

    view, target, path = pane
    revision = preview_requests.SourceRevision.capture(path)
    own = preview_requests.PreviewRequest(target, revision, view.state.view, 'EN')
    foreign = preview_requests.PreviewRequest(target, revision, 'during-course', 'EN')
    source = preview_requests.RenderRequest(lambda _: (path, b'wrong image', (), None), lambda: None)
    source.spec = foreign
    retry = preview_requests.RenderRequest(lambda _: (_ for _ in ()).throw(RuntimeError('retry failed')),
                                           lambda: None)
    retry.spec = own
    monkeypatch.setattr(preview_requests, 'image_group', lambda *a: None)
    alias = preview_requests._ImageConsumer(source, own, ('group', 'evidence'), lambda: retry)
    with pytest.raises(RuntimeError, match='retry failed'):
        alias.wait()
    job = view._job(target, revision_text='BODY', remote=True)
    job.request = alias
    job.generation = view._generation
    view._remote[alias] = job
    view.finish_render(alias)
    assert view._last_pdf is None and view._page.pixmap is None
    assert 'retry failed' in view._error


def test_open_pdf_for_cached_buffer_alias_keeps_captured_revision(pane, tmp_path, monkeypatch):
    from slidemage import preview_requests

    view, target, path = pane
    view.buffer[0] = 'UNSAVED DRAFT'
    spec = preview_requests.PreviewRequest(
        target, preview_requests.SourceRevision.capture(path, view.buffer[0]), view.state.view, 'EN',
        preview_requests.RenderOptions(saved=False))
    png = slide_snapshot.page_png(pdf_at(tmp_path / 'cached.pdf'), 1280)
    monkeypatch.setattr(view._renders, 'selected_preview',
                        lambda *a, **kw: SimpleNamespace(state='verified', fresh=True,
                                                         image=png, pdf=None, request=spec))
    view._refresh()
    assert view._page.pixmap is not None and view._adhoc is None
    captured = []

    def request(*args, **kwargs):
        captured.append((args, kwargs))
        result = preview_requests.RenderRequest(lambda _: None, lambda: None)
        result.spec = spec
        return result

    monkeypatch.setattr(view._renders, 'request', request)
    view._open_pdf()
    assert len(captured) == 1
    args, kwargs = captured[0]
    assert args[1] == 'UNSAVED DRAFT' and kwargs['spec'] is spec and kwargs['require_pdf']
    assert path.read_text() == 'BODY'


def test_open_pdf_after_previous_image_uses_current_editor_buffer(pane, tmp_path, monkeypatch):
    from slidemage import preview_requests

    view, target, path = pane
    view.buffer[0] = 'CURRENT UNSAVED DRAFT'
    png = slide_snapshot.page_png(pdf_at(tmp_path / 'previous.pdf'), 1280)
    monkeypatch.setattr(view._renders, 'selected_preview',
                        lambda *a, **kw: SimpleNamespace(state='previous', fresh=False,
                                                         image=png, pdf=None, request=None,
                                                         note='Previous render'))
    view._refresh()
    assert view._page.pixmap is not None
    captured = []

    def request(*args, **kwargs):
        captured.append((args, kwargs))
        result = preview_requests.RenderRequest(lambda _: None, lambda: None)
        result.spec = None
        return result

    monkeypatch.setattr(view._renders, 'request', request)
    view._open_pdf()
    assert len(captured) == 1
    args, kwargs = captured[0]
    assert args[1] == 'CURRENT UNSAVED DRAFT'
    assert kwargs['saved'] is False and kwargs['spec'] is None and kwargs['require_pdf']
    assert path.read_text() == 'BODY'


def test_open_pdf_ignores_older_whole_slide_adhoc_after_shared_selection(pane, tmp_path, monkeypatch):
    from slidemage import preview_requests

    view, target, path = pane
    view.buffer[0] = 'NEWER BUFFER'
    old = preview_requests.PreviewRequest(
        target, preview_requests.SourceRevision.capture(path, 'OLDER BUFFER'), 'instructor', 'EN',
        preview_requests.RenderOptions(saved=False))
    key = (target.key, 'instructor', 'EN')
    view._adhoc = (key, preview_view.QPixmap(), 'older whole slide')
    view._adhoc_spec = old
    view._adhoc_text = 'OLDER BUFFER'
    newer = preview_requests.PreviewRequest(
        target, preview_requests.SourceRevision.capture(path, view.buffer[0]), 'instructor', 'EN',
        preview_requests.RenderOptions(saved=False))
    png = slide_snapshot.page_png(pdf_at(tmp_path / 'shared.pdf'), 1280)
    monkeypatch.setattr(view._renders, 'selected_preview',
                        lambda *a, **kw: SimpleNamespace(state='verified', fresh=True,
                                                         image=png, pdf=None, request=newer))
    view._refresh()
    assert view._page.pixmap is not None
    captured = []

    def request(*args, **kwargs):
        captured.append((args, kwargs))
        result = preview_requests.RenderRequest(lambda _: None, lambda: None)
        result.spec = newer
        return result

    monkeypatch.setattr(view._renders, 'request', request)
    view._open_pdf()
    assert len(captured) == 1
    args, kwargs = captured[0]
    assert args[1] == 'NEWER BUFFER' and kwargs['spec'] is newer


def test_background_selection_keeps_pixels_during_revalidation_and_records_latency(pane, tmp_path, monkeypatch, qapp):
    import time
    from threading import Event
    from slidemage.preview_selection import SelectedImage

    view, target, _ = pane
    png = slide_snapshot.page_png(pdf_at(tmp_path / 'async.png.pdf'), 1280)
    started, release = Event(), Event()

    def validate(specs, _reference):
        started.set()
        assert release.wait(3)
        spec = specs[0]
        return SelectedImage('verified', png, spec, 'final-image', spec.view, None, '',
                             artifact_revision_hash=spec.revision.content_hash), {
                                 'validation_seconds': 0.1, 'dependency_bytes': 12}

    monkeypatch.setattr(preview_view, 'validate_captured', validate)
    view._background_validation = True
    view._refresh()
    assert started.wait(2)
    ticked = []
    preview_view.QTimer.singleShot(0, lambda: ticked.append(True))
    qapp.processEvents()
    assert ticked  # validation has not blocked the event loop
    release.set()
    deadline = time.monotonic() + 3
    while view._page.pixmap is None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(.01)
    assert view._page.pixmap is not None and view._image_selection.fresh
    assert view._selection_metrics['dependency_bytes'] == 12
    assert view._selection_metrics['gui_event_latency_seconds'] >= 0
    # A periodic recheck of the same text keeps the verified image current while it runs (no flickering status).
    view._selection_validated_at = 0
    view._refresh()
    assert view._page.pixmap is not None and view._image_selection.state == 'verified'
    assert view._selection_pending is not None and not view._status_chip.isVisibleTo(view)


def test_selection_keeps_pixels_when_prune_holds_cache_lock(pane, tmp_path, qapp):
    import hashlib
    import time
    from threading import Event

    from slidemage.filelock import build_lock
    from slidemage.preview_cache import CachedPreview, PreviewCache
    from slidemage.preview_requests import PreviewRequest, RenderOptions, SourceRevision
    from slidemage.preview_selection import SelectedImage

    view, target, path = pane
    png = slide_snapshot.page_png(pdf_at(tmp_path / 'locked.pdf'), 1280)
    generation = tmp_path / 'generation'
    generation.mkdir()
    pdf = pdf_at(generation / 'document.pdf')
    entry = CachedPreview(generation, pdf, png, None, (), (), None)
    revision = SourceRevision.capture(path, 'BODY')
    spec = PreviewRequest(target, revision, view.state.view, view.language,
                          RenderOptions(saved=True))
    selected = SelectedImage('verified', png, spec, 'locked-image', spec.view, pdf, '',
                             cache_entry=entry, artifact_revision_hash=revision.content_hash)
    key = (view._generation, target.key, spec.view, spec.language,
           hashlib.sha256(b'BODY').hexdigest(), 'slide', None)
    view._selection_ticket += 1
    view._selection_pending_key = key
    view._background_validation = True
    held, release = Event(), Event()
    maintenance = PreviewCache(target.context.root).root / 'maintenance.lock'

    def hold_prune_lock():
        with build_lock(maintenance):
            held.set()
            release.wait(3)

    worker = WorkerThread(target=hold_prune_lock)
    worker.start()
    try:
        assert held.wait(2)
        ticked = []
        preview_view.QTimer.singleShot(0, lambda: ticked.append(True))
        started = time.perf_counter()
        view._on_selection_finished((view._selection_ticket, key, (selected, {})))
        qapp.processEvents()
        assert time.perf_counter() - started < .15
        assert ticked and not release.is_set()
        assert view._page.pixmap is not None
        assert view._selection_result.pdf is None
        assert view._renders._display_lease is None
    finally:
        release.set()
        worker.join(timeout=3)


def test_background_selection_rejects_older_buffer_completion(pane, tmp_path, monkeypatch, qapp):
    import time
    from threading import Event
    from slidemage.preview_selection import SelectedImage

    view, _, _ = pane
    first_started, release = Event(), Event()
    png = slide_snapshot.page_png(pdf_at(tmp_path / 'async-buffer.pdf'), 1280)

    def validate(specs, _reference):
        spec = specs[0]
        if spec.revision.text == 'BODY':
            first_started.set()
            assert release.wait(3)
        return SelectedImage('verified', png, spec, spec.revision.content_hash, spec.view, None, '',
                             artifact_revision_hash=spec.revision.content_hash), {}

    monkeypatch.setattr(preview_view, 'validate_captured', validate)
    view._background_validation = True
    view._refresh()
    assert first_started.wait(2)
    view.buffer[0] = 'CHANGED BUFFER'
    view._refresh()
    release.set()
    deadline = time.monotonic() + 3
    while (view._image_selection is None or view._image_selection.request is None or
           view._image_selection.request.revision.text != 'CHANGED BUFFER') and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(.01)
    assert view._image_selection.request.revision.text == 'CHANGED BUFFER'


def test_background_selection_rechecks_same_mtime_disk_edit(pane, tmp_path, monkeypatch, qapp):
    import os
    import time
    from threading import Event
    from slidemage.preview_selection import SelectedImage

    view, _, path = pane
    view._buffer = lambda: None
    first_started, release = Event(), Event()
    png = slide_snapshot.page_png(pdf_at(tmp_path / 'async-disk.pdf'), 1280)
    calls = []

    def validate(specs, _reference):
        spec = specs[0]
        calls.append(spec.revision.text)
        if len(calls) == 1:
            first_started.set()
            assert release.wait(3)
        return SelectedImage('verified', png, spec, spec.revision.content_hash, spec.view, None, '',
                             artifact_revision_hash=spec.revision.content_hash), {}

    monkeypatch.setattr(preview_view, 'validate_captured', validate)
    view._background_validation = True
    view._refresh()
    assert first_started.wait(2)
    before = path.stat()
    path.write_text('EDIT')
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    release.set()
    deadline = time.monotonic() + 3
    while (len(calls) < 2 or view._selection_pending is not None) and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(.01)
    assert calls == ['BODY', 'EDIT']
    assert view._image_selection.request.revision.text == 'EDIT'


def test_newly_accepted_image_displaces_pending_validation_immediately(pane, tmp_path, monkeypatch, qapp):
    import time
    from threading import Event
    from slidemage import preview_requests
    from slidemage.preview_selection import SelectedImage

    view, target, path = pane
    old = slide_snapshot.page_png(pdf_at(tmp_path / 'old-pending.pdf', 'old'), 1280)
    new = slide_snapshot.page_png(pdf_at(tmp_path / 'new-accepted.pdf', 'new'), 1280)
    started, release = Event(), Event()
    calls = []

    def validate(specs, _reference):
        calls.append(1)
        if len(calls) == 1:
            started.set()
            assert release.wait(3)
        spec = specs[0]
        image = old if len(calls) == 1 else new
        return SelectedImage('verified', image, spec, 'accepted' if image == new else 'old', spec.view, None, ''), {}

    monkeypatch.setattr(preview_view, 'validate_captured', validate)
    view._background_validation = True
    view._refresh()
    assert started.wait(2)
    spec = preview_requests.PreviewRequest(
        target, preview_requests.SourceRevision.capture(path, view.buffer[0]), 'instructor', 'EN',
        preview_requests.RenderOptions(saved=False))
    view._show_accepted_while_validating(spec, new)
    view._refresh()
    assert view._image_selection.image == new and view._page.pixmap is not None
    release.set()
    deadline = time.monotonic() + 3
    while (len(calls) < 2 or view._selection_pending is not None) and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(.01)
    assert len(calls) == 2 and view._image_selection.image == new


def test_scoped_background_validation_runs_off_gui_thread(pane, tmp_path, monkeypatch, qapp):
    import time
    from threading import Event
    from slidemage import preview_requests
    from slidemage.preview_selection import SelectedImage

    view, target, path = pane
    png = slide_snapshot.page_png(pdf_at(tmp_path / 'scoped-async.pdf'), 1280)
    pixmap = preview_view.QPixmap()
    assert pixmap.loadFromData(png)
    spec = preview_requests.PreviewRequest(
        target, preview_requests.SourceRevision.capture(path, 'BODY'), 'instructor', 'EN',
        preview_requests.RenderOptions(saved=False, mode='region', overlay=2))
    view._adhoc = ((target.key, 'instructor', 'EN'), pixmap, 'Scoped')
    view._adhoc_spec = spec
    view._adhoc_text = 'BODY'
    started, release = Event(), Event()

    def validate(request):
        started.set()
        assert release.wait(3)
        return SelectedImage('verified', png, request, 'scoped', request.view, None, ''), {}

    monkeypatch.setattr(preview_view, 'validate_scoped', validate)
    monkeypatch.setattr(view._renders, 'cached_spec', lambda *_: pytest.fail('GUI synchronous scoped validation'))
    view._background_validation = True
    view._refresh()
    assert started.wait(2) and view._page.pixmap is not None
    release.set()
    deadline = time.monotonic() + 3
    while (view._image_selection is None or not view._image_selection.fresh) and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(.01)
    assert view._image_selection.fresh


def test_background_validation_shutdown_discards_late_completion(pane, monkeypatch, qapp):
    from threading import Event

    view, _, _ = pane
    started, release = Event(), Event()

    def validate(_specs, _reference):
        started.set()
        assert release.wait(3)
        return None, {}

    monkeypatch.setattr(preview_view, 'validate_captured', validate)
    view._background_validation = True
    view._refresh()
    assert started.wait(2)
    view._dispose()
    release.set()
    qapp.processEvents()
    assert view._closed and view._selection_result is None


def test_previous_whole_slide_selection_outranks_older_ad_hoc_draft(pane, tmp_path, monkeypatch):
    from slidemage import preview_cache, preview_requests, preview_selection

    view, target, path = pane
    env = {'PATH': '', 'HOME': str(tmp_path)}
    monkeypatch.setattr(preview_requests.compiler, 'build_env', lambda _: env)
    saved_pdf = pdf_at(tmp_path / 'newer-saved.pdf', 'new saved image')
    saved_png = slide_snapshot.page_png(saved_pdf)
    old_pixmap = preview_view.QPixmap()
    assert old_pixmap.loadFromData(slide_snapshot.page_png(pdf_at(tmp_path / 'old-draft.pdf', 'old draft')))
    cache = preview_cache.PreviewCache(target.context.root)
    saved = preview_requests.PreviewRequest(target, preview_requests.SourceRevision.capture(path),
                                             'instructor', 'EN', preview_requests.RenderOptions(saved=True))
    assert cache.store(preview_requests.cache_identity(saved), env, pdf=saved_pdf,
                       display_png=saved_png, dependencies=(path,), before=cache.begin(env))
    assert view._renders.selected_preview(target, 'BODY', 'instructor', 'EN').fresh
    key = (target.key, 'instructor', 'EN')
    view._adhoc = (key, old_pixmap, 'Older draft')
    view._adhoc_text = 'OLD DRAFT'
    view._adhoc_spec = preview_requests.PreviewRequest(
        target, preview_requests.SourceRevision.capture(path, 'OLD DRAFT'), 'instructor', 'EN')
    path.write_text('EDIT')  # newer source, unchanged four-byte size
    view.buffer[0] = 'EDIT'
    image, fresh, note = view._image(target)
    selected = view._image_selection
    list_choice = preview_selection.select_image(cache, (
        preview_requests.PreviewRequest(target, preview_requests.SourceRevision.capture(path),
                                        'instructor', 'EN', preview_requests.RenderOptions(saved=True)),), env,
        thumbnail=True)
    assert not fresh and 'Previous render' in note
    assert image.cacheKey() != old_pixmap.cacheKey()
    assert selected.state == list_choice.state == 'previous'
    assert selected.artifact_id == list_choice.artifact_id


def test_real_worker_leaves_qt_event_loop_responsive(qapp, pane, tmp_path, monkeypatch):
    view, target, _ = pane
    monkeypatch.setattr(preview_view, "Thread", WorkerThread)
    started, release = threading.Event(), threading.Event()
    pdf = pdf_at(tmp_path / "worker.pdf")  # MuPDF stays out of the worker thread.

    def work():
        started.set()
        assert release.wait(3)
        return pdf

    job = view._job(target)
    view._start(work, job)
    assert started.wait(1)
    QTest.qWait(20)
    assert view._busy and view._last_pdf is None
    release.set()
    for _ in range(100):
        QTest.qWait(10)
        if not view._busy:
            break
    assert not view._busy and view._last_pdf is not None


@pytest.mark.parametrize("height, text", [(180, "formula and text"), (240, "")], ids=["16:9", "4:3"])
def test_prepared_images_preserve_pixels_aspect_ratio_and_cache_by_pdf_content(
    tmp_path, monkeypatch, height, text,
):
    pdf = pdf_at(tmp_path / "preview.pdf", text, height)
    slide_snapshot._PNG_CACHE.clear()
    images1, snapshots1 = slide_snapshot.prepare_preview(pdf, True)
    assert [size for size, _ in snapshots1] == [
        slide_snapshot.FULL_SIZE,
        slide_snapshot.THUMB_SIZE,
    ]
    display = pymupdf.Pixmap(images1)
    assert (display.width, display.height) == (
        slide_snapshot.FULL_SIZE[0], slide_snapshot.FULL_SIZE[0] * height // 320,
    )
    with pymupdf.open(pdf) as doc:
        page = doc[-1]
        for (width, pixel_height), png in snapshots1:
            original = page.get_pixmap(
                matrix=pymupdf.Matrix(
                    width / page.rect.width, pixel_height / page.rect.height
                )
            )
            current = pymupdf.Pixmap(png)
            assert (current.width, current.height) == (width, pixel_height)
            assert (current.width, current.height, current.samples) == (
                original.width, original.height, original.samples,
            )
    # A second request must not enter the raster process.
    from slidemage import preview_raster_client
    original_render = preview_raster_client.render
    monkeypatch.setattr(
        preview_raster_client,
        "render",
        lambda *a: pytest.fail("cache miss for unchanged PDF"),
    )
    assert slide_snapshot.prepare_preview(pdf, True) == (images1, snapshots1)
    monkeypatch.setattr(preview_raster_client, "render", original_render)
    pdf.unlink()
    pdf_at(pdf, "changed in the same path", height)
    assert slide_snapshot.prepare_preview(pdf, True)[0] != images1


def test_session_pixmaps_are_bounded_and_keep_the_most_recent(pane, tmp_path):
    from PySide6.QtGui import QPixmap

    view, target, _ = pane
    pixmap = QPixmap(1, 1)
    for i in range(13):
        view._pixmaps.put((("old", i), "instructor", "EN"), pixmap, 0, None, "")
    pdf = pdf_at(tmp_path / "recent.pdf")
    view._start(lambda: pdf, view._job(target))
    view._run(*view.launched[0])
    assert len(view._pixmaps) == 12
    assert (target.key, "instructor", "EN") in view._pixmaps
    assert (("old", 0), "instructor", "EN") not in view._pixmaps


def test_disk_snapshot_is_best_effort_not_verified_context(pane, tmp_path, monkeypatch):
    from PySide6.QtGui import QPixmap
    view, target, _ = pane
    snapshot = tmp_path / "snapshot.png"
    pixmap = QPixmap(320, 180)
    pixmap.fill()
    pixmap.save(str(snapshot))
    monkeypatch.setattr(preview_view, "legacy_reference", lambda *a: snapshot)
    assert not view._image(target)[1]


def test_actual_parent_destruction_closes_lifetime_and_discards_worker_result(
    qapp, pane, tmp_path, monkeypatch,
):
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QWidget
    view, target, _ = pane
    parent = QWidget()
    view.setParent(parent)
    started, release = threading.Event(), threading.Event()
    output = tmp_path / "slidemage_preview_closed" / "preview.pdf"
    output.parent.mkdir()
    output.write_bytes(b"finished PDF")
    threads = []

    def thread(**kwargs):
        result = WorkerThread(**kwargs)
        threads.append(result)
        return result

    def work():
        started.set()
        assert release.wait(3)
        return output

    monkeypatch.setattr(preview_view, "Thread", thread)
    monkeypatch.setattr(slide_snapshot, "prepare_preview", lambda *a: pytest.fail("raster after destruction"))
    monkeypatch.setattr(slide_snapshot, "publish_preview", lambda *a: pytest.fail("published after destruction"))
    monkeypatch.setattr(preview_view.slide_preview, "open_pdf", lambda *a: pytest.fail("opened after destruction"))
    view._start(work, view._job(target))
    assert started.wait(1)
    view._start(lambda: pytest.fail("pending job ran after destruction"), view._job(target))
    try:
        parent.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert view._closed and view._pending is None
    finally:
        release.set()
        threads[0].join(3)
    assert not threads[0].is_alive() and not output.exists() and len(threads) == 1


def test_destroyed_pane_discards_a_completion_already_queued_to_qt(pane, tmp_path, monkeypatch):
    from PySide6.QtCore import QCoreApplication, QEvent
    view, target, _ = pane
    output = tmp_path / "slidemage_preview_queued" / "preview.pdf"
    output.parent.mkdir()
    output.write_bytes(b"finished PDF")
    monkeypatch.setattr(slide_snapshot, "prepare_preview", lambda *a: (b"", ()))
    job = view._job(target)
    view._start(lambda: output, job)
    thread = WorkerThread(target=view._run, args=view.launched[0])
    thread.start()
    thread.join(3)  # Deliberately do not deliver the queued completion yet.
    assert not thread.is_alive() and view._last_pdf is None and output.exists()
    from shiboken6 import isValid
    if isValid(view):
        view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert view._closed and not output.exists()


def test_raster_failure_discards_the_new_temp_pdf_and_keeps_last_good_page(pane, tmp_path, monkeypatch):
    view, target, _ = pane
    previous = tmp_path / "previous.pdf"
    view._last_pdf = previous
    output = tmp_path / "slidemage_preview_failed" / "preview.pdf"
    output.parent.mkdir()
    output.write_bytes(b"finished PDF")

    def fails(*args):
        raise RuntimeError("image helper failed")

    monkeypatch.setattr(slide_snapshot, "prepare_preview", fails)
    view._start(lambda: output, view._job(target))
    view._run(*view.launched[0])
    assert not output.exists() and view._last_pdf == previous
    assert "image helper failed" in view._error


def test_any_exception_in_the_render_worker_ends_the_render_with_a_fail_line(pane, monkeypatch):
    # v5.35.7: a render must never stay "rendering" because of an unexpected error
    view, target, _ = pane
    swept = []
    monkeypatch.setattr(preview_view.slide_preview, "sweep_renders", lambda ctx: swept.append(True))

    def broken():
        raise PermissionError(32, "locked")

    view._start(broken, view._job(target))
    assert view._busy
    view._run(*view.launched[0])
    assert not view._busy and view._active is None
    assert any(line.startswith("*** Render failed:") for line in view.logged)
    assert swept == [True]      # and the old renders are swept after every render


@pytest.mark.parametrize("language", ["EN", "DE"])
@pytest.mark.parametrize("mode", ["source", "details"])
def test_composite_show_focuses_slide_and_displays_returned_image_in_student_view(pane, tmp_path, monkeypatch, language, mode):
    from slidemage.ui.workspace.chat.gui_workspace import GuiWorkspace

    view, _, _ = pane
    state = view.state
    state.set_mode(mode)
    state.set_view("after-course")
    path = tmp_path / "slides" / f"bbb-{language}-New-current.tex"
    path.write_text("BODY")
    target = preview_target.for_path(state.project, path)
    deck = SimpleNamespace(path=tmp_path / "decks" / "open.tex", text=f"\\slide{{bbb-{language}-New}}\n", chapters=[])
    state.deck = deck
    state.focused_slide_changed.connect(lambda _: view.show_slide(target, None, "New", ""))
    window = SimpleNamespace(project=state.project, state=state, centre=SimpleNamespace(preview=view))
    workspace = GuiWorkspace(window)
    # The focus snapshot deliberately describes another deck: the live recheck must ignore it.
    workspace._context = SimpleNamespace(deck=None)
    assert workspace.is_open_deck(deck.path)
    assert not workspace.is_open_deck(tmp_path / "other.tex")
    png = slide_snapshot.page_png(pdf_at(tmp_path / "composite.pdf"), 1280)
    workspace.show_slide(path)
    monkeypatch.setattr(preview_target, 'render_text', lambda *a, **k: tmp_path / 'composite.pdf')
    assert workspace.render_preview(target, "BODY", state.view, language,
                                    preview_view.slide_preview.compiler.CancelToken()) == png
    assert state.focused_slide == "bbb" and state.mode == "split" and state.language == language
    assert view._page.message == "" and not view._page.pixmap.isNull()
    assert not view.launched


@pytest.mark.parametrize("change", ["slide", "view", "language", "buffer", "disk", "deleted"])
def test_composite_preview_does_not_publish_an_obsolete_image(pane, tmp_path, monkeypatch, change):
    view, target, path = pane
    png = slide_snapshot.page_png(pdf_at(tmp_path / "composite.pdf"), 1280)
    publications = []
    monkeypatch.setattr(preview_target, 'render_text', lambda *a, **k: tmp_path / 'composite.pdf')
    monkeypatch.setattr(slide_snapshot, 'publish_preview', lambda *a: publications.append(a))
    request = view.request_render(target, 'BODY', 'instructor', 'EN')
    assert request.wait()[3] == png
    if change == "slide":
        view.show_slide(None, None, "", "No slide")
    elif change == "view":
        view.state.set_view("after-course")
    elif change == "language":
        view.state.set_language("DE")
    elif change == "buffer":
        view.buffer[0] = "NEW"
    else:
        view._buffer = lambda: None
        if change == "disk":
            path.write_text("NEW")
        else:
            path.unlink()
    view.finish_render(request)
    assert view._adhoc is None and not view._pixmaps and not publications


@pytest.mark.parametrize('debounce', [False, True])
def test_tool_and_pane_share_one_build_and_raster(pane, tmp_path, monkeypatch, debounce):
    from agent_fakes import FakeWorkspace
    from slidemage import compiler
    from slidemage.ai.tools import build_toolbox
    from slidemage.ai.agent_types import ToolCall
    from slidemage.ai.workspace import WorkspaceContext

    view, target, path = pane
    builds, rasters = [], []
    started, release = threading.Event(), threading.Event()
    pdf = pdf_at(tmp_path / 'shared.pdf')
    png = slide_snapshot.page_png(pdf, 1280)
    def builder(*a, **kw):
        builds.append(kw)
        started.set()
        assert release.wait(3)
        return pdf

    monkeypatch.setattr(preview_target, 'render_text', builder)
    monkeypatch.setattr(slide_snapshot, 'prepare_preview_images', lambda *a: rasters.append(a) or ((png, png), ()))
    job = view._job(target, buffer_text='BODY', revision_text='BODY')
    job.request = view._renders.request(target, 'BODY', 'instructor', 'EN', view.app.log)
    view._start(lambda: None, job, debounce=debounce)
    job = view._pending[1] if debounce else view._active
    if not debounce:
        worker = WorkerThread(target=view._run, args=view.launched[0])
        worker.start()
        assert started.wait(2)
    ws = FakeWorkspace(tmp_path, WorkspaceContext(path=path))

    joined = view._renders.request

    def request(*a, **kw):
        # Release the build only once the tool's request has joined it: a release before that is a race the
        # pane's render can win, and then the tool asks after the shared request has finished.
        try:
            return joined(*a, **kw)
        finally:
            release.set()

    monkeypatch.setattr(view._renders, 'request', request)
    monkeypatch.setattr(ws, 'preview_service', lambda: view._renders)
    box = build_toolbox(ws, lambda _: None, compiler.CancelToken())
    response = box.execute(ToolCall('1', 'render_preview', {}))
    assert not response.is_error
    assert response.images == [png]
    if debounce:
        view._debounce.stop()
        view._launch_pending()
        view._run(*view.launched[0])
    else:
        worker.join(3)
        assert not worker.is_alive()
        view._on_finished(job)
    assert len(builds) == len(rasters) == 1 and view._page.pixmap is not None
    assert not builds[0]['capture_snapshot'] and builds[0]['cancel'] is job.request.cancel


def test_tool_returns_image_when_pane_shows_another_slide(pane, tmp_path, monkeypatch):
    from slidemage import compiler
    from slidemage.ui.workspace.chat.gui_workspace import GuiWorkspace

    view, _, _ = pane
    path = tmp_path / 'slides' / 'bbb-EN-Other-current.tex'
    path.write_text('OTHER')
    target = preview_target.for_path(view.state.project, path)
    pdf = pdf_at(tmp_path / 'other.pdf')
    publications = []
    monkeypatch.setattr(preview_target, 'render_text', lambda *a, **k: pdf)
    monkeypatch.setattr(slide_snapshot, 'publish_preview', lambda *a: publications.append(a))
    workspace = GuiWorkspace(SimpleNamespace(project=view.state.project, centre=SimpleNamespace(preview=view)))
    png = workspace.render_preview(target, 'OTHER', 'instructor', 'EN', compiler.CancelToken())
    assert png.startswith(b'\x89PNG') and not publications and view._page.pixmap is None


@pytest.mark.parametrize("change, outcome", [
    ("none", "displayed"), ("other-slide", "cached"), ("other-view", "cached"),
    ("disk", "superseded"), ("buffer", "superseded"), ("generation", "superseded"),
])
def test_refresh_tool_publishes_saved_artifact_through_gui_workspace(pane, tmp_path, monkeypatch, qapp, change, outcome):
    from slidemage import compiler
    from slidemage.ai.tools import build_toolbox
    from slidemage.ai.agent_types import ToolCall
    from slidemage.ai.workspace import WorkspaceContext
    from slidemage.ui.workspace.chat.gui_workspace import GuiWorkspace

    view, target, path = pane
    # Use the pane's project (the fixture app deliberately has another one).
    view.app.project = view.state.project
    workspace = GuiWorkspace(SimpleNamespace(project=view.state.project, centre=SimpleNamespace(
        preview=view, source=SimpleNamespace(file_for=lambda path: None))))
    workspace._context = WorkspaceContext(path=path, language="EN")
    old = slide_snapshot.page_png(pdf_at(tmp_path / 'old-refresh.pdf', 'old'))
    old_pixmap = preview_view.QPixmap()
    assert old_pixmap.loadFromData(old)
    key = (target.key, 'instructor', 'EN')
    view._pixmaps.put(key, old_pixmap, preview_view._mtime(path), None, '')
    from slidemage import preview_requests, preview_selection
    old_spec = preview_requests.PreviewRequest(
        target, preview_requests.SourceRevision.capture(path), 'instructor', 'EN',
        preview_requests.RenderOptions(saved=True))
    preview_selection.remember_transient(old_spec, old)
    view._refresh()
    old_image = view._page.pixmap.toImage()
    if change == 'other-slide':
        workspace._context = WorkspaceContext(path=tmp_path / 'slides' / 'bbb-EN-Other-current.tex')
        workspace._context.path.write_text('OTHER')
    elif change == 'other-view':
        view.state.set_view('after-course')
    pdf = pdf_at(tmp_path / 'new-refresh.pdf', 'new')
    started, release = threading.Event(), threading.Event()

    def render(*a, **kw):
        assert not kw['capture_snapshot']
        started.set()
        assert release.wait(5)
        return pdf

    monkeypatch.setattr(preview_target, 'render_text', render)
    box = build_toolbox(workspace, lambda _: None, compiler.CancelToken())
    responses = []
    worker = WorkerThread(target=lambda: responses.append(
        box.execute(ToolCall('1', 'refresh_preview', {'view': 'instructor'}))))
    worker.start()
    for _ in range(100):
        qapp.processEvents()
        if started.wait(.01):
            break
    assert started.is_set()
    if change == 'disk':
        path.write_text('new saved revision')
    elif change == 'buffer':
        view.buffer[0] = 'new unsaved revision'
        view._adhoc = (key, old_pixmap, 'Rendered from the editor buffer, not the saved file')
        view._adhoc_text = view.buffer[0]
    elif change == 'generation':
        view._invalidate()
        # A newer pane render owns the page, even with unchanged source.
        view._adhoc = (key, old_pixmap, 'Newer render')
        view._adhoc_text = view.buffer[0]
    release.set()
    for _ in range(500):
        qapp.processEvents()
        worker.join(.01)
        if not worker.is_alive():
            break
    assert not worker.is_alive()
    response, = responses
    assert not response.is_error, response
    text = response.text
    assert 'instructor, EN: rendered' in text and outcome in text
    assert ('displayed' in text) == (outcome == 'displayed')
    if outcome == 'displayed':
        assert view._page.pixmap.toImage() != old_image
        assert view._last_pdf == pdf
    elif change != 'other-view':
        assert view._page.pixmap.toImage() == old_image
    snapshot = slide_snapshot.snapshot_path(view.state.project, 'bbb' if change == 'other-slide' else 'abc', target.template)
    assert snapshot.is_file() == (outcome != 'superseded')
    if change == 'buffer':
        assert view._adhoc_text == 'new unsaved revision'
    workspace.close()


@pytest.mark.parametrize('saved', [True, False])
def test_ui_all_views_captures_context_and_source_before_worker(pane, monkeypatch, saved):
    from slidemage.ui.workspace.chat.gui_workspace import GuiWorkspace

    view, target, path = pane
    view.app.project = view.state.project
    workspace = GuiWorkspace(SimpleNamespace(project=view.state.project, centre=SimpleNamespace(preview=view)))
    view.app.assistant = SimpleNamespace(workspace=workspace)
    workspace.window.centre.source = SimpleNamespace(file_for=lambda path: SimpleNamespace(
        dirty=True, editor=SimpleNamespace(text=lambda: view.buffer[0])))
    monkeypatch.setattr(preview_view.render_check, 'confirm_render', lambda *a, **kw: True)
    view.buffer[0] = 'DRAFT'
    view.state.set_view('during-course')
    view.render_all_views(saved=saved)
    assert len(view.launched) == 1
    work, captured_path, captured_saved, cancel, requests, ticket = view.launched[0]
    assert work is workspace and captured_path == path and captured_saved == saved
    assert [r.view for r in requests] == ['instructor', 'during-course', 'after-course']
    assert {r.revision.text for r in requests} == {'BODY' if saved else 'DRAFT'}
    assert ticket == view._generation and not cancel.is_set()
    # Later edits and focus changes do not change the immutable submitted source.
    view.buffer[0] = 'LATER'
    view.state.set_view('after-course')
    assert {r.revision.text for r in requests} == {'BODY' if saved else 'DRAFT'}
    assert view._batch_cancel is cancel
    assert not view.can_render_all
    view.cancel_batch()
    assert cancel.is_set()
    workspace.close()


def test_all_view_scope_disabled_and_hidden_current_render_is_safe(pane, monkeypatch):
    from dataclasses import replace

    view, target, _ = pane
    monkeypatch.setattr(view._renders, 'request', lambda *a, **kw: pytest.fail('hidden render compiled'))
    view.show_slide(replace(target, hidden=True), None, 'Hidden', '')
    assert not view._render.buttons()[0].isEnabled()
    assert view._render.buttons()[1].isEnabled()
    view.render_now()
    assert view.can_render_all
    for scope, overlay in [('region', 0), ('element', 0), ('slide', 2)]:
        view._scope, view._overlay = scope, overlay
        view._rebuild_menu()
        assert not view.can_render_all
        entries = [e for e in view._menu._entries if e[0] == 'item' and e[1] in (
            preview_view.ALL_SAVED, preview_view.ALL_BUFFER)]
        assert len(entries) == 2 and all(not entry[6] for entry in entries)
        assert 'Whole slide' in view._menu.toolTip()


def test_ui_batch_progress_partial_failure_and_close_cancellation(pane):
    from slidemage.preview_batch import BatchProgress

    view, _, _ = pane
    cancel = threading.Event()
    view._batch_cancel = cancel
    view._on_batch_progress(BatchProgress('during-course', 2, 3, 'rendering', done=1))
    assert view._batch_status == 'Rendering all views · 1/3 done'
    view._on_batch_progress(BatchProgress('instructor', 1, 3, 'rendered', done=2))   # views finish in any order
    assert view._batch_status == 'Rendering all views · 2/3 done'
    view._on_batch_finished(tuple(SimpleNamespace(request=SimpleNamespace(view=key), status=status, error=error)
                                  for key, status, error in (
                                      ('instructor', 'rendered', ''), ('during-course', 'hidden', ''),
                                      ('after-course', 'failed', 'TeX error'))), '')
    assert view._batch_cancel is None
    assert 'During course: hidden' in view._batch_status and 'After course: failed' in view._batch_status
    assert view.logged[-1] == 'Preview · After course: TeX error'
    view._batch_cancel = cancel
    view._dispose()
    assert cancel.is_set()


def test_view_cache_hit_updates_pdf_and_enables_menu_immediately(pane, tmp_path, monkeypatch):
    view, _, _ = pane
    artifacts = {key: SimpleNamespace(pdf=pdf_at(tmp_path / f'{key}.pdf', key), display_png=None)
                 for key in ('instructor', 'during-course', 'after-course')}
    for artifact in artifacts.values():
        artifact.display_png = slide_snapshot.page_png(artifact.pdf)
    monkeypatch.setattr(view._renders, 'selected_preview', lambda target, text, key, *args, **kw:
                        SimpleNamespace(state='verified', fresh=True, image=artifacts[key].display_png,
                                        pdf=artifacts[key].pdf, request=None))
    monkeypatch.setattr(view._renders, 'request', lambda *args, **kw: pytest.fail('view switch compiled'))
    for key, artifact in artifacts.items():
        view.state.set_view(key)
        view._refresh()
        assert view._last_pdf == artifact.pdf
        assert view._page.pixmap is not None
        entry = next(e for e in view._menu._entries if e[0] == 'item' and e[1] == preview_view.OPEN_PDF)
        assert entry[6]


@pytest.mark.parametrize('failure', ['missing', 'prepare'])
def test_ui_batch_preparation_error_is_reported_without_worker(pane, monkeypatch, failure):
    view, _, path = pane
    monkeypatch.setattr(preview_view.render_check, 'confirm_render', lambda *a, **kw: True)
    view.app.assistant = SimpleNamespace(workspace=SimpleNamespace(
        prepare_preview_batch=lambda *a, **kw: (_ for _ in ()).throw(ValueError('Cannot resolve focused slide'))))
    if failure == 'missing':
        path.unlink()
    view.render_all_views()
    assert view._error
    assert view._batch_cancel is None and not view.launched
    assert 'Render all views failed' in view.logged[-1]


@pytest.mark.parametrize("scope,overlay", [("element", 0), ("region", 2)])
def test_buffer_scope_preference_does_not_hide_a_valid_saved_preview(pane, tmp_path, monkeypatch, scope, overlay):
    view, target, _ = pane
    pdf = pdf_at(tmp_path / "saved-full.pdf", "saved full slide")
    png = slide_snapshot.page_png(pdf)
    view._scope, view._overlay = scope, overlay
    monkeypatch.setattr(view._renders, "selected_preview", lambda *args, **kw: SimpleNamespace(
        state='verified', fresh=True, image=png, pdf=pdf, request=None))

    found = view._image(target)

    assert found is not None and found[1] is True
    assert view._last_pdf == pdf


def test_unverified_memory_image_is_not_current_even_when_source_mtime_matches(pane, tmp_path, monkeypatch):
    view, target, path = pane
    pdf = pdf_at(tmp_path / "unverified.pdf", "unverified render")
    png = slide_snapshot.page_png(pdf)
    pixmap = preview_view.QPixmap()
    assert pixmap.loadFromData(png)
    view._pixmaps.put((target.key, "instructor", "EN"), pixmap, preview_view._mtime(path), None, "")
    monkeypatch.setattr(view._renders, "selected_preview", lambda *args, **kw: SimpleNamespace(
        state='missing', image=None))

    # An unverified pane-only pixmap has no shared provenance and is not selected.
    assert view._image(target) is None


def test_full_draft_batch_replaces_the_previous_region_cache_identity(pane, tmp_path, monkeypatch):
    from dataclasses import replace
    from slidemage.preview_requests import PreviewRequest, PreviewResult, RenderOptions, SourceRevision

    view, target, path = pane
    view.buffer[0] = "DRAFT"
    pdf = pdf_at(tmp_path / "draft-full.pdf", "new full draft")
    png = slide_snapshot.page_png(pdf)
    spec = PreviewRequest(target, SourceRevision.capture(path, "DRAFT"), "instructor", "EN", RenderOptions())
    view._adhoc_spec = replace(spec, options=RenderOptions(mode="region"))
    checked = []
    def selected(_target, text, _view, *_args, **_kwargs):
        checked.append(text)
        return SimpleNamespace(state='verified', fresh=True, image=png, pdf=pdf, request=spec)
    monkeypatch.setattr(view._renders, "selected_preview", selected)

    outcome = view.publish_batch_result(PreviewResult.from_artifact(spec, (pdf, png, (), png)), view._generation)

    assert outcome == "displayed"
    assert checked and all(candidate == 'DRAFT' for candidate in checked)
    assert view._image(target)[1] is True


@pytest.mark.parametrize("mode", ["source", "details"])
def test_palette_all_views_resolves_current_focus_when_preview_is_hidden(pane, tmp_path, monkeypatch, mode):
    from slidemage.preview_requests import RenderOptions, resolve_requests
    view, old_target, _ = pane
    path = tmp_path / "slides" / "bbb-EN-New-current.tex"
    path.write_text("NEW FOCUSED SLIDE")
    target = preview_target.for_path(view.state.project, path)
    captured = []
    def prepare(source, **kwargs):
        captured.append(source)
        return resolve_requests(view.state.project, None, source, "all", "EN", options=RenderOptions(saved=True))
    view.app.assistant = SimpleNamespace(workspace=SimpleNamespace(prepare_preview_batch=prepare))
    view.app.centre = SimpleNamespace(preview=view, _preview_context=lambda: (target, None, "New", None))
    view.state.set_mode(mode)
    monkeypatch.setattr(preview_view.render_check, "confirm_render", lambda *a, **kw: True)
    assert view._target is old_target

    view.render_all_views(saved=True)

    assert captured == [path]
    assert view.target_path == path and view.state.mode == mode
    assert {request.revision.text for request in view.launched[0][4]} == {"NEW FOCUSED SLIDE"}


@pytest.mark.parametrize("mode", ["source", "details"])
def test_palette_force_render_resolves_current_focus_when_preview_is_hidden(pane, tmp_path, monkeypatch, mode):
    view, _, _ = pane
    path = tmp_path / "slides" / "bbb-EN-New-current.tex"
    path.write_text("NEW FOCUSED SLIDE")
    target = preview_target.for_path(view.state.project, path)
    view.app.centre = SimpleNamespace(preview=view, _preview_context=lambda: (target, None, "New", None))
    view.state.set_mode(mode)
    seen = []
    monkeypatch.setattr(view, "_render_saved", lambda **kwargs: seen.append((view.target_path, kwargs)))

    view.force_rerender()

    assert seen == [(path, {"precheck": True, "force": True})]
    assert view.state.mode == mode


@pytest.mark.parametrize('canonical', ['instructor', 'during-course', 'after-course'])
def test_restart_preserves_invalidated_view_as_explicitly_older_render(pane, tmp_path, monkeypatch, canonical):
    from slidemage import preview_cache, preview_requests
    view, target, path = pane
    env = {'PATH': '', 'HOME': str(tmp_path)}
    monkeypatch.setattr(preview_requests.compiler, 'build_env', lambda ctx: env)
    pdf = pdf_at(tmp_path.parent / (tmp_path.name + '.pdf'))
    with pymupdf.open(pdf) as doc:
        png = doc[0].get_pixmap().tobytes('png')
    cache = preview_cache.PreviewCache(target.context.root)
    spec = preview_requests.PreviewRequest(target, preview_requests.SourceRevision.capture(path), canonical, 'EN',
                                          preview_requests.RenderOptions(saved=True))
    entry = cache.store(preview_requests.cache_identity(spec), env, pdf=pdf, display_png=png,
                        dependencies=[path], before=cache.begin(env))
    assert entry is not None
    (target.context.root / 'unrelated-frozen-version.tex').write_text('new version')
    assert cache.lookup(preview_requests.cache_identity(spec), env) is None
    view.state.set_view(canonical)
    image, fresh, note = view._image(target)
    assert not image.isNull() and not fresh
    assert 'Previous render' in note
    assert view._last_pdf == entry.pdf
    assert not view._pixmaps  # fresh process: this did not rely on session memory


# -- the display cache: a return visit shows its page at once, while validation runs ----------------------

class _TwoSlides:
    """Slides A and B in the pane with a validator that waits on a gate per text and answers as `outcome` says."""

    def __init__(self, view, target, path, tmp_path, monkeypatch, qapp):
        from slidemage.preview_selection import SelectedImage
        self.view, self.qapp, self.path_a = view, qapp, path
        self.target_a = target
        self.path_b = tmp_path / "slides" / "bbb-EN-Other-current.tex"
        self.path_b.write_text("OTHER")
        self.target_b = preview_target.for_path(view.state.project, self.path_b)
        self.png = {text: slide_snapshot.page_png(pdf_at(tmp_path / f"{text}.pdf", text), 1280)
                    for text in ("BODY", "OTHER", "BODY2")}
        self.gate = {text: threading.Event() for text in self.png}
        for gate in self.gate.values():
            gate.set()
        self.outcome = "verified"
        self.pdf = pdf_at(tmp_path / "verified.pdf", "verified")
        self.validated = []

        def validate(specs, _reference):
            spec = specs[0]
            self.validated.append(spec.revision.text)
            assert self.gate[spec.revision.text].wait(5)
            if self.outcome == "missing":
                return SelectedImage("missing", None, spec, None, None, None, "No preview"), {}
            return SelectedImage(self.outcome, self.png[spec.revision.text], spec, spec.revision.content_hash,
                                 spec.view, self.pdf, "Older render" if self.outcome == "previous" else "",
                                 artifact_revision_hash=spec.revision.content_hash), {}

        monkeypatch.setattr(preview_view, "validate_captured", validate)
        view._buffer = lambda: None            # the saved files are what is on show
        view._background_validation = True

    def pump(self, condition, timeout=3):
        import time
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.qapp.processEvents()
            time.sleep(.01)
        assert condition()

    def show(self, which):
        target = self.target_a if which == "A" else self.target_b
        self.view.show_slide(target, None, which, "")

    def verified(self):
        return self.view._image_selection is not None and self.view._image_selection.fresh

    def visit(self, which):
        """Show a slide and wait until its validation has been published."""
        self.show(which)
        self.pump(lambda: self.view._selection_result_key is not None and self.view._selection_pending_key is None)

    def key(self, which):
        return ((self.target_a if which == "A" else self.target_b).key, self.view.state.view, self.view.language)


@pytest.fixture
def two(pane, tmp_path, monkeypatch, qapp):
    view, target, path = pane
    return _TwoSlides(view, target, path, tmp_path, monkeypatch, qapp)


def test_return_visit_paints_cached_page_while_validation_is_blocked_then_goes_current(two):
    view = two.view
    two.visit("A")
    assert two.verified() and view._last_pdf == two.pdf and two.key("A") in view._pixmaps
    two.visit("B")
    two.gate["BODY"].clear()                      # validating A again waits for the test
    two.show("A")
    two.qapp.processEvents()

    assert view._selection_pending_key is not None and view._selection_result_key is None
    assert view._page.pixmap is not None and view._page.message == ""     # painted before validation answers
    assert view._status_chip.text() == preview_view.CHECKING and view._status_chip.isVisibleTo(view)
    assert view._last_pdf is None and view._displayed_spec is None        # unchecked pixels authorize nothing
    assert view._image_selection is None
    assert view._page.pixmap.toImage() == view._pixmaps.get(two.key("A")).pixmap.toImage()
    view._refresh()                                                        # a poll while checking keeps it so
    assert view._status_chip.text() == preview_view.CHECKING and view._last_pdf is None

    two.gate["BODY"].set()
    two.pump(two.verified)
    assert view._last_pdf == two.pdf and view._displayed_spec is not None
    assert preview_view.CHECKING not in view._status_chip.text()


@pytest.mark.parametrize("outcome", ["missing", "previous"])
def test_return_visit_validation_that_finds_it_stale_applies_the_existing_states(two, outcome):
    view = two.view
    two.visit("A")
    two.visit("B")
    two.gate["BODY"].clear()
    two.show("A")
    assert view._status_chip.text() == preview_view.CHECKING
    two.outcome = outcome
    two.gate["BODY"].set()
    two.pump(lambda: view._selection_result_key is not None)
    if outcome == "missing":
        assert view._page.pixmap is None and view._page.message.startswith("No preview for the")
        assert view._last_pdf is None
    else:
        assert view._page.pixmap is not None and view._status_chip.text() == "Older render"
    assert view._displayed_spec is None


def test_stale_completion_for_a_never_replaces_b(two):
    view = two.view
    two.visit("A")
    two.visit("B")
    two.gate["BODY"].clear()
    two.gate["OTHER"].clear()
    two.show("A")                                  # A's validation starts and waits
    two.pump(lambda: two.validated.count("BODY") == 2)
    two.show("B")                                  # the pane moves on: A's result is stale
    shown = view._page.pixmap.toImage()
    assert shown == view._pixmaps.get(two.key("B")).pixmap.toImage()
    assert shown != view._pixmaps.get(two.key("A")).pixmap.toImage()
    two.gate["BODY"].set()
    for _ in range(20):
        two.qapp.processEvents()
        import time
        time.sleep(.01)
    assert view._page.pixmap.toImage() == shown and view._selection_result is None
    assert view._status_chip.text() == preview_view.CHECKING     # B is still being checked
    two.gate["OTHER"].set()
    two.pump(two.verified)
    assert view._image_selection.request.target.key == two.target_b.key


def test_cached_page_is_not_shown_after_its_file_changed(two):
    import os
    view = two.view
    two.visit("A")
    two.visit("B")
    two.gate["BODY"].clear()
    stat = two.path_a.stat()
    os.utime(two.path_a, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000))   # same text, a newer file
    two.show("A")
    assert view._page.pixmap is None or view._page.dimmed        # A's old page is never shown; B's stays, faint
    assert view._status_chip.text() != preview_view.CHECKING
    two.gate["BODY"].set()
    two.pump(two.verified)
    two.visit("B")
    two.gate["BODY2"].clear()
    two.path_a.write_text("BODY2")                 # another text
    two.show("A")
    assert (view._page.pixmap is None or view._page.dimmed) and view._status_chip.text() != preview_view.CHECKING
    two.gate["BODY2"].set()


def test_cached_page_is_not_shown_for_another_view_or_language(two):
    view = two.view
    two.visit("A")
    two.visit("B")
    two.gate["BODY"].clear()
    view.state.set_view("after-course")
    two.show("A")
    assert (view._page.pixmap is None or view._page.dimmed) and view._status_chip.text() != preview_view.CHECKING
    view.state.set_view("instructor")
    two.show("B")
    two.show("A")
    assert view._page.pixmap is not None and view._status_chip.text() == preview_view.CHECKING
    view._language = "DE"
    view._refresh()
    assert (view._page.pixmap is None or view._page.dimmed) and view._status_chip.text() != preview_view.CHECKING
    two.gate["BODY"].set()


def test_draft_and_part_of_slide_renders_are_never_whole_slide_entries(pane, tmp_path):
    view, target, _ = pane
    pdf = pdf_at(tmp_path / "draft.pdf")
    view._start(lambda: pdf, view._job(target, note="Rendered from the editor buffer, not the saved file",
                                       buffer_text="BODY", revision_text="BODY"))
    view._run(*view.launched[0])
    assert view._adhoc is not None and (target.key, "instructor", "EN") not in view._pixmaps
    view._start(lambda: pdf, view._job(target, revision_text="BODY"))
    view._run(*view.launched[1])
    held = view._pixmaps.get((target.key, "instructor", "EN"))
    assert held is not None and held.mtime == preview_view._mtime(target.source_path)
    assert held.content_hash == hashlib.sha256(b"BODY").hexdigest()


def test_return_visit_after_validation_does_not_decode_again(two, monkeypatch):
    loads = []

    class Counting(preview_view.QPixmap):
        def loadFromData(self, *args, **kwargs):
            loads.append(1)
            return super().loadFromData(*args, **kwargs)

    monkeypatch.setattr(preview_view, "QPixmap", Counting)
    view = two.view
    two.visit("A")
    two.visit("B")
    decoded = len(loads)
    assert decoded >= 2
    two.visit("A")
    two.show("B")
    two.show("A")
    two.pump(two.verified)
    assert len(loads) == decoded
    assert view._page.pixmap is not None and view._last_pdf == two.pdf


def test_display_cache_holds_display_size_pages_within_its_byte_budget():
    from PySide6.QtGui import QPixmap
    cache = preview_view.DisplayCache()
    big = cache.put(("a",), QPixmap(2560, 1440), 0, None, "")
    assert big.width() == preview_view.DISPLAY_WIDTH == 1920 and big.height() == 1080
    for i in range(10):                            # 10 MB each: the budget, not the entry limit, binds
        cache.put((i,), QPixmap(1280, 2000), 0, None, "")
    assert cache.bytes <= preview_view.DISPLAY_BYTES and len(cache) < preview_view.DISPLAY_ENTRIES
    assert (9,) in cache and ("a",) not in cache and (0,) not in cache
    cache.get((5,))                                # recently used survives eviction
    cache.put(("new",), QPixmap(1280, 2000), 0, None, "")
    assert (5,) in cache and cache.bytes <= preview_view.DISPLAY_BYTES
    cache.clear()
    assert len(cache) == 0


def test_pane_cache_is_cleared_with_the_pane(pane):
    from PySide6.QtGui import QPixmap
    view, target, _ = pane
    view._pixmaps.put((target.key, "instructor", "EN"), QPixmap(8, 8), 0, None, "")
    view._dispose()
    assert len(view._pixmaps) == 0


def test_page_view_paints_from_a_scaled_copy_kept_until_the_size_changes(qapp):
    from PySide6.QtGui import QPixmap
    page = preview_view.PageView(lambda: ThemeManager().tokens)
    page.resize(800, 500)
    page.show_image(QPixmap(1280, 720))
    page.grab()
    first = page._scaled
    assert first is not None and first[1].size() == first[0]
    page.grab()
    assert page._scaled is first                   # the second paint at the same size rescaled nothing
    page.resize(640, 400)
    page.grab()
    assert page._scaled is not first and page._scaled[0] != first[0]
    page.show_image(QPixmap(1280, 720))
    assert page._scaled is None
    page.show_message("none", False)
    page.grab()
    assert page._scaled is None


# -- the render store is asked off the GUI thread ----------------------------------------------------------

class _FakeStore:
    """app.background with a stored render per slide; every call is recorded with the thread it ran on."""

    def __init__(self, pngs: dict, steps: dict = None):
        self.pngs, self.steps = pngs, steps or {}
        self.calls = []                  # (what, on the main thread, the deck name)
        self.gate = {key: threading.Event() for key in pngs}
        for gate in self.gate.values():
            gate.set()
        self.entered = threading.Event()

    def stored_page(self, target, view, language, deck_name=""):
        self.calls.append(("page", threading.current_thread() is threading.main_thread(), deck_name))
        self.entered.set()
        assert self.gate[target.key].wait(5)
        return self.pngs.get(target.key)

    def stored_pages(self, target, view, language, deck_name=""):
        self.calls.append(("pages", threading.current_thread() is threading.main_thread(), deck_name))
        return self.steps.get(target.key)


@pytest.fixture
def stored(two):
    """`two` with the validator blocked for both slides, and a store holding a page of each."""
    for gate in two.gate.values():
        gate.clear()
    store = _FakeStore({two.target_a.key: two.png["BODY"], two.target_b.key: two.png["OTHER"]})
    two.view.app.background = store
    two.store = store
    return two


def pixels(png):
    from PySide6.QtGui import QPixmap
    pixmap = QPixmap()
    assert pixmap.loadFromData(png)
    return pixmap.toImage()


def test_a_stored_page_is_looked_up_off_the_gui_thread_and_shown_once_it_arrives(stored):
    view, store = stored.view, stored.store
    stored.show("A")
    assert view._page.pixmap is None and view._page.message == preview_view.LOADING           # its lookup is out
    stored.pump(lambda: view._page.pixmap is not None)
    assert view._page.pixmap.toImage() == pixels(stored.png["BODY"])
    assert view._last_pdf is None and view._displayed_spec is None             # a store page authorizes no PDF
    assert view._selection_result_key is None                                   # shown before validation answered
    assert preview_view.CHECKING not in view._status_chip.text()
    assert store.calls and not any(on_main for _what, on_main, _deck in store.calls)
    assert {what for what, _m, _d in store.calls} == {"page", "pages"}


def test_the_deck_name_is_read_on_the_gui_thread_and_handed_to_the_store(stored):
    stored.view.state.deck = SimpleNamespace(name="course")
    stored.show("A")
    stored.pump(lambda: stored.view._page.pixmap is not None)
    assert {deck for _what, _m, deck in stored.store.calls} == {"course"}


def test_the_stored_page_is_held_for_a_return_visit(stored):
    view = stored.view
    stored.show("A")
    stored.pump(lambda: view._page.pixmap is not None)
    held = view._pixmaps.get(stored.key("A"))
    assert held is not None and held.mtime == preview_view._mtime(stored.path_a)
    stored.show("B")
    stored.pump(lambda: view._page.pixmap is not None and view._page.pixmap.toImage() == pixels(stored.png["OTHER"]))
    stored.store.gate[stored.target_a.key].clear()               # A's lookup is out again: the held page is what shows
    stored.show("A")
    assert view._page.pixmap.toImage() == pixels(stored.png["BODY"])
    assert view._status_chip.text() == preview_view.CHECKING
    stored.store.gate[stored.target_a.key].set()
    stored.pump(lambda: view._status_chip.text() != preview_view.CHECKING)
    assert view._page.pixmap.toImage() == pixels(stored.png["BODY"]) and view._last_pdf is None


def test_a_stored_page_for_a_arriving_after_the_selection_moved_to_b_is_discarded(stored):
    view, store = stored.view, stored.store
    store.gate[stored.target_a.key].clear()
    stored.show("A")
    assert store.entered.wait(5)                                  # A's lookup is running, blocked in the store
    stored.show("B")
    seen = []
    store.gate[stored.target_a.key].set()
    stored.pump(lambda: seen.append(view._page.pixmap is not None and view._page.pixmap.toImage()) or
                (view._page.pixmap is not None and view._page.pixmap.toImage() == pixels(stored.png["OTHER"])))
    assert pixels(stored.png["BODY"]) not in seen                 # B never showed A's page
    assert view._stored[0][0] == stored.target_b.key


def test_with_the_store_blocked_a_new_slide_keeps_the_previous_page_faint_and_loading_until_its_own_arrives(stored):
    # v8.53.0: not a flash of "No preview" for every slide scrolled past; the previous page stays, faint, never as current.
    view, store = stored.view, stored.store
    stored.show("A")
    stored.pump(lambda: view._page.pixmap is not None)
    before = view._page.pixmap
    store.gate[stored.target_b.key].clear()
    stored.show("B")
    for _ in range(10):
        stored.qapp.processEvents()
    assert view._page.pixmap is before and view._page.dimmed and view._status_chip.text() == preview_view.LOADING
    store.gate[stored.target_b.key].set()
    stored.pump(lambda: view._page.pixmap is not before)
    assert view._page.pixmap.toImage() == pixels(stored.png["OTHER"]) and not view._page.dimmed


def test_a_changed_file_discards_the_page_looked_up_for_the_old_one(stored):
    import os
    view, store = stored.view, stored.store
    store.gate[stored.target_a.key].clear()
    stored.show("A")
    assert store.entered.wait(5)
    stat = stored.path_a.stat()
    os.utime(stored.path_a, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000))
    stored.show("A")                                              # the same slide, another revision of its file
    store.gate[stored.target_a.key].set()
    stored.pump(lambda: view._stored is not None and view._stored[0][3] == preview_view._mtime(stored.path_a))


def test_a_stored_page_is_not_decoded_into_a_pixmap_on_the_gui_thread(stored, monkeypatch):
    loads = []

    class Counting(preview_view.QPixmap):
        def loadFromData(self, *args, **kwargs):
            loads.append(threading.current_thread() is threading.main_thread())
            return super().loadFromData(*args, **kwargs)

    monkeypatch.setattr(preview_view, "QPixmap", Counting)
    stored.show("A")
    stored.pump(lambda: stored.view._page.pixmap is not None)
    stored.show("B")
    stored.pump(lambda: stored.view._page.pixmap is not None and
                stored.view._page.pixmap.toImage() == pixels(stored.png["OTHER"]))
    assert not any(loads)


def test_the_stored_page_is_asked_again_at_each_poll_and_only_a_changed_page_refreshes(stored, monkeypatch):
    view, store = stored.view, stored.store

    def asks():
        return [what for what, _m, _d in store.calls].count("page")

    stored.show("A")
    stored.pump(lambda: view._page.pixmap is not None and not view._lookups)
    asked, refreshed = asks(), []
    original = view._refresh
    monkeypatch.setattr(view, "_refresh", lambda: refreshed.append(1) or original())
    view._refresh()                                               # no poll: the page is not asked for again
    stored.pump(lambda: not view._lookups)
    assert asks() == asked
    view._stored_asked = None                                     # a poll
    view._refresh()
    stored.pump(lambda: asks() > asked and not view._lookups)
    assert len(refreshed) == 2                                    # the same page came back: it did not refresh again


def test_a_refresh_that_changes_nothing_rebuilds_neither_the_chips_nor_the_menu(pane, monkeypatch):
    view, _target, _ = pane
    built = {"chips": 0, "menus": 0}

    class CountedChip(preview_view.Chip):
        def __init__(self, *args, **kwargs):
            built["chips"] += 1
            super().__init__(*args, **kwargs)

    class CountedMenu(preview_view.PopoverMenu):
        def __init__(self, *args, **kwargs):
            built["menus"] += 1
            super().__init__(*args, **kwargs)

    shown = [("info", "One", "muted", "tip")]
    monkeypatch.setattr(preview_view, "Chip", CountedChip)
    monkeypatch.setattr(preview_view, "PopoverMenu", CountedMenu)
    monkeypatch.setattr(preview_view, "chips_for", lambda *a, **k: list(shown))
    view._refresh()
    assert built == {"chips": 1, "menus": 0}                      # other chips; the menu is what it was
    for _ in range(3):
        view._refresh()                                           # the poll
    assert built == {"chips": 1, "menus": 0}
    shown.append(("warning", "Two", "warning", "other"))          # a real change of the chips
    view._refresh()
    assert built == {"chips": 3, "menus": 0}
    view._scope = "region"                                        # a real change of the menu
    view._refresh()
    assert built == {"chips": 3, "menus": 1}
    view._refresh()
    assert built == {"chips": 3, "menus": 1}


def test_while_scrolling_no_check_starts_until_the_selection_rests(stored, monkeypatch):
    # v8.53.0: slides scrolled past started checks that the next slide superseded before they answered.
    view, store = stored.view, stored.store
    stored.show("A")                  # on show since the fixture (its first change, a click): no change, checked at once
    assert not view._defer_checks
    stored.pump(lambda: view._page.pixmap is not None)
    asked = len(store.calls)
    # The next change counts as scrolling when it comes within SCROLLING_MS of A's. A was put on show in the fixture,
    # before the three test pages were rendered, so with the real 300 ms that depended on how fast the machine was.
    monkeypatch.setattr(preview_view, "SCROLLING_MS", 60_000)
    stored.show("B")                                              # within SCROLLING_MS: scrolling
    for _ in range(5):
        stored.qapp.processEvents()
    assert view._defer_checks and len(store.calls) == asked and view._selection_pending is None
    assert view._page.dimmed and view._status_chip.text() == preview_view.LOADING
    view._settled()                                               # the selection rests: B is checked now
    assert not view._defer_checks
    stored.pump(lambda: view._page.pixmap is not None and not view._page.dimmed)
    assert view._page.pixmap.toImage() == pixels(stored.png["OTHER"]) and len(store.calls) > asked


def test_a_slide_change_after_the_selection_rested_is_a_click_and_checked_at_once(stored, monkeypatch):
    view = stored.view
    monkeypatch.setattr(preview_view, "SCROLLING_MS", 50)
    time.sleep(.1)                                                # longer than SCROLLING_MS since A was put on show
    stored.show("B")
    assert not view._defer_checks
    stored.pump(lambda: view._page.pixmap is not None and not view._page.dimmed)
    assert view._page.pixmap.toImage() == pixels(stored.png["OTHER"])


def test_the_neighbours_stored_pages_are_read_ahead_and_the_next_slide_shows_at_once(stored):
    view, store = stored.view, stored.store
    view.neighbours = lambda: [(stored.target_b, None)]
    stored.show("A")
    stored.pump(lambda: view._page.pixmap is not None)
    view._settled()                                               # the selection rests: B's page is read ahead
    ident = (stored.target_b.key, view.state.view, view.language, preview_view._mtime(stored.path_b))
    stored.pump(lambda: ident in view._prefetched)
    assert not any(on_main for _what, on_main, _deck in store.calls)
    store.gate[stored.target_b.key].clear()                       # B's own lookup would wait now
    stored.show("B")
    assert view._page.pixmap.toImage() == pixels(stored.png["OTHER"])     # at once, from what was read ahead
    assert not view._page.dimmed and view._status_chip.text() != preview_view.LOADING
    store.gate[stored.target_b.key].set()


def test_the_pages_read_ahead_go_outward_from_the_slide_on_show_through_the_whole_deck(stored):
    view = stored.view
    rows = [SimpleNamespace(position=i) for i in range(6)]
    targets = [SimpleNamespace(key=("slide", i)) for i in range(6)]
    view.deck_targets = lambda: list(zip(targets, rows))
    view._row = rows[2]
    assert [t.key[1] for t in view._preload_order()] == [3, 1, 4, 0, 5]
    view._row, view._target = None, targets[4]                   # not a slide of the deck's list: all but itself
    assert [t.key[1] for t in view._preload_order()] == [0, 1, 2, 3, 5]


def test_beyond_the_nearest_pages_the_deck_is_held_compressed_and_decoded_when_shown(stored, monkeypatch):
    view, store = stored.view, stored.store
    monkeypatch.setattr(preview_view, "PREFETCHED", 0)            # B is not among the nearest decoded pages
    view.neighbours = lambda: [(stored.target_b, None)]
    stored.show("A")
    stored.pump(lambda: view._page.pixmap is not None)
    view._settled()
    ident = (stored.target_b.key, view.state.view, view.language, preview_view._mtime(stored.path_b))
    stored.pump(lambda: ident in view._compressed)
    assert ident not in view._prefetched and view._compressed[ident][0] == stored.png["OTHER"]
    store.gate[stored.target_b.key].clear()                       # B's own lookup would wait now
    stored.show("B")
    assert view._page.pixmap.toImage() == pixels(stored.png["OTHER"])     # decoded from the PNG held, at once
    store.gate[stored.target_b.key].set()


def test_a_slide_whose_store_has_no_page_is_not_asked_again_at_every_rest(stored):
    view, store = stored.view, stored.store
    store.pngs.pop(stored.target_b.key)
    view.neighbours = lambda: [(stored.target_b, None)]
    stored.show("A")
    stored.pump(lambda: view._page.pixmap is not None)
    view._settled()
    ident = (stored.target_b.key, view.state.view, view.language, preview_view._mtime(stored.path_b))
    stored.pump(lambda: ident in view._preload_missing)
    def pages_asked():
        return sum(1 for what, _m, _d in store.calls if what == "page")

    asked = pages_asked()
    view._settled()
    assert not view._prefetching and pages_asked() == asked


def test_another_view_drops_the_pages_read_ahead_and_the_farthest_give_way_at_the_limit(stored, monkeypatch):
    view = stored.view
    view.neighbours = lambda: [(stored.target_b, None)]
    stored.show("A")
    stored.pump(lambda: view._page.pixmap is not None)
    view._settled()
    ident = (stored.target_b.key, view.state.view, view.language, preview_view._mtime(stored.path_b))
    stored.pump(lambda: ident in view._compressed)
    view.state.set_view("during-course")
    view._settled()
    assert ident not in view._compressed and ident not in view._prefetched and view._compressed_bytes == 0
    monkeypatch.setattr(preview_view, "PRELOAD_BYTES", 10)
    view._preload_rank = {"near": 0, "far": 1, "farther": 2}
    view._keep_compressed("far", b"123456", "f")
    view._keep_compressed("farther", b"1234", "g")
    view._keep_compressed("near", b"12345", "n")                   # the farther pages give way to a nearer one
    assert set(view._compressed) == {"near"} and view._compressed_bytes == 5
    view._keep_compressed("farther", b"1234", "g")
    view._keep_compressed("far", b"12", "f")                      # nearer than "farther": that one gives way
    assert set(view._compressed) == {"near", "far"} and view._compressed_bytes == 7
    view._keep_compressed("farther", b"1234", "g")                # the farthest, with no room: not kept
    assert set(view._compressed) == {"near", "far"}
