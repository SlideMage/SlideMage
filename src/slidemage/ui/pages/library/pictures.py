# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Instructor references decoded on workers for all Library views."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from .... import languages, preview_target, render_key, render_lookup, slide_language


def load_picture(ctx, row, resolver, language, *, large=False):
    """Resolve an Instructor reference and decode it off the GUI thread."""
    if resolver is None:
        return QImage()
    try:
        own = slide_language.own_language(row.slug, languages.project_languages(ctx).codes)
        target = preview_target.PreviewTarget(ctx, "slide", row.slug, None, None, None, None,
                                              row.decks[-1].preamble_text if row.decks else None)
        unit = render_key.unit_for(target, "instructor", own if own not in (None, "mult") else language)
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

