# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Availability and copying of archived image and slide descriptions."""
from __future__ import annotations

from test_alt_archive import A, B, TODAY, entry, write_store

from slidemage import alt_archive, alt_images
from slidemage.alt_images import ImageEntry, ImageText, SlideUse


def test_an_image_back_in_the_project_without_text_is_restorable_until_it_has_some(ctx):
    write_store(ctx, {A: entry(A, {"s1": SlideUse()}, short="old")})
    alt_archive.archive_images(ctx, [A], today=TODAY)
    assert alt_archive.restorable_images(ctx) == []                       # no entry in the store: nothing to fill
    alt_images.save_store(ctx, {A: ImageEntry(image=A), B: ImageEntry(image=B)})   # the file is back (a scan adds the row)
    assert alt_archive.restorable_images(ctx) == [A]                      # B was never archived
    alt_archive.restore_image(ctx, A)
    assert alt_archive.restorable_images(ctx) == []


def test_slide_data_is_restorable_when_the_slide_and_its_image_are_there_without_it(ctx):
    write_store(ctx, {A: entry(A, {"s1": SlideUse(takeaway="why", reviewed="2026-01-01")}),
                      B: entry(B, {"s1": SlideUse()})}, notes={"s1": "summary"})
    alt_archive.archive_slides(ctx, [("s1", "s1-EN-X")], today=TODAY)
    write_store(ctx, {A: entry(A, {"s1": SlideUse()})})                   # s1 is back and shows A again
    assert alt_archive.restorable_slides(ctx, ["s1", "s2"]) == ["s1"]
    result = alt_archive.restore_slide(ctx, "s1")
    assert result.uses == [A] and result.summary
    assert alt_archive.restorable_slides(ctx, ["s1", "s2"]) == []


def test_copying_onto_another_image_keeps_its_slides_and_counts_as_unreviewed(ctx):
    archived = entry(A, {"s1": SlideUse(takeaway="x", reviewed="2026-01-01")}, short="chart of sales")
    archived.texts["en"].status = "reviewed"
    archived.texts["de"] = ImageText(short="Umsatz", translated_from="en")
    write_store(ctx, {A: archived})
    alt_archive.archive_images(ctx, [A], today=TODAY)
    alt_images.save_store(ctx, {B: ImageEntry(image=B, used_on={"s2": SlideUse(takeaway="mine")})})
    assert alt_archive.copy_image_text(ctx, A, B) == "copied"
    copied = alt_images.load_store(ctx)[B]
    assert copied.short == "chart of sales" and copied.short_de == "Umsatz" and copied.status == "auto"
    assert list(copied.used_on) == ["s2"] and copied.used_on["s2"].takeaway == "mine"     # its own slides, untouched
    assert alt_archive.copy_image_text(ctx, A, B) == "kept"               # now it has text
    assert alt_archive.copy_image_text(ctx, A, "media/none.png") == "missing"
    assert alt_archive.copy_image_text(ctx, "media/never.png", B) == "none"
    assert len(alt_archive.image_snapshots(ctx, A)) == 1                  # the archive is not changed by a copy
