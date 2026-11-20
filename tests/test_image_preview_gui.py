# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Images page's picture of a tikz illustration is rendered off the GUI thread: the page shows
"Rendering the illustration…" at once and the picture when LaTeX is done (2026-11-16: the page hung for
40 s and more while an illustration compiled on the GUI thread)."""
from __future__ import annotations

import threading
import time

import pytest
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel

from slidemage import image_review
from slidemage.ui.pages import image_preview
from slidemage.ui.pages.image_preview import RENDERING, ImagePreview


def texts(widget):
    return [label.text() for label in widget.findChildren(QLabel) if label.text()]


def pictures(widget):
    return [label for label in widget.findChildren(QLabel) if label.pixmap() is not None and not label.pixmap().isNull()]


def wait_for(condition, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        QTest.qWait(10)
    return condition()


@pytest.fixture
def renders(monkeypatch):
    """A fresh renderer for each test, and a preview_for that waits until the test lets it go."""
    monkeypatch.setattr(image_preview, "_renders", None)
    release, threads, calls = threading.Event(), [], []

    def slow(ctx, reference, log=None):
        threads.append(threading.current_thread().name)
        calls.append(reference)
        if log is not None:
            log(f"rendering {reference}")
        release.wait(5)
        return slow.result

    monkeypatch.setattr(image_review, "preview_for", slow)
    slow.release, slow.threads, slow.calls = release, threads, calls
    return slow


def test_an_illustration_renders_in_the_background_and_then_shows(qapp, ctx, tmp_path, renders):
    png = tmp_path / "pic.png"
    image = QImage(40, 20, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    image.save(str(png))
    renders.result = image_review.Preview(png)
    logged = []

    started = time.monotonic()
    preview = ImagePreview(ctx, "tikz:abc", logged.append)
    assert time.monotonic() - started < 1                        # the GUI thread did not wait for the render
    assert texts(preview) == [RENDERING] and preview.rendering
    second = ImagePreview(ctx, "tikz:abc", logged.append)       # the same one asked again: one render
    renders.release.set()
    assert wait_for(lambda: not preview.rendering and not second.rendering)
    assert len(pictures(preview)) == 1 and RENDERING not in texts(preview)
    assert renders.calls == ["tikz:abc"] and renders.threads == ["illustration-renders"]
    assert "rendering tikz:abc" in logged                       # the log is written on the GUI thread

    again = ImagePreview(ctx, "tikz:abc", logged.append)        # rendered before: the picture at once
    assert not again.rendering and len(pictures(again)) == 1
    assert wait_for(lambda: len(renders.calls) == 2)            # ... and checked again in the background
    for widget in (preview, second, again):
        widget.deleteLater()


def test_a_failed_render_says_why_and_a_closed_preview_is_left_alone(qapp, ctx, renders):
    renders.result = image_review.Preview(None, problem="Could not render the tikz illustration: ! PGF Math Error")
    gone = ImagePreview(ctx, "tikz:bad", lambda line: None)
    gone.deleteLater()
    QTest.qWait(10)                                             # deleted before the render is done
    shown = ImagePreview(ctx, "tikz:bad", lambda line: None)
    renders.release.set()
    assert wait_for(lambda: not shown.rendering)
    assert any("PGF Math Error" in text for text in texts(shown)) and not pictures(shown)
    shown.deleteLater()


def test_an_ordinary_image_is_shown_at_once(qapp, ctx, tmp_path, monkeypatch):
    png = tmp_path / "plain.png"
    image = QImage(10, 10, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    image.save(str(png))
    monkeypatch.setattr(image_review, "preview_for", lambda ctx, reference, log=None: image_review.Preview(png, png))
    preview = ImagePreview(ctx, "media/plain.png", lambda line: None)
    assert not preview.rendering and len(pictures(preview)) == 1
    preview.deleteLater()
