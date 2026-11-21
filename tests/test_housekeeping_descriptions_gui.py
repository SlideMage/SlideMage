# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The archive review of the Housekeeping sheet also offers the image descriptions no slide references."""
from __future__ import annotations

from conftest import wait_until
from PySide6.QtCore import Qt
from test_housekeeping_gui import Window, folders, open_sheet, wait_for_archive  # noqa: F401  (the fixture too)

from slidemage import alt_archive, alt_images
from slidemage.ui.dialogs.housekeeping import ARCHIVE_PAGE


def _entry(image: str) -> alt_images.ImageEntry:
    return alt_images.ImageEntry(image=image, texts={"en": alt_images.ImageText(short=image, long="long")})


def test_archive_review_offers_the_descriptions_no_slide_shows_and_archives_the_ticked_ones(folders, qapp, ctx):
    alt_images.save_store(ctx, {image: _entry(image) for image in
                                ("media/kept.png", "media/gone.png", "media/old.png")})
    sheet = open_sheet(Window(ctx), page=ARCHIVE_PAGE)
    texts = {sheet.files.item(i).text().split()[1]: sheet.files.item(i) for i in range(sheet.files.count())
             if sheet.files.item(i).text().startswith("description")}
    assert set(texts) == {"media/gone.png", "media/old.png"}                   # kept.png is shown by a slide
    assert "file missing" in texts["media/old.png"].text()
    assert texts["media/old.png"].checkState() == Qt.CheckState.Checked        # its file is gone
    assert texts["media/gone.png"].checkState() == Qt.CheckState.Unchecked     # its file is there: maybe a new image
    assert sheet.archive_button.text() == "Archive 3 items"                    # the unused slide and media file, old.png
    sheet.back_button.click()
    assert "1 image description" not in sheet.archive.sub.text() and "2 image descriptions" in sheet.archive.sub.text()
    sheet.archive.button.click()
    sheet.archive_button.click()
    wait_for_archive(sheet)
    wait_until(lambda: sheet._scan is None)
    assert sheet.archive.sub.text().endswith("and 1 image description to the alt-text archive")
    assert set(alt_images.load_store(ctx)) == {"media/kept.png"}
    assert alt_archive.image_snapshots(ctx, "media/old.png")[0]["reason"] == "unused description"
    assert alt_archive.image_snapshots(ctx, "media/gone.png")[0]["reason"] == "image archived"   # its file moved
