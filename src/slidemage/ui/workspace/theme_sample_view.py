# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The sample slides above the theme form (docs/plans/theme-editor.md, section 3.3, stage C1c): the theme sample deck
rendered with the theme as it is in the editor, in the colour mode picked here, one page at a time.

A render starts a pause after the last change of the buffer (from the form or from typing), runs in a thread, and a
change during a render stops it and starts again once it has ended. Nothing renders while the panel is hidden; it
catches up when it is shown."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout

from ... import compiler, theme_sample
from ...theme_file import ThemeFile
from ...theme_form_model import parse_modes_header
from ..kit.tokens import SPACE
from ..kit.widgets import Button, Surface, caption, text_label

RENDER_DELAY_MS = 1200      # after the last change of the buffer
RENDER_DPI = 110


def pdf_pages(pdf: Path, dpi: int = RENDER_DPI) -> list[QImage]:
    """Every page of `pdf` as an image."""
    import pymupdf

    images = []
    with pymupdf.open(pdf) as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            images.append(QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy())
    return images


class ThemeSampleView(Surface):
    """`render(project, text, key, mode, cancel=...)` makes the PDF (theme_sample.render; tests pass their own)."""

    rendered = Signal(object)       # theme_sample.SampleResult, from the render thread

    def __init__(self, editor, key: str, project, render: Optional[Callable] = None) -> None:
        super().__init__()
        self.editor = editor
        self.key = key
        self.project = project
        self._render = render or theme_sample.render
        self._images: list[QImage] = []
        self._page = 2                          # the title bar, lists and footnotes: the page most fields change
        self._cancel: Optional[compiler.CancelToken] = None
        self._again = False
        self._stale = True
        self._error = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE.lg, SPACE.md, SPACE.lg, SPACE.sm)
        layout.setSpacing(SPACE.xs)
        head = QHBoxLayout()
        head.addWidget(text_label("Sample slides", "heading"))
        head.addStretch(1)
        self.mode_combo = QComboBox()
        self.mode_combo.setToolTip("The colour mode the sample slides are rendered in")
        self.mode_combo.activated.connect(lambda _i: self.render_soon(0))
        head.addWidget(self.mode_combo)
        self.previous = Button("‹", "ghost", compact=True)
        self.previous.setToolTip("Previous page")
        self.previous.clicked.connect(lambda: self.show_page(self._page - 1))
        self.next = Button("›", "ghost", compact=True)
        self.next.setToolTip("Next page")
        self.next.clicked.connect(lambda: self.show_page(self._page + 1))
        head.addWidget(self.previous)
        head.addWidget(self.next)
        layout.addLayout(head)
        self.page_label = caption("")
        layout.addWidget(self.page_label)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumHeight(120)
        self.image.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        layout.addWidget(self.image, 1)
        self.status = caption("")
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(RENDER_DELAY_MS)
        self._timer.timeout.connect(self.start)
        editor.text_changed.connect(self._on_text_changed)
        self.rendered.connect(self._on_rendered)
        self._update_modes()
        self._show()

    # --- rendering ---------------------------------------------------------------------------------------------------

    @property
    def mode(self) -> str:
        return self.mode_combo.currentData() or ""

    def _on_text_changed(self) -> None:
        self._update_modes()
        self.render_soon()

    def render_soon(self, delay: Optional[int] = None) -> None:
        self._stale = True
        self._timer.start(RENDER_DELAY_MS if delay is None else delay)

    def start(self) -> None:
        """Render now (or once the running render has stopped); nothing while the panel is not on show."""
        if self.project is None or not self.isVisible():
            return
        if self._cancel is not None:
            self._again = True
            self._cancel.request_stop(wait=False)
            return
        self._stale = False
        self._cancel = cancel = compiler.CancelToken()
        text, mode = self.editor.text(), self.mode
        self.status.setText("Rendering the sample slides…")

        def work() -> None:
            try:
                result = self._render(self.project, text, self.key, mode, cancel=cancel)
            except Exception as exc:        # a failed render must not end the thread silently
                result = theme_sample.SampleResult(None, f"The sample slides could not be rendered: {exc}", mode)
            self.rendered.emit(result)

        threading.Thread(target=work, daemon=True, name="theme-sample").start()

    def _on_rendered(self, result) -> None:
        self._cancel = None
        if self._again:
            self._again = False
            self.start()
            return
        if result.pdf is not None:
            try:
                self._images = pdf_pages(result.pdf)
                self._error = ""
            except Exception as exc:
                self._error = f"The sample slides could not be read: {exc}"
        elif result.log:
            self._error = result.log
        self._show()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._stale:
            self.render_soon(0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._show_image()

    # --- showing -----------------------------------------------------------------------------------------------------

    def _update_modes(self) -> None:
        file = ThemeFile(self.editor.text())
        labels = dict(parse_modes_header(file.value("header:modes") or ""))
        wanted = [(mode_id, labels.get(mode_id) or mode_id.capitalize()) for mode_id, _ in file.modes()] or [("", "Colours")]
        current = [(self.mode_combo.itemData(i), self.mode_combo.itemText(i)) for i in range(self.mode_combo.count())]
        if [data for data, _ in current] != [data for data, _ in wanted]:
            keep = self.mode
            self.mode_combo.clear()
            for data, text in wanted:
                self.mode_combo.addItem(text, data)
            index = self.mode_combo.findData(keep)
            self.mode_combo.setCurrentIndex(max(index, 0))
        self.mode_combo.setVisible(len(wanted) > 1)

    def show_page(self, page: int) -> None:
        if self._images:
            self._page = min(max(page, 1), len(self._images))
        self._show()

    def _show(self) -> None:
        count = len(self._images)
        self._page = min(max(self._page, 1), count) if count else self._page
        names = dict(theme_sample.PAGES)
        self.page_label.setText(f"Page {self._page} of {count}: {names.get(self._page, '')}" if count else "")
        self.previous.setEnabled(count > 0 and self._page > 1)
        self.next.setEnabled(count > 0 and self._page < count)
        if self._error.strip():
            first = self._error.strip().splitlines()[0]
            self.status.setText(f"The theme does not compile as it is: {first} (the whole message is the tooltip)")
            self.status.setToolTip(self._error)
        elif self._cancel is None:
            self.status.setText("" if count else ("The sample slides render when the panel is shown."
                                                  if self.project is not None else "No project: nothing to render."))
            self.status.setToolTip("")
        self._show_image()

    def _show_image(self) -> None:
        if not self._images:
            self.image.clear()
            return
        image = self._images[self._page - 1]
        size = self.image.size()
        if size.width() < 10 or size.height() < 10:
            return
        self.image.setPixmap(QPixmap.fromImage(image).scaled(
            size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
