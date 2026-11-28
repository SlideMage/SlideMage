# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Newest-request publication, source/context changes, and image reuse."""

import gc
import os
import threading
import time
from dataclasses import replace
from threading import Thread as WorkerThread
from types import SimpleNamespace

import pymupdf
import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QPixmap
from shiboken6 import isValid

from slidemage.deck_scan import Deck
from slidemage import compiler, preview_target, slide_snapshot
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.workspace import preview_view
from slidemage.ui.workspace.chat.gui_workspace import GuiWorkspace
from slidemage.ui.workspace.state import WorkspaceState
from slidemage.project import ProjectContext
from conftest import preview_png, pause


@pytest.fixture(autouse=True)
def collect_garbage_first():
    """Collect Qt wrappers on the GUI thread before a render worker can collect them."""
    gc.collect()


@pytest.fixture
def pane(qapp, tmp_path, monkeypatch):
    ctx = ProjectContext.at(tmp_path)
    logged, launched = [], []
    app = SimpleNamespace(theme=ThemeManager(), log=logged.append, project=ctx)
    # Thread creation is controlled; finishing a job exercises the real worker/GUI handoff.
    monkeypatch.setattr(
        preview_view,
        "Thread",
        lambda **kw: SimpleNamespace(start=lambda: launched.append(kw["args"])),
    )
    buffer = ["BODY"]
    view = preview_view.PreviewPane(app, WorkspaceState(ctx), lambda: buffer[0])
    path = tmp_path / "slides" / "abc-EN-One-current.tex"
    path.parent.mkdir()
    path.write_text("BODY")
    target = preview_target.for_path(ctx, path)
    view.show_slide(target, None, "One", "")
    view.launched, view.buffer, view.logged = launched, buffer, logged
    yield view, target, path
    # Release widgets and pixmaps on the GUI thread.
    view._dispose()
    view.model.pixmaps.clear()
    view.model.adhoc.value = None
    view._page.pixmap = None
    if isValid(view):
        view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()


@pytest.fixture
def gui_workspace(pane):
    view, _, _ = pane
    centre = SimpleNamespace(preview=view, show_slide_tab=lambda: None, source=SimpleNamespace(file_for=lambda _: None))
    workspace = GuiWorkspace(SimpleNamespace(project=view.state.project, state=view.state, centre=centre))
    yield workspace
    workspace.close()


@pytest.fixture
def temporary_pdf(tmp_path):
    path = tmp_path / 'slidemage_preview_render' / 'preview.pdf'
    path.parent.mkdir()
    path.write_bytes(b'finished PDF')
    return path


def pdf_at(path, *texts, height=180):
    with pymupdf.open() as doc:
        for text in texts or ("hello",):
            doc.new_page(width=320, height=height).insert_text((30, 30), text)
        doc.save(path)
    return path


def test_a_focused_render_prepares_other_views_for_a_store_hit_until_the_next_edit(pane, tmp_path, monkeypatch):
    from slidemage import background_renders
    from slidemage.render_scheduler import P_IDLE

    view, target, path = pane
    folder = tmp_path / '.temp'
    folder.mkdir()
    pdf = pdf_at(folder / 'slide.pdf')
    pdf.with_suffix('.inputs.json').write_text('[]')
    compiled = []

    def render(_target, text, canonical, language, **kwargs):
        compiled.append((text, canonical, kwargs['cancel'].low_priority))
        return pdf

    monkeypatch.setattr(preview_target, 'render_text', render)
    renderer = view._renders.renderer(target.context)
    renderer.gate.force()
    view.buffer[0] = '\\setSlideVersion{1-0-0+}\nunsaved edit'
    text = view.buffer[0]
    monkeypatch.setattr(background_renders, 'RENDER_OTHER_VIEWS', False)
    view.render_after_save()
    pause(20)
    view._run(*view.launched[-1])
    assert view._last_request.done.wait(10)
    assert not renderer.scheduler.pending()

    monkeypatch.setattr(background_renders, 'RENDER_OTHER_VIEWS', True)
    view.render_after_save()
    pause(20)
    view._run(*view.launched[-1])
    assert renderer.scheduler.pending(P_IDLE) == 2
    renderer.gate.paused = True
    assert not renderer.scheduler.run_next()
    renderer.gate.paused = False
    assert renderer.scheduler.run_next()
    assert compiled == [(text, 'instructor', False), (text, 'during-course', True)]

    view.state.set_view('during-course')
    view._settled()
    wait_for(lambda: view._record is not None, timeout=10)
    assert len(compiled) == 2
    assert view._record['pages'] == 1
    assert renderer.scheduler.pending(P_IDLE) == 1
    view.buffer[0] = 'next edit'
    view.buffer_changed(path)
    assert not renderer.scheduler.pending() and not renderer.scheduler.run_next()


def test_pane_pixels_arrive_before_png_encoding_and_put_and_equal_the_stored_page(pane, tmp_path, monkeypatch):
    from contextlib import contextmanager
    from PySide6.QtGui import QImage
    from slidemage import preview_raster_client, timing

    view, target, _ = pane
    pdf = pdf_at(tmp_path / 'slide.pdf', 'first reveal', 'last reveal')
    pdf.with_suffix('.inputs.json').write_text('[]')
    monkeypatch.setattr(preview_target, 'render_text', lambda *a, **kw: pdf)
    request = view._renders.request(target, 'BODY', 'instructor', 'EN', view.app.log)
    renderer = view._renders.renderer(target.context)
    encoding, release, pixels = threading.Event(), threading.Event(), threading.Event()
    decoding_threads = []
    ask, put, span = preview_raster_client.RasterClient.ask, renderer.store.put, timing.span

    def encode(self, data, *args, **kwargs):
        if data.get('op') == 'pdf_images' or ('sizes' in data and not data.get('raw')):
            assert request.delivered.is_set()
            encoding.set()
            assert release.wait(10)
            assert pixels.is_set()
        return ask(self, data, *args, **kwargs)

    def store(*args, **kwargs):
        assert pixels.is_set()
        return put(*args, **kwargs)

    @contextmanager
    def decode(name, **fields):
        with span(name, **fields):
            yield
        if name == 'preview.decode_raw':
            decoding_threads.append(threading.get_ident())

    monkeypatch.setattr(preview_raster_client.RasterClient, 'ask', encode)
    monkeypatch.setattr(renderer.store, 'put', store)
    monkeypatch.setattr(timing, 'span', decode)
    job = view._job(target, request=request, revision_text='BODY')
    view._start(lambda: None, job)
    worker = WorkerThread(target=view._run, args=view.launched[0])
    worker.start()
    try:
        assert encoding.wait(10)
        wait_for(lambda: not view._busy, timeout=10)
        assert not request.done.is_set()
        assert decoding_threads == [worker.ident] and worker.ident != threading.get_ident()
        shown = view._page.pixmap.toImage().convertToFormat(QImage.Format.Format_RGB888)
        pixels.set()
    finally:
        release.set()
        worker.join(10)
        assert request.done.wait(10)
    assert request.error is None
    record = renderer.store.find(renderer.resolver.fast_key(request.spec.unit, 'BODY'))
    assert record['pages'] == 2
    stored_bytes = renderer.store.page(record, 2)
    assert request.wait()[1] == stored_bytes
    stored = QImage.fromData(stored_bytes).convertToFormat(QImage.Format.Format_RGB888)
    assert shown == stored


@pytest.mark.parametrize(
    "change", ["slide", "view", "language", "preamble", "disk", "buffer"]
)
def test_obsolete_results_never_replace_the_page(
    pane, tmp_path, change
):
    view, target, path = pane
    job = view._job(
        target,
        buffer_text="BODY" if change == "buffer" else None,
    )
    pdf = pdf_at(tmp_path / "old.pdf")
    view._start(lambda: pdf, job)
    if change == "slide":
        view.show_slide(
            preview_target.for_path(target.context, tmp_path / "slides" / "bbb-EN-Two-current.tex"),
            None,
            "Two",
            "",
        )
        assert view._page.pixmap is None
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
    assert view._record is None and not view._busy


def test_only_first_and_latest_run_and_only_current_failure_reaches_the_pane(pane, monkeypatch):
    view, target, _ = pane
    swept = []
    monkeypatch.setattr(preview_view.slide_preview, "sweep_renders", swept.append)

    def broken():
        raise PermissionError(32, "locked")

    view._start(broken, view._job(target))
    view._start(lambda: pytest.fail("superseded middle request ran"), view._job(target))
    view._start(broken, view._job(target))
    assert len(view.launched) == 1 and view._busy
    view._run(*view.launched[0])
    assert len(view.launched) == 2 and not view._error and view._busy
    view._run(*view.launched[1])
    assert not view._busy and view._active is None
    assert "locked" in view._error and any(line.startswith("*** Render failed:") for line in view.logged)
    assert swept == [target.context, target.context]


def test_repeated_automatic_requests_are_debounced_and_can_be_invalidated(
    pane, tmp_path
):
    view, target, _ = pane
    work = lambda: pdf_at(tmp_path / "p.pdf")
    view._start(work, view._job(target), debounce=True)
    view._start(work, view._job(target), debounce=True)
    assert not view.launched
    # Saves already follow the editor's typing debounce. Only coalesce notifications from this turn.
    pause(20)
    assert len(view.launched) == 1
    view._start(work, view._job(target), debounce=True)
    view.state.set_language("DE")
    view._run(*view.launched[0])
    pause(350)
    assert len(view.launched) == 1 and not view._busy


def test_presentation_opens_pdf_without_rasterizing(pane, tmp_path, monkeypatch):
    view, target, _ = pane
    pdf = pdf_at(tmp_path / "presenter.pdf")
    opened = []
    monkeypatch.setattr(preview_view.slide_preview, "open_pdf", opened.append)
    monkeypatch.setattr(
        slide_snapshot,
        "prepare_preview_images",
        lambda *a: pytest.fail("presenter rasterized"),
    )
    view._start(lambda: pdf, view._job(target, external=True))
    view._run(*view.launched[0])
    assert len(opened) == 1 and opened[0] != pdf and opened[0].read_bytes() == pdf.read_bytes()


@pytest.mark.parametrize('shared', [False, True])
def test_new_revision_detaches_obsolete_pane_without_cancelling_other_consumers(pane, tmp_path, monkeypatch, shared):
    from slidemage import preview_build
    from slidemage.preview_requests import PreviewRequest, RenderRequest, SourceRevision

    view, target, path = pane
    started, release = threading.Event(), threading.Event()
    old_pdf, new_pdf = pdf_at(tmp_path / 'old.pdf'), pdf_at(tmp_path / 'new.pdf', 'new')
    png = preview_png(new_pdf)
    monkeypatch.setattr(view, '_after_render', lambda job: None)

    def old_work(cancel):
        started.set()
        while not release.wait(.01):
            preview_build.check_cancel(cancel)
        return old_pdf, png, (), None

    old = RenderRequest(old_work, lambda: None)
    old.spec = PreviewRequest(target, SourceRevision.capture(path, 'BODY'), 'instructor', 'EN')
    first = view._job(target, revision_text='BODY', request=old)
    view._start(lambda: None, first)
    pane_worker = WorkerThread(target=view._run, args=view.launched[0])
    tool_result = []

    tool = WorkerThread(target=lambda: tool_result.append(old.wait(timeout=5))) if shared else None
    try:
        if tool is not None:
            tool.start()
        pane_worker.start()
        assert started.wait(2)
        deadline = time.monotonic() + 2
        while len(old._consumers) != (2 if shared else 1) and time.monotonic() < deadline:
            time.sleep(.005)
        assert len(old._consumers) == (2 if shared else 1)
        view.buffer[0] = 'NEW'
        new = RenderRequest(lambda cancel: (new_pdf, png, (), None), lambda: None)
        new.spec = PreviewRequest(target, SourceRevision.capture(path, 'NEW'), 'instructor', 'EN')
        latest = view._job(target, revision_text='NEW', request=new)
        view._start(lambda: None, latest)
        pane_worker.join(2)
        assert not pane_worker.is_alive()     # the old render has not been released
        assert first.cancel.is_set() and old.cancel.is_set() == (not shared)
        view._on_finished(first)
        assert len(view.launched) == 2
        view._run(*view.launched[-1])
        assert view._page.pixmap is not None
        assert not any('Render failed' in line for line in view.logged)
        if shared:
            assert not old.done.is_set() and not tool_result
    finally:
        release.set()
        pane_worker.join(3)
        if tool is not None:
            tool.join(3)
        old.done.wait(3)
    if shared:
        assert tool_result[0][0] == old_pdf


def test_identical_inflight_revision_is_not_cancelled_when_save_joins_it(pane):
    view, target, _ = pane
    request = SimpleNamespace(cancelled=lambda: False, spec=request_for(view, target))
    first = view._job(target, request=request)
    view._start(lambda: None, first)
    view._start(lambda: None, view._job(target, request=request))
    assert not first.cancel.is_set() and len(view.launched) == 1
    view._pending = None


def test_edit_then_undo_reacquires_request_that_was_cancelled_while_pending(pane, tmp_path, monkeypatch):
    view, target, _ = pane
    pdf = pdf_at(tmp_path / 'latest.pdf')
    png = preview_png(pdf)
    builds = []
    monkeypatch.setattr(preview_target, 'render_text', lambda *a, **k: builds.append(a[1]) or pdf)
    monkeypatch.setattr(slide_snapshot, 'prepare_preview_images', lambda *a, **kw: ((png, png), ()))
    monkeypatch.setattr(view, '_after_render', lambda job: None)

    def request(text):
        return view._renders.request(target, text, 'instructor', 'EN', view.app.log)

    old = request('BODY')
    first = view._job(target, revision_text='BODY', request=old)
    view._start(lambda: None, first)
    view._start(lambda: None, view._job(target, revision_text='EDIT', request=request('EDIT')))
    latest = view._job(target, revision_text='BODY', request=request('BODY'))
    assert latest.request is old and first.cancel.is_set()
    view._start(lambda: None, latest)
    view._run(*view.launched[0])
    assert latest.request is not old and not latest.request.cancelled()
    view._run(*view.launched[-1])
    assert builds == ['BODY'] and view._page.pixmap is not None and not view._error


def test_prepared_images_preserve_aspect_ratio_and_cache_by_pdf_content(tmp_path, monkeypatch):
    from slidemage import preview_raster_client

    pdf = pdf_at(tmp_path / "preview.pdf", height=240)
    slide_snapshot._PNG_CACHE.clear()
    width = slide_snapshot.FULL_SIZE[0]
    images, _ = slide_snapshot.prepare_preview_images(pdf, False, (width,))
    display = pymupdf.Pixmap(images[0])
    assert (display.width, display.height) == (width, width * 3 // 4)
    with monkeypatch.context() as patch:
        patch.setattr(preview_raster_client, "render", lambda *a: pytest.fail("cache miss for unchanged PDF"))
        assert slide_snapshot.prepare_preview_images(pdf, False, (width,))[0] == images
    pdf.unlink()
    pdf_at(pdf, "changed in the same path", height=240)
    assert slide_snapshot.prepare_preview_images(pdf, False, (width,))[0] != images


def test_session_pixmaps_are_bounded_and_keep_the_most_recent(pane, tmp_path):
    view, target, _ = pane
    pixmap = QPixmap(1, 1)
    for i in range(13):
        view.model.pixmaps.put((("old", i), "instructor", "EN"), pixmap, 0, None, "")
    pdf = pdf_at(tmp_path / "recent.pdf")
    view._start(lambda: pdf, view._job(target))
    view._run(*view.launched[0])
    assert len(view.model.pixmaps) == 12
    assert (target.key, "instructor", "EN") in view.model.pixmaps
    assert (("old", 0), "instructor", "EN") not in view.model.pixmaps
    view._dispose()
    assert len(view.model.pixmaps) == 0


def test_actual_parent_destruction_closes_lifetime_and_discards_worker_result(
    pane, temporary_pdf, monkeypatch,
):
    from PySide6.QtWidgets import QWidget
    view, target, _ = pane
    parent = QWidget()
    view.setParent(parent)
    started, release = threading.Event(), threading.Event()
    threads = []

    def thread(**kwargs):
        result = WorkerThread(**kwargs)
        threads.append(result)
        return result

    def work():
        started.set()
        assert release.wait(3)
        return temporary_pdf

    monkeypatch.setattr(preview_view, "Thread", thread)
    monkeypatch.setattr(slide_snapshot, "prepare_preview_images", lambda *a: pytest.fail("raster after destruction"))
    monkeypatch.setattr(preview_view.slide_preview, "open_pdf", lambda *a: pytest.fail("opened after destruction"))
    view._start(work, view._job(target))
    try:
        assert started.wait(1)
        pause(20)
        assert view._busy and view._record is None
        view._start(lambda: pytest.fail("pending job ran after destruction"), view._job(target))
        parent.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert view._closed and view._pending is None
    finally:
        release.set()
        threads[0].join(3)
    assert not threads[0].is_alive() and not temporary_pdf.exists() and len(threads) == 1


def test_destroyed_pane_discards_a_completion_already_queued_to_qt(pane, temporary_pdf, monkeypatch):
    view, target, _ = pane
    monkeypatch.setattr(slide_snapshot, "prepare_preview_images", lambda *a: ((b"",), ()))
    job = view._job(target)
    view._start(lambda: temporary_pdf, job)
    thread = WorkerThread(target=view._run, args=view.launched[0])
    thread.start()
    thread.join(3)  # Deliberately do not deliver the queued completion yet.
    assert not thread.is_alive() and view._record is None and temporary_pdf.exists()
    if isValid(view):
        view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert view._closed and not temporary_pdf.exists()


def test_raster_failure_discards_the_new_temp_pdf(pane, temporary_pdf, monkeypatch):
    view, target, _ = pane

    def fails(*args):
        raise RuntimeError("image helper failed")

    monkeypatch.setattr(slide_snapshot, "prepare_preview_images", fails)
    view._start(lambda: temporary_pdf, view._job(target))
    view._run(*view.launched[0])
    assert not temporary_pdf.exists()
    assert "image helper failed" in view._error


def test_composite_show_focuses_slide_and_displays_returned_image_in_student_view(pane, gui_workspace, tmp_path, monkeypatch):
    view, _, _ = pane
    state = view.state
    language = "DE"
    state.set_mode("source")
    state.set_view("after-course")
    path = tmp_path / "slides" / f"bbb-{language}-New-current.tex"
    path.write_text("BODY")
    target = preview_target.for_path(state.project, path)
    deck = Deck("open", tmp_path / "decks" / "open.tex", False, f"\\slide{{bbb-{language}-New}}\n", False, False, None, [], {})
    state.deck = deck
    state.focused_slide_changed.connect(lambda _: view.show_slide(target, None, "New", ""))
    # A stale focus snapshot must not override the open deck.
    gui_workspace._context = SimpleNamespace(deck=None)
    assert gui_workspace.is_open_deck(deck.path)
    assert not gui_workspace.is_open_deck(tmp_path / "other.tex")
    png = preview_png(pdf_at(tmp_path / "composite.pdf"), 1280)
    gui_workspace.show_slide(path)
    monkeypatch.setattr(preview_target, 'render_text', lambda *a, **k: tmp_path / 'composite.pdf')
    assert gui_workspace.render_preview(target, "BODY", state.view, language,
                                    preview_view.slide_preview.compiler.CancelToken()) == png
    assert state.focused_slide == "bbb" and state.mode == "split" and state.language == language
    assert view._page.message == "" and not view._page.pixmap.isNull()
    assert not view.launched


@pytest.mark.parametrize("change", ["buffer", "deleted"])
def test_composite_preview_does_not_publish_an_obsolete_image(pane, tmp_path, monkeypatch, change):
    view, target, path = pane
    png = preview_png(pdf_at(tmp_path / "composite.pdf"), 1280)
    monkeypatch.setattr(preview_target, 'render_text', lambda *a, **k: tmp_path / 'composite.pdf')
    request = view.request_render(target, 'BODY', 'instructor', 'EN')
    assert request.wait()[3] == png
    if change == "buffer":
        view.buffer[0] = "NEW"
    else:
        view._buffer = lambda: None
        path.unlink()
    view.finish_render(request)
    assert view.model.adhoc.value is None and not view.model.pixmaps


@pytest.mark.parametrize('debounce', [False, True])
def test_tool_and_pane_share_one_build(pane, tmp_path, monkeypatch, debounce):
    from agent_fakes import FakeWorkspace
    from slidemage.ai.tools import build_toolbox
    from slidemage.ai.agent_types import ToolCall
    from slidemage.ai.workspace import WorkspaceContext

    view, target, path = pane
    builds, rasters = [], []
    started, release = threading.Event(), threading.Event()
    pdf = pdf_at(tmp_path / 'shared.pdf')
    png = preview_png(pdf, 1280)
    def builder(*a, **kw):
        builds.append(kw)
        started.set()
        assert release.wait(3)
        return pdf

    monkeypatch.setattr(preview_target, 'render_text', builder)
    monkeypatch.setattr(slide_snapshot, 'prepare_preview_images', lambda *a, **kw: rasters.append(a) or ((png, png), ()))
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
    from slidemage import render_lookup
    renderer = view._renders.renderer(target.context)
    spec = job.request.spec
    state, record = render_lookup.select(dict(resolver=renderer.resolver, unit=spec.unit, spec=spec), strict=True)
    assert state == 'current' and response.images == [renderer.store.page(record, record['pages'])]
    if debounce:
        view._debounce.stop()
        view._launch_pending()
        view._run(*view.launched[0])
    else:
        worker.join(3)
        assert not worker.is_alive()
        view._on_finished(job)
    assert len(builds) == 1 and len(rasters) == (1 if debounce else 2) and view._page.pixmap is not None
    assert builds[0]['cancel'] is job.request.cancel


def test_tool_returns_image_when_pane_shows_another_slide(pane, gui_workspace, tmp_path, monkeypatch):
    view, _, _ = pane
    path = tmp_path / 'slides' / 'bbb-EN-Other-current.tex'
    path.write_text('OTHER')
    target = preview_target.for_path(view.state.project, path)
    pdf = pdf_at(tmp_path / 'other.pdf')
    monkeypatch.setattr(preview_target, 'render_text', lambda *a, **k: pdf)
    png = gui_workspace.render_preview(target, 'OTHER', 'instructor', 'EN', compiler.CancelToken())
    assert png.startswith(b'\x89PNG') and view._page.pixmap is None


@pytest.mark.parametrize("change, outcome", [
    ("none", "displayed"), ("other-slide", "cached"),
    ("disk", "superseded"), ("buffer", "superseded"), ("generation", "superseded"),
])
def test_refresh_tool_publishes_saved_artifact_through_gui_workspace(pane, gui_workspace, tmp_path, monkeypatch, change, outcome):
    from slidemage.ai.tools import build_toolbox
    from slidemage.ai.agent_types import ToolCall
    from slidemage.ai.workspace import WorkspaceContext

    view, target, path = pane
    gui_workspace._context = WorkspaceContext(path=path, language="EN")
    spec = request_for(view, target)
    old = page_record(spec, 'red')['images'][0]
    old_result = view._rendered_page(spec, view._generation, old)
    view._remember(old_result, 'BODY')
    view._refresh()
    old_image = preview_view.QImage.fromData(old)
    if change == 'other-slide':
        other = path.with_name('bbb-EN-Other-current.tex')
        other.write_text('OTHER')
        gui_workspace._context = WorkspaceContext(path=other)
    pdf = pdf_at(tmp_path / 'new-refresh.pdf', 'new')
    started, release = threading.Event(), threading.Event()

    def render(*a, **kw):
        started.set()
        assert release.wait(5)
        return pdf

    monkeypatch.setattr(preview_target, 'render_text', render)
    box = build_toolbox(gui_workspace, lambda _: None, compiler.CancelToken())
    responses = []
    worker = WorkerThread(target=lambda: responses.append(
        box.execute(ToolCall('1', 'refresh_preview', {'view': 'instructor'}))))
    worker.start()
    try:
        wait_for(started.is_set, timeout=1)
        if change == 'disk':
            path.write_text('new saved revision')
        elif change == 'buffer':
            view.buffer[0] = 'new unsaved revision'
            view.model.adhoc.hold(old_result, view.buffer[0], 'Unsaved render')
        elif change == 'generation':
            view._invalidate()
            view.model.adhoc.hold(old_result, view.buffer[0], 'Newer render')
    finally:
        release.set()
        wait_for(lambda: not worker.is_alive())
        worker.join()
    response, = responses
    assert not response.is_error, response
    text = response.text
    assert 'instructor, EN: rendered' in text and outcome in text
    assert ('displayed' in text) == (outcome == 'displayed')
    if outcome == 'displayed':
        assert view._page.pixmap is not None and view._page.pixmap.toImage() != old_image
    else:
        assert view._page.pixmap is None or view._page.pixmap.toImage() == old_image
    if change == 'buffer':
        assert view.model.adhoc.text == 'new unsaved revision'


@pytest.mark.parametrize('saved', [True, False])
def test_ui_all_views_captures_context_and_source_before_worker(pane, gui_workspace, monkeypatch, saved):
    view, target, path = pane
    view.app.assistant = SimpleNamespace(workspace=gui_workspace)
    gui_workspace.window.centre.source = SimpleNamespace(file_for=lambda _: SimpleNamespace(
        dirty=True, editor=SimpleNamespace(text=lambda: view.buffer[0])))
    monkeypatch.setattr(preview_view.render_check, 'confirm_render', lambda *a, **kw: True)
    view.buffer[0] = 'DRAFT'
    view.state.set_view('during-course')
    view.render_all_views(saved=saved)
    assert len(view.launched) == 1
    work, captured_path, captured_saved, cancel, requests, ticket = view.launched[0]
    assert (work, captured_path, captured_saved) == (gui_workspace, path, saved)
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


def test_hidden_current_render_is_safe(pane, monkeypatch):
    view, target, _ = pane
    monkeypatch.setattr(view._renders, 'request', lambda *a, **kw: pytest.fail('hidden render compiled'))
    view.show_slide(replace(target, hidden=True), None, 'Hidden', '')
    assert not view._render.buttons()[0].isEnabled()
    assert view._render.buttons()[1].isEnabled()
    view.render_now()
    assert view.can_render_all


def test_ui_batch_progress_partial_failure_and_close_cancellation(pane):
    from slidemage.batch_render import BatchProgress

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


def test_palette_renders_resolve_live_focus_when_preview_is_hidden(pane, monkeypatch):
    from slidemage.batch_render import plan_slide
    from slidemage.preview_requests import RenderOptions

    view, old_target, path = pane
    path = path.with_name("bbb-EN-New-current.tex")
    path.write_text("NEW FOCUSED SLIDE")
    target = preview_target.for_path(view.state.project, path)
    view.app.centre = SimpleNamespace(preview=view, _preview_context=lambda: (target, None, "New", None))
    view.state.set_mode("source")
    seen = []
    monkeypatch.setattr(view, "_render_saved", lambda **kwargs: seen.append((view.target_path, kwargs)))
    view.force_rerender()
    assert seen == [(path, {"precheck": True, "force": True})]
    assert view.state.mode == "source"

    def prepare(source, **kwargs):
        assert source == path
        return plan_slide(view.state.project, None, source, "all", "EN", options=RenderOptions(saved=True))

    view.show_slide(old_target, None, "One", "")
    view.app.assistant = SimpleNamespace(workspace=SimpleNamespace(prepare_preview_batch=prepare))
    monkeypatch.setattr(preview_view.render_check, "confirm_render", lambda *a, **kw: True)
    view.render_all_views(saved=True)
    assert view.target_path == path and view.state.mode == "source"
    assert {request.revision.text for request in view.launched[0][4]} == {"NEW FOCUSED SLIDE"}


def test_display_cache_holds_display_size_pages_within_its_byte_budget(qapp):
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


def test_poll_and_typing_keep_the_last_page_with_the_right_revision_label(pane):
    view, target, path = pane
    page = page_record(request_for(view, target), 'blue')
    artifact = (None, page['images'][0], (), None)
    assert view.publish_refresh(target, 'BODY', preview_view._mtime(path), view.state.view,
                                view.language, artifact, view._generation) == 'displayed'
    view.show()
    wait_for(lambda: not view._checking())
    note = view._status_chip.text()
    assert 'Temporary preview' in note
    view._poll_selection()
    assert_page(view, page, 0, note)

    shown = view._page.pixmap
    for text in ('BODY typed', 'BODY typed again'):
        view._defer_checks = True
        view.buffer[0] = text
        view.buffer_changed(path)
        pause(170)
        assert view._page.pixmap is shown and view._page.badge == preview_view.SOURCE_CHANGED
        assert view._page.message != preview_view.LOADING
        view.model.pixmaps.clear()
    view._defer_checks = False
    wait_for(lambda: not view._checking())
    assert_page(view, page, 0, preview_view.SOURCE_CHANGED)


def test_the_poll_recheck_keeps_the_step_list_until_the_store_answers(pane):
    view, target, _ = pane
    key = view._current_steps(target)[0]
    spec = request_for(view, target, all_steps=True)
    pages = tuple(page_record(spec, 'red', 'blue')['images'])
    result = preview_view._PageResult(view._generation, spec, 'current', pages=pages)
    view._steps_found(key, result)
    view._on_step_selected(1)
    shown = view._page.pixmap
    view.show()
    view._poll_selection()
    assert view.model.steps.pages[key] is result and key in view.model.steps.recheck
    updated = preview_view._PageResult(view._generation, spec, 'previous', pages=pages)
    view._steps_found(key, updated)
    assert view.model.steps.pages[key] is updated and key not in view.model.steps.recheck
    assert view._page.pixmap is shown and 'Previous render' in view._status_chip.text()
    view._poll_selection()
    view._steps_found(key, preview_view._PageResult(view._generation, spec, 'missing'))
    assert key not in view.model.steps.pages


def test_steps_rendered_here_survive_the_poll_until_the_slide_is_saved(pane, monkeypatch):
    """A slide that needs its deck never has standalone steps stored: dropping them re-rendered it every 5 s."""
    view, target, path = pane
    key = view._current_steps(target)[0]
    spec = request_for(view, target, all_steps=True)
    result = preview_view._PageResult(view._generation, spec, 'rendered', pages=(b'step 1', b'step 2'))
    view._on_steps_ready(key, result, '')
    view.show()
    view._poll_selection()
    view._steps_found(key, preview_view._PageResult(view._generation, spec, 'missing'))
    assert view.model.steps.pages[key] is result
    asked = []
    monkeypatch.setattr(view, '_queue_steps', lambda *a: asked.append(a[1]))
    monkeypatch.setattr(view, 'neighbours', lambda: [(target, None)])
    view._poll_selection()
    view._probe_steps()
    assert asked == []
    del view.model.steps.pages[key]
    view._probe_steps()
    assert asked == [key, key]  # The slide and its neighbour (itself here).
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
    assert view._current_steps(target)[0] != key


@pytest.fixture
def stored_pages(pane, monkeypatch):
    """Control when the display worker's captured lookup answers reach the pane."""
    from concurrent.futures import Future

    view, target, _ = pane
    pending, choices = [], {}
    renderer = view._renders.renderer(target.context)

    def submit(work):
        future = Future()
        assert future.set_running_or_notify_cancel()
        def lookup():
            result = work()
            return lambda: future.set_result(result)

        pending.append(lookup)
        return future

    def choose(request, *, strict):
        spec = request['spec']
        return choices.get((spec.target.id_slug, spec.view, spec.options.all_steps), ('missing', None))

    def answer():
        while pending:
            pending.pop(0)()()

    monkeypatch.setattr(view._display_executor, 'submit', submit)
    monkeypatch.setattr(preview_view.render_lookup, 'select', choose)
    monkeypatch.setattr(renderer.store, 'pages', lambda record: record['images'])
    view.app.background = SimpleNamespace(renderer=renderer)
    return choices, pending, answer


def page_record(spec, *colors, source_hash=None):
    from io import BytesIO
    from PIL import Image

    images = []
    for color in colors:
        png = BytesIO()
        Image.new('RGB', (64, 64), color).save(png, 'PNG')
        images.append(png.getvalue())
    return dict(unit=spec.unit.label, images=images, pages=len(images), manifest=[
        ['project', spec.revision.path.relative_to(spec.target.context.root).as_posix(),
         source_hash or spec.revision.content_hash],
    ])


def request_for(view, target, *, all_steps=False):
    return preview_view.PreviewRequest(
        target, preview_view.SourceRevision.capture(target.source_path), view.state.view, view.language,
        preview_view.RenderOptions(all_steps=all_steps))


def wait_for(done, *, timeout=5):
    deadline = time.monotonic() + timeout
    while not done() and time.monotonic() < deadline:
        pause(10)
    assert done()


def assert_page(view, record, index, label):
    assert view._page.pixmap is not None
    assert view._page.pixmap.toImage() == preview_view.QImage.fromData(record['images'][index])
    assert label in view._status_chip.text()


def test_switching_selection_waits_for_its_lookup_even_with_read_ahead(pane, stored_pages):
    import hashlib

    view, one, path = pane
    choices, pending, answer = stored_pages
    view.buffer[0] = None
    path.write_text(r'\setSlideVersion{1-0-0}')
    first = page_record(request_for(view, one), 'red')
    choices[one.id_slug, 'instructor', False] = 'current', first
    view.show_slide(one, None, 'One', '')
    answer()
    assert_page(view, first, 0, 'v1.0.0')
    view.show()
    view._poll_selection()
    old_lookup = pending.pop(0)()

    second_path = path.with_name('def-EN-Two-current.tex')
    second_path.write_text(r'\setSlideVersion{2-0-0}')
    two = preview_target.for_path(one.context, second_path)
    second = page_record(request_for(view, two), 'blue')
    data = second['images'][0]
    context = (view._deck_name(), view.state.view, view.language)
    ahead = view.model.ahead
    ahead.switch_context(context)
    ident = (two.key, view.state.view, view.language, preview_view._mtime(second_path))
    ahead.keep_compressed(ident, data, hashlib.sha256(data).hexdigest())
    choices[two.id_slug, 'instructor', False] = 'current', second
    view.buffer[0] = None
    view.show_slide(two, None, 'Two', '')
    view._settled()
    assert view._page.pixmap is None and view._page.message == preview_view.LOADING
    assert view._status_chip.text() == preview_view.LOADING
    answer()
    old_lookup()
    assert_page(view, second, 0, 'v2.0.0')


@pytest.mark.parametrize('change', ['view', 'same-stat overwrite'])
def test_late_stored_steps_cannot_replace_the_selected_revision(pane, stored_pages, change):
    view, target, _ = pane
    choices, pending, answer = stored_pages
    overwrite = change == 'same-stat overwrite'
    target = replace(target, version='1-0-0' if overwrite else None, macro='slidestep', steps='2')
    path = target.source_path
    text = r'\setSlideVersion{1-0-0}' '\n' r'\onslide<2>{X}'
    path.write_text(text)
    view.buffer[0] = None
    choices[target.id_slug, 'instructor', True] = 'current', page_record(
        request_for(view, target, all_steps=True), 'red', 'orange')
    if overwrite:
        view.set_step_choice(path, 1)
    view.show_slide(target, None, 'One', '')
    view._settled()
    late = pending.pop()()

    if overwrite:
        stat = path.stat()
        path.write_text(text.replace('{X}', '{Y}'))
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        assert (path.stat().st_size, path.stat().st_mtime_ns) == (stat.st_size, stat.st_mtime_ns)
    else:
        view.state.set_view('after-course')

    selected = page_record(request_for(view, target, all_steps=True), 'blue', 'green')
    choices[target.id_slug, view.state.view, True] = 'current', selected
    if overwrite:
        view.show_slide(target, None, 'One', '')
        assert view._page.pixmap is None and view._page.message == preview_view.LOADING
    else:
        view._on_step_selected(1)
    answer()
    label = ('Instructor' if overwrite else 'After') + ' · EN · v1.0.0 · Step 1/2'
    assert_page(view, selected, 0, label)
    late()
    assert_page(view, selected, 0, label)


def test_new_lookup_labels_the_record_it_found(pane, stored_pages):
    view, target, path = pane
    choices, _, answer = stored_pages
    view.buffer[0] = None
    path.write_text(r'\setSlideVersion{2-0-0}')
    previous = page_record(request_for(view, target), 'red', 'orange', source_hash='old content')
    choices[target.id_slug, 'instructor', False] = 'previous', previous
    view.show_slide(target, None, 'One', '')
    view._on_step_selected(1)
    answer()
    assert_page(view, previous, 0, 'Previous render · Instructor · EN · Unknown revision · Step 1/2')
    assert 'v2.0.0' not in view._status_chip.text()


def test_dependency_change_updates_the_label_with_identical_pixels(pane):
    from slidemage import render_evidence

    view, target, path = pane
    view.buffer[0] = None
    path.write_text(r'\setSlideVersion{1-0-0}')
    dependency = target.context.root / 'dependency.tex'
    dependency.write_text('before')
    spec = request_for(view, target)
    renderer = view._renders.renderer(target.context)
    resolver = renderer.resolver
    manifest = resolver.build_manifest([str(path), str(dependency)])
    validation = render_evidence.ValidationPass()
    inventory = render_evidence.search_inventory(target.context.root, validation.build_env(target.context))
    record = page_record(spec, 'blue', 'green')
    pdf = pdf_at(target.context.root / 'input.pdf')
    renderer.store.put(resolver.fast_key(spec.unit), pdf, record['images'], dict(
        unit=spec.unit.label, template=spec.unit.template, manifest=manifest.entries,
        inventory=render_evidence.inventory_state(inventory, [path, dependency]),
        frame_number=spec.unit.frame_number, rendered_at=time.time()))
    view.show_slide(target, None, 'One', '')
    view._on_step_selected(1)
    view.show()

    wait_for(lambda: not view._checking())
    assert_page(view, record, 0, 'Instructor · EN · v1.0.0 · Step 1/2')
    assert 'Previous render' not in view._status_chip.text()
    dependency.write_text('after')
    view._poll_selection()
    wait_for(lambda: not view._checking())
    assert_page(view, record, 0, 'Previous render · Instructor · EN · v1.0.0 · Step 1/2')
