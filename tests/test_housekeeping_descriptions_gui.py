# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from conftest import wait_until
from PySide6.QtCore import Qt
from test_housekeeping_gui import Window, folders as folders, open_sheet, wait_for_archive

from slidemage import alt_archive, alt_images
from slidemage.ui.dialogs.housekeeping import ARCHIVE_PAGE


def _archive_items(sheet):
    return [sheet.files.item(i) for i in range(sheet.files.count())]


def _entry(image: str) -> alt_images.ImageEntry:
    return alt_images.ImageEntry(image=image, texts={"en": alt_images.ImageText(short=image, long="long")})


def test_archive_review_offers_the_descriptions_no_slide_shows_and_archives_the_ticked_ones(folders, qapp, ctx):
    alt_images.save_store(ctx, {image: _entry(image) for image in
                                ("media/kept.png", "media/gone.png", "media/old.png")})
    sheet = open_sheet(Window(ctx), page=ARCHIVE_PAGE)
    items = _archive_items(sheet)
    texts = {item.text().split()[1]: item for item in items if item.text().startswith("description")}
    assert set(texts) == {"media/old.png"}              # kept.png is shown by a slide; gone.png goes with its file
    assert "file missing" in texts["media/old.png"].text()
    assert texts["media/old.png"].checkState() == Qt.CheckState.Checked        # its file is gone
    media = next(item for item in items if item.text().startswith("media    gone.png"))
    assert "its description goes along" in media.text()      # one item with its file, not a second row to untick
    assert media.checkState() == Qt.CheckState.Checked
    sheet.archive_button.click()
    wait_for_archive(sheet)
    wait_until(lambda: sheet._scan is None)
    assert sheet.archive.sub.text().endswith("and 1 image description to the alt-text archive")
    assert set(alt_images.load_store(ctx)) == {"media/kept.png"}
    assert alt_archive.image_snapshots(ctx, "media/old.png")[0]["reason"] == "unused description"
    assert alt_archive.image_snapshots(ctx, "media/gone.png")[0]["reason"] == "image archived"   # its file moved


def test_archive_conflict_leaves_the_media_unchecked(folders, qapp, ctx):
    archive = ctx.media_dir / "archive"
    archive.mkdir()
    (archive / "gone.png").write_bytes(b"another picture")
    sheet = open_sheet(Window(ctx), page=ARCHIVE_PAGE)
    media = next(item for item in _archive_items(sheet) if item.text().startswith("media    gone.png"))
    assert "different file of this name is in media/archive/" in media.text()
    assert media.checkState() == Qt.CheckState.Unchecked
    assert any(item.checkState() == Qt.CheckState.Checked for item in _archive_items(sheet))
