"""A small in-app popup showing a slide's cached compile-time PNG snapshot
(slide_snapshot.py) -- the whole point of that cache: look at how a slide
last compiled without paying a LaTeX compile to find out. Shared by
qt_deck_editor_tab.py (its per-row "Preview" button) and
qt_slide_source_tab.py (its "Preview" button next to "Render to PDF").

Deliberately dumb about *how* to render: the caller supplies `render_fn`,
a zero-argument callable that performs whatever compile is appropriate for
its own context (a deck row knows its own preamble/frame number; the
source editor knows whether to render the saved file or the in-editor
buffer) and raises on failure. This popup only knows how to display the
result and offer to call it.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from . import slide_snapshot
from .qt_theme import MUTED_LABEL, WARNING_LABEL


class _PopupSignals(QObject):
    # Optional[str]: an error message, or None on success -- mirrors the
    # render_fn contract (raises on failure) without letting a background
    # thread touch widgets directly.
    render_done = Signal(object)


class SlidePreviewPopup(QDialog):
    def __init__(self, parent, slide_id: str, slide_path: Path,
                 render_fn: Optional[Callable[[], None]] = None,
                 template: str = slide_snapshot.DEFAULT_TEMPLATE,
                 precheck_fn: Optional[Callable[[], bool]] = None) -> None:
        super().__init__(parent)
        template_name = slide_snapshot.TEMPLATES.get(
            template, slide_snapshot.TEMPLATES[slide_snapshot.DEFAULT_TEMPLATE])
        self.setWindowTitle(f"Preview — {slide_id} ({template_name})")
        self._slide_id = slide_id
        self._slide_path = slide_path
        self._render_fn = render_fn
        # Pre-render syntax check (2026-09-26): runs on the GUI thread before
        # "Render now" starts its worker; False = the user cancelled.
        self._precheck_fn = precheck_fn
        self._template = template
        self._template_name = template_name
        self._rendering = False

        self._signals = _PopupSignals()
        self._signals.render_done.connect(self._on_render_done)

        outer = QVBoxLayout(self)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        # Fixed white, not theme-following -- same reasoning as the review
        # tab's own image previews (qt_transcript_tab.py): a slide's own
        # background is white regardless of the app's dark/light toggle.
        self.image_label.setStyleSheet("background-color: #ffffff;")
        outer.addWidget(self.image_label, stretch=1)

        self.status_label = QLabel()
        self.status_label.setObjectName(MUTED_LABEL)
        outer.addWidget(self.status_label)

        buttons_row = QHBoxLayout()
        self.render_button = QPushButton("Render now")
        self.render_button.clicked.connect(self._on_render_clicked)
        self.render_button.setVisible(render_fn is not None)
        buttons_row.addWidget(self.render_button)
        buttons_row.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(self.reject)
        box.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        buttons_row.addWidget(box)
        outer.addLayout(buttons_row)

        self._load_image()
        self.resize(920, 600)

    # -- display --------------------------------------------------------------

    def _max_pixmap_size(self):
        # Scale to fit comfortably within the screen rather than always
        # showing the native 1920x1080 -- a preview is for a quick look,
        # not a pixel-exact check (the "Render now" / real PDF is what's
        # for that).
        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else None
        if geo is None:
            return 1280, 720
        return int(geo.width() * 0.7), int(geo.height() * 0.7)

    def _load_image(self) -> None:
        # Full size only -- the popup is for a real look, not a fast glance
        # (that's the hover tooltip's job, at the thumbnail size instead).
        # Strict per-template lookup: no fallback to some other template's
        # cached image, so this never silently shows the wrong institution's
        # branding.
        png_path = slide_snapshot.snapshot_path(
            self._slide_id, self._template, slide_snapshot.FULL_SIZE)
        if not png_path.is_file():
            self.image_label.setText(
                f"<i>No {self._template_name} preview captured yet for "
                f"this slide.</i>"
                + ("<br>Click “Render now” to generate one."
                   if self._render_fn is not None else "")
            )
            self.image_label.setStyleSheet("")  # no image -- don't force white-on-nothing
            self.status_label.setText("")
            return

        pixmap = QPixmap(str(png_path))
        if pixmap.isNull():
            self.image_label.setText(f"<i>Could not load {png_path.name}</i>")
            self.status_label.setText("")
            return

        max_w, max_h = self._max_pixmap_size()
        self.image_label.setPixmap(
            pixmap.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        self.image_label.setStyleSheet("background-color: #ffffff;")

        if slide_snapshot.is_fresh(self._slide_id, self._slide_path, self._template):
            self.status_label.setText(
                f"{self._slide_id} ({self._template_name}) — captured from "
                f"the last compile.")
        else:
            self.status_label.setObjectName(WARNING_LABEL)
            self.status_label.setText(
                f"{self._slide_id} ({self._template_name}) — may be "
                f"outdated: the slide source has changed since this was "
                f"captured."
            )
            # setObjectName after the widget is already styled needs a
            # polish to pick up the new QSS rule.
            self.status_label.style().unpolish(self.status_label)
            self.status_label.style().polish(self.status_label)

    # -- render-now -------------------------------------------------------------

    def _on_render_clicked(self) -> None:
        if self._rendering or self._render_fn is None:
            return
        if self._precheck_fn is not None and not self._precheck_fn():
            return
        self._rendering = True
        self.render_button.setEnabled(False)
        self.render_button.setText("Rendering…")
        self.status_label.setObjectName(MUTED_LABEL)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.status_label.setText("Rendering — this runs a real compile, so it can take a while…")
        threading.Thread(target=self._render_bg, daemon=True).start()

    def _render_bg(self) -> None:
        try:
            self._render_fn()
        except Exception as exc:  # noqa: BLE001 -- surfaced to the user below
            self._signals.render_done.emit(str(exc))
        else:
            self._signals.render_done.emit(None)

    def _on_render_done(self, error: object) -> None:
        self._rendering = False
        self.render_button.setEnabled(True)
        self.render_button.setText("Render now")
        if error is not None:
            self.status_label.setObjectName(WARNING_LABEL)
            self.status_label.setText(f"Render failed: {error}")
            self.status_label.style().unpolish(self.status_label)
            self.status_label.style().polish(self.status_label)
            return
        self._load_image()
