# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The alt-text archive sheet of the Images page and the note that offers it (ui/pages/image_archive_sheet.py)."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QInputDialog, QMessageBox, QWidget
from test_alt_archive import A, B, TODAY, entry, write_store
from test_images_page_gui import CHART, make_page  # noqa: F401  (the fixture too)

from slidemage import alt_archive, alt_images
from slidemage.alt_images import ImageEntry, SlideUse
from slidemage.ui.pages.image_archive_sheet import AltArchiveSheet, describe_image_snapshot


@pytest.fixture
def parent(qapp) -> QWidget:
    return QWidget()


def answer(monkeypatch, button=QMessageBox.StandardButton.Yes) -> list[str]:
    asked: list[str] = []
    monkeypatch.setattr(QMessageBox, "question", lambda _parent, _title, text, *_a, **_k: asked.append(text) or button)
    monkeypatch.setattr(QMessageBox, "information", lambda _parent, _title, text, *_a, **_k: asked.append(text))
    return asked


def archived_project(ctx) -> None:
    """A and B archived with a text each, and the slide s1 archived with a takeaway on a third image."""
    write_store(ctx, {A: entry(A, {"s1": SlideUse(takeaway="why")}, short="sales by year"),
                      B: entry(B, {"s9": SlideUse()}, short="map of Austria")}, notes={"s1": "the summary"})
    alt_archive.archive_slides(ctx, [("s1", "s1-EN-Demo")], today=TODAY)       # takes A, which only s1 used
    alt_archive.archive_images(ctx, [B], today=TODAY)


def row_of(pane, key: str) -> int:
    return next(i for i in range(pane.list.count()) if pane.list.item(i).data(0x0100) == key)


def test_the_sheet_lists_what_is_archived_and_searches_names_and_texts(ctx, parent):
    archived_project(ctx)
    sheet = AltArchiveSheet(parent, ctx)
    assert sheet.images.list.count() == 2 and sheet.slides.list.count() == 1
    sheet.images.search.setText("austria")                 # a word of the text, not of the file name
    assert sheet.images.list.count() == 1 and sheet.images.key == B
    assert "map of Austria" in sheet.images.text.toPlainText()
    sheet.images.search.setText("nothing like this")
    assert sheet.images.list.count() == 0 and "matches" in sheet.images.empty.text()
    assert not sheet.restore_image_button.isEnabled()
    sheet.slides.search.setText("s1-EN-Demo")
    assert sheet.slides.key == "s1" and "the summary" in sheet.slides.text.toPlainText()


def test_restorable_images_come_first_and_restoring_one_fills_the_store(ctx, parent):
    archived_project(ctx)
    alt_images.save_store(ctx, {A: ImageEntry(image=A), B: ImageEntry(image=B)})
    sheet = AltArchiveSheet(parent, ctx, restorable={B})
    assert sheet.images.key == B and sheet.images.list.item(0).text().startswith("↩")
    sheet.restore_image_button.click()
    assert alt_images.load_store(ctx)[B].short == "map of Austria" and sheet.changed
    assert not sheet.images.list.item(row_of(sheet.images, B)).text().startswith("↩")
    assert alt_images.load_store(ctx)[A].short == ""        # the other one is untouched


def test_restoring_onto_text_asks_and_keeps_the_text_if_the_answer_is_no(ctx, parent, monkeypatch):
    archived_project(ctx)
    alt_images.save_store(ctx, {A: entry(A, {}, short="written since")})
    sheet = AltArchiveSheet(parent, ctx)
    sheet.images.list.setCurrentRow(row_of(sheet.images, A))
    asked = answer(monkeypatch, QMessageBox.StandardButton.No)
    sheet.restore_image_button.click()
    assert len(asked) == 1 and alt_images.load_store(ctx)[A].short == "written since" and not sheet.changed
    answer(monkeypatch)
    sheet.restore_image_button.click()
    assert alt_images.load_store(ctx)[A].short == "sales by year" and sheet.changed
    assert len(alt_archive.image_snapshots(ctx, A)) == 2    # the text it replaced is archived


def test_copy_offers_only_images_without_a_description(ctx, parent, monkeypatch):
    archived_project(ctx)
    other = "media/other.png"
    alt_images.save_store(ctx, {A: entry(A, {}, short="has text"), other: ImageEntry(image=other)})
    sheet = AltArchiveSheet(parent, ctx)
    sheet.images.list.setCurrentRow(row_of(sheet.images, B))
    offered: list[list[str]] = []
    monkeypatch.setattr(QInputDialog, "getItem", lambda _p, _t, _l, items, *_a, **_k: (offered.append(items) or other, True))
    answer(monkeypatch)
    sheet.copy_button.click()
    assert offered == [[other]]
    copied = alt_images.load_store(ctx)[other]
    assert copied.short == "map of Austria" and copied.status == "auto" and sheet.changed


def test_delete_removes_one_version_only_after_asking(ctx, parent, monkeypatch):
    archived_project(ctx)
    sheet = AltArchiveSheet(parent, ctx)
    sheet.images.list.setCurrentRow(row_of(sheet.images, A))
    answer(monkeypatch, QMessageBox.StandardButton.No)
    sheet.delete_image_button.click()
    assert alt_archive.image_snapshots(ctx, A) and not sheet.changed
    answer(monkeypatch)
    sheet.delete_image_button.click()
    assert alt_archive.image_snapshots(ctx, A) == [] and sheet.changed and sheet.images.list.count() == 1
    assert alt_archive.image_snapshots(ctx, B)              # the other is still there


def test_restoring_slide_data_reports_images_it_cannot_reach(ctx, parent, monkeypatch):
    archived_project(ctx)
    alt_images.save_store(ctx, {A: ImageEntry(image=A, used_on={"s1": SlideUse()})})   # B has no entry
    sheet = AltArchiveSheet(parent, ctx, restorable_slides={"s1"})
    asked = answer(monkeypatch)
    sheet.restore_slide_button.click()
    assert alt_images.load_store(ctx)[A].used_on["s1"].takeaway == "why" and sheet.changed
    assert asked == [] or "restore them first" in asked[0]


def test_a_snapshot_reads_as_text_with_every_language(ctx):
    archived_project(ctx)
    text = describe_image_snapshot(A, alt_archive.image_snapshots(ctx, A)[0])
    assert "slide deleted" in text and "sales by year" in text and "Used on slides: s1" in text


def test_the_page_offers_the_archive_and_says_when_something_can_be_restored(make_page, ctx):
    page = make_page()
    assert page.archive_button.isHidden() and page.archive_note.isHidden()          # nothing archived yet
    page.store[CHART] = entry(CHART, {"one": SlideUse()}, short="chart text")
    alt_archive.archive_images(ctx, [CHART], today=TODAY)
    page.store[CHART] = ImageEntry(image=CHART)                                      # the file is back, a scan adds the row
    page.reload()
    assert not page.archive_button.isHidden() and not page.archive_note.isHidden()
    assert "1 image description" in page.archive_note.text()
    assert page._restorable[0] == {CHART}
