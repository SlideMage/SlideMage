# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Archiving and restoring image descriptions and slide notes."""
from __future__ import annotations

import json

import pytest

from slidemage import alt_archive, alt_images, slide_rename, unused_content
from slidemage.alt_images import ImageEntry, ImageText, NewerStoreError, SlideUse

A, B = "media/a.png", "media/b.png"
TODAY = "2026-11-21"


def text(short: str, long: str = "long", status: str = "auto") -> ImageText:
    return ImageText(short=short, long=long, status=status)


def write_store(ctx, entries: dict[str, ImageEntry], notes: dict[str, str] | None = None) -> None:
    alt_images.save_store(ctx, entries)
    if notes:
        alt_images.update_slide_notes(ctx, lambda current: current.update(
            {k: alt_images.SlideNotes(summary=v) for k, v in notes.items()}) or True)


def entry(image: str, uses: dict[str, SlideUse], short: str = "short", **kw) -> ImageEntry:
    return ImageEntry(image=image, texts={"en": text(short)}, used_on=uses, **kw)


def slide(ctx, slide_id: str, *images: str) -> None:
    """A current slide file that includes these images."""
    (ctx.slides_dir).mkdir(exist_ok=True)
    body = "\n".join(rf"\includegraphics{{{image}}}" for image in images)
    (ctx.slides_dir / f"{slide_id}-EN-Demo-current.tex").write_text(
        "\\setSlideVersion{1-0-0}\n" + body, encoding="utf-8")


def archive_json(ctx) -> dict:
    return json.loads(alt_archive.archive_path(ctx).read_text(encoding="utf-8"))


def test_the_slide_data_and_the_entry_only_that_slide_used_go_to_the_archive(ctx):
    stale = "media/stale.png"
    write_store(ctx, {
        A: entry(A, {"s1": SlideUse(takeaway="why on s1", reviewed="2026-01-01", stored_hash="h"),
                     "s2": SlideUse(takeaway="why on s2")}),
        B: entry(B, {"s1": SlideUse(takeaway="only here")}, short="b text"),
        stale: entry(stale, {"s1": SlideUse(takeaway="cache missed the other use")}),
    }, notes={"s1": "summary of s1"})
    slide(ctx, "s2", A, stale)
    result = alt_archive.archive_slides(ctx, [("s1", "s1-EN-Demo")], alt_archive.REASON_SLIDE_DELETED, today=TODAY)
    assert result.slides == ["s1"] and result.images == [B]
    store = alt_images.load_store(ctx)
    assert set(store) == {A, stale} and set(store[A].used_on) == {"s2"}
    assert "s1" not in alt_images.load_slide_notes(ctx)
    data = archive_json(ctx)
    assert data["version"] == alt_archive.ARCHIVE_VERSION
    snap = data["slides"]["s1"][0]
    assert snap["name"] == "s1-EN-Demo" and snap["summary"] == "summary of s1" and snap["reason"] == "slide deleted"
    assert snap["uses"][A] == {"takeaway": {"en": "why on s1"}, "reviewed": "2026-01-01", "hash": "h"}
    assert snap["uses"][B] == {"takeaway": {"en": "only here"}}
    image = data["images"][B][0]
    assert image["slides"] == ["s1"] and image["entry"]["text"]["en"]["short"] == "b text"
    assert set(data["images"]) == {B}


def test_two_slides_archived_together_take_a_shared_image_with_them(ctx):
    write_store(ctx, {A: entry(A, {"s1": SlideUse(), "s2": SlideUse()})})
    result = alt_archive.archive_slides(ctx, [("s1", "s1-EN-X"), ("s2", "s2-EN-X")], today=TODAY)
    assert result.images == [A] and alt_images.load_store(ctx) == {}
    assert alt_archive.load(ctx)["images"][A][0]["slides"] == ["s1", "s2"]


def test_an_entry_with_no_text_is_dropped_without_a_snapshot(ctx):
    write_store(ctx, {A: ImageEntry(image=A, used_on={"s1": SlideUse()})})
    result = alt_archive.archive_slides(ctx, [("s1", "s1-EN-X")], today=TODAY)
    assert result.dropped == [A] and result.images == [] and alt_images.load_store(ctx) == {}
    assert not alt_archive.archive_path(ctx).exists()


def test_archiving_the_same_content_twice_adds_one_snapshot_and_changed_content_adds_another(ctx):
    for _ in range(2):
        write_store(ctx, {A: entry(A, {"s1": SlideUse(takeaway="t")})})
        alt_archive.archive_slides(ctx, [("s1", "s1-EN-X")], today=TODAY)
    assert len(alt_archive.slide_snapshots(ctx, "s1")) == 1 and len(alt_archive.image_snapshots(ctx, A)) == 1
    write_store(ctx, {A: entry(A, {"s1": SlideUse(takeaway="t2")}, short="new text")})
    alt_archive.archive_slides(ctx, [("s1", "s1-EN-X")], "slide archived", today="2026-12-01")
    snaps = alt_archive.image_snapshots(ctx, A)
    assert [s["entry"]["text"]["en"]["short"] for s in snaps] == ["short", "new text"]      # newest last
    assert snaps[-1]["reason"] == "slide archived" and snaps[-1]["archived"] == "2026-12-01"


def test_a_slide_with_nothing_authored_changes_nothing(ctx):
    write_store(ctx, {A: entry(A, {"s2": SlideUse()})})
    result = alt_archive.archive_slides(ctx, [("s9", "s9-EN-X")], today=TODAY)
    assert not result.changed and not alt_archive.archive_path(ctx).exists()
    assert list(alt_images.load_store(ctx)) == [A]


def test_a_newer_archive_is_never_written(ctx):
    path = alt_archive.archive_path(ctx)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"version": 99, "images": {}, "slides": {}}), encoding="utf-8")
    write_store(ctx, {A: entry(A, {"s1": SlideUse(takeaway="t")})})
    with pytest.raises(NewerStoreError):
        alt_archive.archive_slides(ctx, [("s1", "s1-EN-X")], today=TODAY)
    assert alt_images.load_store(ctx)[A].used_on["s1"].takeaways == {"en": "t"}      # the store is untouched
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 99


def test_the_unreferenced_entries_are_the_ones_no_slide_shows(ctx):
    write_store(ctx, {A: entry(A, {}), B: entry(B, {})})
    slide(ctx, "s1", A)
    assert alt_archive.unreferenced_entries(ctx) == [B]


def test_restore_image_puts_the_text_back_but_never_over_text_that_is_there(ctx):
    write_store(ctx, {A: entry(A, {"s1": SlideUse(takeaway="t")}, short="old"), B: ImageEntry(image=B)})
    assert alt_archive.archive_images(ctx, [A, B, "media/none.png"], today=TODAY) == [A]
    assert not alt_archive.image_snapshots(ctx, B) and alt_images.load_store(ctx) == {}
    assert alt_archive.restore_image(ctx, A) == "restored"
    assert alt_images.load_store(ctx)[A].short == "old"
    write_store(ctx, {A: entry(A, {"s7": SlideUse(takeaway="mine")}, short="current")})
    assert alt_archive.restore_image(ctx, A) == "kept"
    assert alt_images.load_store(ctx)[A].short == "current"
    assert alt_archive.restore_image(ctx, A, overwrite=True) == "restored"
    restored = alt_images.load_store(ctx)[A]
    assert restored.short == "old" and set(restored.used_on) == {"s1", "s7"}      # uses from both
    assert alt_archive.restore_image(ctx, "media/none.png") == "none"
    # restoring keeps the snapshot, and the "current" text it overwrote joined it
    snapshots = alt_archive.image_snapshots(ctx, A)
    assert [s["entry"]["text"]["en"]["short"] for s in snapshots] == ["old", "current"]
    assert snapshots[-1]["reason"] == alt_archive.REASON_REPLACED


def test_restore_slide_brings_back_takeaways_and_summary_and_names_what_is_missing(ctx):
    write_store(ctx, {A: entry(A, {"s1": SlideUse(takeaway="t", reviewed="2026-01-01")}),
                      B: entry(B, {"s1": SlideUse(takeaway="u")}, short="b")}, notes={"s1": "sum"})
    alt_archive.archive_slides(ctx, [("s1", "s1-EN-X")], today=TODAY)      # takes both entries, A and B, with it
    write_store(ctx, {A: entry(A, {})})                                    # only A is back
    result = alt_archive.restore_slide(ctx, "s1")
    assert result.uses == [A] and result.missing == [B] and result.summary
    assert alt_images.load_store(ctx)[A].used_on["s1"].reviewed == "2026-01-01"
    assert alt_images.load_slide_notes(ctx)["s1"].summary == "sum"
    again = alt_archive.restore_slide(ctx, "s1")                           # what is there now is kept
    assert again.uses == [] and not again.summary
    assert not alt_archive.restore_slide(ctx, "nope").found


def test_purge_removes_one_snapshot_or_all_and_only_when_asked(ctx):
    write_store(ctx, {A: entry(A, {"s1": SlideUse()})})
    alt_archive.archive_images(ctx, [A], today=TODAY)
    write_store(ctx, {A: entry(A, {}, short="v2")})
    alt_archive.archive_images(ctx, [A], today="2026-12-01")
    assert alt_archive.purge_image(ctx, A, 0) == 1 and len(alt_archive.image_snapshots(ctx, A)) == 1
    assert alt_archive.purge_image(ctx, A, 5) == 0
    assert alt_archive.purge_image(ctx, A) == 1 and alt_archive.load(ctx)["images"] == {}
    assert alt_archive.purge_slide(ctx, "s1") == 0


def test_deleting_a_slide_keeps_its_alt_text_data_in_the_archive(ctx):
    ctx.decks_dir.mkdir(exist_ok=True)
    slide(ctx, "s1x", A)
    write_store(ctx, {A: entry(A, {"s1x": SlideUse(takeaway="why", reviewed="2026-02-02")})}, notes={"s1x": "sum"})
    slide_rename.delete_slide_id(ctx, "s1x-EN-Demo")
    assert alt_images.load_store(ctx) == {} and alt_images.load_slide_notes(ctx) == {}
    assert alt_archive.slide_snapshots(ctx, "s1x")[0]["uses"][A]["takeaway"] == {"en": "why"}
    assert alt_archive.image_snapshots(ctx, A)[0]["reason"] == "slide deleted"


def test_archiving_unused_slides_and_media_moves_their_descriptions(ctx):
    (ctx.root / "decks").mkdir()
    (ctx.root / "media").mkdir()
    slide(ctx, "s1x", A)
    slide(ctx, "s2x", B)
    (ctx.root / "media" / "a.png").write_bytes(b"i")
    (ctx.root / "media" / "b.png").write_bytes(b"i")
    write_store(ctx, {A: entry(A, {"s1x": SlideUse(takeaway="t")}), B: entry(B, {"s2x": SlideUse()}, short="b")},
                notes={"s1x": "sum"})
    current = ctx.slides_dir / "s1x-EN-Demo-current.tex"
    old = current.with_name("s1x-EN-Demo-v1-0-0.tex")
    old.write_text("old")
    assert unused_content.archive_files(ctx, [], [old], lambda _line: None) == (0, 1)
    assert alt_images.load_store(ctx)[A].used_on["s1x"].takeaway == "t"
    assert not alt_archive.archive_path(ctx).exists()
    moved = unused_content.archive_files(ctx, [ctx.media_dir / "b.png"], [current], lambda _line: None)
    assert moved == (1, 1)
    assert alt_images.load_store(ctx) == {}
    assert list(archive_json(ctx)["images"]) == [A, B]
    assert alt_archive.slide_snapshots(ctx, "s1x")[0]["summary"] == "sum"
    assert alt_archive.image_snapshots(ctx, A)[0]["reason"] == "slide archived"
    assert alt_archive.image_snapshots(ctx, B)[0]["reason"] == "image archived"


def test_unused_descriptions_distinguish_missing_text_and_moving_files(ctx):
    (ctx.root / "media").mkdir()
    (ctx.root / "media" / "b.png").write_bytes(b"i")
    write_store(ctx, {A: entry(A, {}), B: ImageEntry(image=B), "tikz:t1": entry("tikz:t1", {}),
                      "media/shown.png": entry("media/shown.png", {})})
    slide(ctx, "s1", "media/shown.png")
    found = {d.image: d for d in alt_archive.unused_descriptions(ctx)}
    assert list(found) == [A, "tikz:t1"]       # sorted; the shown one is not offered, nor B: empty, and its file is there
    assert found[A].file_missing and found[A].has_text and found[A].suggested
    assert found["tikz:t1"].file_missing
    (ctx.root / "media" / "b.png").unlink()                                     # an empty row whose file is gone is offered
    assert alt_archive.described_images(ctx, [A, B, "media/none.png"]) == {A}
    gone = {d.image: d for d in alt_archive.unused_descriptions(ctx)}
    assert list(gone) == [A, B, "tikz:t1"] and not gone[B].has_text and gone[B].suggested
    alt_images.save_store(ctx, {**alt_images.load_store(ctx), B: entry(B, {})})     # with text and its file back
    (ctx.root / "media" / "b.png").write_bytes(b"i")
    kept = {d.image: d for d in alt_archive.unused_descriptions(ctx)}
    assert B in kept and kept[B].has_text and not kept[B].suggested
    assert B not in {d.image for d in alt_archive.unused_descriptions(ctx, moving=[B])}
    assert alt_archive.described_images(ctx, [A, B, "media/none.png"]) == {A, B}
