"""Newest-request publication, source/context changes, and image reuse."""

from types import SimpleNamespace
import threading
from threading import Thread as WorkerThread

import pymupdf
import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from slidemage import preview_target, slide_snapshot
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.workspace import preview_view
from slidemage.ui.workspace.state import WorkspaceState


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def pane(qapp, tmp_path, monkeypatch):
    logged, launched = [], []
    app = SimpleNamespace(
        theme=ThemeManager(),
        log=logged.append,
        signals=SimpleNamespace(log=SimpleNamespace(emit=logged.append)),
    )
    monkeypatch.setattr(preview_target, "SLIDES_DIR", tmp_path)
    monkeypatch.setattr(slide_snapshot, "SNAPSHOT_DIR", tmp_path / "snapshots")
    monkeypatch.setattr(preview_target, "cached_image", lambda target: None)
    # Thread creation is controlled; finishing a job exercises the real worker/GUI handoff.
    monkeypatch.setattr(
        preview_view,
        "Thread",
        lambda **kw: SimpleNamespace(start=lambda: launched.append(kw["args"])),
    )
    buffer = ["BODY"]
    view = preview_view.PreviewPane(app, WorkspaceState(), lambda: (buffer[0], ""))
    path = tmp_path / "abc-EN-One-current.tex"
    path.write_text("BODY")
    target = preview_target.for_path(path)
    view.show_slide(target, None, "One", "")
    view.launched, view.buffer, view.logged = launched, buffer, logged
    return view, target, path


def pdf_at(path, text="hello"):
    with pymupdf.open() as doc:
        page = doc.new_page(width=320, height=180)
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
    "change", ["slide", "view", "language", "timestamp", "preamble", "disk", "buffer"]
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
            preview_target.for_path(tmp_path / "bbb-EN-Two-current.tex"),
            None,
            "Two",
            "",
        )
    elif change == "view":
        view.state.set_view("after-course")
    elif change == "language":
        view.state.set_language("DE")
    elif change == "timestamp":
        view.state.set_footer_timestamp(True)
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


def test_png_cache_follows_pdf_content_and_keeps_exact_canonical_sizes(
    tmp_path, monkeypatch
):
    pdf = pdf_at(tmp_path / "preview.pdf", "first")
    slide_snapshot._PNG_CACHE.clear()
    images1, snapshots1 = slide_snapshot.prepare_preview(pdf, True)
    assert [size for size, _ in snapshots1] == [
        slide_snapshot.FULL_SIZE,
        slide_snapshot.THUMB_SIZE,
    ]
    for size, data in snapshots1:
        pix = pymupdf.Pixmap(data)
        assert (pix.width, pix.height) == size
    # A second request must use the cache without opening/rasterizing the PDF.
    original_open = slide_snapshot.fitz.open
    monkeypatch.setattr(
        slide_snapshot.fitz,
        "open",
        lambda *a, **kw: pytest.fail("duplicate rasterization"),
    )
    assert slide_snapshot.prepare_preview(pdf, True) == (images1, snapshots1)
    monkeypatch.setattr(slide_snapshot.fitz, "open", original_open)
    pdf.unlink()
    pdf_at(pdf, "changed in the same path")
    assert slide_snapshot.prepare_preview(pdf, True)[0] != images1


def test_full_slide_display_keeps_a_four_by_three_decks_aspect_ratio(tmp_path):
    pdf = tmp_path / "four-by-three.pdf"
    with pymupdf.open() as doc:
        doc.new_page(width=320, height=240)
        doc.save(pdf)
    display, snapshots = slide_snapshot.prepare_preview(pdf, True)
    pix = pymupdf.Pixmap(display)
    assert (pix.width, pix.height) == (1920, 1440)
    assert [size for size, _ in snapshots] == [
        slide_snapshot.FULL_SIZE,
        slide_snapshot.THUMB_SIZE,
    ]


def test_prepared_canonical_images_match_the_original_rasterization(tmp_path):
    pdf = pdf_at(tmp_path / "canonical.pdf", "formula and text")
    _, snapshots = slide_snapshot.prepare_preview(pdf, True)
    with pymupdf.open(pdf) as doc:
        page = doc[-1]
        for (width, height), png in snapshots:
            original = page.get_pixmap(
                matrix=pymupdf.Matrix(
                    width / page.rect.width, height / page.rect.height
                )
            )
            current = pymupdf.Pixmap(png)
            assert (current.width, current.height, current.samples) == (
                original.width,
                original.height,
                original.samples,
            )


def test_switching_slides_does_not_claim_the_new_slide_is_rendering(pane, tmp_path):
    view, target, _ = pane
    view._start(lambda: pdf_at(tmp_path / "a.pdf"), view._job(target))
    other = preview_target.for_path(tmp_path / "bbb-EN-Two-current.tex")
    view.show_slide(other, None, "Two", "")
    assert "No preview" in view._page.message
    assert not view._page.render_button.isHidden()
    assert view._busy  # the obsolete compiler is still finishing in the background


def test_session_pixmaps_are_bounded_and_keep_the_most_recent(pane, tmp_path):
    from PySide6.QtGui import QPixmap

    view, target, _ = pane
    pixmap = QPixmap(1, 1)
    for i in range(13):
        view._pixmaps[(("old", i), "instructor", "EN", False)] = (pixmap, 0)
    pdf = pdf_at(tmp_path / "recent.pdf")
    view._start(lambda: pdf, view._job(target))
    view._run(*view.launched[0])
    assert len(view._pixmaps) == 12
    assert (target.key, "instructor", "EN", False) in view._pixmaps
    assert (("old", 0), "instructor", "EN", False) not in view._pixmaps


@pytest.mark.parametrize("buffer_render", [False, True])
def test_timestamp_changes_make_accepted_images_stale_and_switching_back_restores_them(
    pane, tmp_path, buffer_render,
):
    view, target, _ = pane
    pdf = pdf_at(tmp_path / "accepted.pdf")
    fields = dict(note="Buffer", buffer_text="BODY") if buffer_render else {}
    view._start(lambda: pdf, view._job(target, **fields))
    view._run(*view.launched[0])
    previous = view._image(target)[0]
    assert view._image(target)[1]
    view.state.set_footer_timestamp(True)
    image, fresh, note = view._image(target)
    assert image.cacheKey() == previous.cacheKey() and not fresh
    assert note == "Timestamp setting changed" and view._pending is None
    view.state.set_footer_timestamp(False)
    assert view._image(target)[1]


def test_disk_snapshot_is_best_effort_not_verified_context(pane, tmp_path, monkeypatch):
    from PySide6.QtGui import QPixmap
    view, target, _ = pane
    snapshot = tmp_path / "snapshot.png"
    pixmap = QPixmap(320, 180)
    pixmap.fill()
    pixmap.save(str(snapshot))
    monkeypatch.setattr(preview_target, "cached_image", lambda _: (snapshot, True))
    assert view._image(target)[1:] == (
        False, "Cached preview; render to verify current settings",
    )


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
