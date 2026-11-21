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
    items = [sheet.files.item(i) for i in range(sheet.files.count())]
    texts = {item.text().split()[1]: item for item in items if item.text().startswith("description")}
    assert set(texts) == {"media/old.png"}              # kept.png is shown by a slide; gone.png goes with its file
    assert "file missing" in texts["media/old.png"].text()
    assert texts["media/old.png"].checkState() == Qt.CheckState.Checked        # its file is gone
    media = next(item for item in items if item.text().startswith("media    gone.png"))
    assert "its description goes along" in media.text()      # one item with its file, not a second row to untick
    assert media.checkState() == Qt.CheckState.Checked
    assert sheet.archive_button.text() == "Archive 3 items"                    # the unused slide and media file, old.png
    sheet.back_button.click()
    assert "1 image description" in sheet.archive.sub.text() and "2 image descriptions" not in sheet.archive.sub.text()
    sheet.archive.button.click()
    sheet.archive_button.click()
    wait_for_archive(sheet)
    wait_until(lambda: sheet._scan is None)
    assert sheet.archive.sub.text().endswith("and 1 image description to the alt-text archive")
    assert set(alt_images.load_store(ctx)) == {"media/kept.png"}
    assert alt_archive.image_snapshots(ctx, "media/old.png")[0]["reason"] == "unused description"
    assert alt_archive.image_snapshots(ctx, "media/gone.png")[0]["reason"] == "image archived"   # its file moved


def test_a_file_whose_name_archive_holds_with_other_content_is_listed_unticked_with_a_note(folders, qapp, ctx):
    (ctx.media_dir / "archive").mkdir()
    (ctx.media_dir / "archive" / "gone.png").write_bytes(b"another picture")        # media/gone.png holds b"i"
    sheet = open_sheet(Window(ctx), page=ARCHIVE_PAGE)
    media = next(sheet.files.item(i) for i in range(sheet.files.count())
                 if sheet.files.item(i).text().startswith("media    gone.png"))
    assert "different file of this name is in media/archive/" in media.text()
    assert media.checkState() == Qt.CheckState.Unchecked                              # archiving would leave it
    slide = next(sheet.files.item(i) for i in range(sheet.files.count())
                 if sheet.files.item(i).text().startswith("slide"))
    assert "different file" not in slide.text() and slide.checkState() == Qt.CheckState.Checked
    ticked = len(sheet._checked())
    assert 0 < ticked < sheet.files.count()
    intro = sheet.archive_intro.text()           # says how many are listed and how many of them are ticked
    assert f"<b>{sheet.files.count()} files</b> listed" in intro and f"<b>{ticked} ticked</b>" in intro and "listed" in intro
