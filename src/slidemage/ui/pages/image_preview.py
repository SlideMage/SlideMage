# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""An image as the Images page shows it: large enough to check a number against the chart, on
the white of a slide with a thin outline that shows where the picture ends.

What there is to show (the file, a rendered .pdf page, a rendered tikz illustration) is
image_review.preview_for()'s; this only paints it, or says why it cannot.

A tikz illustration is rendered by LaTeX, which takes seconds (and 40 s and more when it fails):
that runs on one background thread (`_IllustrationRenders`), never on the GUI thread. Until it is
done the preview says "Rendering the illustration…"; one rendered in this session shows its last
picture at once and is checked again in the background.
"""
from __future__ import annotations

import queue
import threading
from typing import Callable, Optional

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QVBoxLayout

from ..kit.tokens import SPACE
from ... import alt_blocks, image_review, open_path
from ...project import ProjectContext
from ..kit import kit_qss as q
from ..kit.widgets import Button, Surface, caption, clear_layout

MAX_WIDTH, MAX_HEIGHT = 760, 420
RENDERING = "Rendering the illustration…"


class _IllustrationRenders(QObject):
    """Renders tikz illustrations one at a time on a daemon thread, so that the window never waits for LaTeX and
    closing it never waits for a render. `done` is emitted on the GUI thread with the request's key, its Preview
    and the log lines the render wrote (the window's log is not called from the worker)."""

    done = Signal(object, object, object)       # (project root, reference), Preview, [log lines]

    def __init__(self) -> None:
        super().__init__()
        self._queue: "queue.Queue[tuple[ProjectContext, str]]" = queue.Queue()
        self._pending: set[tuple[str, str]] = set()
        self._thread: Optional[threading.Thread] = None
        self.last: dict[tuple[str, str], image_review.Preview] = {}     # this session's latest per key
        self.done.connect(self._finished)

    @staticmethod
    def key(project: ProjectContext, reference: str) -> tuple[str, str]:
        return str(project.root), reference

    def request(self, project: ProjectContext, reference: str) -> None:
        """Render `reference` unless it is already queued or rendering."""
        key = self.key(project, reference)
        if key in self._pending:
            return
        self._pending.add(key)
        self._queue.put((project, reference))
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._work, name="illustration-renders", daemon=True)
            self._thread.start()

    def is_pending(self, project: ProjectContext, reference: str) -> bool:
        return self.key(project, reference) in self._pending

    def _work(self) -> None:
        while True:
            project, reference = self._queue.get()
            lines: list[str] = []
            try:
                preview = image_review.preview_for(project, reference, lines.append)
            except Exception as exc:  # noqa: BLE001 -- shown in the preview, never raised in the thread
                preview = image_review.Preview(None, problem=f"Could not render the tikz illustration: {exc}")
            try:
                self.done.emit(self.key(project, reference), preview, lines)
            except RuntimeError:
                return                  # the application is gone

    def _finished(self, key, preview, _lines) -> None:
        self._pending.discard(key)
        self.last[key] = preview


_renders: Optional[_IllustrationRenders] = None


def illustration_renders() -> _IllustrationRenders:
    """The one renderer of the process, made on first use (on the GUI thread)."""
    global _renders
    if _renders is None:
        _renders = _IllustrationRenders()
    return _renders


class ImagePreview(Surface):
    def __init__(self, project: ProjectContext, reference: str, log: Callable[[str], None], *, max_size: tuple[int, int] = (MAX_WIDTH, MAX_HEIGHT)):
        super().__init__()
        self._project, self._reference, self._log, self._max_size = project, reference, log, max_size
        self._shown: Optional[image_review.Preview] = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(SPACE.sm)
        if not reference.startswith(alt_blocks.TIKZ_PREFIX):
            self._show(image_review.preview_for(project, reference, log))
            return
        renders = illustration_renders()
        self._key = renders.key(project, reference)
        renders.done.connect(self._on_rendered)
        last = renders.last.get(self._key)
        if last is not None:
            self._show(last)                    # this session's picture now, checked again below
        else:
            self._layout.addWidget(caption(RENDERING))
        renders.request(project, reference)

    @property
    def rendering(self) -> bool:
        """Still waiting for the illustration's first picture."""
        return self._shown is None

    def _on_rendered(self, key, preview: image_review.Preview, lines) -> None:
        if key != self._key:
            return
        for line in lines:
            self._log(line)
        if self._shown is not None and self._shown == preview:
            return
        clear_layout(self._layout)
        self._show(preview)

    def _show(self, preview: image_review.Preview) -> None:
        self._shown = preview
        pixmap = QPixmap(str(preview.image)) if preview.image is not None else QPixmap()
        if pixmap.isNull():
            problem = preview.problem or f"Could not load {preview.image.name if preview.image else self._reference}"
            line = QHBoxLayout()
            line.addWidget(caption(problem), 1)
            if preview.original is not None:
                open_button = Button(f"Open {preview.original.name}", "secondary", compact=True)
                open_button.clicked.connect(lambda: self._open(preview.original))
                line.addWidget(open_button)
            self._layout.addLayout(line)
            return
        scaled = pixmap.scaled(*self._max_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        picture = QLabel()
        picture.setObjectName(q.IMAGE_PREVIEW)
        picture.setPixmap(scaled)
        picture.setFixedSize(scaled.size() + QSize(2, 2))   # room for the outline
        self._layout.addWidget(picture, 0, Qt.AlignmentFlag.AlignLeft)

    def _open(self, path) -> None:
        try:
            open_path.open_in_default_app(path)
        except OSError as exc:
            QMessageBox.warning(self, "Could not open file", str(exc))
