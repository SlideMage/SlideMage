"""An image as the Images page shows it: large enough to check a number against the chart, on
the white of a slide with a thin outline that shows where the picture ends.

What there is to show (the file, a rendered .pdf page, a rendered tikz illustration) is
image_review.preview_for()'s; this only paints it, or says why it cannot.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QVBoxLayout

from ... import image_review, open_path
from ..kit import kit_qss as q
from ..kit.widgets import Button, Surface, caption

MAX_WIDTH, MAX_HEIGHT = 760, 420


class ImagePreview(Surface):
    def __init__(self, reference: str, log: Callable[[str], None], *, max_size: tuple[int, int] = (MAX_WIDTH, MAX_HEIGHT)):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        preview = image_review.preview_for(reference, log)
        pixmap = QPixmap(str(preview.image)) if preview.image is not None else QPixmap()
        if pixmap.isNull():
            problem = preview.problem or f"Could not load {preview.image.name if preview.image else reference}"
            line = QHBoxLayout()
            line.addWidget(caption(problem), 1)
            if preview.original is not None:
                open_button = Button(f"Open {preview.original.name}", "secondary", compact=True)
                open_button.clicked.connect(lambda: self._open(preview.original))
                line.addWidget(open_button)
            layout.addLayout(line)
            return
        scaled = pixmap.scaled(*max_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        picture = QLabel()
        picture.setObjectName(q.IMAGE_PREVIEW)
        picture.setPixmap(scaled)
        picture.setFixedSize(scaled.size() + QSize(2, 2))   # room for the outline
        layout.addWidget(picture, 0, Qt.AlignmentFlag.AlignLeft)

    def _open(self, path) -> None:
        try:
            open_path.open_in_default_app(path)
        except OSError as exc:
            QMessageBox.warning(self, "Could not open file", str(exc))
