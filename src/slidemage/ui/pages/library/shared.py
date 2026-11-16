# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pictures and scrolling columns shared by the Library views; references are decoded on workers."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QScrollArea, QVBoxLayout

from .... import languages, library_data, preview_target, render_key, render_lookup, slide_language
from ...background import run_in_background
from ...kit.widgets import Surface, text_label


def save_library(view, change, done):
    """Update library.json on a worker, then `done(data)` on the GUI thread; `data` is None after a failure,
    which shows in `view.status`. Returns the worker handle."""
    ctx = view.app.project

    def finished(data, error):
        if error is not None:
            view.status.setText(f"Could not save library: {error}")
            view.status.show()
        done(data if error is None else None)

    return run_in_background(lambda: library_data.update(ctx, change), finished, parent=view)


def scroll_column(spacing):
    """A frameless scroll area and the margin-less column inside it."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    content = Surface()
    column = QVBoxLayout(content)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(spacing)
    area.setWidget(content)
    return area, column


def resolver_of(app):
    """The render store's resolver; None while rendering is disabled or its store is unavailable."""
    try:
        return app.background.renderer.resolver
    except Exception:
        return None


def show_picture(label, image) -> bool:
    """Scale `image` into `label`; False (and no change) when there is none."""
    shown = image is not None and not image.isNull()
    if shown:
        label.setPixmap(QPixmap.fromImage(image).scaled(
            label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
    return shown


def picture_label(image, width, height):
    """A fixed-size label with `image`, or "No render yet"."""
    label = text_label("No render yet", "secondary")
    label.setFixedSize(width, height)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    show_picture(label, image)
    return label


def instructor_target(ctx, slug, decks, language):
    """The preview target and language of a slide's Instructor reference: its own language, else `language`."""
    own = slide_language.own_language(slug, languages.project_languages(ctx).codes)
    target = preview_target.PreviewTarget(ctx, "slide", slug, None, None, None, None,
                                          decks[-1].preamble_text if decks else None)
    return target, own if own not in (None, "mult") else language


def load_picture(ctx, slug, decks, resolver, language, *, large=False):
    """Resolve an Instructor reference and decode it off the GUI thread."""
    if resolver is None:
        return QImage()
    try:
        target, language = instructor_target(ctx, slug, decks, language)
        unit = render_key.unit_for(target, "instructor", language)
        record = render_lookup.instructor_reference(dict(resolver=resolver, unit=unit), strict=True)
        if record is None:
            return QImage()
        if large:
            data = resolver.store.page(record, record["pages"])
        else:
            path = resolver.store.thumbnail_path(record)
            data = path.read_bytes() if path is not None else None
        image = QImage.fromData(data) if data else QImage()
        return image if image.isNull() else image.scaled(
            608 if large else 256, 342 if large else 144,
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    except Exception:  # Rendering can be disabled; publications can disappear during a read.
        return QImage()

